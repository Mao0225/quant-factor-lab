"""Frozen segment evaluation, paired reward attribution, and one pool decision."""
from pathlib import Path
import time
import uuid
import numpy as np
import pandas as pd

from .backtest import backtest, prepare_market
from .expressions import ExpressionSpace, ExpressionError
from .scoring import standardized, quality, InvalidProposal
from .search import search
from .storage import digest, atomic_json, read_json


class SegmentEvaluator:
    def __init__(self, data, p, artifacts):
        self.data, self.p, self.segment = data, p, data.segment
        self.space, self.artifacts = ExpressionSpace(p), Path(artifacts)
        self.signal_mask = data.frame.date.isin(data.signal_dates).to_numpy()
        self.signal_frame = data.frame.loc[self.signal_mask].reset_index(drop=True)
        self.values, self.cache = {}, {}
        self.normalized, self.quality_cache = {}, {}
        self.normalization_computations = 0
        self.market = prepare_market(data.frame)
        self.signal_groups = self.signal_frame.groupby('date', sort=True).indices
        self.logical_calls = self.actual_calls = self.cache_hits = 0

    def factor(self, expression):
        if expression not in self.values:
            self.values[expression] = self.space.evaluate(expression, self.data.frame)[self.signal_mask]
        return self.values[expression]

    def quality(self, expression):
        if expression not in self.quality_cache:
            self.quality_cache[expression] = quality(self.signal_frame, self.factor(expression), self.p)
        return self.quality_cache[expression]

    def scores(self, weights):
        active = {k: w for k, w in weights.items() if abs(w) > 1e-12}
        if not active or len(active) > self.p.max_factors or not np.isclose(sum(abs(w) for w in active.values()), 1.):
            raise InvalidProposal('weights must be finite, L1=1 and within pool capacity')
        result = self.signal_frame[['date', 'code', 'eligible']].copy()
        scores, observed = np.zeros(len(result)), np.zeros(len(result), dtype=bool)
        for key, weight in active.items():
            if not np.isfinite(weight):
                raise InvalidProposal('nonfinite weight')
            if key not in self.normalized:
                self.normalized[key] = standardized(self.signal_frame, self.factor(key), self.p.epsilon)
                self.normalization_computations += 1
            z, present = self.normalized[key]
            scores += weight * z
            observed |= present
            result[f'contribution:{key}'] = weight*z
            result[f'missing:{key}'] = ~present
        if (result.eligible.to_numpy(dtype=bool) & ~observed).any():
            raise InvalidProposal('all active factors missing on a fixed eligible sample')
        result['score'] = scores
        return result

    def rankings(self, scores):
        values = scores.score.to_numpy()
        codes = scores.code.to_numpy()
        eligible = scores.eligible.to_numpy(dtype=bool) & np.isfinite(values)
        result = {}
        for day, idx in self.signal_groups.items():
            idx = idx[eligible[idx]]
            chosen = idx[np.lexsort((codes[idx], -values[idx]))[:self.p.top_k]]
            result[pd.Timestamp(day)] = (codes[chosen].tolist(), values[chosen].tolist())
        return result

    def evaluate(self, weights):
        weights = {k: float(v) for k, v in sorted(weights.items()) if abs(v) > 1e-12}
        key = digest(dict(protocol=self.p.digest, snapshot=self.data.snapshot_id, segment=self.segment,
                          bounds=[self.data.start, self.data.end], weights=weights))
        self.logical_calls += 1
        if key in self.cache:
            self.cache_hits += 1
            return {**self.cache[key], "cache_hit": True}
        path = self.artifacts / (f"{key}.json.gz" if self.p.compress_artifacts else f"{key}.json")
        # Persistent cache identity covers data, intervals, rules, optimizer, seed and weights.
        if path.exists():
            stored = read_json(path)
            if stored.get("identity") != key or digest(stored["result"]) != stored.get("result_digest"):
                raise RuntimeError("backtest artifact integrity mismatch")
            self.cache_hits += 1
            entry = dict(objective=stored["result"]["metrics"]["objective"], artifact_id=key)
            self.cache[key] = entry
            return {**entry, "cache_hit": True}
        scores = self.scores(weights)
        receipt_path = self.artifacts / "invocations" / f"{uuid.uuid4().hex}.json"
        receipt = dict(artifact_id=key, protocol_digest=self.p.digest, snapshot_id=self.data.snapshot_id,
                       segment=self.segment, status="started", seconds=None)
        atomic_json(receipt_path, receipt)
        started = time.perf_counter()
        result = backtest(self.data.frame, scores, self.data.start, self.data.end, self.p,
                          prepared=self.market, rankings=self.rankings(scores)).to_dict()
        receipt.update(status="completed", seconds=time.perf_counter()-started)
        atomic_json(receipt_path, receipt)
        self.actual_calls += 1
        atomic_json(path, dict(identity=key, result_digest=digest(result), protocol_digest=self.p.digest,
                               snapshot_id=self.data.snapshot_id, segment=self.segment, weights=weights, result=result))
        entry = dict(objective=result["metrics"]["objective"], artifact_id=key)
        self.cache[key] = entry
        return {**entry, "cache_hit": False}

    def ic(self, weights=None, expression=None):
        """Signed daily Pearson IC: signal t vs next open -> h sessions later open.

        Both execution endpoints must be inside this segment; no cross-boundary label.
        """
        f = self.data.frame
        price = f.pivot(index="date", columns="code", values="exec_open").sort_index()
        dates = price.index
        by_date = self.signal_frame.copy()
        by_date["value"] = self.factor(expression) if expression else self.scores(weights).score.to_numpy()
        ics = []
        for date, g in by_date.groupby("date", sort=True):
            loc = dates.get_loc(date)
            a, b = loc + 1, loc + 1 + self.p.ic_horizon
            if b >= len(dates) or dates[a] < pd.Timestamp(self.data.start) or dates[b] > pd.Timestamp(self.data.end):
                continue
            label = price.iloc[b] / price.iloc[a] - 1
            x = g.loc[g.eligible].set_index("code").value
            pair = pd.concat([x.rename("x"), label.rename("y")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
            if len(pair) >= 2 and pair.x.std(ddof=0) > self.p.epsilon and pair.y.std(ddof=0) > self.p.epsilon:
                ics.append(float(pair.x.corr(pair.y)))
        return float(np.mean(ics)) if ics else 0.


def complexity(weights, p, space):
    return sum(len(space.parse(k).tokens) for k, w in weights.items() if abs(w) > 1e-12) / (p.max_factors * p.max_tokens)


def paired_reward(new, base, new_complexity, base_complexity, used, p):
    raw = float(new - base - p.beta*(new_complexity-base_complexity))
    delta = raw if used else 0.
    return dict(raw_comparison_delta=raw, delta=delta, reward=float(np.tanh(delta/p.tau)), candidate_used=bool(used))


def commit_pool(incumbent, contenders, p):
    best = max([incumbent] + contenders, key=lambda c: c["utility"])
    changed = best["utility"] > incumbent["utility"] + p.delta
    return dict(changed=bool(changed), chosen=best if changed else incumbent,
                incumbent_utility=incumbent["utility"], best_utility=best["utility"], threshold=p.delta,
                reason="improvement_over_incumbent" if changed else "incumbent_threshold_not_met")


class BatchEvaluator:
    def __init__(self, incumbent, fit, feedback, p, batch_id):
        if fit.segment != "F" or feedback.segment != "E":
            raise PermissionError("batch needs isolated F and E evaluators")
        self.incumbent, self.f, self.e, self.p, self.batch_id = incumbent, fit, feedback, p, batch_id
        self.space = fit.space
        self.seed = p.seed + batch_id * 1009
        self.baseline = search(sorted(incumbent), incumbent, fit, p, self.seed)
        self.baseline_e = feedback.evaluate(self.baseline.weights)
        self.incumbent_e = feedback.evaluate(incumbent)
        self.baseline_c = complexity(self.baseline.weights, p, self.space)

    def summary(self):
        return dict(batch_id=self.batch_id, incumbent=self.incumbent, baseline=self.baseline.to_dict(),
                    baseline_e=self.baseline_e, incumbent_e=self.incumbent_e, seed=self.seed)

    def candidate(self, expression):
        row = dict(expression=expression, batch_id=self.batch_id, baseline_artifact=self.baseline_e["artifact_id"],
                   baseline_objective=self.baseline_e["objective"], logical_baseline_budget=self.p.search_budget,
                   baseline_shared=True, candidate_used=False)
        try:
            canonical = self.space.parse(expression).text
            row["expression"] = canonical
            if canonical in self.incumbent:
                return {**row, "status": "duplicate", "reward": 0., "delta": 0.}
            checks = {"F": self.f.quality(canonical), "E": self.e.quality(canonical)}
            row["quality"] = checks
            if not all(c["passed"] for c in checks.values()):
                return {**row, "status": "quality_failure", "reason": "coverage_or_degeneracy", "reward": -1., "delta": None}
            expressions = sorted(self.incumbent) + [canonical]
            initial = {**self.incumbent, canonical: 0.}
            result = search(expressions, initial, self.f, self.p, self.seed)
            row["search"] = result.to_dict()
            new = self.e.evaluate(result.weights)
            used = canonical in result.weights
            new_c = complexity(result.weights, self.p, self.space)
            reward = paired_reward(new["objective"], self.baseline_e["objective"], new_c, self.baseline_c, used, self.p)
            row.update(reward, status="evaluated", weights=result.weights, candidate_artifact=new["artifact_id"],
                       candidate_objective=new["objective"], utility=new["objective"]-self.p.beta*new_c,
                       complexity_new=new_c, complexity_base=self.baseline_c)
            # Only this terminal reward changes across C/D/E; downstream search/commit stay fixed.
            if self.p.reward_mode == "single_ic":
                row["reward"] = self.e.ic(expression=canonical)
            elif self.p.reward_mode == "combo_ic":
                row["ic_delta"] = self.e.ic(weights=result.weights)-self.e.ic(weights=self.baseline.weights) if used else 0.
                row["reward"] = float(np.tanh(row["ic_delta"]/self.p.tau))
            elif self.p.reward_mode == "absolute_trade":
                row["reward"] = float(np.tanh(row["utility"]/self.p.tau)) if used else 0.
            return row
        except (ExpressionError, InvalidProposal) as exc:
            return {**row, "status": "quality_failure", "reason": str(exc), "reward": -1., "delta": None}

    def decision(self, rows):
        incumbent = dict(weights=self.incumbent, source="incumbent", artifact_id=self.incumbent_e["artifact_id"],
                         utility=self.incumbent_e["objective"]-self.p.beta*complexity(self.incumbent, self.p, self.space))
        contenders = [dict(weights=self.baseline.weights, source="refit_baseline", artifact_id=self.baseline_e["artifact_id"],
                           utility=self.baseline_e["objective"]-self.p.beta*self.baseline_c)]
        contenders += [dict(weights=r["weights"], source="candidate" if r["candidate_used"] else "old_factors_refit",
                            candidate_index=i, artifact_id=r["candidate_artifact"], utility=r["utility"])
                       for i, r in enumerate(rows) if r["status"] == "evaluated"]
        return commit_pool(incumbent, contenders, self.p)
