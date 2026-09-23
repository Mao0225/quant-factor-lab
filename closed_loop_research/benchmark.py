"""F/E-only throughput measurement; never opens model-selection/test data."""
from pathlib import Path
import time
from .data import DataAccess
from .evaluation import SegmentEvaluator
from .storage import atomic_json


def benchmark(p, snapshot, output):
    output = Path(output)
    audit, rows = [], []
    access = DataAccess(snapshot, p, 'train', audit)
    for segment in 'FE':
        started = time.perf_counter()
        evaluator = SegmentEvaluator(access.load(segment), p, output / segment)
        preparation = time.perf_counter()-started
        for weights in [p.initial_weights, (.3, .4, .3), (.3, .3, .4)]:
            started = time.perf_counter()
            result = evaluator.evaluate(dict(zip(p.initial_expressions, weights)))
            rows.append(dict(segment=segment, seconds=time.perf_counter()-started,
                             preparation_seconds=preparation, **result))
    report = dict(protocol_digest=p.digest, snapshot_id=access.manifest['snapshot_id'],
                  data_audit=audit, measurements=rows,
                  bytes=sum(f.stat().st_size for f in output.rglob('*.gz')))
    atomic_json(output / 'benchmark.json', report)
    return report
