from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from .helpers import metadata, panel, protocol, snapshot
from closed_loop_research.protocol import Protocol
from closed_loop_research.data import DataAccess, prepare_snapshot, DataIntegrityError
from closed_loop_research.expressions import ExpressionSpace, ExpressionError
from closed_loop_research.scoring import score, quality, InvalidProposal
from closed_loop_research.backtest import backtest, objective, ExecutionError


def test_protocol_strict_immutable_and_temporal():
    p = protocol()
    with pytest.raises(FrozenInstanceError):
        p.top_k = 3
    with pytest.raises(ValueError):
        protocol(segments={"F": ["2020-01-01", "2020-02-01"],
                           "E": ["2020-01-20", "2020-03-01"],
                           "V": ["2020-04-01", "2020-04-02"],
                           "T": ["2020-05-01", "2020-05-02"]})
    with pytest.raises(ValueError):
        protocol(tau=0)
    with pytest.raises(ValueError):
        protocol(windows=[-1])
    with pytest.raises(ValueError):
        Protocol.from_dict({"name": "incomplete"})
    assert p.digest == Protocol.from_dict(p.to_dict()).digest


def test_training_does_not_open_selection_or_test(tmp_path):
    p, path = snapshot(tmp_path)
    # Poison future files: development must still load without hashing/parsing them.
    (path / "T.parquet").write_bytes(b"must never be opened by training")
    (path / "V.parquet").write_bytes(b"must never be opened by training")
    access = DataAccess(path, p, role="train")
    fit = access.load("F")
    assert fit.frame.date.max() <= pd.Timestamp(p.bounds("F")[1])
    with pytest.raises(PermissionError):
        access.load("T")
    with pytest.raises(PermissionError):
        access.load("V")
    assert [x["segment"] for x in access.audit if x["allowed"]] == ["F"]


def test_snapshot_detects_used_partition_tamper_and_refuses_overwrite(tmp_path):
    p, path = snapshot(tmp_path)
    with pytest.raises(FileExistsError):
        prepare_snapshot(panel(), path, p, metadata())
    with (path / "F.parquet").open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(DataIntegrityError):
        DataAccess(path, p, role="train").load("F")


def test_unverified_or_missing_time_fields_fail_closed(tmp_path):
    m = metadata()
    m["close"]["verified"] = False
    with pytest.raises(ValueError):
        prepare_snapshot(panel(), tmp_path / "bad", protocol(), m)
    with pytest.raises(ValueError):
        prepare_snapshot(panel().drop(columns="can_buy_open"), tmp_path / "bad2", protocol(), metadata())


def test_late_data_mask_and_no_future_influence(tmp_path):
    p = protocol()
    a = panel()
    a.loc[a.date == pd.Timestamp("2020-01-07"), "close__available_at"] = pd.Timestamp("2020-01-08 15:00")
    prepare_snapshot(a, tmp_path / "s", p, metadata())
    f = DataAccess(tmp_path / "s", p, role="train").load("F")
    space = ExpressionSpace(p)
    first = space.evaluate("mean_2(close)", f.frame)
    changed = f.frame.copy()
    changed.loc[changed.date > pd.Timestamp("2020-01-07"), "close"] *= 1000
    second = space.evaluate("mean_2(close)", changed)
    past = f.frame.date <= pd.Timestamp("2020-01-07")
    np.testing.assert_allclose(first[past], second[past], equal_nan=True)
    assert f.frame.loc[f.frame.date == pd.Timestamp("2020-01-07"), "close"].isna().all()
    for expr in ["delay_-1(close)", "__import__('os')", "mean_3(close)", "future_return", "mean_2.5(close)"]:
        with pytest.raises(ExpressionError):
            space.parse(expr)


def test_standardization_eligibility_missing_and_stable_order():
    p = protocol()
    f = pd.DataFrame({"date": [pd.Timestamp("2020-01-03")] * 3,
                      "code": ["b", "a", "c"], "eligible": [True, True, False]})
    values = {"a": np.array([1., 3., 1000.]), "b": np.array([np.nan, 8., 8.])}
    out = score(f, values, {"a": 1.}, p)
    np.testing.assert_allclose(out.score.iloc[:2], [-1., 1.])
    assert not out.eligible.iloc[2]
    assert score(f, values, {"a": 0.5, "b": 0.5}, p).score.notna().all()
    with pytest.raises(InvalidProposal):
        score(f, values, {"b": 1.}, p)
    assert not quality(f, np.array([1., 1., 1.]), p)["passed"]


