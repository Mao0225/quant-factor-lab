import pytest

from .helpers import protocol, snapshot, panel, metadata
from closed_loop_research.data import prepare_snapshot
from closed_loop_research.runner import run_experiment
from closed_loop_research.selection import select_model, test_model as execute_test
from closed_loop_research.report import build_report
from closed_loop_research.storage import read_json, atomic_json


def test_test_is_locked_until_registered_selection_and_freeze(tmp_path):
    p, path = snapshot(tmp_path)
    root = tmp_path / "run"
    run_experiment(p, path, root, max_batches_this_call=1)
    with pytest.raises(PermissionError):
        select_model(root)
    with pytest.raises(PermissionError):
        execute_test(root)
    run_experiment(p, path, root)
    report = build_report(root)
    assert "最终测试尚未解锁" in report.read_text(encoding="utf-8")
    model = select_model(root)
    selection = read_json(root / "selection.json")
    assert [c["batch_id"] for c in selection["checkpoints"]] == list(p.selection_batches)
    pool = read_json(root / "pools" / f"batch-{model['selected_batch']:04d}.json")
    assert model["weights"] == pool["weights"]
    result = execute_test(root)
    assert result["frozen_model_id"] == model["model_id"]
    assert execute_test(root) == result
    assert all(x["segment"] == "V" for x in read_json(root / "selection.json")["data_audit"])
    assert all(x["segment"] == "T" for x in result["data_audit"])
    assert not read_json(root / "status.json")["test_locked"]
    report = build_report(root)
    assert "最终测试已执行" in report.read_text(encoding="utf-8")


def test_report_escapes_expressions_and_has_real_evidence(tmp_path):
    p, path = snapshot(tmp_path)
    root = tmp_path / "run"
    state = run_experiment(p, path, root)
    text = build_report(root).read_text(encoding="utf-8")
    for word in ["协议", "迭代记录", "PPO", "研究概览", "当前组合", "验证报告", "500"]:
        if word != "500":
            assert word in text
    assert state["parameter_digest"] in text
    assert len(state["completed"]) == p.batches


def test_selection_refuses_different_valid_snapshot(tmp_path):
    p, path = snapshot(tmp_path)
    root = tmp_path / "run"
    run_experiment(p, path, root)
    replacement = panel()
    replacement["volume"] *= 2
    prepare_snapshot(replacement, tmp_path / "another", p, metadata())
    experiment = read_json(root / "experiment.json")
    experiment["snapshot_path"] = str(tmp_path / "another")
    atomic_json(root / "experiment.json", experiment)
    with pytest.raises(ValueError, match="snapshot"):
        select_model(root)


def test_total_budget_reserves_selection_and_test(tmp_path):
    p = protocol(generator="fixed", batches=1, selection_batches=[1], max_backtests=10)
    p, path = snapshot(tmp_path, p)
    state = run_experiment(p, path, tmp_path / "run")
    assert state["batch"] == 0
    assert state["stop_reason"] == "backtest_budget"
