from pathlib import Path
import importlib

import numpy as np
import pandas as pd
import pytest

from .helpers import metadata, panel, protocol
from closed_loop_research.data import prepare_snapshot, DataAccess
from closed_loop_research.evaluation import SegmentEvaluator
from closed_loop_research.runner import run_experiment
from closed_loop_research.selection import select_model
from closed_loop_research.storage import atomic_json, read_json, file_digest


class FixtureData:
    def __init__(self):
        self.market = panel()
        self.market['name'] = self.market.code.map({'000001': 'A', '000002': 'B', '000003': 'C'})
        self.market['board'] = self.market.code.map({'000001': 'main', '000002': 'growth', '000003': 'main'})
        self.market['listing_days'] = 1000.
        self.market['turnover'] = 2.
        self.market['amount'] = self.market.volume * self.market.close
        self.dataset = dict(id='dataset-test', name='Synthetic', status='ready',
                            latest_complete_date='2020-01-24', data_mode='legacy_prototype',
                            fields={k: {'enabled': True} for k in ['close', 'volume']},
                            field_metadata=metadata(),
                            scoring_contract={'eligibility': 'synthetic fixed eligible codes'},
                            universe={'codes': ['000001', '000002', '000003']},
                            filters={k: {'enabled': True, 'unit': 'test'} for k in ['board', 'listing_days', 'turnover', 'amount']})

    def get_dataset(self, dataset_id):
        if dataset_id != self.dataset['id']:
            raise ValueError('unknown dataset')
        return self.dataset.copy()

    def load_market(self, dataset_id):
        self.get_dataset(dataset_id)
        return self.market.copy()

    def list_datasets(self):
        return [self.get_dataset(self.dataset['id'])]


@pytest.fixture
def research(tmp_path):
    p = protocol(generator='fixed', batches=1, selection_batches=[1], search_budget=1,
                 initial_weights=[1.], top_k=1)
    snapshot = tmp_path/'snapshot'
    prepare_snapshot(panel(), snapshot, p, metadata(), source_metadata={'dataset_id': 'dataset-test'})
    run = tmp_path/'run'
    run_experiment(p, snapshot, run)
    select_model(run)
    return p, snapshot, run, FixtureData()


def service(root, data):
    path = Path(__file__).parents[1]/'app'/'models.py'
    assert path.exists(), 'v1 ModelService has not been implemented'
    return importlib.import_module('closed_loop_research.app.models').ModelService(root, data)


def test_model_pack_scores_without_run_and_matches_research(research, tmp_path):
    p, snapshot, run, data = research
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test', name='Test model')
    assert model['status'] == 'candidate' and model['data_ready']
    with pytest.raises(ValueError, match='available|可用'):
        app.select({'model_version': model['version_id'], 'top_n': 3})
    app.set_status(model['version_id'], 'available')
    data.dataset['latest_complete_date'] = '2020-01-14'
    ref = SegmentEvaluator(DataAccess(snapshot, p, 'train').load('E'), p, tmp_path/'reference')
    expected = ref.scores(model['weights'])
    expected = expected[expected.date == pd.Timestamp('2020-01-14')].set_index('code')
    run.rename(tmp_path/'unavailable-original-run')
    result = app.select({'model_version': model['version_id'], 'top_n': 3})
    assert result['data_date'] == '2020-01-14'
    for row in result['rows']:
        assert row['score'] == pytest.approx(expected.loc[row['code'], 'score'])
        assert sum(x['contribution'] for x in row['contributions']) == pytest.approx(row['score'])
    data.dataset['latest_complete_date'] = '2020-01-24'
    latest = app.select({'model_version': model['version_id'], 'top_n': 3})
    assert latest['data_date'] == '2020-01-24'
    assert latest['id'] != result['id']
    assert len(app.list_results()) == 2


