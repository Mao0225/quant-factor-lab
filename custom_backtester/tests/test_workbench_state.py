from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import workbench_state as state


class WorkbenchStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_read_json_tolerates_missing_corrupt_and_non_mapping_documents(self):
        path = self.root / "meta.json"
        self.assertEqual(state.read_json(path), {})
        for content in ("{", "null", "[]", '"value"'):
            path.write_text(content, encoding="utf-8")
            self.assertEqual(state.read_json(path), {})
        self.write_json(path, {"fields": ["close"]})
        self.assertEqual(state.read_json(path), {"fields": ["close"]})

    def test_store_requires_metadata_file_and_stock_directory(self):
        master, legacy = self.root / "master", self.root / "legacy"
        self.assertEqual(state.resolve_store(master, legacy), legacy)
        self.write_json(master / "meta.json", {})
        self.assertEqual(state.resolve_store(master, legacy), legacy)
        (master / "stocks").mkdir()
        self.assertEqual(state.resolve_store(master, legacy), master)
        (master / "stocks").rmdir()
        (master / "stocks").write_text("", encoding="utf-8")
        self.assertEqual(state.resolve_store(master, legacy), legacy)

    def test_jobs_merge_roots_without_colliding_same_named_jobs(self):
        first, second = self.root / "web" / "same", self.root / "ai" / "same"
        self.write_json(first / "status.json", {"run_name": "manual run", "status": "running", "updated_at": "2026-09-16", "message": "working"})
        self.write_json(second / "status.json", {"status": "queued", "updated_at": "2026-09-17"})
        self.write_json(second / "platform_job.json", {"operation": "generate_factors", "payload": {"generation_config": {"run_id": "batch-a"}}})
        rows = state.list_jobs([first.parent, second.parent, first.parent / ".", self.root / "missing"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["operation"], "generate_factors")
        self.assertEqual(rows[1]["operation"], "manual")
        self.assertEqual(rows[1]["label"], "manual run")
        self.assertEqual(rows[1]["message"], "working")
        self.assertEqual(rows[1]["path"], str(first.resolve()))
        self.assertEqual(rows[0]["payload"]["generation_config"]["run_id"], "batch-a")

    def test_jobs_recover_metadata_when_status_is_corrupt(self):
        job = self.root / "jobs" / "manual"
        job.mkdir(parents=True)
        (job / "status.json").write_text("{", encoding="utf-8")
        self.write_json(job / "job.json", {"run_name": "from metadata", "backtest": {}, "alphas": [{"expr": "close"}], "created_at": "2026-01-01"})
        rows = state.list_jobs([job.parent])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "from metadata")
        self.assertEqual(rows[0]["status"], "unknown")
        self.assertEqual(rows[0]["operation"], "manual")
        self.assertEqual(rows[0]["updated_at"], "2026-01-01")

    def test_jobs_ignore_unrelated_directories_and_infer_yaml_backtest(self):
        root = self.root / "jobs"
        (root / "empty").mkdir(parents=True)
        (root / "manual").mkdir()
        (root / "manual" / "config.yaml").write_text("run_name: saved\nalphas: []\n", encoding="utf-8")
        rows = state.list_jobs([root])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operation"], "manual")
        self.assertEqual(rows[0]["label"], "saved")

    def test_scoped_jobs_match_generation_backtest_and_compose_sources(self):
        rows = [
            {"operation": "generate_factors", "payload": {"generation_config": {"run_id": "run-a"}}},
            {"operation": "backtest_factors", "payload": {"factor_run_dir": "F:\\runs\\run-a"}},
            {"operation": "compose_factors", "payload": {"factor_run_dirs": ["/runs/run-a", "/runs/run-b"]}},
            {"operation": "backtest_factors", "payload": {"factor_run_dir": "/runs/run-ab"}},
            {"operation": "manual", "payload": {}},
        ]
        self.assertEqual(state.jobs_for(rows, factor_run_id="run-a"), rows[:3])
        self.assertEqual(state.jobs_for(rows, operation="backtest_factors", factor_run_id="run-a"), rows[1:2])
        self.assertEqual(state.jobs_for(rows, operation="manual"), rows[-1:])
        self.assertEqual(state.jobs_for(rows, factor_run_id="missing"), [])

    def test_choose_id_preserves_valid_selection_and_recovers_stale_values(self):
        self.assertEqual(state.choose_id(["a", "b"], "b"), "b")
        self.assertEqual(state.choose_id(["a", "b"], "missing"), "a")
        self.assertIsNone(state.choose_id([], "b"))

    def test_copy_manual_run_uses_snapshot_and_new_name_without_mutation(self):
        run = {"run_name": "old", "canonical_expression": "rank(close)", "pool_id": "pool-a", "config": {"alphas": [{"expr": "close"}], "backtest": {"top_k": 10, "extra": {"keep": True}}}}
        draft = state.copy_manual_run(run)
        other = state.copy_manual_run(run)
        self.assertTrue(draft["name"].startswith("old"))
        self.assertNotEqual(draft["name"], "old")
        self.assertNotEqual(draft["name"], other["name"])
        self.assertEqual(draft["expr"], "rank(close)")
        self.assertEqual(draft["pool_id"], "pool-a")
        draft["backtest"]["extra"]["keep"] = False
        self.assertTrue(run["config"]["backtest"]["extra"]["keep"])

    def test_copy_legacy_manual_run_recovers_weighted_expressions_and_pool(self):
        run = {"config": {"run_name": "legacy", "pool_id": "pool-b", "alphas": [{"expr": "close", "weight": 0.4}, {"expr": "open", "weight": 0.6}], "backtest": {"top_k": 20}}}
        draft = state.copy_manual_run(run)
        self.assertEqual(draft["expr"], "(0.4)*(close) + (0.6)*(open)")
        self.assertEqual(draft["pool_id"], "pool-b")
        self.assertEqual(draft["backtest"], {"top_k": 20})
        self.assertEqual(state.copy_manual_run({"config": {"alphas": [{"expr": "close"}]}})["expr"], "close")

    def test_validate_accepts_valid_and_partially_overlapping_data_ranges(self):
        config = {"start_date": "2020-01-01", "end_date": "2024-12-31", "top_k": 10, "initial_cash": 100, "buy_cost": 0, "sell_cost": 0, "slippage": 0, "min_cost": 0, "max_weight_per_stock": 0.1}
        self.assertEqual(state.validate_backtest(config, {"date_min": "2021-01-01", "date_max": "2025-01-01"}), [])

    def test_validate_reports_bad_dates_and_no_data_overlap(self):
        for config, fragment in [
            ({"start_date": "2024-02-30", "end_date": "2024-03-01"}, "开始日期"),
            ({"start_date": "2024-03-02", "end_date": "2024-03-01"}, "早于"),
            ({"start_date": "2020-01-01", "end_date": "2020-12-31"}, "数据"),
        ]:
            self.assertTrue(any(fragment in e for e in state.validate_backtest(config, {"date_min": "2024-01-01", "date_max": "2024-12-31"})))

    def test_validate_reports_nonpositive_nonfinite_and_negative_costs(self):
        base = {"start_date": "2024-01-01", "end_date": "2024-12-31"}
        for key, value in [("top_k", 0), ("top_k", 1.5), ("initial_cash", -1), ("initial_cash", float("nan")), ("max_weight_per_stock", 0), ("buy_cost", -0.1), ("sell_cost", "bad"), ("slippage", float("inf")), ("min_cost", -1)]:
            with self.subTest(key=key, value=value):
                self.assertTrue(state.validate_backtest(dict(base, **{key: value})))


if __name__ == "__main__":
    unittest.main()
