"""Preregister and execute the user's twelve-factor exploratory comparison via the app."""
import argparse
import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from closed_loop_research.protocol import Protocol
from closed_loop_research.storage import atomic_json, read_json


FACTORS = ['return_20', 'return_60', 'neg(return_1)', 'neg(return_5)',
           'neg(volatility_20)', 'neg(volatility_60)', 'volume_ratio_5', 'volume_ratio_20',
           'neg(ma_gap_5)', 'neg(ma_gap_20)', 'neg(range_relative)', 'neg(intraday_return)']


def protocols(template):
    dense = copy.deepcopy(template)
    dense.update(name='twelve-factor-exploration-v1', max_factors=16,
                 initial_expressions=FACTORS, initial_weights=[1/12]*12,
                 batches=4, episodes_per_batch=6, search_budget=12,
                 perturbations=[.05, .025, .01], restart_after=8,
                 selection_batches=[1, 2, 3, 4], max_backtests=1000, wall_seconds=None,
                 reward_mode='trade_delta', search_mode='adaptive')
    rows = []
    for key, title, expressions, weights in [
        ('fixed3', '三因子固定基准｜原组合不调权', template['initial_expressions'], template['initial_weights']),
        ('fixed12', '十二因子等权基准｜人工设定起点', FACTORS, [1/12]*12),
    ]:
        p = copy.deepcopy(dense)
        p.update(name=key+'-reference', generator='fixed', search_mode='fixed', seed=7,
                 batches=1, selection_batches=[1], search_budget=1,
                 initial_expressions=expressions, initial_weights=weights)
        rows.append(dict(key=key, name=title, protocol=p))
    for seed in [7, 19]:
        for generator, title in [('random', '随机候选搜索'), ('ppo', 'PPO交易反馈')]:
            p = copy.deepcopy(dense)
            key = f'{generator}{seed}'
            p.update(name=key+'-twelve-factor', generator=generator, seed=seed)
            rows.append(dict(key=key, name=f'十二因子起点·{title}｜种子{seed}｜4轮×6候选', protocol=p))
    for row in rows:
        row['protocol_digest'] = Protocol.from_dict(row['protocol']).digest
    return rows


def run(output, base_url):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=base_url, timeout=120)
    def request(method, route, body=None):
        response = client.request(method, '/api/'+route, json=body) if body is not None else client.request(method, '/api/'+route)
        response.raise_for_status()
        return response.json()
    registration = output/'registration.json'
    if registration.exists():
        record = read_json(registration)
    else:
        dataset = 'raw500_75b3494c10edbcd9'
        rows = protocols(request('GET', f'datasets/{dataset}/protocol'))
        # The plan and all parameter digests exist before any training dispatch.
        record = dict(created_at=datetime.now(timezone.utc).isoformat(), dataset_id=dataset,
                      purpose='12-formula starting pool; same-budget random/PPO seeds7/19; no factor-count guarantee for optimized arms',
                      selection_rule='keep all arms; individual automatic V selection; no T-driven choices',
                      rows=rows)
        atomic_json(output/'preregistration.json', record)
        project = request('POST', 'projects', dict(name='十二因子组合探索｜固定基准与随机/PPO对照',
            question='比较人工设计的12因子等权起点、原3因子基准和同预算随机/PPO组合搜索；所有组预先登记，不强制搜索保留12因子。'))
        record['project_id'] = project['id']
        for row in rows:
            experiment = request('POST', 'experiments', dict(project_id=project['id'], dataset_id=dataset,
                name=row['name'], protocol=row['protocol']))
            row['experiment_id'] = experiment['id']
        atomic_json(registration, record)
    rows = record['rows']
    for row in rows:
        current = request('GET', f"experiments/{row['experiment_id']}")
        if current['status'] == 'draft':
            row['job_id'] = request('POST', f"experiments/{row['experiment_id']}/start", {})['id']
            atomic_json(registration, record)
    previous, last_print = None, 0
    while True:
        states = []
        for row in rows:
            e = request('GET', f"experiments/{row['experiment_id']}")
            s = e.get('run_status', {})
            states.append(dict(key=row['key'], status=e['status'], batch=s.get('batch', 0),
                               pool_version=s.get('pool_version', 0), factors=len(s.get('pool', {})),
                               trials=len(e.get('trials', [])), error=e.get('error')))
        atomic_json(output/'progress.json', states)
        if states != previous or time.monotonic()-last_print >= 45:
            print(json.dumps(states, ensure_ascii=False), flush=True)
            previous, last_print = states, time.monotonic()
        if any(s['status'] in {'failed', 'stopped', 'interrupted', 'paused'} for s in states):
            raise RuntimeError('A registered run needs attention; inspect progress.json. No replacement or T test was launched.')
        if all(s['status'] == 'finished' for s in states):
            break
        time.sleep(5)
    # Every model is now frozen. Only now submit final historical tests.
    for row in rows:
        row['test_job_id'] = request('POST', f"experiments/{row['experiment_id']}/test", {})['id']
    atomic_json(registration, record)
    while True:
        jobs = [request('GET', 'jobs/'+r['test_job_id']) for r in rows]
        if any(j['status'] in {'failed', 'interrupted'} for j in jobs):
            raise RuntimeError('Final test failed; existing records retained')
        if all(j['status'] == 'succeeded' for j in jobs):
            break
        time.sleep(5)
    results = []
    for row in rows:
        e = request('GET', f"experiments/{row['experiment_id']}")
        model = request('GET', 'models/'+e['model_version'])
        trials = e['trials']
        ppo = [u for u in e['updates'] if not u.get('skipped')]
        results.append(dict(key=row['key'], name=row['name'], experiment_id=e['id'], model_version=e['model_version'],
            weights=model['weights'], factor_count=len(model['weights']), evaluation=model['evaluation'],
            trials=len(trials), quality_failures=sum(t['status']=='quality_failure' for t in trials),
            positive_rewards=sum(t['reward']>0 for t in trials), negative_rewards=sum(t['reward']<0 for t in trials),
            candidates_used=sum(t.get('candidate_used', False) for t in trials), ppo_updates=len(ppo),
            pool_version=e['run_status']['pool_version'], budget=e['run_status']['budget']))
    atomic_json(output/'results.json', dict(project_id=record['project_id'], rows=results,
        note='All pre-registered arms retained. Historical T was already observed. Prototype data; no significance claim.'))
    print('COMPLETE '+str(output/'results.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='closed_loop_research/workspace/system_v1/studies/twelve_factor_v1')
    parser.add_argument('--url', default='http://127.0.0.1:8767')
    args = parser.parse_args()
    run(args.output, args.url)
