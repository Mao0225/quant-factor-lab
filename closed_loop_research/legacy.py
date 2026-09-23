"""Read-only migration of the old 500-code snapshot into a labelled prototype."""
from pathlib import Path
import numpy as np
import pandas as pd

from .protocol import Protocol
from .data import prepare_snapshot
from .storage import atomic_json, file_digest


def prototype_protocol(dates, seed=7, max_tokens=7, windows=(1, 3), **overrides):
    n = len(dates)
    cuts = [0, int(n*.4), int(n*.67), int(n*.83), n]
    if min(np.diff(cuts)) < 2:
        raise ValueError("at least two sessions required in each segment")
    segments = {s: [str(pd.Timestamp(dates[cuts[i]]).date()), str(pd.Timestamp(dates[cuts[i+1]-1]).date())] for i, s in enumerate("FEVT")}
    config = dict(name="legacy-500-prototype", synthetic=False, seed=seed, segments=segments,
                  fields=["open", "close", "volume"], windows=list(windows), constants=[-1., 0., 1.],
                  max_tokens=max_tokens, max_factors=3, top_k=50, initial_cash=1000000., lot_size=100,
                  buy_fee=0.0003, sell_fee=0.0013, minimum_fee=5., slippage=0.0005,
                  annual_days=252, risk_lambda=1., beta=0.01, tau=0.1, delta=1e-8,
                  min_daily_coverage=0.95, max_low_coverage_fraction=0.05, max_degenerate_fraction=0.2,
                  epsilon=1e-8, search_budget=8, perturbations=[1., .5, .1], restart_after=2,
                  batches=3, episodes_per_batch=4, selection_batches=[1, 2, 3], max_backtests=1000,
                  wall_seconds=None, ic_horizon=1, reward_mode="trade_delta", generator="ppo", search_mode="adaptive",
                  ppo_epochs=4, learning_rate=0.001, clip_ratio=0.2, value_coefficient=0.5, entropy_coefficient=0.01,
                  initial_expressions=["close"], initial_weights=[1.], data_mode="legacy_prototype",
                  universe_note="Fixed legacy 500-code sample, chosen using 2021-2024 liquidity; prototype, selection/survivorship bias unresolved.",
                  execution_note="Legacy price adjustment unverified. Assume no cash dividends/splits; open-price tradability approximation, daily suspension flags, no limit-price/volume-cap model. Missing rows frozen at last observed close; no delisting settlement. Costs are prototype assumptions.")
    config.update(overrides)
    return Protocol.from_dict(config)


def import_legacy(source, destination, sessions=120, warmup=22, seed=7):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    if warmup < 8:
        raise ValueError("warmup must be >= 8")
    windows = (1, max(1, (warmup-1)//7))
    windows = tuple(sorted(set(windows)))
    fields = ["date", "code", "open", "close", "volume", "Ifsuspend"]
    raw = pd.read_parquet(source, columns=fields)
    raw.date = pd.to_datetime(raw.date).dt.normalize()
    raw.code = raw.code.astype(str).str.zfill(6)
    if raw.duplicated(["date", "code"]).any():
        raise ValueError("legacy data contains duplicates")
    dates = sorted(raw.date.unique())
    if len(dates) < sessions + warmup:
        raise ValueError("source does not contain requested sessions + warm-up")
    chosen_dates, codes = dates[-(sessions+warmup):], sorted(raw.code.unique())
    selected = raw[raw.date.isin(chosen_dates)].copy()
    p = prototype_protocol(chosen_dates[-sessions:], seed=seed, windows=windows)
    # Keep all original codes. Forward valuations use only past observations, including
    # history before the copied window. Missing dates cannot trade or supply a signal.
    index = pd.MultiIndex.from_product([dates, codes], names=["date", "code"])
    expanded = raw.set_index(["date", "code"]).reindex(index)
    observed = expanded.close.notna() & expanded.open.notna()
    mark = expanded.close.groupby(level="code").ffill()
    expanded["eligible"] = observed & (expanded.close > 0) & (expanded.open > 0) & (expanded.volume > 0)
    tradable = observed & (expanded.open > 0) & expanded.Ifsuspend.eq(0) & (expanded.volume > 0)
    expanded["can_buy_open"], expanded["can_sell_open"] = tradable, tradable
    previous_mark = mark.groupby(level="code").shift(1)
    expanded["open"] = expanded.open.fillna(previous_mark)
    expanded["close"] = expanded.close.fillna(mark)
    expanded["volume"] = expanded.volume.fillna(0.)
    expanded["share_multiplier"], expanded["cash_dividend"] = 1., 0.
    data = expanded.reset_index()
    data = data[data.date.isin(chosen_dates)].copy()
    for field in p.fields:
        data[f"{field}__available_at"] = data.date + pd.Timedelta(hours=15)
    sha = file_digest(source)
    metadata = {f: dict(verified=False, source=f"legacy market.parquet SHA256 {sha}",
                         unit="shares" if f == "volume" else "legacy price unit", description=f,
                         availability="assumed known by daily close; vendor availability not audited",
                         adjustment="legacy_unknown", prototype_assumption=p.execution_note) for f in p.fields}
    destination.mkdir(parents=True)
    atomic_json(destination / "protocol.json", p.to_dict())
    manifest = prepare_snapshot(data, destination / "snapshot", p, metadata)
    report = dict(source=str(source.resolve()), source_sha256=sha, copied_sessions=len(chosen_dates),
                  evaluation_sessions=sessions, source_codes=len(codes), observed_codes_in_window=int(selected.code.nunique()),
                  observed_rows=len(selected), copied_rows=len(data), padded_untradable_rows=len(data)-len(selected),
                  snapshot_id=manifest["snapshot_id"], data_mode=p.data_mode,
                  segments=p.to_dict()["segments"], assumptions=[p.universe_note, p.execution_note])
    atomic_json(destination / "import_report.json", report)
    return report
