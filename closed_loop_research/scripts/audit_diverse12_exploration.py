"""Audit the registered six-run study using existing evidence only.

No market data is loaded and no backtest, selection, testing, or policy update
entry point is called. Only evidence_audit.json is written, after all six runs
have finished and already have their one-shot test_result.json.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re

import torch

from ..protocol import Protocol
from ..expressions import ExpressionSpace
from ..runner import code_identity, load_state
from ..storage import atomic_json, digest, file_digest, read_json


class NotReady(RuntimeError):
    """The audit never advances an unfinished experiment."""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(a, b, context):
    require(math.isfinite(float(a)) and math.isfinite(float(b)) and
            math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-12), context)


def active(weights):
    require(all(math.isfinite(float(w)) for w in weights.values()), 'nonfinite factor weight')
    return {k: float(v) for k, v in weights.items() if abs(float(v)) > 1e-12}


def model_digest(model):
    value = hashlib.sha256()
    for tensor in model.values():
        value.update(tensor.detach().cpu().numpy().tobytes())
    return value.hexdigest()


def permissions(entries, role, segments, snapshot):
    require(bool(entries), f'missing {role} data permissions')
    require({x['segment'] for x in entries} == set(segments), f'{role} segments differ')
    require(all(x['role'] == role and x['allowed'] is True and
                x['snapshot_id'] == snapshot for x in entries), f'{role} permission/snapshot mismatch')


def artifact_index(run, p, snapshot):
    """Verify full serialized results, retaining only compact lookup metadata."""
    result, receipt_counts = {}, {}
    for directory, segments in [('backtests', {'F', 'E'}), ('selection_backtests', {'V'}),
                                ('test_backtests', {'T'})]:
        paths = sorted(set((run / directory).glob('*.json')) |
                       set((run / directory).glob('*.json.gz')))
        require(bool(paths), f'{run.name}: no {directory} artifacts')
        for path in paths:
            artifact = read_json(path)
            segment = artifact['segment']
            require(segment in segments, f'{path}: segment boundary violation')
            require(artifact['protocol_digest'] == p.digest and artifact['snapshot_id'] == snapshot,
                    f'{path}: artifact identity mismatch')
            require(digest(artifact['result']) == artifact['result_digest'], f'{path}: result digest mismatch')
            key = digest(dict(protocol=p.digest, snapshot=snapshot, segment=segment,
                              bounds=list(p.bounds(segment)), weights=artifact['weights']))
            require(artifact['identity'] == key and path.name in {key+'.json', key+'.json.gz'},
                    f'{path}: artifact key mismatch')
            require(key not in result, f'duplicate physical artifact: {key}')
            result[key] = dict(segment=segment, weights=artifact['weights'],
                               objective=artifact['result']['metrics']['objective'],
                               result_digest=artifact['result_digest'])
        receipts = [read_json(path) for path in (run / directory / 'invocations').glob('*.json')]
        for receipt in receipts:
            require(receipt['segment'] in segments and receipt['protocol_digest'] == p.digest and
                    receipt['snapshot_id'] == snapshot, f'{directory}: invocation identity mismatch')
            if receipt['status'] == 'completed':
                require(receipt['artifact_id'] in result, f'{directory}: completed invocation lacks artifact')
        receipt_counts[directory] = {
            'actual': len(receipts), 'completed': sum(x['status'] == 'completed' for x in receipts),
            'seconds': sum(x['seconds'] or 0.0 for x in receipts),
            **{segment: sum(x['segment'] == segment for x in receipts) for segment in segments}}
    return result, receipt_counts


def verify_policy_checkpoints(run, saved, completed, identity):
    """Check actual stored tensors, not just the update log's claimed norm."""
    phases = {}
    for path in sorted((run / 'checkpoints').glob('*.pt')):
        checksum = file_digest(path)
        require(path.stem.endswith(checksum[:16]), f'{path}: checkpoint filename checksum differs')
        checkpoint = torch.load(path, map_location='cpu', weights_only=False)
        require(checkpoint['identity'] == identity, f'{path}: checkpoint identity differs')
        state = checkpoint['state']
        require(model_digest(checkpoint['trainer']['model']) == state['parameter_digest'],
                f'{path}: tensor parameter digest differs')
        if state['phase'] in {'evaluated', 'ppo_updated'} and state.get('pending'):
            key = (state['pending']['batch_id'], state['phase'])
            if key in phases:
                require(model_digest(phases[key]) == state['parameter_digest'],
                        f'{path}: conflicting durable phase checkpoints')
            phases[key] = checkpoint['trainer']['model']
    for batch in completed:
        bid, update = batch['batch_id'], batch['ppo_update']
        before, after = phases[(bid, 'evaluated')], phases[(bid, 'ppo_updated')]
        require(model_digest(before) == update['before'] and model_digest(after) == update['after'],
                f'batch {bid}: PPO log does not match durable tensors')
        require(list(before) == list(after), f'batch {bid}: parameter shape/key mismatch')
        distance = torch.cat([(after[k]-before[k]).flatten() for k in before]).norm().item()
        require(distance > 0 and math.isclose(distance, update['parameter_l2_change'],
                                             rel_tol=1e-5, abs_tol=1e-8),
                f'batch {bid}: actual PPO parameter change differs')
    require(model_digest(saved['trainer']['model']) == completed[-1]['ppo_update']['after'],
            'final policy does not match the last recorded PPO update')


