"""Import the entire historical 500-stock sample with documented causal features."""
from pathlib import Path
import numpy as np
import pandas as pd

from .features import engineer_features, FEATURE_LOOKBACKS, RAW_FIELDS, feature_formula
from .legacy import prototype_protocol
from .data import prepare_snapshot
from .storage import atomic_json, file_digest


def import_history(source, destination, seed=7):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    raw = pd.read_parquet(source, columns=["date", "code", *RAW_FIELDS, "Ifsuspend"])
    raw.date = pd.to_datetime(raw.date).dt.normalize()
    raw.code = raw.code.astype(str).str.zfill(6)
    if raw.duplicated(["date", "code"]).any():
        raise ValueError("duplicate historical date/code")
    dates, codes = sorted(raw.date.unique()), sorted(raw.code.unique())
    bounds = {}
    for segment, lo, hi in [("F", "2022-01-01", "2023-12-31"), ("E", "2024-01-01", "2024-12-31"),
                            ("V", "2025-01-01", "2025-12-31"), ("T", "2026-01-01", "2026-12-31")]:
        part = [d for d in dates if pd.Timestamp(lo) <= d <= pd.Timestamp(hi)]
        if not part:
            raise ValueError(f"source does not cover the registered {segment} period")
        bounds[segment] = [str(pd.Timestamp(part[0]).date()), str(pd.Timestamp(part[-1]).date())]
    index = pd.MultiIndex.from_product([dates, codes], names=["date", "code"])
    expanded = raw.set_index(["date", "code"]).reindex(index)
    known_mark = expanded.close.groupby(level="code").ffill()
    previous_mark = known_mark.groupby(level="code").shift(1)
    expanded["exec_open"] = expanded.open.fillna(previous_mark)
    expanded["exec_close"] = known_mark
    expanded["eligible"] = (expanded.close > 0) & (expanded.open > 0) & (expanded.volume > 0)
    # Never use today's eventual close or volume to decide an opening trade.
    # The legacy daily suspension flag is explicitly assumed to describe the whole day.
    expanded["can_buy_open"] = (expanded.open > 0) & expanded.Ifsuspend.eq(0)
    expanded["can_sell_open"] = expanded.can_buy_open
    expanded["share_multiplier"], expanded["cash_dividend"] = 1., 0.
    data = engineer_features(expanded.reset_index())
    p = prototype_protocol(dates, seed=seed, name="legacy500-multiyear", segments=bounds,
          fields=list(FEATURE_LOOKBACKS), windows=[1, 5, 10, 20, 60], max_tokens=15, max_factors=5,
          max_lookback=120, field_lookbacks=FEATURE_LOOKBACKS, operator_profile="extended", require_feature=True,
          compress_artifacts=True, holdout_status="previously_observed_historical",
          initial_expressions=["return_20", "neg(return_5)", "neg(volatility_20)"], initial_weights=[.4, .3, .3],
          batches=8, episodes_per_batch=16, search_budget=24, selection_batches=[2, 4, 8], max_backtests=10000,
          execution_note="Legacy adjustment/preprocessing unverified. No extra corporate actions assumed. Tradability uses positive observed opening price and daily suspension flag assumed all-day; no future close/volume filter, no intraday limit/volume model. Missing opening valuation uses strictly previous known close, close valuation carries past marks. No delisting settlement. Costs unchanged from first edition.")
    for field in p.fields:
        data[f"{field}__available_at"] = data.date+pd.Timedelta(hours=15)
    source_sha = file_digest(source)
    meta = {f: dict(verified=False, source=f"legacy SHA256 {source_sha}", unit="source units" if f in RAW_FIELDS else "dimensionless",
                    description=feature_formula(f), availability="causal daily feature, assumed available at close",
                    adjustment="legacy_unknown", history_sessions=FEATURE_LOOKBACKS[f],
                    prototype_assumption=p.execution_note) for f in p.fields}
    report = dict(source=str(source.resolve()), source_sha256=source_sha, source_rows=len(raw), copied_rows=len(data),
                  source_codes=len(codes), source_sessions=len(dates), source_start=str(pd.Timestamp(dates[0]).date()),
                  source_end=str(pd.Timestamp(dates[-1]).date()), segments=bounds,
                  signal_fields=len(p.fields), max_lookback=p.max_lookback, holdout_status=p.holdout_status,
                  split_note="2021 history is warm-up; F 2022-2023, E 2024, V 2025, T previously observed 2026 history")
    destination.mkdir(parents=True)
    # Full offline copy is outside the trainer's snapshot directory; runtime only loads F/E partitions.
    data.to_parquet(destination / "market.parquet", index=False)
    report["market_sha256"] = file_digest(destination / "market.parquet")
    atomic_json(destination / "protocol.json", p.to_dict())
    manifest = prepare_snapshot(data, destination / "snapshot", p, meta, source_metadata=report)
    report["snapshot_id"] = manifest["snapshot_id"]
    atomic_json(destination / "import_report.json", report)
    return report
