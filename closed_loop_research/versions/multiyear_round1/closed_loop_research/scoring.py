"""Identical eligibility and missing-value policy for training and frozen models."""
import numpy as np
import pandas as pd


class InvalidProposal(ValueError):
    pass


def standardized(frame, values, epsilon):
    v = pd.Series(np.asarray(values, dtype=float), index=frame.index)
    v = v.where(frame.eligible & np.isfinite(v))
    grouped = v.groupby(frame.date)
    mu = grouped.transform("mean")
    std = grouped.transform(lambda a: a.std(ddof=0))
    z = (v - mu) / std.clip(lower=epsilon)
    return z.fillna(0.).to_numpy(), v.notna().to_numpy()


def quality(frame, values, p):
    rows = []
    values = np.asarray(values)
    for day, idx in frame.groupby("date", sort=True).indices.items():
        eligible = frame.iloc[idx].eligible.to_numpy(dtype=bool)
        v = values[idx][eligible]
        finite = v[np.isfinite(v)]
        coverage = len(finite) / len(v) if len(v) else 1.
        degenerate = bool(len(v) and (len(finite) < 2 or np.std(finite) < p.epsilon))
        rows.append(dict(date=str(pd.Timestamp(day).date()), coverage=coverage, degenerate=degenerate))
    low = np.mean([r["coverage"] < p.min_daily_coverage for r in rows]) if rows else 1.
    deg = np.mean([r["degenerate"] for r in rows]) if rows else 1.
    return dict(passed=bool(low <= p.max_low_coverage_fraction and deg <= p.max_degenerate_fraction),
                low_coverage_fraction=float(low), degenerate_fraction=float(deg), days=rows)


def score(frame, values, weights, p):
    weights = {k: float(w) for k, w in weights.items() if abs(w) > 1e-12}
    if not weights or len(weights) > p.max_factors or not np.isclose(sum(abs(w) for w in weights.values()), 1.):
        raise InvalidProposal("weights must be finite, L1=1 and within pool capacity")
    result = frame[["date", "code", "eligible"]].copy()
    scores, observed = np.zeros(len(frame)), np.zeros(len(frame), dtype=bool)
    for key, weight in weights.items():
        if not np.isfinite(weight):
            raise InvalidProposal("nonfinite weight")
        z, present = standardized(frame, values[key], p.epsilon)
        scores += weight * z
        observed |= present
        result[f"contribution:{key}"] = weight * z
        result[f"missing:{key}"] = ~present
    if (frame.eligible.to_numpy(dtype=bool) & ~observed).any():
        raise InvalidProposal("all active factors missing on a fixed eligible sample")
    result["score"] = scores
    return result
