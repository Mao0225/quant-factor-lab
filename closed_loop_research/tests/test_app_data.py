import pandas as pd
import pytest

from closed_loop_research.app.data_service import DataService, _build_market, import_raw_500
from closed_loop_research.data import DataIntegrityError
from closed_loop_research.storage import file_digest, digest, atomic_json


def test_missing_rows_are_not_complete_or_tradable_and_no_finance_features():
    frame = pd.DataFrame([
        dict(code=c, timestamps=date, open=10, close=11, high=12, low=9, vol=100,
             amount=1100, Ifsuspend=0, ListedDate='2020-01-01')
        for date, codes in [('2024-01-01', ['000001', '000002']), ('2024-01-02', ['000001'])]
        for c in codes])
    market, quality, complete = _build_market(frame, ['000001', '000002'])
    assert complete == '2024-01-01'
    missing = market[(market.code == '000002') & (market.date == '2024-01-02')].iloc[0]
    assert not missing.eligible and not missing.can_buy_open
    assert missing.exec_open == 11 and pd.isna(missing.close)
    assert quality['padded_rows'] == 1


def test_stream_import_quarantines_finance_hashes_and_detects_tamper(tmp_path):
    codes = [str(i).zfill(6) for i in range(1, 501)]
    codefile = tmp_path / 'codes.parquet'
    pd.DataFrame({'code': codes}).to_parquet(codefile)
    source = tmp_path / 'raw.tsv'
    rows = pd.DataFrame([dict(code=code, timestamps=date, open=10, close=11, high=12, low=9,
        vol=100, amount=1100, Ifsuspend=0, TurnoverRate=.5, SecuAbbr='Example',
        ListedDate='2020-01-01', InfoPublDate='2029-01-01', ROE=123,
        idx_InfoPublDate='2029-01-01', idx_ROETTM=222)
        for date in pd.bdate_range('2023-01-01', periods=145).strftime('%Y-%m-%d') for code in codes])
    pd.concat([rows, pd.DataFrame([{'code': None}])], ignore_index=True).to_csv(source, sep='\t', index=False)
    root = tmp_path / 'system'
    report = import_raw_500(source, codefile, root)
    assert report['source']['sha256'] == file_digest(source)
    assert report['quality']['invalid_source_codes_excluded'] == 1
    assert report['quality']['financial_publication_audit']['InfoPublDate']['future'] == len(rows)
    assert not report['filters']['amount']['enabled']
    assert report['filters']['turnover']['enabled']
    service = DataService(root)
    market = service.load_market(report['id'])
    assert 'ROE' not in market and 'idx_ROETTM' not in market
    protocol = service.protocol_template(report['id'])
    manifest = service.prepare_research_snapshot(report['id'], protocol, tmp_path / 'snapshot')
    assert manifest['source_metadata']['dataset_id'] == report['id']
    falsified = dict(protocol, field_lookbacks={f: 0 for f in protocol['fields']})
    with pytest.raises(ValueError, match='lookback'):
        service.prepare_research_snapshot(report['id'], falsified, tmp_path / 'bad_history')
    protocol['fields'] = list(protocol['fields']) + ['ROE']
    with pytest.raises(ValueError, match='financial'):
        service.prepare_research_snapshot(report['id'], protocol, tmp_path / 'rejected')
    assert import_raw_500(source, codefile, root)['id'] == report['id']
    artifact = root / 'datasets' / report['id'] / 'market.parquet'
    with artifact.open('ab') as f:
        f.write(b'tampered')
    with pytest.raises(DataIntegrityError, match='changed'):
        service.load_market(report['id'])


def test_dataset_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match='id'):
        DataService(tmp_path).get_dataset('../outside')


@pytest.mark.parametrize('latest_turnover, enabled', [(0., False), (.8, True)])
def test_turnover_availability_is_latest_day_not_historical_any(tmp_path, monkeypatch, latest_turnover, enabled):
    directory = tmp_path / 'datasets' / 'sample'
    directory.mkdir(parents=True)
    codes = ['000001', '000002']
    frame = pd.DataFrame([dict(date=pd.Timestamp(date), code=code, turnover=turnover, volume=100,
        open=10, close=11, high=12, low=9, amount=1100)
        for date, turnover in [('2026-06-09', 1.5), ('2026-06-16', latest_turnover)] for code in codes])
    artifact = directory / 'market.parquet'
    frame.to_parquet(artifact, index=False)
    manifest = dict(id='sample', latest_complete_date='2026-06-16',
        universe=dict(codes=codes, hash=digest(codes)), market_sha256=file_digest(artifact),
        files={'market.parquet': file_digest(artifact)}, filters={'turnover': dict(enabled=True, unit='percent')})
    manifest['manifest_digest'] = digest(manifest)
    atomic_json(directory / 'manifest.json', manifest)
    before_manifest = file_digest(directory / 'manifest.json')
    calls = []
    reader = pd.read_parquet
    def counted(*args, **kwargs):
        calls.append(kwargs)
        return reader(*args, **kwargs)
    monkeypatch.setattr(pd, 'read_parquet', counted)
    service = DataService(tmp_path)
    result = service.get_dataset('sample')
    assert result['filters']['turnover']['enabled'] is enabled
    assert result['filter_quality']['rows'] == 2
    assert result['filter_quality']['fields']['volume']['positive'] == 2
    if not enabled:
        assert '疑似缺失值占位' in result['filters']['turnover']['reason']
    result['filter_quality']['turnover']['enabled'] = not enabled
    assert service.get_dataset('sample')['filters']['turnover']['enabled'] is enabled
    assert len(calls) == 1 and calls[0]['filters'] == [('date', '==', pd.Timestamp('2026-06-16'))]
    assert file_digest(directory / 'manifest.json') == before_manifest
    assert file_digest(artifact) == manifest['market_sha256']
