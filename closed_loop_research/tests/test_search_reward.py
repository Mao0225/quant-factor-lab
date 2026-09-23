import numpy as np
import pytest

from .helpers import protocol, snapshot
from closed_loop_research.data import DataAccess
from closed_loop_research.search import search
from closed_loop_research.evaluation import SegmentEvaluator, BatchEvaluator, paired_reward, commit_pool


class ToyFit:
    segment = "F"
    def evaluate(self, weights):
        value = weights.get("close", 0.)
        return {"objective": value, "artifact_id": str(value), "cache_hit": False}


def test_search_is_feedback_driven_and_counts_zero_candidate_start():
    p = protocol()
    result = search(["close", "volume"], {"close": -1., "volume": 0.}, ToyFit(), p, seed=4)
    assert sum(t["budgeted"] for t in result.trials) == p.search_budget
    assert result.trials[0]["proposal"]["volume"] == 0.
    assert result.objective > -1
    assert any(t["accepted"] and t["index"] > 0 for t in result.trials)
    for trial in result.trials:
        assert "next_state" in trial and "previous_state" in trial
    class NotFit(ToyFit):
        segment = "E"
    with pytest.raises(PermissionError):
        search(["close"], {"close": 1.}, NotFit(), p, seed=4)


def test_unused_candidate_reward_zero_and_negative_delta():
    p = protocol(beta=0.1)
    assert paired_reward(0.3, 0.2, 0.5, 0.1, False, p)["reward"] == 0
    r = paired_reward(0.19, 0.2, 0.5, 0.1, True, p)
    assert r["delta"] == pytest.approx(-0.05)
    assert r["reward"] == pytest.approx(np.tanh(-0.5))


def test_duplicate_and_failure_no_extra_backtests(tmp_path):
    p, path = snapshot(tmp_path)
    data = DataAccess(path, p, "train")
    f = SegmentEvaluator(data.load("F"), p, tmp_path / "artifacts")
    e = SegmentEvaluator(data.load("E"), p, tmp_path / "artifacts")
    batch = BatchEvaluator({"close": 1.}, f, e, p, batch_id=1)
    before = (f.actual_calls, e.actual_calls)
    duplicate = batch.candidate(" close ")
    assert duplicate["status"] == "duplicate" and duplicate["reward"] == 0
    bad = batch.candidate("sub(close,close)")
    assert bad["status"] == "quality_failure" and bad["reward"] == -1
    assert (f.actual_calls, e.actual_calls) == before
    valid = batch.candidate("volume")
    assert valid["status"] == "evaluated"
    assert sum(t["budgeted"] for t in valid["search"]["trials"]) == p.search_budget
    assert valid["baseline_artifact"] == batch.baseline_e["artifact_id"]
    assert valid["logical_baseline_budget"] == p.search_budget
    assert f.actual_calls <= f.logical_calls
    assert f.evaluate({"close": 1.})["cache_hit"]


def test_pool_commit_uses_incumbent_not_degraded_refit():
    p = protocol(delta=0.01)
    incumbent = dict(weights={"close": 1.}, utility=0.3, source="incumbent")
    candidates = [dict(weights={"volume": 1.}, utility=0.25, source="candidate")]
    decision = commit_pool(incumbent, candidates, p)
    assert not decision["changed"]
    candidates += [dict(weights={"volume": 1.}, utility=0.32, source="candidate")]
    decision = commit_pool(incumbent, candidates, p)
    assert decision["changed"] and decision["chosen"]["weights"] == {"volume": 1.}


def test_data_failure_is_not_quality_reward(tmp_path):
    p, path = snapshot(tmp_path)
    data = DataAccess(path, p, "train")
    f, e = [SegmentEvaluator(data.load(s), p, tmp_path / "artifacts") for s in "FE"]
    batch = BatchEvaluator({"close": 1.}, f, e, p, 1)
    original = f.quality
    def broken(expression):
        raise OSError("disk broke")
    f.quality = broken
    with pytest.raises(OSError):
        batch.candidate("volume")


def test_zero_proposals_do_not_consume_objective_call_budget():
    class Counted(ToyFit):
        calls = 0
        def evaluate(self, weights):
            self.calls += 1
            return super().evaluate(weights)
    for expressions in [["close"], ["close", "volume"]]:
        fit = Counted()
        result = search(expressions, {"close": 1.}, fit, protocol(), seed=0)
        assert fit.calls == 8
        assert sum(t["budgeted"] for t in result.trials) == 8
