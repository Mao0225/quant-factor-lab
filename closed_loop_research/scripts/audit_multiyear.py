"""Run after the registered suite finishes; writes assertions and factual totals."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import sys
import numpy as np
from closed_loop_research.storage import read_json, atomic_json, digest, file_digest
from closed_loop_research.runner import load_state, code_identity
from closed_loop_research.protocol import Protocol
from closed_loop_research.expressions import ExpressionSpace
from closed_loop_research.evaluation import paired_reward, complexity


def audit(root, member=None):
    root = Path(root)
    manifest, result = read_json(root/'suite_manifest.json'), read_json(root/'comparison.json')
    archived = Path(__file__).resolve().parents[1]/'versions/multiyear_round1/closed_loop_research'
    archive_identity = digest({p.name:file_digest(p) for p in sorted(archived.glob('*.py'))}) if archived.exists() else None
    assert manifest['code_identity'] in {code_identity(), archive_identity}
    assert len(result['runs']) == len(manifest['groups'])*len(manifest['seeds'])
    summaries, checks = [], 0
    for row in result['runs']:
        run = Path(row['run'])
        if member is not None and run.name != member:
            continue
        p = Protocol.from_dict(read_json(run/'protocol.json'))
        space = ExpressionSpace(p)
        state = load_state(run)['state']
        frozen, test = read_json(run/'frozen_model.json'), read_json(run/'test_result.json')
        assert state['phase']=='finished' and state['batch']==p.batches
        assert state['stop_reason']=='registered_batches_complete'
        assert all(a['segment'] in 'FE' and a['role']=='train' and a['allowed'] for a in state['data_audit'])
        assert frozen['holdout_status']==test['holdout_status']=='previously_observed_historical'
        assert frozen['selected_batch'] in p.selection_batches
        assert test['frozen_model_id']==frozen['model_id']
        assert all(a['segment']=='T' and a['role']=='test' for a in test['data_audit'])
        selection=read_json(run/'selection.json')
        assert selection['logical_calls']==len(p.selection_batches)
        assert all(a['segment']=='V' and a['role']=='selection' for a in selection['data_audit'])
        assert state['budget']['logical_f']+state['budget']['logical_e']+selection['logical_calls']+test['logical_calls']<=p.max_backtests
        expected_updates=0 if p.generator!='ppo' else p.batches
        assert state['ppo_updates']==expected_updates
        previous=0
        candidates=positive=negative=legal_negative=failures=used=0
        for batch in state['completed']:
            assert batch['loaded_pool_version']==previous
            previous=batch['next_pool_version']
            assert sum(t['budgeted'] for t in batch['summary']['baseline']['trials'])==p.search_budget
            if p.generator=='ppo':
                update=batch['ppo_update']
                assert update['before']!=update['after'] and update['parameter_l2_change']>0
            for trial in batch['trials']:
                candidates+=1
                positive+=trial['reward']>0
                negative+=trial['reward']<0
                failures+=trial['status']=='quality_failure'
                legal_negative+=trial['status']=='evaluated' and trial['reward']<0
                used+=trial['candidate_used']
                expression=space.parse(trial['expression'])
                assert space.lookback(expression)<=p.max_lookback
                if trial['status']=='evaluated':
                    assert sum(t['budgeted'] for t in trial['search']['trials'])==p.search_budget
                    expect=paired_reward(trial['candidate_objective'],trial['baseline_objective'],
                                         trial['complexity_new'],trial['complexity_base'],trial['candidate_used'],p)
                    assert expect['reward']==trial['reward'] and expect['delta']==trial['delta']
                    checks+=1
                elif trial['status']=='quality_failure':
                    assert trial['reward']==-1
                else:
                    assert trial['status']=='duplicate' and trial['reward']==0
        assert candidates==(0 if p.generator=='fixed' else p.batches*p.episodes_per_batch)
        # Read every persisted artifact and re-hash its complete execution evidence.
        artifacts=0
        for directory in ['backtests','selection_backtests','test_backtests']:
            for path in (run/directory).glob('*.json.gz'):
                artifact=read_json(path)
                assert artifact['result_digest']==digest(artifact['result'])
                assert artifact['protocol_digest']==p.digest
                assert artifact['segment'] in dict(backtests='FE',selection_backtests='V',test_backtests='T')[directory]
                artifacts+=1
        receipts=[read_json(f) for f in (run/'backtests/invocations').glob('*.json')]
        assert all(r['status']=='completed' for r in receipts)
        assert len(receipts)==state['budget']['actual_f']+state['budget']['actual_e']
        print(f"Verified {run.name}: {artifacts} complete artifacts, {candidates} candidates", flush=True)
        summaries.append(dict(group=row['group'],seed=row['seed'],candidates=candidates,positive=positive,negative=negative,
                              legal_negative=legal_negative,quality_failures=failures,candidate_used=used,
                              pool_changes=state['pool_version'],ppo_updates=state['ppo_updates'],artifacts_verified=artifacts,
                              actual_backtests=len(receipts)+selection['actual_calls']+test['actual_calls'],
                              logical_backtests=state['budget']['logical_f']+state['budget']['logical_e']+selection['logical_calls']+test['logical_calls']))
    report=dict(passed=True,code_identity=manifest['code_identity'],runs=summaries,rewards_recomputed=checks,
                totals={k:sum(r[k] for r in summaries) for k in ['candidates','positive','negative','legal_negative','quality_failures','candidate_used','pool_changes','ppo_updates','artifacts_verified','actual_backtests','logical_backtests']})
    atomic_json(root/'acceptance.json' if member is None else root/'audit_parts'/f'{member}.json',report)
    return report


if __name__=='__main__':
    import json
    root=Path(sys.argv[1])
    members=[Path(r['run']).name for r in read_json(root/'comparison.json')['runs']]
    with ProcessPoolExecutor(max_workers=4) as pool:
        parts=list(pool.map(audit,[root]*len(members),members))
    report=dict(passed=all(p['passed'] for p in parts),code_identity=parts[0]['code_identity'],
                runs=[r for p in parts for r in p['runs']],rewards_recomputed=sum(p['rewards_recomputed'] for p in parts),
                totals={k:sum(p['totals'][k] for p in parts) for k in parts[0]['totals']})
    atomic_json(root/'acceptance.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
