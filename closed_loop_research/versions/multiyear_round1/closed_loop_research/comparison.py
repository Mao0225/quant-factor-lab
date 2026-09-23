"""Pre-registered A/B/C/D/E comparisons, all seeds retained, no best-seed picking."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
import numpy as np

from .protocol import Protocol
from .runner import run_experiment, code_identity
from .selection import select_model, test_model
from .storage import read_json, atomic_json, digest, writer_lock

GROUPS = {
    "A": ("fixed", "trade_delta"),
    "B": ("random", "trade_delta"),
    "C": ("ppo", "single_ic"),
    "D": ("ppo", "combo_ic"),
    "E": ("ppo", "trade_delta"),
}


def _progress(group, seed, state):
    print(f"{group} seed={seed} batch={state['batch']} pool=v{state['pool_version']} actual={state['budget']['actual_f']+state['budget']['actual_e']}", flush=True)


def _train_member(raw, snapshot, root, group, seed):
    p, root = Protocol.from_dict(raw), Path(root)
    config = p.to_dict()
    config.update(name=f"{p.name}-{group}-{seed}", seed=seed, generator=GROUPS[group][0], reward_mode=GROUPS[group][1])
    if group == "A":
        config.update(batches=1, selection_batches=[1])
    protocol = Protocol.from_dict(config)
    run = root / f"{group}-seed-{seed}"
    state = run_experiment(protocol, snapshot, run, progress=partial(_progress, group, seed))
    trials = [t for b in state["completed"] for t in b["trials"]]
    return dict(group=group, seed=seed, run=str(run.resolve()), protocol_digest=protocol.digest,
                     candidates=len(trials), failure_rate=sum(t["status"] == "quality_failure" for t in trials)/len(trials) if trials else 0.,
                     negative_rewards=sum(t["reward"] < 0 for t in trials), budget=state["budget"],
                     test_locked=not (run / "test_result.json").exists())


def run_suite(p, snapshot, root, seeds, groups=tuple(GROUPS), final_test=False, workers=1):
    root = Path(root)
    if workers < 1:
        raise ValueError("workers must be positive")
    seeds, groups = list(seeds), list(groups)
    if not seeds or len(set(seeds)) != len(seeds) or not groups or len(set(groups)) != len(groups) or any(g not in GROUPS for g in groups):
        raise ValueError("unique seeds and valid groups required")
    manifest = dict(protocol=p.to_dict(), data_digest=p.data_digest, snapshot=str(Path(snapshot).resolve()),
                    snapshot_id=read_json(Path(snapshot)/"manifest.json")["snapshot_id"], seeds=seeds, groups=groups,
                    code_identity=code_identity(), budget_mode="wall_boundary" if p.wall_seconds is not None else "logical_backtests",
                    comparison_note="same search/execution/space; fixed group uses one search batch and discloses actual use")
    with writer_lock(root):
        if (root / "suite_manifest.json").exists() and read_json(root / "suite_manifest.json") != manifest:
            raise ValueError("suite identity changed; create a new suite")
        atomic_json(root / "suite_manifest.json", manifest)
        jobs = [(p.to_dict(), str(snapshot), str(root), group, seed) for group in groups for seed in seeds]
        if workers == 1:
            runs = [_train_member(*job) for job in jobs]
        else:
            runs = []
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_train_member, *job) for job in jobs]
                for future in as_completed(futures):
                    runs.append(future.result())
        runs.sort(key=lambda r: (groups.index(r['group']), seeds.index(r['seed'])))
        for row in runs:
            model = select_model(row['run'])
            row.update(selection_objective=model['selection_objective'], frozen_model_id=model['model_id'])
        # Freeze all methods and seeds before opening any T partition.
        if final_test:
            for row in runs:
                result = test_model(row["run"])
                row.update(test_locked=False, test_objective=result["objective"], test_metrics=result["metrics"])
        summary = {}
        for group in groups:
            members = [r for r in runs if r["group"] == group]
            values = [r["selection_objective"] for r in members]
            entry = dict(seeds=len(members), V_objective_mean=float(np.mean(values)), V_objective_std=float(np.std(values, ddof=0)),
                         failure_rate_mean=float(np.mean([r["failure_rate"] for r in members])),
                         actual_backtests_mean=float(np.mean([r["budget"]["actual_f"]+r["budget"]["actual_e"] for r in members])),
                         logical_backtests_mean=float(np.mean([r["budget"]["logical_f"]+r["budget"]["logical_e"] for r in members])),
                         wall_seconds_mean=float(np.mean([r["budget"]["wall_seconds"] for r in members])))
            if final_test:
                entry.update(T_objective_mean=float(np.mean([r["test_objective"] for r in members])),
                             T_objective_std=float(np.std([r["test_objective"] for r in members], ddof=0)))
            summary[group] = entry
        result = dict(suite_id=digest(manifest), runs=runs, summary=summary, data_mode=p.data_mode,
                      synthetic=p.synthetic, holdout_status=p.holdout_status, interpretation="descriptive seed statistics; no significance or method-effectiveness claim")
        atomic_json(root / "comparison.json", result)
        return result
