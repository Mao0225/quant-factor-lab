"""Frozen, date-explicit scoring. This module never loads a run or a PPO checkpoint."""
from pathlib import Path

import numpy as np
import pandas as pd

from ..expressions import ExpressionSpace
from ..protocol import Protocol
from ..scoring import score
from ..storage import digest, file_digest


def scorer_identity():
    kernel = Path(__file__).parents[1]
    files = [kernel/name for name in ('expressions.py', 'scoring.py', 'features.py', 'protocol.py')]
    files.append(Path(__file__))
    return digest({p.name: file_digest(p) for p in files})


def field_contract(metadata):
    """Source location can change; units, formula and information timing cannot."""
    return {key: metadata.get(key, 0 if key == 'history_sessions' else None)
            for key in ('unit', 'description', 'availability', 'adjustment', 'history_sessions')}


def validate_dataset_contract(bundle, dataset):
    for field, expected in bundle['field_contracts'].items():
        current = dataset.get('field_metadata', {}).get(field)
        if current is None or field_contract(current) != expected:
            raise ValueError(f'field calculation contract mismatch: {field}')
    expected = bundle.get('dataset_scoring_contract')
    if expected is not None:
        if expected != dataset.get('scoring_contract'):
            raise ValueError('dataset scoring/eligibility contract mismatch')
    elif dataset['id'] != bundle['dataset_id']:
        raise ValueError('cross-dataset scoring requires an explicit compatible eligibility contract')


def compute_scores(bundle, market, as_of):
    """Return the entire frozen universe on as_of, before user filters or Top N.

    Derived fields are materialized by the dataset's registered feature pipeline.
    Historical rows remain present for nested rolling/rank expressions; no future
    row is evaluated and no next-session execution date is required.
    """
    if bundle['scorer_identity'] != scorer_identity():
        raise ValueError('model scorer identity changed; use the registered implementation')
    p = Protocol.from_dict(bundle['protocol'])
    required = set(bundle['required_fields'])
    columns = {'date', 'code', 'eligible'} | required | {f'{f}__available_at' for f in required}
    if not columns.issubset(market):
        raise ValueError(f'model required fields unavailable: {sorted(columns-set(market))}')
    day = pd.Timestamp(as_of).normalize()
    scope = set(bundle['universe']['codes'])
    # DataService's shared market can be large. Project rows and columns before
    # copying; do not mutate it or duplicate unrelated source/audit attributes.
    source_dates = pd.to_datetime(market.date, errors='raise').dt.normalize()
    source_codes = market.code.astype(str)
    in_scope = source_codes.isin(scope) & (source_dates <= day)
    dates = sorted(source_dates.loc[in_scope].unique())
    history = bundle['lookback']
    if not dates or pd.Timestamp(dates[-1]) != day or len(dates) < history+1:
        raise ValueError('latest date or required historical sessions unavailable')
    selected_rows = in_scope & (source_dates >= dates[-(history+1)])
    attributes = [c for c in ('name', 'board', 'listing_days', 'amount', 'turnover') if c in market]
    frame = market.loc[selected_rows, sorted(columns | set(attributes))].copy()
    frame['date'] = source_dates.loc[selected_rows]
    frame['code'] = source_codes.loc[selected_rows]
    frame = frame.sort_values(['date', 'code']).reset_index(drop=True)
    if frame.duplicated(['date', 'code']).any():
        raise ValueError('duplicate date/code in model universe')
    # A missing row must not shift a rolling expression onto a different calendar.
    if any(set(g.code) != scope for _, g in frame.groupby('date', sort=False)):
        raise ValueError('incomplete frozen scoring universe; missing rows cannot change scope')
    if frame.eligible.isna().any() or not frame.eligible.isin([True, False]).all():
        raise ValueError('explicit basic eligibility is required')
    frame['eligible'] = frame.eligible.astype(bool)
    for field in required:
        frame[field] = pd.to_numeric(frame[field], errors='raise')
        available = pd.to_datetime(frame[f'{field}__available_at'], errors='raise')
        frame.loc[available.isna() | (available > frame.date+pd.Timedelta(hours=15)), field] = np.nan
    space = ExpressionSpace(p)
    mask = (frame.date == day).to_numpy()
    today = frame.loc[mask].reset_index(drop=True)
    weights = bundle['weights']
    values = {expr: space.evaluate(expr, frame)[mask] for expr in weights}
    scored = score(today, values, weights, p)
    # Keep source attributes alongside exactly the research scoring output.
    for attr in attributes:
        scored[attr] = today[attr].to_numpy()
    for expr, raw in values.items():
        scored[f'raw:{expr}'] = raw
    return scored
