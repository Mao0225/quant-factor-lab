import inspect
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from custom_bt.data import build_master_store
from custom_bt.factor_backtest import backtest_accepted_factors
from custom_bt.factor_composition import (
    _find_factor_backtest_summary,
    _load_records_from_factor_run,
    compose_factors,
)
from custom_bt.pools import create_pool
from custom_bt.results import list_runs


class ExperimentHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run_dir = self.root / "factor_runs" / "run_a"
        self.run_dir.mkdir(parents=True)
        self.outputs = self.root / "outputs"
        self.saved = self.outputs / "saved_backtests"
        self.pool_id = "pool_a"
        self.manifest = {"pool_id": self.pool_id, "run_id": "run_a"}
        self._write_run()

    def _write_run(self):
        (self.run_dir / "factor_run.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.run_dir / "accepted_factors.jsonl").write_text(
            json.dumps({"expression": "close", "score": 1.0, "ic": 0.05}) + "\n", encoding="utf-8"
        )

    def _market(self):
        rows = []
        for day, date in enumerate(pd.date_range("2024-01-01", periods=5)):
            for index in range(1, 4):
                price = 10.0 + index + day * 0.1
                rows.append({
                    "code": f"{index:06d}", "timestamps": date.strftime("%Y-%m-%d"),
                    "open": price, "close": price + 0.2, "high": price + 0.3,
                    "low": price - 0.1, "vol": 1000.0, "amount": 1000.0 * index,
                    "Ifsuspend": 0, "if_up": 0, "if_down": 0,
                })
        source = self.root / "daily.csv"
        pd.DataFrame(rows).to_csv(source, index=False)
        build_master_store(source, self.root / "master", fields=[])
        pool = create_pool(self.root / "master", self.root / "pools", "liquid_3",
                           "2024-01-01", "2024-01-05", top_n=3, min_coverage=1.0)
        self.pool_id = pool["pool_id"]
        self.manifest.update(pool_id=self.pool_id, source_signature=pool["source_signature"])
        self._write_run()
        self.common = dict(master_store=self.root / "master", pools_root=self.root / "pools",
                           outputs_root=self.outputs,
                           backtest_config={"start_date": "2024-01-01", "end_date": "2024-01-05",
                                            "top_k": 1, "max_weight_per_stock": 1.0})
        # Plot rendering is unrelated to experiment identity and adds substantial test time.
        self.plot_patch = patch("custom_bt.results.save_summary_png")
        self.plot_patch.start()
        self.addCleanup(self.plot_patch.stop)

    def test_batch_experiments_keep_prior_artifacts_and_record_identity(self):
        self.assertIn("experiment_id", inspect.signature(backtest_accepted_factors).parameters)
        self._market()
        first = backtest_accepted_factors(**self.common, factor_run_dir=self.run_dir, experiment_id="batch_001")
        first_summary = Path(first["output_dir"]) / "factor_backtest_summary.csv"
        prior_bytes = first_summary.read_bytes()
        second = backtest_accepted_factors(**self.common, factor_run_dir=self.run_dir, experiment_id="batch_002")
        self.assertEqual(first["completed"], 1)
        self.assertEqual(second["completed"], 1)
        self.assertEqual(Path(first["output_dir"]), self.saved / "factor" / self.pool_id / "batch_001" / "run_a")
        self.assertNotEqual(first["output_dir"], second["output_dir"])
        self.assertEqual(first_summary.read_bytes(), prior_bytes)
        self.assertEqual(first["experiment_id"], "batch_001")
        batch_manifest = json.loads((first_summary.parent / "factor_backtest_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(batch_manifest["experiment_id"], "batch_001")
        self.assertEqual({run["experiment_id"] for run in list_runs(self.saved)}, {"batch_001", "batch_002"})

    def test_batch_default_and_existing_root_aliases_keep_legacy_path(self):
        self._market()
        for root in (self.outputs, self.saved, self.outputs / "factor_backtests"):
            with self.subTest(root=root):
                args = {**self.common, "outputs_root": root}
                result = backtest_accepted_factors(**args, factor_run_dir=self.run_dir)
                self.assertEqual(Path(result["output_dir"]), self.saved / "factor" / self.pool_id / "run_a")

    def test_composition_experiments_are_distinct_within_the_same_second(self):
        self.assertIn("experiment_id", inspect.signature(compose_factors).parameters)
        self._market()
        args = {**self.common, "pool_id": self.pool_id, "factor_run_dirs": [self.run_dir],
                "sweep_sizes": [1], "max_factors": 1, "target_horizon": 1}
        with patch("custom_bt.factor_composition.datetime") as clock:
            clock.now.return_value = datetime(2024, 1, 1, 12, 0, 0)
            legacy = compose_factors(**args)
            legacy_again = compose_factors(**args)
            first = compose_factors(**args, experiment_id="compose_001")
            second = compose_factors(**args, experiment_id="compose_002")
        self.assertEqual(legacy["composition_id"], legacy_again["composition_id"])
        self.assertEqual(len({legacy["composition_id"], first["composition_id"], second["composition_id"]}), 3)
        self.assertEqual(first["experiment_id"], "compose_001")
        legacy_manifest = json.loads((Path(legacy["output_dirs"][0]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("experiment_id", legacy_manifest["config"]["composition"])
        for result, identity in ((first, "compose_001"), (second, "compose_002")):
            manifest = json.loads((Path(result["output_dirs"][0]) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["experiment_id"], identity)
            self.assertEqual(manifest["config"]["composition"]["experiment_id"], identity)
        self.assertEqual(len(list_runs(self.saved)), 3)

    def test_invalid_experiment_ids_are_rejected_before_io(self):
        self.assertIn("experiment_id", inspect.signature(backtest_accepted_factors).parameters)
        self.assertIn("experiment_id", inspect.signature(compose_factors).parameters)
        args = dict(master_store="missing", pools_root="missing", outputs_root=self.outputs, backtest_config={})
        for identity in ("", ".", "..", "../escape", "a/b", "a\\b", "C:escape", "bad.", "CON", 123):
            for operation, extra in ((backtest_accepted_factors, {"factor_run_dir": "missing"}),
                                     (compose_factors, {"pool_id": "missing", "factor_run_dirs": []})):
                with self.subTest(identity=identity, operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError, "experiment_id"):
                        operation(**args, **extra, experiment_id=identity)
        self.assertFalse(self.outputs.exists())

    def _summary(self, parent, sharpe, modified):
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / "factor_backtest_summary.csv"
        pd.DataFrame([{"expression": "close", "backtest_sharpe": sharpe}]).to_csv(path, index=False)
        os.utime(path, (modified, modified))
        return path

    def test_latest_nested_summary_overrides_older_direct_and_local_summaries(self):
        base = self.saved / "factor" / self.pool_id
        self._summary(self.run_dir, 0.5, 1000)
        self._summary(base / "run_a", 1.0, 2000)
        self._summary(base / "zzz_old" / "run_a", 2.0, 3000)
        newest = self._summary(base / "aaa_new" / "run_a", 3.0, 4000)
        self.assertEqual(_find_factor_backtest_summary(self.run_dir, self.manifest, self.pool_id, self.saved), newest)
        records, _ = _load_records_from_factor_run(self.run_dir, self.pool_id, None, self.saved)
        self.assertEqual(records[0]["backtest_sharpe"], 3.0)

    def test_latest_summary_considers_manifest_run_id_and_direct_results(self):
        self.manifest["run_id"] = "original_run"
        base = self.saved / "factor" / self.pool_id
        self._summary(base / "exp1" / "run_a", 1.0, 1000)
        newest = self._summary(base / "original_run", 2.0, 2000)
        self.assertEqual(_find_factor_backtest_summary(self.run_dir, self.manifest, self.pool_id, self.saved), newest)

    def test_summary_lookup_without_results_root_uses_latest_local_file(self):
        self._summary(self.run_dir, 1.0, 1000)
        newest = self._summary(self.run_dir.parent, 2.0, 2000)
        self.assertEqual(_find_factor_backtest_summary(self.run_dir, self.manifest, self.pool_id, None), newest)


if __name__ == "__main__":
    unittest.main()