def trading_frame():
    return pd.DataFrame([
        dict(date=pd.Timestamp(d), code=c, open=o, close=cl, eligible=True,
             can_buy_open=True, can_sell_open=True, share_multiplier=1., cash_dividend=0.)
        for d, c, o, cl in [
            ("2020-01-03", "a", 10., 10.), ("2020-01-03", "b", 10., 10.),
            ("2020-01-06", "a", 20., 22.), ("2020-01-06", "b", 10., 10.),
            ("2020-01-07", "a", 22., 22.), ("2020-01-07", "b", 10., 10.)]])


def signals(frame, ranks=(1., 0.)):
    s = frame[["date", "code", "eligible"]].copy()
    s["score"] = [ranks[0] if c == "a" else ranks[1] for c in s.code]
    return s


def test_next_open_cash_costs_no_overnight_gain_and_first_day_drawdown():
    f = trading_frame()
    p = protocol(top_k=1, buy_fee=0.01, minimum_fee=1.)
    result = backtest(f, signals(f), "2020-01-06", "2020-01-06", p)
    # 49 shares * 20 + 9.8 fee; cash 10.2; close value 1078.
    assert result.daily[0]["nav"] == pytest.approx(1088.2)
    assert result.daily[0]["cash"] == pytest.approx(10.2)
    assert result.trades[0]["date"] == "2020-01-06"
    assert result.trades[0]["shares"] == 49
    flat = f.copy()
    flat.loc[flat.date == pd.Timestamp("2020-01-06"), "close"] = flat.loc[flat.date == pd.Timestamp("2020-01-06"), "open"]
    assert backtest(flat, signals(flat), "2020-01-06", "2020-01-06", p).metrics["max_drawdown"] < 0


def test_less_than_k_no_rescale_and_buy_block_no_substitute():
    f = trading_frame()
    s = signals(f)
    s.loc[s.code == "b", "eligible"] = False
    r = backtest(f, s, "2020-01-06", "2020-01-06", protocol())
    assert r.daily[0]["cash"] == 500.
    f.loc[(f.date == pd.Timestamp("2020-01-06")) & (f.code == "a"), "can_buy_open"] = False
    r = backtest(f, signals(f), "2020-01-06", "2020-01-06", protocol(top_k=1))
    assert r.daily[0]["nav"] == 1000.
    assert not r.trades
    assert r.orders[0]["reason"] == "blocked"


def test_failed_sell_retains_holding_and_no_leverage():
    f = trading_frame()
    s = signals(f)
    s.loc[(s.date == pd.Timestamp("2020-01-06")) & (s.code == "b"), "score"] = 2.
    f.loc[(f.date == pd.Timestamp("2020-01-07")) & (f.code == "a"), "can_sell_open"] = False
    r = backtest(f, s, "2020-01-06", "2020-01-07", protocol(top_k=1))
    assert r.positions[-1]["code"] == "a"
    assert r.daily[-1]["cash"] >= 0
    assert r.daily[-1]["holding_count"] == 1
    assert any(o["side"] == "sell" and o["reason"] == "blocked" for o in r.orders)


def test_split_dividend_and_unknown_mark_fail():
    f = trading_frame()
    idx = (f.date == pd.Timestamp("2020-01-07")) & (f.code == "a")
    f.loc[idx, ["open", "close", "share_multiplier", "cash_dividend"]] = [10.5, 10.5, 2., 1.]
    r = backtest(f, signals(f), "2020-01-06", "2020-01-07", protocol(top_k=1))
    assert r.daily[-1]["nav"] == pytest.approx(1100.)
    f.loc[idx, "close"] = np.nan
    with pytest.raises(ExecutionError):
        backtest(f, signals(f), "2020-01-06", "2020-01-07", protocol(top_k=1))


def test_objective_uses_population_variance_and_rejects_bankruptcy():
    r = np.array([0.02, -0.01, 0.])
    logs = np.log1p(r)
    assert objective(r, protocol()) == pytest.approx(252 * (logs.mean() - 0.5 * logs.var()))
    with pytest.raises(ExecutionError):
        objective([-1.], protocol())
