import copy
import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from custom_bt.factor_composition import FACTOR_PREPROCESS, daily_cross_section_zscore


@pytest.fixture
def selection_api():
    try:
        return importlib.import_module('custom_bt.stock_selection')
    except ModuleNotFoundError:
        pytest.fail('stock selection backend must exist')


@pytest.fixture
def fixture(tmp_path):
    store = tmp_path / 'master'
    stocks = store / 'stocks'
    stocks.mkdir(parents=True)
    codes = ['000001', '000002', '000003', '000004']
    for idx, code in enumerate(codes):
        pd.DataFrame({
            'date': pd.to_datetime(['2024-01-04', '2024-01-05', '2024-01-08']),
            'code': code, 'close': [10.0 + idx, 11.0 + idx, 90.0 + idx],
            'signal': [float(idx), float(idx), 1000.0 * idx],
            'other': [float(3 - idx)] * 3, 'Ifsuspend': [0, int(idx == 3), 0],
            'ChiName': 'Stock ' + code,
        }).to_parquet(stocks / (code + '.parquet'), index=False)
    (store / 'meta.json').write_text(json.dumps({'source_signature': 'version-1'}))
    pools = tmp_path / 'pools'
    pool = pools / 'pool1'
    pool.mkdir(parents=True)
    (pool / 'manifest.json').write_text(json.dumps({'pool_id': 'pool1', 'selected_codes': codes, 'source_signature': 'version-1'}))
    (pool / 'codes.txt').write_text('\n'.join(codes))
    comp = tmp_path / 'composite'
    comp.mkdir()
    (comp / 'manifest.json').write_text(json.dumps({
        'result_type': 'composite', 'pool_id': 'pool1', 'run_name': 'fixed strategy',
        'created_at': '2024-01-06T10:00:00',
        'config': {'backtest': {'end_date': '2024-01-04'}},
    }))
    weights = [{'factor_id': 'f1', 'expression': 'ts_mean(signal,2)', 'weight': 2.0, 'preprocess': FACTOR_PREPROCESS},
               {'factor_id': 'f2', 'expression': 'other', 'weight': -0.5, 'preprocess': FACTOR_PREPROCESS}]
    (comp / 'factor_weights.json').write_text(json.dumps(weights))
    return store, pools, comp, tmp_path / 'selections'


def test_snapshot_and_reproducible_original_cross_section(selection_api, fixture):
    store, pools, comp, out = fixture
    strategy = selection_api.load_strategy(comp, pools)
    assert strategy['fingerprint'] == selection_api.load_strategy(comp, pools)['fingerprint']
    assert strategy['research_end'] == '2024-01-04'
    # Changing the source file after freezing cannot alter the saved strategy.
    (comp / 'factor_weights.json').write_text('[]')
    result = selection_api.run_stock_selection(store, strategy, out, '2024-01-07', 2)
    assert result['requested_date'] == '2024-01-07'
    assert result['as_of_date'] == '2024-01-05'
    assert result['retrospective'] is True
    assert result['selected_count'] == 2
    assert result['eligible_count'] == 3
    path = Path(result['output_dir'])
    ranking = pd.read_csv(path / 'rankings.csv', dtype={'code': str}).set_index('code')
    expected = (np.array([0, 1, 2, 3]) - 1.5) / np.std([0, 1, 2, 3]) * 2.5
    np.testing.assert_allclose(ranking.reindex(strategy['codes'])['score'], expected)
    assert ranking.loc['000004', 'reason'] == 'suspended'
    assert ranking.loc['000003', 'rank'] == 1
    assert pd.read_csv(path / 'candidates.csv', dtype={'code': str})['code'].tolist() == ['000003', '000002']
    assert len(pd.read_csv(path / 'contributions.csv')) == 8
    assert json.loads((path / 'strategy.json').read_text(encoding='utf-8')) == strategy
    assert selection_api.list_selections(out)[0]['path'] == str(path)
    again = selection_api.run_stock_selection(store, strategy, out, '2024-01-07', 2)
    assert again['output_dir'] != result['output_dir']


@pytest.mark.parametrize('expression', ['delay(close,-1)', 'ts_delta(close,n=-2)', 'delay(close,1-2)', 'ts_mean(close,-2)', 'delay(close,other)'])
def test_reject_future_or_dynamic_lookbacks(selection_api, fixture, expression):
    _, pools, comp, _ = fixture
    weights = json.loads((comp / 'factor_weights.json').read_text())
    weights[0]['expression'] = expression
    (comp / 'factor_weights.json').write_text(json.dumps(weights))
    with pytest.raises(ValueError, match='lookback|lag|window'):
        selection_api.load_strategy(comp, pools)


