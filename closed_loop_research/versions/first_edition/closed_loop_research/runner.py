"""Single-writer, phase-aware experiment scheduling and joint checkpoint recovery."""
import io
import platform
from pathlib import Path
import time

import numpy as np
import pandas as pd
import torch

from .data import DataAccess
from .evaluation import SegmentEvaluator, BatchEvaluator
from .ppo import PPOTrainer
from .storage import digest, file_digest, read_json, atomic_json, atomic_bytes, writer_lock


class InjectedInterruption(RuntimeError):
    """Test-only interruption after a durable transaction boundary."""


def code_identity():
    return digest({p.name: file_digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))})


def load_state(root):
    root = Path(root)
    pointer = read_json(root / "checkpoint.json")
    path = root / "checkpoints" / pointer["file"]
    if path.parent != root / "checkpoints" or file_digest(path) != pointer["sha256"]:
        raise RuntimeError("checkpoint integrity mismatch")
    # Only load trusted local checkpoints produced by this experiment, never arbitrary downloads.
    return torch.load(path, map_location="cpu", weights_only=False)


def _save(root, state, trainer, identity):
    # Reconcile durable invocation receipts, including work done before a crash.
    receipts = [read_json(p) for p in (root / "backtests" / "invocations").glob("*.json")]
    if any(r["protocol_digest"] != identity["protocol_digest"] or r["snapshot_id"] != identity["snapshot_id"] for r in receipts):
        raise ValueError("backtest invocation identity mismatch")
    for segment in "FE":
        state["budget"][f"actual_{segment.lower()}"] = sum(r["segment"] == segment for r in receipts)
    state["budget"]["completed_backtests"] = sum(r["status"] == "completed" for r in receipts)
    state["budget"]["backtest_seconds"] = sum(r["seconds"] or 0. for r in receipts)
    state["parameter_digest"] = trainer.parameter_digest()
    content = dict(identity=identity, state=state, trainer=trainer.state())
    buffer = io.BytesIO()
    torch.save(content, buffer)
    raw = buffer.getvalue()
    import hashlib
    checksum = hashlib.sha256(raw).hexdigest()
    name = f"{state['batch']:04d}-{state['phase']}-{checksum[:16]}.pt"
    atomic_bytes(root / "checkpoints" / name, raw)
    atomic_json(root / "checkpoint.json", dict(file=name, sha256=checksum))
    atomic_json(root / "status.json", {k: state[k] for k in ["batch", "phase", "pool_version", "pool", "ppo_updates", "budget", "stop_reason", "parameter_digest"]} | {"test_locked": True})