def audit_run(row, run, saved, kernel):
    p = Protocol.from_dict(read_json(run / 'protocol.json'))
    require(p.digest == row['protocol_digest'] == Protocol.from_dict(row['protocol']).digest,
            f"{row['key']}: protocol differs from registration")
    experiment = read_json(run / 'experiment.json')
    identity = {k: experiment[k] for k in ('protocol_digest', 'snapshot_id', 'code_identity')}
    require(identity == saved['identity'] and identity['code_identity'] == kernel and
            identity['protocol_digest'] == p.digest, f"{row['key']}: kernel/protocol identity differs")
    snapshot = identity['snapshot_id']
    require(read_json(Path(experiment['snapshot_path']) / 'manifest.json')['snapshot_id'] == snapshot,
            'snapshot manifest differs')
    state = saved['state']
    require(state['phase'] == 'finished' and state['batch'] == p.batches, 'registered training not complete')
    require(p.reward_mode == 'trade_delta', 'this audit accepts registered trade_delta evidence only')
    space = ExpressionSpace(p)

    def complexity(weights):
        return sum(len(space.parse(expression).tokens) for expression in active(weights)) / (p.max_factors*p.max_tokens)
    permissions(state['data_audit'], 'train', {'F', 'E'}, snapshot)
    selection, frozen, test = [read_json(run / name) for name in
                              ('selection.json', 'frozen_model.json', 'test_result.json')]
    permissions(selection['data_audit'], 'selection', {'V'}, snapshot)
    permissions(test['data_audit'], 'test', {'T'}, snapshot)
    require(digest({k: v for k, v in frozen.items() if k != 'model_id'}) == frozen['model_id'],
            'frozen model content digest differs')
    require(frozen['model_id'] == selection['frozen_model_id'] == test['frozen_model_id'],
            'selection/frozen/test model identity differs')
    require(all(frozen[k] == identity[k] for k in identity), 'frozen experiment identity differs')
    require(selection['rule'] == frozen['rule'] == 'max_V_J_earliest_tie_no_refit', 'unexpected selection rule')
    checks = selection['checkpoints']
    require([x['batch_id'] for x in checks] == list(p.selection_batches), 'selection checkpoints differ')
    best = max(checks, key=lambda x: x['objective'])
    require(frozen['selected_batch'] == best['batch_id'] and frozen['weights'] == best['weights'] and
            frozen['selection_artifact'] == best['artifact_id'] and frozen['pool_version'] == best['pool_version'],
            'frozen model is not the registered V winner')
    close(frozen['selection_objective'], best['objective'], 'frozen V objective differs')
    artifacts, receipts = artifact_index(run, p, snapshot)

    def referenced(key, segment, objective=None, weights=None):
        require(key in artifacts and artifacts[key]['segment'] == segment, 'missing/cross-segment artifact')
        item = artifacts[key]
        if objective is not None:
            close(item['objective'], objective, 'referenced objective differs from artifact')
        if weights is not None:
            require(item['weights'] == active(weights), 'referenced weights differ from artifact')

    for check in checks:
        pool = read_json(run / 'pools' / f"batch-{check['batch_id']:04d}.json")
        require(pool['protocol_digest'] == p.digest and pool['registered_for_selection'] is True and
                pool['weights'] == check['weights'] and pool['pool_version'] == check['pool_version'],
                'V checkpoint differs from committed pool')
        referenced(check['artifact_id'], 'V', check['objective'], check['weights'])
    referenced(test['artifact_id'], 'T', test['objective'], frozen['weights'])
    close(test['metrics']['objective'], test['objective'], 'test metrics objective differs')
    counts = dict(candidates=0, positive=0, negative=0, quality_failures=0, duplicates=0,
                  rewards_recomputed=0, artifacts_verified=len(artifacts))
    previous, previous_version = dict(zip(p.initial_expressions, p.initial_weights)), 0
    logical_f, logical_e = 0, 0
    completed = state['completed']
    require([x['batch_id'] for x in completed] == list(range(1, p.batches+1)), 'missing/duplicate training batch')
    for batch in completed:
        bid, summary, trials = batch['batch_id'], batch['summary'], batch['trials']
        require(read_json(run / 'batches' / f'{bid:04d}-committed.json') == batch, 'committed batch differs')
        require(batch['loaded_pool_version'] == previous_version and summary['incumbent'] == previous,
                'training pool continuity differs')
        require(len(trials) == (0 if p.generator == 'fixed' else p.episodes_per_batch), 'candidate budget differs')
        referenced(summary['baseline_e']['artifact_id'], 'E', summary['baseline_e']['objective'], summary['baseline']['weights'])
        referenced(summary['incumbent_e']['artifact_id'], 'E', summary['incumbent_e']['objective'], previous)
        logical_f += p.search_budget
        logical_e += 2
        for trial in trials:
            counts['candidates'] += 1
            counts['positive'] += trial['reward'] > 0
            counts['negative'] += trial['reward'] < 0
            require(trial['batch_id'] == bid and trial['logical_baseline_budget'] == p.search_budget,
                    'trial batch/baseline budget differs')
            referenced(trial['baseline_artifact'], 'E', trial['baseline_objective'])
            if trial['status'] == 'quality_failure':
                require(trial['reward'] == -1 and trial['delta'] is None, 'quality-failure reward differs')
                counts['quality_failures'] += 1
            elif trial['status'] == 'duplicate':
                require(trial['reward'] == 0 and trial['delta'] == 0, 'duplicate reward differs')
                counts['duplicates'] += 1
            else:
                require(trial['status'] == 'evaluated', 'unknown trial outcome')
                referenced(trial['candidate_artifact'], 'E', trial['candidate_objective'], trial['weights'])
                require(trial['candidate_used'] == (trial['expression'] in active(trial['weights'])),
                        'candidate use flag differs from actual weights')
                close(trial['complexity_new'], complexity(trial['weights']), 'candidate formula complexity differs')
                close(trial['complexity_base'], complexity(summary['baseline']['weights']), 'baseline formula complexity differs')
                raw = trial['candidate_objective']-trial['baseline_objective']-p.beta*(trial['complexity_new']-trial['complexity_base'])
                delta = raw if trial['candidate_used'] else 0.0
                close(raw, trial['raw_comparison_delta'], 'raw paired delta differs')
                close(delta, trial['delta'], 'used-factor delta differs')
                close(math.tanh(delta/p.tau), trial['reward'], 'trade_delta reward differs')
                counts['rewards_recomputed'] += 1
                logical_e += 1
            logical_f += sum(x['budgeted'] for x in trial.get('search', {}).get('trials', []))
        decision = batch['decision']
        previous = decision['chosen']['weights']
        previous_version += bool(decision['changed'])
        require(batch['next_pool_version'] == previous_version, 'pool version continuity differs')
        pool = read_json(run / 'pools' / f'batch-{bid:04d}.json')
        require(pool['weights'] == previous and pool['pool_version'] == previous_version, 'committed pool differs')
        update = batch['ppo_update']
        require(read_json(run / 'batches' / f'{bid:04d}-ppo.json') == update, 'PPO receipt differs')
        if p.generator != 'ppo':
            require(update['skipped'] and update['before'] == update['after'] and update['parameter_l2_change'] == 0,
                    'non-PPO arm changed policy')
    require(state['pool'] == previous and state['pool_version'] == previous_version, 'final pool differs')
    expected_updates = p.batches if p.generator == 'ppo' else 0
    require(state['ppo_updates'] == expected_updates, 'PPO update budget differs')
    if p.generator == 'ppo':
        verify_policy_checkpoints(run, saved, completed, identity)
    budget = state['budget']
    require(budget['logical_f'] == logical_f and budget['logical_e'] == logical_e, 'training logical budget differs')
    require(budget['actual_f'] == receipts['backtests']['F'] and budget['actual_e'] == receipts['backtests']['E'] and
            budget['completed_backtests'] == receipts['backtests']['completed'], 'training invocation budget differs')
    close(budget['backtest_seconds'], receipts['backtests']['seconds'], 'backtest elapsed accounting differs')
    require(selection['logical_calls'] == len(checks) and test['logical_calls'] == 1, 'V/T logical budget differs')
    require(selection['actual_calls'] == receipts['selection_backtests']['actual'] and
            test['actual_calls'] == receipts['test_backtests']['actual'], 'V/T invocation budget differs')
    total = logical_f+logical_e+selection['logical_calls']+test['logical_calls']
    require(total <= p.max_backtests, 'registered total backtest cap exceeded')
    initial = active(dict(zip(p.initial_expressions, p.initial_weights)))
    weights = active(frozen['weights'])
    require(0 < len(initial) <= p.max_factors and 0 < len(weights) <= p.max_factors, 'factor count outside capacity')
    close(sum(abs(v) for v in weights.values()), 1.0, 'frozen L1 weight normalization differs')
    return dict(key=row['key'], experiment_id=row['experiment_id'], run=str(run), generator=p.generator,
                seed=p.seed, protocol_digest=p.digest, frozen_model_id=frozen['model_id'],
                initial_active_factors=len(initial), frozen_active_factors=len(weights),
                pool_changes=state['pool_version'], ppo_updates=expected_updates, selected_batch=best['batch_id'],
                logical_budget_total=total, max_backtests=p.max_backtests, training_budget=budget,
                V_objective=best['objective'], T_objective=test['objective'], **counts)


