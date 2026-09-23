"""Read-only F/E parity audit; never opens V/T partitions or evaluation artifacts.

Run from the repository parent directory::

    python -m closed_loop_research.scripts.verify_v1_scoring --run RUN --output REPORT

Use --require-frozen after normal model selection to include the frozen weights.
Only the requested report is written; no experiment state/budget is changed.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from closed_loop_research.app.model_scoring import compute_scores, scorer_identity
from closed_loop_research.data import DataAccess
from closed_loop_research.evaluation import SegmentEvaluator
from closed_loop_research.expressions import ExpressionSpace
from closed_loop_research.protocol import Protocol
from closed_loop_research.storage import atomic_json, digest, file_digest, read_json


def verify(run, require_frozen=False):
    run = Path(run).resolve()
    p = Protocol.from_dict(read_json(run/'protocol.json'))
    experiment = read_json(run/'experiment.json')
    if p.digest != experiment['protocol_digest']:
        raise ValueError('protocol differs from locked experiment')
    access = DataAccess(experiment['snapshot_path'], p, 'train')
    if access.manifest['snapshot_id'] != experiment['snapshot_id']:
        raise ValueError('snapshot differs from locked experiment')
    universe = access.manifest['source_metadata']['universe']
    if digest(universe['codes']) != universe['hash']:
        raise ValueError('source universe hash mismatch')
    space = ExpressionSpace(p)
    cases = [dict(name='registered_initial', kind='diagnostic',
                  weights=dict(zip(p.initial_expressions, p.initial_weights)))]
    cases.append(dict(name='nested_119_session_history', kind='diagnostic',
                      weights={'mean_60(delay_60(close))': .6, 'neg(return_20)': .4}))
    frozen_path = run/'frozen_model.json'
    if require_frozen and not frozen_path.exists():
        raise ValueError('frozen model is required but normal model selection has not finished')
    if frozen_path.exists():
        frozen = read_json(frozen_path)
        if digest({k: v for k, v in frozen.items() if k != 'model_id'}) != frozen['model_id']:
            raise ValueError('frozen model hash mismatch')
        if any(frozen[key] != experiment[key] for key in ('protocol_digest', 'snapshot_id', 'code_identity')):
            raise ValueError('frozen model identity mismatch')
        cases.append(dict(name='selected_frozen', kind='frozen_model',
                          frozen_model_id=frozen['model_id'], weights=frozen['weights']))
    report = dict(schema=1, created_at=datetime.now(timezone.utc).isoformat(),
                  source_run=str(run), source_dataset_id=access.manifest['source_metadata']['dataset_id'],
                  snapshot_id=experiment['snapshot_id'], protocol_digest=p.digest,
                  source_kernel_identity=experiment['code_identity'], scorer_identity=scorer_identity(),
                  verifier_sha256=file_digest(__file__), universe=universe,
                  data_mode=p.data_mode, holdout_status=p.holdout_status,
                  interpretation='Scoring parity only; prototype price/corporate-action assumptions remain. '
                                 'Diagnostic cases are not selected models. No performance claim or new holdout claim.',
                  tolerance=dict(rtol=1e-12, atol=1e-12), cases=cases)
    for case in cases:
        nodes = [space.parse(expr) for expr in case['weights']]
        case['lookback'] = max(space.lookback(node) for node in nodes)
        case['required_fields'] = sorted({t for n in nodes for t in n.tokens if t in p.fields})
        case['checks'] = []
    for segment in ('F', 'E'):
        data = access.load(segment)
        # scores() is pure; evaluate() (backtest/cache/receipt writes) is never called.
        reference = SegmentEvaluator(data, p, run/'unused-parity-artifacts')
        days = sorted(set(data.signal_dates))
        selected_days = sorted({days[0], days[len(days)//2], days[-1]})
        for case in cases:
            weights = case['weights']
            bundle = dict(protocol=p.to_dict(), weights=weights, universe=universe,
                          required_fields=case['required_fields'], lookback=case['lookback'],
                          scorer_identity=report['scorer_identity'])
            expected_all = reference.scores(weights)
            for day in selected_days:
                actual = compute_scores(bundle, data.frame, day).sort_values('code').reset_index(drop=True)
                expected = expected_all.loc[expected_all.date == day].sort_values('code').reset_index(drop=True)
                aligned = actual[['date', 'code', 'eligible']].equals(expected[['date', 'code', 'eligible']])
                cols = ['score']+[f'contribution:{expr}' for expr in weights]
                errors = {col: float(np.max(np.abs(actual[col].to_numpy()-expected[col].to_numpy()))) for col in cols}
                numeric = all(np.allclose(actual[col], expected[col], rtol=1e-12, atol=1e-12) for col in cols)
                missing = all(np.array_equal(actual[f'missing:{expr}'], expected[f'missing:{expr}']) for expr in weights)
                def ranking(frame):
                    return frame.loc[frame.eligible].sort_values(['score', 'code'], ascending=[False, True]).code.tolist()
                rank_equal = ranking(actual) == ranking(expected)
                case['checks'].append(dict(segment=segment, date=str(pd.Timestamp(day).date()),
                                          rows=len(actual), aligned=aligned, max_absolute_errors=errors,
                                          numeric_equal=bool(numeric), missing_flags_equal=bool(missing),
                                          complete_eligible_ranking_equal=rank_equal,
                                          passed=bool(aligned and numeric and missing and rank_equal)))
    report['data_access_audit'] = access.audit
    report['passed'] = all(row['passed'] for case in cases for row in case['checks'])
    report['partitions_opened'] = [entry['segment'] for entry in access.audit]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--require-frozen', action='store_true')
    args = parser.parse_args()
    report = verify(args.run, args.require_frozen)
    atomic_json(args.output, report)
    checks = sum(len(case['checks']) for case in report['cases'])
    print(f"passed={report['passed']} checks={checks} partitions={report['partitions_opened']} report={args.output}")
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
