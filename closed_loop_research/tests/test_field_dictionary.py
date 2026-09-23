import copy

import pandas as pd
import pytest

from closed_loop_research.app.data_service import DataService, _catalog
from closed_loop_research.storage import atomic_json, digest, file_digest


def test_import_catalog_contains_exact_source_descriptions_without_permission_changes():
    fields = {f['name']: f for f in _catalog(['open', 'vol', 'ROE', 'idx_ROE', 'ListedSector'], ['open', 'vol', 'ROE'])}
    assert fields['open'].get('description') == '开盘价'
    assert fields['vol']['description'] == '成交量'
    assert fields['vol']['canonical_name'] == 'volume'
    assert fields['ROE']['description'] == '净资产收益率(摊薄)(%)'
    assert '归母净利润' in fields['ROE']['source_notes']
    assert not fields['ROE']['training_allowed'] and not fields['ROE']['verified']
    assert fields['ListedSector']['description_status'] == 'unmatched'
    assert '未收录' in fields['ListedSector']['description']


def test_exact_matching_escaped_notes_provenance_and_no_gate_promotion(tmp_path):
    from closed_loop_research.app.field_dictionary import enrich_catalog
    document = tmp_path / 'dictionary.md'
    document.write_text('## 财务\n| 字段名 | 中文解释 | 备注 |\n|---|---|---|\n'
        '| ROE | 原值 | A \\| B |\n| idx_ROE | 指标值 | 独立字段 |\n', encoding='utf8')
    fields = [dict(name=n, verified=False, training_allowed=False, unit='unverified', imported=False)
              for n in ['ROE', 'idx_ROE', 'roe', 'Extra']]
    before = copy.deepcopy(fields)
    enriched, summary = enrich_catalog(fields, document)
    assert fields == before
    assert [r['description'] for r in enriched[:2]] == ['原值', '指标值']
    assert enriched[0]['source_notes'] == 'A | B'
    assert enriched[0]['documentation']['line'] == 4
    assert enriched[0]['documentation']['sha256'] == file_digest(document)
    assert summary['matched'] == 2 and summary['unmatched_fields'] == ['roe', 'Extra']
    assert all(not f['verified'] and not f['training_allowed'] and f['unit'] == 'unverified' for f in enriched)
    enriched[0]['documentation']['line'] = 900
    assert enrich_catalog(fields, document)[0][0]['documentation']['line'] == 4


def test_conflicting_duplicate_dictionary_field_is_rejected(tmp_path):
    from closed_loop_research.app.field_dictionary import enrich_catalog
    document = tmp_path / 'bad.md'
    document.write_text('| open | 开盘价 | |\n| open | 收盘价 | |\n', encoding='utf8')
    with pytest.raises(ValueError, match='duplicate'):
        enrich_catalog([dict(name='open')], document)


def test_existing_dataset_gets_documentation_without_rewriting_frozen_manifest(tmp_path):
    directory = tmp_path / 'datasets' / 'sample'
    directory.mkdir(parents=True)
    market = directory / 'market.parquet'
    pd.DataFrame([dict(date=pd.Timestamp('2026-06-16'), code='000001', turnover=0., volume=100)]).to_parquet(market)
    fields = [dict(name='TurnoverRate', verified=False, training_allowed=False),
              dict(name='InfoPublDate', verified=False, training_allowed=False)]
    manifest = dict(id='sample', fields=fields, latest_complete_date='2026-06-16',
                    universe=dict(codes=['000001'], hash=digest(['000001'])),
                    files={'market.parquet': file_digest(market)}, market_sha256=file_digest(market),
                    filters={'turnover': dict(enabled=True)}, signal_fields=['close'])
    manifest['manifest_digest'] = digest(manifest)
    atomic_json(directory / 'manifest.json', manifest)
    before = file_digest(directory / 'manifest.json')
    result = DataService(tmp_path).get_dataset('sample')
    assert result['fields'][0].get('description') == '换手率(%)'
    assert result['field_dictionary']['matched'] == 2
    assert not result['filters']['turnover']['enabled']
    assert result['signal_fields'] == ['close']
    assert file_digest(directory / 'manifest.json') == before
    assert result['manifest_digest'] == manifest['manifest_digest']


def test_bundled_user_document_counts_and_known_missing_security_section():
    from closed_loop_research.app.field_dictionary import enrich_catalog
    fields, summary = enrich_catalog([dict(name=n) for n in ['open', 'idx_ROETTM', 'InnerCode']])
    assert summary['document_fields'] == 425
    assert summary['matched'] == 2
    assert fields[-1]['description_status'] == 'unmatched'
