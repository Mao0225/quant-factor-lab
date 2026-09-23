"""Finite-budget feedback-driven subset/weight search, authorized for F only."""
from dataclasses import dataclass, asdict
import numpy as np

from .scoring import InvalidProposal


@dataclass
class SearchResult:
    weights: dict
    objective: float
    artifact_id: str
    trials: list

    def to_dict(self):
        return asdict(self)


def search(expressions, initial, fit, p, seed):
    if fit.segment != "F":
        raise PermissionError("search only receives an F evaluator")
    rng = np.random.default_rng(seed)
    expressions = tuple(expressions)
    current = np.array([initial.get(k, 0.) for k in expressions], dtype=float)
    best, best_j, best_id = current.copy(), -np.inf, None
    stalls, scale, restarts = 0, 0, 0
    trials = []
    def state():
        return dict(weights=dict(zip(expressions, current.tolist())), best_objective=None if not np.isfinite(best_j) else float(best_j),
                    stalls=stalls, scale_index=scale, restarts=restarts)
    calls, i = 0, 0
    while calls < p.search_budget:
        before = state()
        proposed = current.copy()
        action = "initial"
        if i and p.search_mode == "adaptive":
            if i == 1:
                proposed = -current
                action = "sign_flip"
            elif stalls >= p.restart_after * len(p.perturbations):
                proposed[:] = 0.
                proposed[int(rng.integers(len(expressions)))] = rng.choice([-1., 1.])
                restarts += 1
                stalls, scale = 0, 0
                action = "restart"
            else:
                index = int(rng.integers(len(expressions)))
                action = ["coordinate", "disable", "replace", "perturb"][i % 4]
                if action == "disable":
                    proposed[index] = 0.
                elif action == "replace":
                    nonzero = np.flatnonzero(np.abs(proposed) > 1e-12)
                    if len(nonzero):
                        proposed[int(rng.choice(nonzero))] = 0.
                    proposed[index] = rng.choice([-1., 1.]) * p.perturbations[scale]
                elif action == "perturb":
                    proposed += rng.normal(0., p.perturbations[scale], len(proposed))
                else:
                    proposed[index] += rng.choice([-1., 1.]) * p.perturbations[scale]
        # Subset projection before any backtest. Zero stays illegal.
        if np.count_nonzero(np.abs(proposed) > 1e-12) > p.max_factors:
            keep = np.argsort(-np.abs(proposed), kind="stable")[:p.max_factors]
            proposed = np.where(np.isin(np.arange(len(proposed)), keep), proposed, 0.)
        total = np.abs(proposed).sum()
        value, artifact, hit, reason = None, None, False, None
        budgeted = False
        if total > 1e-12:
            proposed /= total
            calls += 1
            budgeted = True
            try:
                evaluation = fit.evaluate(dict(zip(expressions, proposed.tolist())))
                value, artifact, hit = evaluation["objective"], evaluation["artifact_id"], evaluation["cache_hit"]
            except InvalidProposal as exc:
                reason = str(exc)
        else:
            reason = "all-zero proposal"
        accepted = value is not None and value > best_j
        if accepted:
            best, best_j, best_id = proposed.copy(), value, artifact
            current, stalls, scale = best.copy(), 0, 0
        else:
            stalls += 1
            scale = min(len(p.perturbations)-1, stalls // p.restart_after)
            current = best.copy()
        trials.append(dict(index=i, objective_calls=calls, budgeted=budgeted, action=action, proposal=dict(zip(expressions, proposed.tolist())), objective=value,
                           accepted=accepted, reason=reason, artifact_id=artifact, cache_hit=hit,
                           previous_state=before, next_state=state()))
        i += 1
    if best_id is None:
        raise InvalidProposal("no valid proposal in F budget")
    return SearchResult({k: float(w) for k, w in zip(expressions, best) if abs(w) > 1e-12}, float(best_j), best_id, trials)
