"""Lifecycle gates: registered V selection, frozen F weights, separate one-shot T."""
from pathlib import Path

from .data import DataAccess
from .evaluation import SegmentEvaluator
from .protocol import Protocol
from .runner import load_state, code_identity
from .storage import read_json, atomic_json, digest, writer_lock


def _context(root):
    p = Protocol.from_dict(read_json(root / "protocol.json"))
    experiment = read_json(root / "experiment.json")
    saved = load_state(root)
    if saved["identity"]["protocol_digest"] != p.digest or experiment["protocol_digest"] != p.digest:
        raise ValueError("protocol identity changed")
    if saved["identity"]["snapshot_id"] != experiment["snapshot_id"]:
        raise ValueError("experiment/checkpoint snapshot identity mismatch")
    if saved["identity"]["code_identity"] != experiment["code_identity"]:
        raise ValueError("experiment/checkpoint code identity mismatch")
    if saved["identity"]["code_identity"] != code_identity():
        raise ValueError("code identity changed; frozen evaluation requires the original kernel")
    if saved["state"]["phase"] != "finished":
        raise PermissionError("finish registered development before model selection/test")
    return p, experiment, saved["state"]


def _read_frozen(root, p, experiment):
    model = read_json(root / "frozen_model.json")
    if digest({k: v for k, v in model.items() if k != "model_id"}) != model["model_id"]:
        raise ValueError("frozen model was modified")
    if model["protocol_digest"] != p.digest or model["snapshot_id"] != experiment["snapshot_id"]:
        raise ValueError("frozen identity mismatch")
    return model


def select_model(run_root):
    root = Path(run_root)
    with writer_lock(root):
        p, experiment, state = _context(root)
        if (root / "frozen_model.json").exists():
            return _read_frozen(root, p, experiment)
        registered = [b for b in p.selection_batches if b <= state["batch"]]
        if not registered:
            raise PermissionError("no completed pre-registered selection checkpoint")
        audit = []
        access = DataAccess(experiment["snapshot_path"], p, "selection", audit)
        if access.manifest["snapshot_id"] != experiment["snapshot_id"]:
            raise ValueError("selection snapshot differs from locked experiment")
        spent = state["budget"]["logical_f"]+state["budget"]["logical_e"]
        if spent+len(registered)+1 > p.max_backtests:
            raise PermissionError("insufficient registered budget for selection and final test")
        token = dict(kind="registered_selection", protocol_digest=p.digest, checkpoints=registered)
        evaluator = SegmentEvaluator(access.load("V", token), p, root / "selection_backtests")
        rows = []
        for batch in registered:
            pool = read_json(root / "pools" / f"batch-{batch:04d}.json")
            if pool["protocol_digest"] != p.digest or not pool["registered_for_selection"]:
                raise ValueError("selection pool identity mismatch")
            evaluation = evaluator.evaluate(pool["weights"])
            rows.append(dict(batch_id=batch, weights=pool["weights"], pool_version=pool["pool_version"], **evaluation))
        # max is stable: ties choose the earliest registered checkpoint.
        best = max(rows, key=lambda r: r["objective"])
        model = dict(kind="frozen_model", protocol_digest=p.digest, snapshot_id=experiment["snapshot_id"],
                     code_identity=experiment["code_identity"], selected_batch=best["batch_id"],
                     pool_version=best["pool_version"], weights=best["weights"],
                     selection_artifact=best["artifact_id"], selection_objective=best["objective"],
                     rule="max_V_J_earliest_tie_no_refit", data_mode=p.data_mode, synthetic=p.synthetic)
        model["model_id"] = digest(model)
        atomic_json(root / "selection.json", dict(checkpoints=rows, rule=model["rule"], frozen_model_id=model["model_id"],
                                                   data_audit=audit, logical_calls=evaluator.logical_calls, actual_calls=evaluator.actual_calls))
        atomic_json(root / "frozen_model.json", model)
        return model


def test_model(run_root):
    root = Path(run_root)
    with writer_lock(root):
        if not (root / "frozen_model.json").exists():
            raise PermissionError("T is locked until registered V selection and model freeze")
        p, experiment, state = _context(root)
        model = _read_frozen(root, p, experiment)
        if (root / "test_result.json").exists():
            result = read_json(root / "test_result.json")
            if result["frozen_model_id"] != model["model_id"]:
                raise ValueError("test belongs to a different frozen model")
            return result
        audit = []
        access = DataAccess(experiment["snapshot_path"], p, "test", audit)
        if access.manifest["snapshot_id"] != experiment["snapshot_id"]:
            raise ValueError("test snapshot differs from frozen experiment")
        selection = read_json(root / "selection.json")
        spent = state["budget"]["logical_f"]+state["budget"]["logical_e"]+selection["logical_calls"]
        if spent+1 > p.max_backtests:
            raise PermissionError("insufficient registered total budget for test")
        evaluator = SegmentEvaluator(access.load("T", model), p, root / "test_backtests")
        evaluation = evaluator.evaluate(model["weights"])
        artifact = read_json(root / "test_backtests" / f"{evaluation['artifact_id']}.json")
        result = dict(frozen_model_id=model["model_id"], **evaluation, metrics=artifact["result"]["metrics"],
                      data_audit=audit, logical_calls=evaluator.logical_calls, actual_calls=evaluator.actual_calls,
                      data_mode=p.data_mode, synthetic=p.synthetic,
                      interpretation="prototype diagnostic only" if p.data_mode == "legacy_prototype" or p.synthetic else "held-out test")
        atomic_json(root / "test_result.json", result)
        status = read_json(root / "status.json")
        status["test_locked"] = False
        atomic_json(root / "status.json", status)
        return result