@pytest.mark.parametrize('change', ['nan_weight', 'all_zero', 'preprocess', 'noncomposite', 'pool_changed'])
def test_reject_unsupported_strategy(selection_api, fixture, change):
    _, pools, comp, _ = fixture
    weights = json.loads((comp / 'factor_weights.json').read_text())
    if change == 'nan_weight':
        weights[0]['weight'] = float('nan')
    elif change == 'all_zero':
        for item in weights:
            item['weight'] = 0
    elif change == 'preprocess':
        weights[0]['preprocess']['std_ddof'] = 1
    elif change == 'noncomposite':
        manifest = json.loads((comp / 'manifest.json').read_text())
        manifest['result_type'] = 'factor'
        (comp / 'manifest.json').write_text(json.dumps(manifest))
    else:
        (pools / 'pool1' / 'codes.txt').write_text('000001')
    (comp / 'factor_weights.json').write_text(json.dumps(weights))
    with pytest.raises(ValueError):
        selection_api.load_strategy(comp, pools)


def test_missing_coverage_stale_price_and_zero_weight(selection_api, fixture):
    store, pools, comp, out = fixture
    weights = json.loads((comp / 'factor_weights.json').read_text())
    weights.append({'factor_id': 'inactive', 'expression': 'signal', 'weight': 0, 'preprocess': FACTOR_PREPROCESS})
    (comp / 'factor_weights.json').write_text(json.dumps(weights))
    for code, mode in [('000001', 'missing'), ('000002', 'stale'), ('000003', 'price')]:
        file = store / 'stocks' / (code + '.parquet')
        frame = pd.read_parquet(file)
        if mode == 'missing':
            frame['signal'] = np.nan
            frame['other'] = np.nan
        elif mode == 'stale':
            frame = frame[frame['date'] != pd.Timestamp('2024-01-05')]
        else:
            frame.loc[frame['date'] == '2024-01-05', 'close'] = 0
        frame.to_parquet(file, index=False)
    strategy = selection_api.load_strategy(comp, pools)
    result = selection_api.run_stock_selection(store, strategy, out, '2024-01-05', exclude_suspended=False, min_factor_coverage=0)
    ranking = pd.read_csv(Path(result['output_dir']) / 'rankings.csv', dtype={'code': str}).set_index('code')
    assert result['selected_count'] == 1
    assert ranking.loc['000001', 'reason'] == 'all_factors_missing'
    assert ranking.loc['000002', 'reason'] == 'missing_as_of_date'
    assert ranking.loc['000003', 'reason'] == 'invalid_close'
    assert ranking.loc['000004', 'coverage'] == 1


def test_validation_and_partial_outputs_hidden(selection_api, fixture):
    store, pools, comp, out = fixture
    strategy = selection_api.load_strategy(comp, pools)
    for date in ['not-a-date', '2024-01-09', '2023-01-01']:
        with pytest.raises(ValueError):
            selection_api.run_stock_selection(store, strategy, out, date)
    changed = copy.deepcopy(strategy)
    changed['codes'].pop()
    with pytest.raises(ValueError, match='fingerprint'):
        selection_api.run_stock_selection(store, changed, out)
    for file in (store / 'stocks').glob('*.parquet'):
        frame = pd.read_parquet(file).drop(columns=['Ifsuspend'])
        frame.to_parquet(file, index=False)
    with pytest.raises(ValueError, match='Ifsuspend'):
        selection_api.run_stock_selection(store, strategy, out)
    partial = out / '.partial-123'
    partial.mkdir(parents=True)
    (partial / 'selection.json').write_text('{}')
    assert selection_api.list_selections(out) == []


def test_signature_refresh_is_visible_and_factor_research_end_included(selection_api, fixture):
    store, pools, comp, out = fixture
    run = comp.parent / 'factor_run'
    run.mkdir()
    (run / 'factor_run.json').write_text(json.dumps({'config': {'end_date': '2024-01-08'}}))
    manifest = json.loads((comp / 'manifest.json').read_text())
    manifest['config']['composition'] = {'run_dirs': [str(run)]}
    manifest['created_at'] = '2020-01-01T00:00:00'
    (comp / 'manifest.json').write_text(json.dumps(manifest))
    strategy = selection_api.load_strategy(comp, pools)
    assert strategy['research_end'] == '2024-01-08'
    (store / 'meta.json').write_text(json.dumps({'source_signature': 'version-2'}))
    result = selection_api.run_stock_selection(store, strategy, out, '2024-01-08')
    assert result['retrospective']
    assert any('signature' in warning for warning in result['warnings'])


def test_unknown_research_provenance_and_newer_pool_are_retrospective(selection_api, fixture):
    store, pools, comp, out = fixture
    manifest = json.loads((comp / 'manifest.json').read_text())
    manifest['config'] = {}
    manifest['created_at'] = '2020-01-01T00:00:00'
    (comp / 'manifest.json').write_text(json.dumps(manifest))
    strategy = selection_api.load_strategy(comp, pools)
    result = selection_api.run_stock_selection(store, strategy, out)
    assert result['retrospective'] is True
    assert any('未知' in warning for warning in result['warnings'])
    pool_path = pools / 'pool1' / 'manifest.json'
    pool = json.loads(pool_path.read_text())
    pool.update({'created_at': '2024-01-09T10:00:00', 'selection_end': '2024-01-04'})
    pool_path.write_text(json.dumps(pool))
    strategy = selection_api.load_strategy(comp, pools)
    assert strategy['formed_at'] == '2024-01-09T10:00:00'
    assert selection_api.run_stock_selection(store, strategy, out)['retrospective'] is True


