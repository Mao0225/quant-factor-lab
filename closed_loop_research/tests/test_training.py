from pathlib import Path

import pytest

from .helpers import protocol, snapshot
from closed_loop_research.ppo import PPOTrainer
from closed_loop_research.runner import run_experiment, load_state, InjectedInterruption
from closed_loop_research.storage import read_json


def test_masked_complete_episodes_and_actual_parameter_update():
    p = protocol()
    trainer = PPOTrainer(p)
    before = trainer.parameter_digest()
    episodes = trainer.collect({"close": 1.}, batch_id=1)
    assert len(episodes) == p.episodes_per_batch
    for ep in episodes:
        assert ep["steps"][-1]["action"] == 0
        assert len(ep["steps"]) <= p.max_tokens + 1
        for step in ep["steps"]:
            assert step["mask"][step["action"]]
            assert step["observation"]["pool_weights"][0] == 1.
    for i, ep in enumerate(episodes):
        ep["reward"] = -1. if i % 2 == 0 else -0.1
    result = trainer.update(episodes, batch_id=1)
    assert trainer.parameter_digest() != before
    assert result["parameter_l2_change"] > 0
    assert result["negative_episodes"] == p.episodes_per_batch
    assert result["initial_ratio_max_error"] < 1e-5
    with pytest.raises(ValueError):
        trainer.update(episodes, batch_id=2)


@pytest.mark.parametrize("stage", ["evaluated", "ppo_updated", "committed"])
def test_resume_transaction_matches_uninterrupted(tmp_path, stage):
    p, path = snapshot(tmp_path)
    full, resumed = tmp_path / "full", tmp_path / "resumed"
    expected = run_experiment(p, path, full)
    with pytest.raises(InjectedInterruption):
        run_experiment(p, path, resumed, interrupt_after=stage)
    actual = run_experiment(p, path, resumed)
    assert actual["batch"] == expected["batch"] == p.batches
    assert actual["ppo_updates"] == expected["ppo_updates"] == p.batches
    assert actual["pool"] == expected["pool"]
    assert actual["parameter_digest"] == expected["parameter_digest"]
    assert len(actual["completed"]) == p.batches
    assert actual["completed"][1]["loaded_pool_version"] == actual["completed"][0]["next_pool_version"]
    assert all(a["segment"] in "FE" for a in actual["data_audit"])
    again = run_experiment(p, path, resumed)
    assert again["ppo_updates"] == p.batches
    assert read_json(resumed / "status.json")["test_locked"]


def test_protocol_change_cannot_resume_same_experiment(tmp_path):
    p, path = snapshot(tmp_path)
    run = tmp_path / "run"
    run_experiment(p, path, run)
    changed = protocol(beta=0.)
    with pytest.raises(ValueError, match="identity"):
        run_experiment(changed, path, run)


def test_budget_stop_has_no_fake_update(tmp_path):
    p, path = snapshot(tmp_path, protocol(max_backtests=1))
    state = run_experiment(p, path, tmp_path / "run")
    assert state["ppo_updates"] == 0 and state["batch"] == 0
    assert state["stop_reason"] == "backtest_budget"


def test_complete_episode_prefix_grammar_stays_valid():
    p = protocol()
    t = PPOTrainer(p)
    for batch in range(1, 6):
        episodes = t.collect({"close": .5, "volume": -.5}, batch)
        for e in episodes:
            assert len(t.space.parse(e["expression"]).tokens) <= p.max_tokens


def test_orphaned_backtests_are_counted_after_mid_evaluation_crash(tmp_path, monkeypatch):
    import closed_loop_research.runner as runner
    p, path = snapshot(tmp_path, protocol(batches=1, selection_batches=[1]))
    root = tmp_path / "run"
    write = runner.atomic_json
    def crash(target, value):
        if str(target).endswith("-evaluated.json"):
            raise OSError("interrupted before evaluated checkpoint")
        write(target, value)
    monkeypatch.setattr(runner, "atomic_json", crash)
    with pytest.raises(OSError):
        run_experiment(p, path, root)
    artifacts = list((root / "backtests").glob("*.json"))
    assert len(artifacts) > 0
    monkeypatch.setattr(runner, "atomic_json", write)
    state = run_experiment(p, path, root)
    assert state["budget"]["actual_f"] + state["budget"]["actual_e"] >= len(artifacts)