def run_experiment(p, snapshot_path, root, interrupt_after=None, max_batches_this_call=None):
    root = Path(root)
    with writer_lock(root):
        manifest = read_json(Path(snapshot_path) / "manifest.json")
        identity = dict(protocol_digest=p.digest, snapshot_id=manifest["snapshot_id"], code_identity=code_identity())
        trainer = PPOTrainer(p)
        if (root / "checkpoint.json").exists():
            saved = load_state(root)
            if saved["identity"] != identity:
                raise ValueError("experiment identity changed; derive a new run instead of resuming")
            state = saved["state"]
            trainer.restore(saved["trainer"])
            if state["phase"] == "finished":
                return state
        else:
            atomic_json(root / "protocol.json", p.to_dict())
            atomic_json(root / "experiment.json", {**identity, "snapshot_path": str(Path(snapshot_path).resolve()),
                        "data_mode": p.data_mode, "synthetic": p.synthetic,
                        "environment": dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__, torch=torch.__version__)})
            pool = {trainer.space.parse(k).text: float(w) for k, w in zip(p.initial_expressions, p.initial_weights)}
            if len(pool) != len(p.initial_expressions):
                raise ValueError("duplicate canonical initial expressions")
            state = dict(batch=0, phase="ready", pool=pool, pool_version=0, ppo_updates=0,
                         budget=dict(logical_f=0, logical_e=0, actual_f=0, actual_e=0, cache_hits=0, tokens=0, wall_seconds=0.),
                         completed=[], data_audit=[], stop_reason=None, pending=None)
        start_clock = time.monotonic()
        clock_base = state["budget"]["wall_seconds"]
        access = DataAccess(snapshot_path, p, "train", audit=state["data_audit"])
        f = SegmentEvaluator(access.load("F"), p, root / "backtests")
        e = SegmentEvaluator(access.load("E"), p, root / "backtests")
        if state["batch"] == 0 and state["phase"] == "ready":
            for evaluator in [f, e]:
                for expr in state["pool"]:
                    values = evaluator.factor(expr)
                    eligible = evaluator.signal_frame.eligible.to_numpy(dtype=bool)
                    if not np.isfinite(values[eligible]).all() or not evaluator.quality(expr)["passed"]:
                        raise ValueError("initial factors must have complete eligible coverage and pass quality in F/E")
            _save(root, state, trainer, identity)
        completed_this_call = 0
        def save():
            state["budget"]["wall_seconds"] = clock_base + time.monotonic()-start_clock
            _save(root, state, trainer, identity)
            if interrupt_after == state["phase"]:
                raise InjectedInterruption(state["phase"])
        while state["batch"] < p.batches:
            if state["phase"] == "committed":
                state["phase"] = "ready"
                state["pending"] = None
            if state["phase"] == "ready":
                n = 0 if p.generator == "fixed" else p.episodes_per_batch
                worst_batch = (n+1)*p.search_budget+n+2
                consumed = state["budget"]["logical_f"]+state["budget"]["logical_e"]
                if consumed+worst_batch+len(p.selection_batches)+1 > p.max_backtests:
                    state["stop_reason"] = "backtest_budget"
                    break
                if p.wall_seconds is not None and clock_base+time.monotonic()-start_clock >= p.wall_seconds:
                    state["stop_reason"] = "wall_budget"
                    break
                batch_id = state["batch"]+1
                f_before, e_before = f.actual_calls, e.actual_calls
                e_logical_before, hits_before = e.logical_calls, f.cache_hits+e.cache_hits
                evaluator = BatchEvaluator(state["pool"], f, e, p, batch_id)
                episodes = trainer.collect(state["pool"], batch_id) if n else []
                trials = []
                for ep in episodes:
                    trial = evaluator.candidate(ep["expression"])
                    ep["reward"] = trial["reward"]
                    trials.append(trial)
                decision = evaluator.decision(trials)
                logical_f = p.search_budget + sum(sum(s["budgeted"] for s in t.get("search", {}).get("trials", [])) for t in trials)
                state["budget"]["logical_f"] += logical_f
                state["budget"]["logical_e"] += e.logical_calls-e_logical_before
                state["budget"]["actual_f"] += f.actual_calls-f_before
                state["budget"]["actual_e"] += e.actual_calls-e_before
                state["budget"]["cache_hits"] += f.cache_hits+e.cache_hits-hits_before
                state["budget"]["tokens"] += sum(len(ep["steps"]) for ep in episodes)
                pending = dict(batch_id=batch_id, loaded_pool_version=state["pool_version"],
                               summary=evaluator.summary(), episodes=episodes, trials=trials, decision=decision)
                state["pending"], state["phase"] = pending, "evaluated"
                atomic_json(root / "batches" / f"{batch_id:04d}-evaluated.json", pending)
                save()
            if state["phase"] == "evaluated":
                pending = state["pending"]
                if p.generator == "ppo":
                    update = trainer.update(pending["episodes"], pending["batch_id"])
                    state["ppo_updates"] += 1
                else:
                    update = dict(batch_id=pending["batch_id"], skipped=True, reason=p.generator,
                                  before=trainer.parameter_digest(), after=trainer.parameter_digest(), parameter_l2_change=0.)
                pending["ppo_update"] = update
                state["phase"] = "ppo_updated"
                atomic_json(root / "batches" / f"{pending['batch_id']:04d}-ppo.json", update)
                save()
            if state["phase"] == "ppo_updated":
                pending = state["pending"]
                decision = pending["decision"]
                if decision["changed"]:
                    state["pool"] = decision["chosen"]["weights"]
                    state["pool_version"] += 1
                state["batch"] = pending["batch_id"]
                pending["next_pool_version"] = state["pool_version"]
                state["completed"].append({k: v for k, v in pending.items() if k != "episodes"})
                atomic_json(root / "batches" / f"{state['batch']:04d}-committed.json", state["completed"][-1])
                atomic_json(root / "pools" / f"batch-{state['batch']:04d}.json", dict(batch_id=state["batch"],
                            pool_version=state["pool_version"], weights=state["pool"], protocol_digest=p.digest,
                            registered_for_selection=state["batch"] in p.selection_batches))
                state["phase"] = "committed"
                save()
                completed_this_call += 1
                if max_batches_this_call is not None and completed_this_call >= max_batches_this_call:
                    return state
        state["stop_reason"] = state["stop_reason"] or "registered_batches_complete"
        state["phase"] = "finished"
        state["pending"] = None
        save()
        return state