def test_report_and_missing_source_manifest_research_provenance(selection_api, fixture):
    store, pools, comp, out = fixture
    pd.DataFrame({'date': ['2024-01-04', '2024-01-08']}).to_csv(comp / 'daily_report.csv', index=False)
    strategy = selection_api.load_strategy(comp, pools)
    assert strategy['research_end'] == '2024-01-08'
    manifest = json.loads((comp / 'manifest.json').read_text())
    manifest['config']['composition'] = {'run_dirs': [str(comp / 'gone')]}
    (comp / 'manifest.json').write_text(json.dumps(manifest))
    strategy = selection_api.load_strategy(comp, pools)
    result = selection_api.run_stock_selection(store, strategy, out)
    assert any('缺失' in warning for warning in result['warnings'])


def test_future_rows_do_not_change_historical_selection_and_ties_use_codes(selection_api, fixture):
    store, pools, comp, out = fixture
    weights = [{'factor_id': 'constant', 'expression': '1', 'weight': 1, 'preprocess': FACTOR_PREPROCESS}]
    (comp / 'factor_weights.json').write_text(json.dumps(weights))
    strategy = selection_api.load_strategy(comp, pools)
    first = selection_api.run_stock_selection(store, strategy, out, '2024-01-05', top_n=2)
    candidates = pd.read_csv(Path(first['output_dir']) / 'candidates.csv', dtype={'code': str})
    assert candidates['code'].tolist() == ['000001', '000002']
    file = store / 'stocks' / '000001.parquet'
    frame = pd.read_parquet(file)
    frame.loc[frame['date'] > '2024-01-05', ['signal', 'close']] = -999999
    frame.to_parquet(file, index=False)
    second = selection_api.run_stock_selection(store, strategy, out, '2024-01-05', top_n=2)
    pd.testing.assert_frame_equal(pd.read_csv(Path(first['output_dir']) / 'rankings.csv'), pd.read_csv(Path(second['output_dir']) / 'rankings.csv'))


def test_runtime_cache_end_and_same_day_formation(selection_api, fixture):
    store, pools, comp, out = fixture
    run = comp.parent / 'factor_run'
    run.mkdir()
    runtime = run / 'runtime_manifest.json'
    runtime.write_text(json.dumps({'splits': {'train': {'cache_end': '2024-01-08'}}}))
    (run / 'factor_run.json').write_text(json.dumps({'runtime_manifest': str(runtime)}))
    manifest = json.loads((comp / 'manifest.json').read_text())
    manifest['config']['composition'] = {'run_dirs': [str(run)]}
    manifest['created_at'] = '2024-01-08T10:00:00'
    (comp / 'manifest.json').write_text(json.dumps(manifest))
    strategy = selection_api.load_strategy(comp, pools)
    assert strategy['research_end'] == '2024-01-08'
    assert selection_api.run_stock_selection(store, strategy, out)['retrospective'] is True


def test_unknown_suspension_and_top_n_reasons(selection_api, fixture):
    store, pools, comp, out = fixture
    file = store / 'stocks' / '000001.parquet'
    frame = pd.read_parquet(file)
    frame.loc[frame['date'] == '2024-01-05', 'Ifsuspend'] = np.nan
    frame.to_parquet(file, index=False)
    result = selection_api.run_stock_selection(store, selection_api.load_strategy(comp, pools), out, '2024-01-05', top_n=1)
    rankings = pd.read_csv(Path(result['output_dir']) / 'rankings.csv', dtype={'code': str}).set_index('code')
    assert rankings.loc['000001', 'reason'] == 'suspension_status_unknown'
    assert rankings.loc['000002', 'reason'] == 'outside_top_n'
    assert rankings.loc['000002', 'eligible']


@pytest.mark.parametrize('linked_runtime', [False, True])
def test_sparse_factor_research_provenance_is_unknown(selection_api, fixture, linked_runtime):
    store, pools, comp, out = fixture
    run = comp.parent / 'ai_factor_run'
    run.mkdir()
    run_manifest = {'run_id': 'ai_run_1', 'pool_id': 'pool1', 'created_at': '2020-01-01T00:00:00', 'accepted_count': 2}
    if linked_runtime:
        runtime = run / 'runtime_manifest.json'
        runtime.write_text(json.dumps({'pool_id': 'pool1', 'fields': ['close']}))
        run_manifest['runtime_manifest'] = str(runtime)
    (run / 'factor_run.json').write_text(json.dumps(run_manifest))
    manifest = json.loads((comp / 'manifest.json').read_text())
    manifest['created_at'] = '2020-01-01T00:00:00'
    manifest['config']['composition'] = {'run_dirs': [str(run)]}
    (comp / 'manifest.json').write_text(json.dumps(manifest))
    strategy = selection_api.load_strategy(comp, pools)
    result = selection_api.run_stock_selection(store, strategy, out, '2024-01-08')
    assert result['retrospective'] is True
    assert any('研究' in warning and '未知' in warning for warning in result['warnings'])
