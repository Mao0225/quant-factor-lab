"""The catalogue explains existing evidence without opening market/backtest payloads."""
import pytest

from closed_loop_research.app.research import ResearchService
from closed_loop_research.storage import atomic_json


def service(tmp_path):
    atomic_json(tmp_path/'experiments'/'example'/'record.json', {'id':'example','status':'finished'})
    return ResearchService(tmp_path, None, None, None), tmp_path/'experiments'/'example'/'run'


def artifact(run, key, segment, *, receipt=True, exists=True):
    directory = {'F':'backtests','E':'backtests','V':'selection_backtests','T':'test_backtests'}[segment]
    if exists:
        path = run/directory/f'{key}.json.gz'
        path.parent.mkdir(parents=True, exist_ok=True)
        # Deliberately unreadable: catalogue must use metadata, never decompress payloads.
        path.write_bytes(b'not a backtest payload')
    if receipt:
        atomic_json(run/'backtests'/'invocations'/f'{key}.json',
                    dict(status='completed', artifact_id=key, segment=segment))


def test_shared_e_and_f_artifacts_keep_all_meaningful_references(tmp_path):
    svc, run = service(tmp_path)
    artifact(run, 'shared-e', 'E')
    artifact(run, 'shared-f', 'F')
    weights = {'return_20':1., 'return_5':0.}
    for batch_id in [1, 2]:
        search = dict(artifact_id='shared-f', objective=.3, weights=weights,
                      trials=[dict(artifact_id='shared-f', index=0, proposal=weights, objective=.3)])
        atomic_json(run/'batches'/f'{batch_id:04d}-committed.json', dict(
            batch_id=batch_id,
            summary=dict(incumbent=weights, incumbent_e=dict(artifact_id='shared-e', objective=.2),
                         baseline=search, baseline_e=dict(artifact_id='shared-e', objective=.2)),
            trials=[dict(expression='volume_ratio_5', candidate_artifact='shared-e',
                         candidate_objective=.2, weights=weights, search=search)],
            decision=dict(chosen=dict(artifact_id='shared-e', weights=weights, source='incumbent'))))
    rows = {r['artifact_id']:r for r in svc.backtests('example')}
    e = rows['shared-e']
    assert e['roles'] == ['adopted', 'candidate', 'baseline', 'incumbent']
    assert len(e['references']) == 8
    assert {r['batch_id'] for r in e['references']} == {1, 2}
    assert e['factor_count'] == 1 and e['objective'] == .2
    assert '当轮采用' in e['label'] and 'shared-e' not in e['label']
    f = rows['shared-f']
    assert len(f['references']) == 4
    assert {r.get('candidate_index') for r in f['references']} == {None, 1}
    assert all(r['search_step'] == 1 for r in f['references'])


def test_uncommitted_or_unrun_evidence_cannot_expand_permission(tmp_path):
    svc, run = service(tmp_path)
    artifact(run, 'orphan-f', 'F')
    artifact(run, 'unrun-t', 'T')
    artifact(run, 'no-receipt', 'E', receipt=False)
    artifact(run, 'missing-file', 'F', exists=False)
    atomic_json(run/'batches'/'0001-committed.json', dict(batch_id=1, summary={}, trials=[],
                decision=dict(chosen=dict(artifact_id='no-receipt', weights={'x':1}))))
    atomic_json(run/'batches'/'0002-pending.json', dict(batch_id=2, summary={}, trials=[],
                decision=dict(chosen=dict(artifact_id='orphan-f', weights={'x':1}))))
    rows = svc.backtests('example')
    assert len(rows) == 1 and rows[0]['artifact_id'] == 'orphan-f'
    assert rows[0]['label'] == '训练期 · 中间权重方案 1'
    assert rows[0]['references'] == [] and 'batch_id' not in rows[0]
    with pytest.raises(PermissionError):
        svc.backtest('example', 'unrun-t')


def test_selected_checkpoint_is_frozen_choice_and_t_requires_record(tmp_path):
    svc, run = service(tmp_path)
    artifact(run, 'validation-shared', 'V', receipt=False)
    artifact(run, 'final-existing', 'T', receipt=False)
    checkpoints = [dict(artifact_id='validation-shared',batch_id=b,weights={'x':1},objective=.4)
                   for b in [2,3]]
    atomic_json(run/'selection.json', dict(checkpoints=checkpoints,frozen_model_id='model-one'))
    atomic_json(run/'frozen_model.json', dict(model_id='model-one',selected_batch=2,
                selection_artifact='validation-shared',selection_objective=.4,weights={'x':1}))
    rows = svc.backtests('example')
    assert len(rows) == 1 and rows[0]['segment'] == 'V'
    assert rows[0]['roles'] == ['selected', 'validation']
    assert len(rows[0]['references']) == 3
    assert rows[0]['batch_id'] == 2 and '已选中' in rows[0]['label']
    atomic_json(run/'test_result.json', dict(artifact_id='final-existing',objective=.1))
    rows = svc.backtests('example')
    assert rows[0]['roles'] == ['final_test'] and rows[0]['segment'] == 'T'
    assert rows[0]['factor_count'] == 1 and rows[0]['objective'] == .1
    assert '冻结组合' in rows[0]['label']


def test_experiment_detail_exposes_actual_decision_without_repeating_search(tmp_path):
    svc, run = service(tmp_path)
    decision=dict(changed=False, chosen=dict(source='incumbent',weights={'x':1},utility=.2),
                  reason='incumbent_threshold_not_met')
    atomic_json(run/'batches'/'0001-committed.json', dict(
        batch_id=1, loaded_pool_version=0, next_pool_version=0, decision=decision,
        trials=[dict(expression='y',reward=0)],
        summary=dict(incumbent={'x':1}, incumbent_e={'objective':.2},baseline_e={'objective':.1},
                     baseline=dict(weights={'x':-1},objective=.3,artifact_id='f',trials=[{'large':'search'}]))))
    result=svc.detail('example')
    assert result['batches'][0]['decision']==decision
    assert result['batches'][0]['loaded_pool_version']==0
    assert result['batches'][0]['summary']['baseline']['weights']=={'x':-1}
    assert 'trials' not in result['batches'][0]
    assert 'trials' not in result['batches'][0]['summary']['baseline']
    assert result['trials']==[dict(expression='y',reward=0,batch_id=1)]
