"""Next-open, long-only cash/share ledger. No next-close ranking or replacements."""
from dataclasses import dataclass, asdict
import math

import numpy as np
import pandas as pd


class ExecutionError(RuntimeError):
    """Run/data failure, never a candidate quality penalty."""


def objective(returns, p):
    returns = np.asarray(returns, dtype=float)
    if not len(returns) or not np.isfinite(returns).all() or (returns <= -1).any():
        raise ExecutionError("invalid returns / nonpositive NAV")
    logs = np.log1p(returns)
    result = p.annual_days * (logs.mean() - p.risk_lambda * logs.var(ddof=0) / 2)
    if not np.isfinite(result):
        raise ExecutionError("nonfinite objective")
    return float(result)


@dataclass
class BacktestResult:
    daily: list
    trades: list
    orders: list
    positions: list
    selections: list
    actions: list
    metrics: dict

    def to_dict(self):
        return asdict(self)


def prepare_market(frame):
    columns = ['date', 'code', 'open', 'close', 'exec_open', 'exec_close',
               'can_buy_open', 'can_sell_open', 'share_multiplier', 'cash_dividend']
    frame = frame[[c for c in columns if c in frame]].sort_values(['date', 'code'])
    return {pd.Timestamp(d): g.set_index('code').to_dict('index') for d, g in frame.groupby('date', sort=True)}


