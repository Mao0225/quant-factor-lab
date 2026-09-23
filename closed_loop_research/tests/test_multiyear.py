import numpy as np
import pandas as pd
import pytest

from .helpers import protocol
from closed_loop_research.features import engineer_features, FEATURE_LOOKBACKS
from closed_loop_research.history import import_history
from closed_loop_research.expressions import ExpressionSpace, ExpressionError
from closed_loop_research.protocol import Protocol
from closed_loop_research.data import DataAccess
from closed_loop_research.storage import read_json, file_digest


def long_panel():
    dates = pd.bdate_range("2021-06-18", "2026-06-16")
    t = np.arange(len(dates), dtype=float)
    parts = []
    for j, code in enumerate(["000001", "000002", "000003"]):
        close = 20+j*7+t*.015*(j+1)+np.sin(t/(3+j))*.5
        parts.append(pd.DataFrame(dict(date=dates, code=code, open=close-.1, close=close,
                         high=close+.4, low=close-.6, volume=1000+j*100+t,
                         amount=(1000+j*100+t)*close, Ifsuspend=0)))
    return pd.concat(parts).sort_values(["date", "code"]).reset_index(drop=True)


def test_features_use_only_past_and_population_volatility():
    raw = long_panel().iloc[:600].copy()
    result = engineer_features(raw)
    changed = raw.copy()
    cutoff = raw.date.unique()[130]
    changed.loc[changed.date > cutoff, ["open", "close", "high", "low", "volume", "amount"]] *= 77
    future_changed = engineer_features(changed)
    for name in FEATURE_LOOKBACKS:
        np.testing.assert_allclose(result.loc[result.date <= cutoff, name], future_changed.loc[future_changed.date <= cutoff, name], equal_nan=True)
    one = result[result.code == "000001"]
    assert one.return_20.iloc[80] == pytest.approx(one.close.iloc[80]/one.close.iloc[60]-1)
    expected = one.close.pct_change(fill_method=None).iloc[61:81].std(ddof=0)
    assert one.volatility_20.iloc[80] == pytest.approx(expected)
    raw.loc[raw.date < cutoff, "volume"] = 0.
    assert not np.isinf(engineer_features(raw).volume_ratio_20).any()


def test_explicit_lookback_includes_feature_history_and_masks_completion():
    p = protocol(fields=["close", "return_20"], windows=[1, 20, 60], max_tokens=15,
                 max_lookback=120, field_lookbacks={"close": 0, "return_20": 20},
                 operator_profile="extended", require_feature=True)
    assert p.warmup == 121
    space = ExpressionSpace(p)
    assert space.lookback(space.parse("mean_60(delay_20(return_20))")) == 99
    with pytest.raises(ExpressionError, match="history"):
        space.parse("delay_60(delay_60(return_20))")
    prefix = ["delay_60", "delay_60"]
    mask = space.mask(prefix)
    assert mask[space.ids["close"]]
    assert not mask[space.ids["return_20"]]
    assert not space.mask([])[space.ids["const:1"]]
    assert not mask[space.ids["mean_20"]]


def test_extended_operators_have_causal_exact_semantics():
    p = protocol(operator_profile="extended", windows=[1, 2, 5], max_tokens=15)
    space = ExpressionSpace(p)
    f = long_panel().iloc[:90].copy()
    f["eligible"] = True
    subset = f[f.code == "000001"]
    for op, method in [("std", "std"), ("min", "min"), ("max", "max")]:
        actual = space.evaluate(f"{op}_5(close)", f)[f.code == "000001"]
        rolling = subset.close.rolling(5, min_periods=5)
        expected = getattr(rolling, method)(ddof=0) if op == "std" else getattr(rolling, method)()
        np.testing.assert_allclose(actual, expected.to_numpy(), equal_nan=True)
    actual = space.evaluate("delta_5(close)", f)[f.code == "000001"]
    np.testing.assert_allclose(actual, subset.close.diff(5).to_numpy(), equal_nan=True)


def test_mask_reserves_history_for_required_derived_field():
    p = protocol(fields=['return_20'], initial_expressions=['return_20'], initial_weights=[1.],
                 field_lookbacks={'return_20':20}, max_lookback=120, max_tokens=4,
                 windows=[1,20,60], require_feature=True)
    space = ExpressionSpace(p)
    assert space.mask([])[space.ids['delay_60']]
    assert not space.mask(['delay_60'])[space.ids['delay_60']]
    assert space.mask(['delay_60'])[space.ids['neg']]


def test_full_history_snapshot_retains_source_and_labels_previously_seen_test(tmp_path):
    raw = long_panel()
    source = tmp_path / "old.parquet"
    raw.to_parquet(source, index=False)
    before = file_digest(source)
    report = import_history(source, tmp_path / "history")
    assert report["source_rows"] == report["copied_rows"] == len(raw)
    assert report["source_start"] == "2021-06-18"
    assert file_digest(source) == before
    p = Protocol.from_dict(read_json(tmp_path / "history/protocol.json"))
    assert p.holdout_status == "previously_observed_historical"
    assert p.initial_expressions != ("close",)
    assert p.max_tokens == 15 and max(p.windows) == 60 and p.max_factors == 5
    assert len(p.fields) >= 20
    assert p.bounds("F")[0].startswith("2022") and p.bounds("E")[0].startswith("2024")
    assert p.bounds("V")[0].startswith("2025") and p.bounds("T")[0].startswith("2026")
    access = DataAccess(tmp_path / "history/snapshot", p, "train")
    assert access.manifest["source_metadata"]["source_rows"] == len(raw)
    with pytest.raises(PermissionError):
        access.load("T")


def test_next_open_trade_flags_do_not_depend_on_same_day_close_or_volume(tmp_path):
    raw = long_panel()
    date = pd.Timestamp("2024-03-15")
    raw.loc[(raw.date == date) & (raw.code == "000001"), ["close", "volume"]] = [np.nan, 0.]
    source = tmp_path / "old.parquet"
    raw.to_parquet(source, index=False)
    import_history(source, tmp_path / "history")
    p = Protocol.from_dict(read_json(tmp_path / "history/protocol.json"))
    f = DataAccess(tmp_path / "history/snapshot", p, "train").load("E").frame
    row = f[(f.date == date) & (f.code == "000001")].iloc[0]
    assert row.can_buy_open and row.can_sell_open
    assert not row.eligible
