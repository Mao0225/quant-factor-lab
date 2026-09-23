"""Verify A/B/C/E evidence without fitting, generating or executing new trades."""
from pathlib import Path
import argparse
import numpy as np
from ..data import DataAccess
from ..evaluation import SegmentEvaluator, paired_reward
from ..protocol import Protocol
from ..runner import load_state, code_identity
from ..storage import read_json, atomic_json, digest


def audit(root):
    root=Path(root)
    manifest=read_json(root/'suite_manifest.json')
    comparison=read_json(root/'comparison.json')
    assert manifest['code_identity']==code_identity()
    assert manifest['groups']==['A','B','C','E'] and len(manifest['seeds'])>=2
    assert len(comparison['runs'])==len(manifest['groups'])*len(manifest['seeds'])
    reports=[]
    for row in comparison['runs']:
        run=Path(row['run'])
        p=Protocol.from_dict(read_json(run/'protocol.json'))
        state=load_state(run)['state']
        assert state['phase']=='finished' and state['batch']==p.batches
        assert all(a['role']=='train' and a['segment'] in {'F','E'} and a['allowed'] for a in state['data_audit'])
        selection=read_json(run/'selection.json')
        frozen=read_json(run/'frozen_model.json')
        test=read_json(run/'test_result.json')
        assert digest({k:v for k,v in frozen.items() if k!='model_id'})==frozen['model_id']
        assert test['frozen_model_id']==selection['frozen_model_id']==frozen['model_id']
        assert frozen['selected_batch'] in p.selection_batches
        assert all(x['segment']=='V' and x['role']=='selection' for x in selection['data_audit'])
        assert all(x['segment']=='T' and x['role']=='test' for x in test['data_audit'])
        assert state['budget']['logical_f']+state['budget']['logical_e']+selection['logical_calls']+test['logical_calls']<=p.max_backtests
        assert state['ppo_updates']==(p.batches if p.generator=='ppo' else 0)
        ic=None
        if p.reward_mode=='single_ic':
            access=DataAccess(manifest['snapshot'],p,'train')
            ic=SegmentEvaluator(access.load('E'),p,run/'audit-no-backtest-execution')
        counts=dict(candidates=0,positive=0,negative=0,quality_failures=0,rewards_recomputed=0,artifacts_verified=0)
        previous=0
        for batch in state['completed']:
            assert batch['loaded_pool_version']==previous
            previous=batch['next_pool_version']
            if p.generator=='ppo':
                assert batch['ppo_update']['before']!=batch['ppo_update']['after']
                assert batch['ppo_update']['parameter_l2_change']>0
            for trial in batch['trials']:
                counts['candidates']+=1
                counts['positive']+=trial['reward']>0
                counts['negative']+=trial['reward']<0
                if trial['status']=='quality_failure':
                    counts['quality_failures']+=1
                    assert trial['reward']==-1
                elif trial['status']=='duplicate':
                    assert trial['reward']==0
                else:
                    expected=paired_reward(trial['candidate_objective'],trial['baseline_objective'],trial['complexity_new'],trial['complexity_base'],trial['candidate_used'],p)
                    assert expected['delta']==trial['delta']
                    reward=ic.ic(expression=trial['expression']) if ic else expected['reward']
                    assert np.isclose(reward,trial['reward'],rtol=1e-12,atol=1e-12)
                    counts['rewards_recomputed']+=1
        for directory in ('backtests','selection_backtests','test_backtests'):
            for path in (run/directory).glob('*.json.gz'):
                artifact=read_json(path)
                assert artifact['protocol_digest']==p.digest
                assert digest(artifact['result'])==artifact['result_digest']
                counts['artifacts_verified']+=1
        reports.append(dict(group=row['group'],seed=row['seed'],ppo_updates=state['ppo_updates'],pool_changes=state['pool_version'],**counts))
    report=dict(passed=True,code_identity=code_identity(),runs=reports,
                totals={key:sum(r[key] for r in reports) for key in reports[0] if key not in {'group','seed'}},
                note='Audit recomputed C rewards from E only; no new backtests or policy updates. Historical T already observed.')
    atomic_json(root/'v1_acceptance.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');args=parser.parse_args()
    result=audit(args.root)
    print(result['totals'])