def backtest(frame, scores, start, end, p, prepared=None, rankings=None):
    groups = prepare_market(frame) if prepared is None else prepared
    signal_groups = rankings if rankings is not None else {pd.Timestamp(d): g for d, g in scores.groupby("date", sort=True)}
    dates = sorted(groups)
    holdings, cash, previous_nav = {}, float(p.initial_cash), float(p.initial_cash)
    daily, trades, orders, positions, selections, actions = [], [], [], [], [], []
    def fee(amount, side):
        return max(amount * (p.buy_fee if side == "buy" else p.sell_fee), p.minimum_fee) if amount > 0 else 0.
    def price(row, name):
        v = float(row.get(f"exec_{name}", row.get(name, np.nan)))
        if not math.isfinite(v) or v <= 0:
            raise ExecutionError(f"missing/invalid {name} valuation")
        return v
    for idx, date in enumerate(dates):
        if not pd.Timestamp(start) <= date <= pd.Timestamp(end):
            continue
        if idx == 0 or dates[idx-1] not in signal_groups:
            raise ExecutionError("previous-session signal required at interval boundary")
        day, stamp = groups[date], str(date.date())
        # Entitlements apply only to yesterday's position, before today's trading.
        for code, shares in list(holdings.items()):
            if code not in day:
                raise ExecutionError(f"missing held security {code} on {stamp}")
            row = day[code]
            mult, dividend = float(row["share_multiplier"]), float(row["cash_dividend"])
            if mult != 1 or dividend != 0:
                cash += shares * dividend
                holdings[code] = shares * mult
                actions.append(dict(date=stamp, code=code, previous_shares=shares,
                                    share_multiplier=mult, cash_received=shares*dividend))
        nav_open = cash + sum(shares * price(day[c], "open") for c, shares in holdings.items())
        previous_signal = signal_groups[dates[idx-1]]
        if rankings is None:
            eligible = previous_signal.loc[previous_signal.eligible & np.isfinite(previous_signal.score)]
            chosen = eligible.sort_values(["score", "code"], ascending=[False, True], kind="stable").head(p.top_k)
            selected, chosen_scores = chosen.code.tolist(), chosen.score.tolist()
        else:
            selected, chosen_scores = previous_signal
        selections.append(dict(date=stamp, signal_date=str(dates[idx-1].date()),
                               codes=selected, scores=[float(x) for x in chosen_scores]))
        target = {}
        for c in selected:
            row = day.get(c)
            if row is None or not np.isfinite(row.get("exec_open", row.get("open", np.nan))) or row.get("exec_open", row.get("open", 0)) <= 0:
                target[c] = holdings.get(c, 0.)
                orders.append(dict(date=stamp, code=c, side="buy", requested=0., shares=0., reason="missing_open"))
            else:
                target[c] = math.floor((nav_open / p.top_k) / price(row, "open") / p.lot_size) * p.lot_size
        turnover, fees, slippage = 0., 0., 0.
        # Sell every surplus, including retained names above their target.
        proposals = [("sell", c, max(0., holdings[c] - target.get(c, 0.))) for c in sorted(holdings)]
        proposals += [("buy", c, max(0., target[c] - holdings.get(c, 0.))) for c in selected]
        for side, code, requested in proposals:
            if requested <= 1e-10:
                continue
            row = day.get(code)
            order = dict(date=stamp, code=code, side=side, requested=requested, shares=0., reason="blocked")
            if row is None or not row[f"can_{side}_open"]:
                orders.append(order)
                continue
            raw_price = price(row, "open")
            fill_price = raw_price * (1 + p.slippage if side == "buy" else 1 - p.slippage)
            shares = requested
            if side == "buy":
                affordable = min(cash / (fill_price * (1 + p.buy_fee)), max(0., cash-p.minimum_fee) / fill_price)
                shares = min(requested, math.floor(affordable / p.lot_size) * p.lot_size)
            amount = shares * fill_price
            cost = fee(amount, side)
            if shares <= 0 or (side == "sell" and amount < cost):
                order["reason"] = "cash_or_minimum_fee"
                orders.append(order)
                continue
            if side == "sell":
                cash += amount - cost
                holdings[code] -= shares
                if holdings[code] <= 1e-10:
                    del holdings[code]
            else:
                cash -= amount + cost
                holdings[code] = holdings.get(code, 0.) + shares
            if cash < -1e-7:
                raise ExecutionError("negative cash")
            cash = max(0., cash)
            turnover += amount
            fees += cost
            slip = shares * abs(fill_price - raw_price)
            slippage += slip
            trade = dict(date=stamp, code=code, side=side, price=fill_price, shares=shares, amount=amount, fee=cost, slippage=slip)
            trades.append(trade)
            order.update(shares=shares, reason="filled" if shares == requested else "partial_cash")
            orders.append(order)
        stock_value = sum(shares * price(day[c], "close") for c, shares in holdings.items())
        nav = cash + stock_value
        if nav <= 0 or not math.isfinite(nav):
            raise ExecutionError("nonpositive/nonfinite NAV")
        for c, shares in sorted(holdings.items()):
            value = shares * price(day[c], "close")
            positions.append(dict(date=stamp, code=c, shares=shares, price=price(day[c], "close"), value=value, weight=value/nav))
        daily.append(dict(date=stamp, nav=nav, cash=cash, stock_value=stock_value,
                          net_return=nav/previous_nav-1, fee=fees, slippage=slippage,
                          turnover=turnover/previous_nav, holding_count=len(holdings),
                          invested_fraction=stock_value/nav))
        previous_nav = nav
    returns = np.array([r["net_return"] for r in daily])
    j = objective(returns, p)
    navs = np.array([p.initial_cash] + [r["nav"] for r in daily])
    logs = np.log1p(returns)
    metrics = dict(objective=j, annual_return=float(np.expm1(logs.mean()*p.annual_days)),
                   annual_volatility=float(logs.std(ddof=0)*np.sqrt(p.annual_days)),
                   max_drawdown=float(np.min(navs/np.maximum.accumulate(navs)-1)),
                   total_return=float(navs[-1]/navs[0]-1), average_turnover=float(np.mean([r["turnover"] for r in daily])),
                   total_fees=float(sum(r["fee"] for r in daily)), total_slippage=float(sum(r["slippage"] for r in daily)),
                   average_invested_fraction=float(np.mean([r["invested_fraction"] for r in daily])),
                   average_holding_count=float(np.mean([r["holding_count"] for r in daily])))
    return BacktestResult(daily, trades, orders, positions, selections, actions, metrics)