def audit(study):
    study = Path(study).resolve()
    registration = read_json(study / 'registration.json')
    rows = registration['rows']
    require(len(rows) == 6 and len({r['key'] for r in rows}) == 6 and
            len({r['experiment_id'] for r in rows}) == 6, 'expected six distinct registered study arms')
    # Registration maps to ordinary application experiments, not the older ABCE suite format.
    system_root = study.parent.parent
    require(system_root.name == 'system_v1' or (system_root / 'experiments').is_dir(), 'cannot locate app experiment root')
    runs, pending = [], []
    for row in rows:
        require(re.fullmatch(r'[A-Za-z0-9_-]+', row['experiment_id']) is not None, 'invalid experiment id')
        run = system_root / 'experiments' / row['experiment_id'] / 'run'
        if not (run / 'checkpoint.json').exists():
            pending.append(f"{row['key']}: no checkpoint")
            continue
        saved = load_state(run)
        if saved['state']['phase'] != 'finished' or not (run / 'test_result.json').exists():
            pending.append(f"{row['key']}: phase={saved['state']['phase']}, existing T={bool((run/'test_result.json').exists())}")
        runs.append((row, run, saved))
    if pending:
        raise NotReady('未就绪：必须六组均 finished 且已有 test_result；审计不会启动任何计算。\n'+'\n'.join(pending))
    prereg = read_json(study / 'preregistration.json')
    before = {r['key']: r for r in prereg['rows']}
    require(set(before) == {r['key'] for r in rows}, 'registered arms differ from preregistration')
    require(prereg['dataset_id'] == registration['dataset_id'], 'preregistered dataset differs')
    for row in rows:
        require(row['protocol'] == before[row['key']]['protocol'] and
                row['protocol_digest'] == before[row['key']]['protocol_digest'], 'protocol changed after preregistration')
        record = read_json(system_root / 'experiments' / row['experiment_id'] / 'record.json')
        require(record['dataset_id'] == registration['dataset_id'] and
                record['protocol_digest'] == row['protocol_digest'], 'application registration differs')
        require(datetime.fromisoformat(prereg['created_at']) <= datetime.fromisoformat(record['created_at']),
                'experiment predates its preregistration')
    pairs = []
    random = {r['protocol']['seed']: r for r in rows if r['protocol']['generator'] == 'random'}
    ppo = {r['protocol']['seed']: r for r in rows if r['protocol']['generator'] == 'ppo'}
    require(len(random) == len(ppo) == 2 and set(random) == set(ppo), 'expected two paired random/PPO seeds')
    require(sum(r['protocol']['generator'] == 'fixed' for r in rows) == 2, 'expected two fixed references')
    for seed, left in random.items():
        right = ppo[seed]
        diffs = {k for k in set(left['protocol']) | set(right['protocol'])
                 if left['protocol'].get(k) != right['protocol'].get(k)}
        require(diffs == {'name', 'generator'}, f'seed {seed}: unfair random/PPO protocol differences {diffs}')
        pairs.append(dict(seed=seed, random=left['key'], ppo=right['key'], differing_fields=sorted(diffs),
                          planned_candidates=left['protocol']['batches']*left['protocol']['episodes_per_batch'],
                          search_budget=left['protocol']['search_budget'], max_backtests=left['protocol']['max_backtests']))
    kernel = code_identity()
    reports = [audit_run(row, run, saved, kernel) for row, run, saved in runs]
    totals_keys = ('candidates', 'positive', 'negative', 'quality_failures', 'duplicates', 'rewards_recomputed',
                   'artifacts_verified', 'ppo_updates', 'pool_changes')
    report = dict(passed=True, audited_at=datetime.now(timezone.utc).isoformat(), code_identity=kernel,
                  registration_digest=digest(registration), preregistration_digest=digest(prereg),
                  protocol_fairness=pairs, runs=reports,
                  totals={key: sum(r[key] for r in reports) for key in totals_keys},
                  note='Read-only evidence audit; no new backtests, V/T evaluations, policy updates or market-data access. Equal registered training opportunities do not imply equal actual calls after quality failures/cache hits. T was previously observed historical data; this audit does not establish superiority.')
    atomic_json(study / 'evidence_audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', help='directory containing registration.json and preregistration.json')
    args = parser.parse_args()
    try:
        result = audit(args.study)
    except NotReady as exc:
        parser.exit(2, str(exc)+'\n')
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.exit(1, '证据核验失败：'+str(exc)+'\n')
    print(result['totals'])
