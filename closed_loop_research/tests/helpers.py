from dataclasses import replace

import pandas as pd


def protocol(**changes):
    from closed_loop_research.protocol import Protocol
    raw = dict(
        name="synthetic-test", synthetic=True, seed=7,
        segments={"F": ["2020-01-06", "2020-01-09"],
                  "E": ["2020-01-10", "2020-01-15"],
                  "V": ["2020-01-16", "2020-01-20"],
                  "T": ["2020-01-21", "2020-01-24"]},
        fields=["close", "volume"], windows=[1, 2], constants=[-1., 1.],
        max_tokens=7, max_factors=2, top_k=2, initial_cash=1000., lot_size=1,
        buy_fee=0., sell_fee=0., minimum_fee=0., slippage=0.,
        annual_days=252, risk_lambda=1., beta=0.01, tau=0.1, delta=1e-8,
        min_daily_coverage=0.8, max_low_coverage_fraction=0.25,
        max_degenerate_fraction=0.25, epsilon=1e-8,
        search_budget=8, perturbations=[1., 0.5, 0.1], restart_after=2,
        batches=2, episodes_per_batch=4, selection_batches=[1, 2],
        max_backtests=1000, wall_seconds=None, ic_horizon=1,
        reward_mode="trade_delta", generator="ppo", search_mode="adaptive",
        ppo_epochs=3, learning_rate=0.002, clip_ratio=0.2,
        value_coefficient=0.5, entropy_coefficient=0.01,
        initial_expressions=["close"], initial_weights=[1.],
        universe_note="SYNTHETIC fixed codes; not a research result",
        execution_note="SYNTHETIC raw prices, explicit open flags and corporate actions",
    )
    raw.update(changes)
    return Protocol.from_dict(raw)


def panel():
    rows = []
    for t, date in enumerate(pd.bdate_range("2019-12-02", "2020-01-24")):
        for j, code in enumerate(["000001", "000002", "000003"]):
            price = 10. + j * 3. + t * (j + 1) * 0.02
            rows.append(dict(date=date, code=code, open=price, close=price + j * 0.03,
                             volume=100. + (2 - j) * 20. + t,
                             eligible=True, can_buy_open=True, can_sell_open=True,
                             share_multiplier=1., cash_dividend=0.,
                             close__available_at=date + pd.Timedelta(hours=15),
                             volume__available_at=date + pd.Timedelta(hours=15)))
    return pd.DataFrame(rows)


def metadata():
    return {name: dict(verified=True, source="synthetic fixture", unit="test-unit",
                       description=name, availability="row available_at <= signal close",
                       adjustment="raw") for name in ["close", "volume"]}


def snapshot(tmp_path, p=None):
    from closed_loop_research.data import prepare_snapshot
    p = p or protocol()
    path = tmp_path / "snapshot"
    prepare_snapshot(panel(), path, p, metadata())
    return p, path