def test_filter_after_full_scoring_before_top_n_and_unknowns_fail(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test')
    app.set_status(model['version_id'], 'available')
    full = app.select({'model_version': model['version_id'], 'top_n': 3})
    # Research top_k=1, but filtering must still find the second-ranked growth stock.
    filtered = app.select({'model_version': model['version_id'], 'filters': {'board': ['growth']}, 'top_n': 5})
    assert [r['code'] for r in filtered['rows']] == ['000002']
    reference = next(r for r in full['rows'] if r['code'] == '000002')
    assert filtered['rows'][0]['score'] == reference['score']
    assert filtered['counts']['scoring_universe'] == 3
    assert filtered['counts']['after_filter'] == filtered['counts']['selected'] == 1
    assert '自定义' in filtered['evaluation_note']
    with pytest.raises(ValueError, match='filter|过滤'):
        app.select({'model_version': model['version_id'], 'filters': {'market_cap': {'min': 0}}, 'top_n': 2})
    data.market.loc[data.market.code == '000002', 'turnover'] = np.nan
    empty = app.select({'model_version': model['version_id'], 'filters': {'board': ['growth'], 'turnover': {'min': 0}}, 'top_n': 5})
    assert empty['rows'] == []


def test_unavailable_attribute_is_not_presented_as_a_valid_zero(research,tmp_path):
    _,_,run,data=research
    app=service(tmp_path/'system',data)
    model=app.register_run(run,'dataset-test')
    app.set_status(model['version_id'],'available')
    data.market['turnover']=0.
    data.dataset['filters']['turnover']={'enabled':False,'reason':'suspected missing placeholder','unit':'percent'}
    result=app.select({'model_version':model['version_id'],'top_n':2})
    assert all(row['turnover'] is None for row in result['rows'])
    assert all(row['attribute_status']['turnover']['available'] is False for row in result['rows'])
    with pytest.raises(ValueError,match='unavailable'):
        app.select({'model_version':model['version_id'],'filters':{'turnover':{'max':3}}})


def test_metadata_disabled_history_and_immutable_plan_revisions(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test', name='Before')
    version = model['version_id']
    app.set_status(version, 'available')
    result = app.select({'model_version': version, 'top_n': 2})
    first = app.save_plan({'name': 'My plan', 'config': result['config']})
    second = app.save_plan({'id': first['id'], 'name': 'Updated', 'config': {**result['config'], 'top_n': 1}})
    assert second['revision'] == 2 and second['parent_id'] == first['id']
    assert second['id'] != first['id']
    assert app.get_plan(first['id'])['config']['top_n'] == 2
    changed = app.update_metadata(version, {'name': 'After', 'description': 'Text', 'tags': ['price'], 'researcher': 'Local researcher'})
    assert changed['version_id'] == version
    assert changed['researcher'] == 'Local researcher'
    with pytest.raises(ValueError):
        app.update_metadata(version, {'weights': {'volume': 1.}})
    app.set_status(version, 'disabled')
    assert app.get_result(result['id']) == result
    assert app.get_result(result['id'])['model_name'] == 'Before'
    assert app.get_plan(first['id'])['config']['model_version'] == version
    with pytest.raises(ValueError, match='available|可用'):
        app.select(first['config'])
    assert len(list((tmp_path/'system'/'models'/'audit').glob('*.json'))) >= 4


def test_invalid_source_pack_and_missing_universe_are_rejected(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    frozen = read_json(run/'frozen_model.json')
    frozen['weights'] = {'volume': 1.}
    atomic_json(run/'frozen_model.json', frozen)
    with pytest.raises(ValueError, match='identity|hash|modified|身份|修改'):
        app.register_run(run, 'dataset-test')


def test_missing_rows_and_disabled_filter_never_silently_change_scope(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test')
    app.set_status(model['version_id'], 'available')
    data.dataset['filters']['board']['enabled'] = False
    with pytest.raises(ValueError, match='filter|过滤'):
        app.select({'model_version': model['version_id'], 'filters': {'board': ['growth']}})
    data.market = data.market[data.market.code != '000003']
    with pytest.raises(ValueError, match='universe|范围|完整'):
        app.select({'model_version': model['version_id']})
    assert app.list_results() == []


def test_registered_package_identity_and_idempotent_registration(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    first = app.register_run(run, 'dataset-test')
    assert app.register_run(run, 'dataset-test')['version_id'] == first['version_id']
    assert len(app.list_models()) == 1
    with pytest.raises(ValueError):
        app.get_result('../protocol')
    data.dataset['latest_complete_date'] = None
    current = app.get_model(first['version_id'])
    assert not current['data_ready'] and current['blocked_reason']


def test_model_groups_default_versions_do_not_rebind_saved_plans(research, tmp_path):
    p, snapshot, run, data = research
    app = service(tmp_path/'system', data)
    first = app.register_run(run, 'dataset-test')
    app.set_status(first['version_id'], 'available')
    plan = app.save_plan({'name': 'Pinned', 'config': {'model_version': first['version_id'], 'top_n': 2}})
    from closed_loop_research.protocol import Protocol
    p2 = Protocol.from_dict({**p.to_dict(), 'seed': 19})
    run2 = tmp_path/'run2'
    run_experiment(p2, snapshot, run2)
    select_model(run2)
    second = app.register_run(run2, 'dataset-test')
    assert second['model_id'] != first['model_id']
    changed = app.update_metadata(second['version_id'], {'model_id': first['model_id'], 'default_version': second['version_id']})
    assert changed['model_id'] == first['model_id']
    assert app.get_model(first['version_id'])['default_version'] == second['version_id']
    assert app.get_plan(plan['id'])['config']['model_version'] == first['version_id']
    with pytest.raises(ValueError):
        app.update_metadata(first['version_id'], {'default_version': 'model_unknown'})


def test_appends_test_evidence_without_changing_package_or_availability(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    first = app.register_run(run, 'dataset-test')
    app.set_status(first['version_id'], 'available')
    package = tmp_path/'system'/'models'/'versions'/f"{first['version_id']}.json"
    original = file_digest(package)
    from closed_loop_research.selection import test_model as execute_test
    execute_test(run)
    updated = app.register_run(run, 'dataset-test')
    assert updated['version_id'] == first['version_id']
    assert updated['status'] == 'available'
    assert updated['evaluation']['test']['segment'] == 'T'
    assert file_digest(package) == original


def test_integrity_failure_is_exposed_as_data_blocked(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    first = app.register_run(run, 'dataset-test')
    from closed_loop_research.data import DataIntegrityError
    def corrupt(_):
        raise DataIntegrityError('dataset file changed')
    data.get_dataset = corrupt
    current = app.get_model(first['version_id'])
    assert not current['data_ready'] and 'changed' in current['blocked_reason']


def test_delayed_rank_scores_preserve_research_history(tmp_path):
    p = protocol(generator='fixed', batches=1, selection_batches=[1], search_budget=1,
                 initial_expressions=['mean_2(rank(delay_1(close)))'], initial_weights=[1.])
    snapshot = tmp_path/'snapshot'
    prepare_snapshot(panel(), snapshot, p, metadata(), source_metadata={'dataset_id': 'dataset-test'})
    run = tmp_path/'run'
    run_experiment(p, snapshot, run)
    select_model(run)
    data = FixtureData()
    data.dataset['latest_complete_date'] = '2020-01-14'
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test')
    app.set_status(model['version_id'], 'available')
    result = app.select({'model_version': model['version_id'], 'top_n': 3})
    evaluator = SegmentEvaluator(DataAccess(snapshot, p, 'train').load('E'), p, tmp_path/'reference')
    expected = evaluator.scores(model['weights'])
    expected = expected[expected.date == pd.Timestamp(result['data_date'])].set_index('code')
    for row in result['rows']:
        assert row['score'] == pytest.approx(expected.loc[row['code'], 'score'])


def test_ready_checks_current_coverage_and_frozen_field_semantics(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test')
    data.market.loc[(data.market.date == pd.Timestamp('2020-01-24')) & (data.market.code == '000001'), 'close'] = np.nan
    blocked = app.get_model(model['version_id'])
    assert not blocked['data_ready']
    with pytest.raises(ValueError):
        app.set_status(model['version_id'], 'available')
    data.market = FixtureData().market
    data.dataset['field_metadata']['close']['unit'] = 'different currency'
    blocked = app.get_model(model['version_id'])
    assert not blocked['data_ready'] and 'contract' in blocked['blocked_reason']


def test_saved_plan_uses_latest_compatible_dataset_but_result_locks_snapshot(research, tmp_path):
    _, _, run, data = research
    app = service(tmp_path/'system', data)
    model = app.register_run(run, 'dataset-test')
    app.set_status(model['version_id'], 'available')
    first = app.select({'model_version': model['version_id'], 'top_n': 2})
    plan = app.save_plan({'name': 'Updates data', 'config': first['config']})
    assert 'dataset_id' not in plan['config']
    original_get, original_load = data.get_dataset, data.load_market
    new = {**data.dataset, 'id': 'dataset-new', 'latest_complete_date': '2020-01-27'}
    extra = data.market[data.market.date == pd.Timestamp('2020-01-24')].copy()
    extra['date'] = pd.Timestamp('2020-01-27')
    for col in ['close__available_at', 'volume__available_at']:
        extra[col] = pd.Timestamp('2020-01-27 15:00')
    new_market = pd.concat([data.market, extra], ignore_index=True)
    data.get_dataset = lambda identifier: new.copy() if identifier == 'dataset-new' else original_get(identifier)
    data.list_datasets = lambda: [original_get('dataset-test'), new.copy()]
    data.load_market = lambda identifier: new_market.copy() if identifier == 'dataset-new' else original_load(identifier)
    current = app.get_model(model['version_id'])
    assert current['dataset_id'] == 'dataset-new' and current['source_dataset_id'] == 'dataset-test'
    second = app.select(app.get_plan(plan['id'])['config'])
    assert second['dataset_id'] == 'dataset-new' and second['data_date'] == '2020-01-27'
    assert second['model_version'] == first['model_version']
    assert app.get_result(first['id'])['dataset_id'] == 'dataset-test'
