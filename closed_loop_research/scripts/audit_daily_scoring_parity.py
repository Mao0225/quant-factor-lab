"""Measure every F/E signal date against the unchanged frozen serving scorer.

No backtests, model updates or V/T access. Retains strict 1e-12 results and
measures an explicitly separate absolute error bound and exact ranking parity.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from closed_loop_research.app.model_scoring import compute_scores, scorer_identity
from closed_loop_research.data import DataAccess
from closed_loop_research.evaluation import SegmentEvaluator
from closed_loop_research.expressions import ExpressionSpace
from closed_loop_research.protocol import Protocol
from closed_loop_research.storage import atomic_json, digest, read_json


def audit(run, output):
    run, output = Path(run), Path(output)
    p = Protocol.from_dict(read_json(run/'protocol.json'))
    identity = read_json(run/'experiment.json')
    frozen = read_json(run/'frozen_model.json')
    assert p.digest == identity['protocol_digest'] == frozen['protocol_digest']
    assert digest({k:v for k,v in frozen.items() if k != 'model_id'}) == frozen['model_id']
    access = DataAccess(identity['snapshot_path'], p, 'train')
    space = ExpressionSpace(p)
    weights = frozen['weights']
    nodes = [space.parse(expr) for expr in weights]
    bundle = dict(protocol=p.to_dict(), weights=weights,
                  universe=access.manifest['source_metadata']['universe'],
                  required_fields=sorted({t for n in nodes for t in n.tokens if t in p.fields}),
                  lookback=max(space.lookback(n) for n in nodes), scorer_identity=scorer_identity())
    report = dict(source_run=str(run.resolve()), frozen_model_id=frozen['model_id'],
                  scorer_identity=bundle['scorer_identity'], strict_tolerance=1e-12,
                  diagnostic_absolute_bound=1e-9, days=[],
                  interpretation='Numerical diagnostic, not a changed scoring implementation. '
                  'Strict failures are retained separately. No V/T and no backtests.')
    def ranking(frame):
        return frame.loc[frame.eligible].sort_values(['score','code'],ascending=[False,True]).code.tolist()
    for segment in ('F','E'):
        data = access.load(segment)
        reference = SegmentEvaluator(data,p,run/'unused-daily-parity-artifacts')
        all_scores = reference.scores(weights)
        for index, (day, expected) in enumerate(all_scores.groupby('date',sort=True)):
            expected = expected.sort_values('code').reset_index(drop=True)
            actual = compute_scores(bundle,data.frame,day).sort_values('code').reset_index(drop=True)
            cols = ['score']+[f'contribution:{expr}' for expr in weights]
            errors = {c:float(np.max(np.abs(actual[c].to_numpy()-expected[c].to_numpy()))) for c in cols}
            strict = all(np.allclose(actual[c],expected[c],rtol=1e-12,atol=1e-12) for c in cols)
            r1,r2=ranking(actual),ranking(expected)
            report['days'].append(dict(segment=segment,date=str(pd.Timestamp(day).date()),
                aligned=actual[['date','code','eligible']].equals(expected[['date','code','eligible']]),
                missing_flags_equal=all(np.array_equal(actual[f'missing:{e}'],expected[f'missing:{e}']) for e in weights),
                max_absolute_errors=errors, strict_numeric_equal=bool(strict),
                absolute_bound_met=bool(all(np.isfinite(v) and v<=1e-9 for v in errors.values())),
                complete_ranking_equal=r1==r2, top50_equal=r1[:50]==r2[:50]))
            if (index+1)%50==0:
                print(f'{segment}: {index+1} dates audited',flush=True)
    checks=report['days']
    report.update(data_access_audit=access.audit,days_checked=len(checks),
                  strict_failed_days=sum(not x['strict_numeric_equal'] for x in checks),
                  max_absolute_error=max(max(x['max_absolute_errors'].values()) for x in checks),
                  exact_ranking_all_days=all(x['complete_ranking_equal'] for x in checks),
                  top50_all_days=all(x['top50_equal'] for x in checks),
                  diagnostic_bound_met=all(x['absolute_bound_met'] and x['aligned'] and x['missing_flags_equal'] for x in checks))
    atomic_json(output,report)
    print({k:report[k] for k in ('days_checked','strict_failed_days','max_absolute_error','exact_ranking_all_days','top50_all_days','diagnostic_bound_met')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    audit(args.run,args.output)
