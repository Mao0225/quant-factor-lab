"""Apply frozen composition weights to a dated cross-section without refitting."""
from __future__ import annotations

import ast
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from custom_bt.canonical_expression import normalize_expression
from custom_bt.data import load_meta, load_pool_panel, normalize_code
from custom_bt.expressions import OPERATORS, _preprocess_expression, evaluate_expression
from custom_bt.factor_composition import FACTOR_PREPROCESS, daily_cross_section_zscore
from custom_bt.pools import load_pool_codes, load_pool_manifest


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _fingerprint(strategy: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in strategy.items() if key != 'fingerprint'}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _date(value: Any, label: str) -> pd.Timestamp:
    try:
        date = pd.Timestamp(value)
        if pd.isna(date) or date.tzinfo is not None:
            raise ValueError()
        return date.normalize()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f'{label} must be a valid date without timezone: {value!r}') from exc


def _validate_expression(expression: str) -> str:
    expression = normalize_expression(expression)
    tree = ast.parse(_preprocess_expression(expression), mode='eval')
    # Check the arguments used by the evaluator, including aliases and keywords.
    # Lookbacks must be literal integers; computed/dynamic windows are ambiguous.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in OPERATORS:
            raise ValueError('Only registered factor operators are supported')
        name = node.func.id
        spec = OPERATORS[name]
        if spec.category != 'time_series' and name != 'group_backfill':
            continue
        if name in {'days_from_last_change', 'hump', 'ts_step'}:
            continue
        position = 2 if name in {'ts_corr', 'ts_covariance', 'ts_regression', 'group_backfill'} else 1
        window = node.args[position] if len(node.args) > position else next(
            (item.value for item in node.keywords if item.arg in {'n', 'd'}), None
        )
        try:
            value = ast.literal_eval(window) if window is not None else None
        except (ValueError, TypeError):
            value = None
        minimum = 0 if name in {'delay', 'delta', 'ts_delay', 'ts_delta'} else 1
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value != int(value) or value < minimum:
            raise ValueError(f'{name} lookback/lag window must be a literal integer >= {minimum}; future values are forbidden')
    return expression


def _components(rows: Any, default_preprocess: Any = None) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError('factor_weights.json must contain at least one component')
    result = []
    ids = set()
    for row in rows:
        factor_id = str(row.get('factor_id') or '').strip()
        if not factor_id or factor_id in ids:
            raise ValueError('Each component needs a unique factor_id')
        ids.add(factor_id)
        try:
            weight = float(row['weight'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Each component needs a finite weight') from exc
        if not np.isfinite(weight):
            raise ValueError('All component weights must be finite')
        preprocess = row.get('preprocess') or default_preprocess
        if preprocess is None:
            raise ValueError('该历史组合缺少标准化记录，请重新生成组合')
        if preprocess != FACTOR_PREPROCESS:
            raise ValueError('Unsupported factor preprocessing; regenerate the composition with daily population z-scores')
        if row.get('applied_to', 'preprocessed_alpha') != 'preprocessed_alpha':
            raise ValueError('Composition weights must apply to preprocessed_alpha')
        expression = str(row.get('expression') or '').strip()
        if not expression:
            raise ValueError('Each component needs its raw expression')
        result.append({'factor_id': factor_id, 'expression': _validate_expression(expression),
                       'weight': weight, 'preprocess': dict(preprocess)})
    if not any(item['weight'] != 0 for item in result):
        raise ValueError('At least one component must have a nonzero weight')
    return result


def _research_dates(value: Any) -> list[pd.Timestamp]:
    dates = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'end_date', 'date_max', 'selection_end', 'research_end', 'train_end', 'valid_end', 'test_end', 'cache_end'} and child:
                dates.append(_date(child, key))
            elif isinstance(child, (dict, list)):
                dates.extend(_research_dates(child))
    elif isinstance(value, list):
        for child in value:
            dates.extend(_research_dates(child))
    return dates


def load_strategy(composition_dir: str | Path, pools_root: str | Path) -> dict[str, Any]:
    """Freeze raw expressions, preprocessing, weights and the original stock pool."""
    source = Path(composition_dir).expanduser().resolve()
    manifest = _read_json(source / 'manifest.json')
    if manifest.get('result_type') != 'composite':
        raise ValueError('Only composite backtests with factor_weights.json can become strategies')
    components = _components(_read_json(source / 'factor_weights.json'), manifest.get('factor_preprocess'))
    pool_id = str(manifest.get('pool_id') or '')
    if not pool_id:
        raise ValueError('Composition has no pool_id')
    pool = load_pool_manifest(pools_root, pool_id)
    codes = sorted(set(load_pool_codes(pools_root, pool_id)))
    if not codes:
        raise ValueError('Original pool is empty')
    original = pool.get('selected_codes')
    if original is not None and sorted({normalize_code(code) for code in original}) != codes:
        raise ValueError('Original pool codes changed; restore the original pool before freezing a strategy')
    dates = _research_dates(manifest.get('config', {})) + _research_dates(pool)
    dates.extend(_research_dates({'research_end': manifest.get('research_end')}))
    report_path = source / 'daily_report.csv'
    if report_path.is_file():
        report = pd.read_csv(report_path, usecols=['date'])
        dates.extend(_date(value, 'daily_report.date') for value in report['date'].dropna())
    config = manifest.get('config', {})
    composition = config.get('composition', {})
    research_sources = []
    provenance_warnings = []
    for raw_path in composition.get('run_dirs', []):
        run_path = Path(raw_path).expanduser()
        if not run_path.is_absolute():
            run_path = source / run_path
        run_manifest = run_path / 'factor_run.json'
        if run_manifest.is_file():
            run = _read_json(run_manifest)
            run_dates = _research_dates(run)
            dates.extend(run_dates)
            research_sources.append(str(run_manifest.resolve()))
            if run.get('runtime_manifest'):
                runtime_path = Path(run['runtime_manifest'])
                if not runtime_path.is_absolute():
                    runtime_path = run_path / runtime_path
                if runtime_path.is_file():
                    runtime_dates = _research_dates(_read_json(runtime_path))
                    dates.extend(runtime_dates)
                    research_sources.append(str(runtime_path.resolve()))
                    if not runtime_dates:
                        provenance_warnings.append(f'研究运行数据清单未记录截止日期，研究时间未知：{runtime_path}')
                else:
                    provenance_warnings.append(f'研究运行数据清单缺失，无法确认研究截止时间：{runtime_path}')
            elif not run_dates:
                provenance_warnings.append(f'来源因子清单未记录截止日期或关联数据清单，研究时间未知：{run_manifest}')
        else:
            provenance_warnings.append(f'来源因子清单缺失，无法确认研究截止时间：{run_manifest}')
    formed_at = manifest.get('created_at') or datetime.fromtimestamp((source / 'factor_weights.json').stat().st_mtime).isoformat(timespec='seconds')
    if not manifest.get('created_at'):
        provenance_warnings.append('组合形成时间未知，暂以权重文件修改时间记录。')
    if pool.get('created_at'):
        _date(pool['created_at'], 'pool.created_at')
        formed_at = max(str(formed_at), str(pool['created_at']), key=pd.Timestamp)
    _date(formed_at, 'formed_at')
    strategy = {
        'schema_version': 1, 'source_path': str(source),
        'name': str(manifest.get('run_name') or source.name), 'pool_id': pool_id,
        'codes': codes, 'components': components, 'formed_at': str(formed_at),
        'research_end': max(dates).strftime('%Y-%m-%d') if dates else None,
        'research_sources': research_sources,
        'provenance_warnings': provenance_warnings,
        'source_signature': manifest.get('source_signature') or pool.get('source_signature'),
        'source_csv': manifest.get('source_csv') or pool.get('source_csv'),
    }
    strategy['fingerprint'] = _fingerprint(strategy)
    return strategy


def run_stock_selection(
    master_store: str | Path, strategy: Mapping[str, Any], outputs_root: str | Path,
    as_of_date: str | None = None, top_n: int = 20, min_factor_coverage: float = 1.0,
    exclude_suspended: bool = True,
) -> dict[str, Any]:
    """Score the frozen pool using only history through the requested cache date."""
    if isinstance(top_n, bool) or int(top_n) != top_n or top_n < 1:
        raise ValueError('top_n must be a positive integer')
    if not np.isfinite(min_factor_coverage) or not 0 <= min_factor_coverage <= 1:
        raise ValueError('min_factor_coverage must be between 0 and 1')
    snapshot = json.loads(json.dumps(dict(strategy), allow_nan=False))
    if snapshot.get('fingerprint') != _fingerprint(snapshot):
        raise ValueError('Strategy fingerprint mismatch; reload the original composition')
    components = _components(snapshot['components'])
    active = [item for item in components if item['weight'] != 0]
    codes = snapshot['codes']
    if not codes or sorted(set(codes)) != codes:
        raise ValueError('Frozen pool codes must be nonempty, unique and sorted')
    meta = load_meta(master_store)
    warnings = list(snapshot.get('provenance_warnings', []))
    if snapshot.get('source_csv') and meta.get('source_csv'):
        if Path(snapshot['source_csv']).resolve() != Path(meta['source_csv']).resolve():
            raise ValueError('Strategy and master cache have different source_csv data sources')
    if snapshot.get('source_signature') and meta.get('source_signature') and snapshot['source_signature'] != meta['source_signature']:
        warnings.append('数据源签名 (signature) 已变更；本次使用当前缓存版本和策略固定股票池，请核对是否仅追加了行情。')
    # Load all earlier rows, preserving rolling warm-up history. No expression sees future rows.
    panel = load_pool_panel(master_store, codes)
    if panel.empty or panel['date'].dropna().empty:
        raise ValueError('The fixed pool has no dated data in the master cache')
    if panel['date'].isna().any() or panel.duplicated(['date', 'code']).any():
        raise ValueError('Master cache contains invalid dates or duplicate date/code rows')
    panel['code'] = panel['code'].map(normalize_code)
    if not set(panel['code']).issubset(set(codes)):
        raise ValueError('Master cache stock files contain codes outside the frozen pool')
    cache_max = panel['date'].max().normalize()
    requested = cache_max if as_of_date is None else _date(as_of_date, 'as_of_date')
    if requested > cache_max:
        raise ValueError(f'as_of_date is beyond available cache maximum {cache_max:%Y-%m-%d}; refresh the cache first')
    panel = panel[panel['date'] <= requested].copy()
    if panel.empty:
        raise ValueError('No data exists on or before as_of_date')
    actual = panel['date'].max()
    if actual != requested:
        warnings.append(f'请求日期无股票池数据，已使用此前最近可用日期 {actual:%Y-%m-%d}。')
    if 'close' not in panel:
        raise ValueError('Master cache is missing close prices')
    if exclude_suspended and 'Ifsuspend' not in panel:
        raise ValueError('Master cache is missing Ifsuspend; reimport this field or disable suspension filtering explicitly')
    current = panel.loc[panel['date'] == actual].set_index('code').reindex(codes)
    contributions = []
    score = pd.Series(0.0, index=codes)
    coverage = pd.Series(0.0, index=codes)
    for component in active:
        alpha = evaluate_expression(component['expression'], panel)
        raw = alpha.loc[alpha['date'] == actual, ['date', 'code', 'alpha']]
        # Use exactly composition normalization, before trade eligibility filtering.
        standardized = daily_cross_section_zscore(raw).set_index('code')['alpha'].reindex(codes).fillna(0.0)
        values = raw.set_index('code')['alpha'].reindex(codes)
        finite = np.isfinite(pd.to_numeric(values, errors='coerce'))
        coverage += finite.astype(float) / len(active)
        contribution = standardized * component['weight']
        score += contribution
        contributions.append(pd.DataFrame({
            'code': codes, 'factor_id': component['factor_id'], 'raw_value': values.values,
            'standardized_value': standardized.values, 'weight': component['weight'],
            'contribution': contribution.values,
        }))
    coverage = coverage.clip(0, 1)
    reasons = pd.Series('', index=codes)
    missing = ~pd.Index(codes).isin(panel.loc[panel['date'] == actual, 'code'])
    close = pd.to_numeric(current['close'], errors='coerce')
    checks = [('missing_as_of_date', missing), ('invalid_close', ~np.isfinite(close) | (close <= 0))]
    if exclude_suspended:
        suspension = pd.to_numeric(current['Ifsuspend'], errors='coerce')
        checks.append(('suspension_status_unknown', ~np.isfinite(suspension)))
        checks.append(('suspended', suspension.ne(0)))
    checks.extend([('all_factors_missing', coverage <= 0),
                   ('insufficient_factor_coverage', coverage + 1e-12 < min_factor_coverage),
                   ('invalid_score', ~np.isfinite(score))])
    for reason, mask in checks:
        reasons.loc[(reasons == '') & mask] = reason
    name = pd.Series('', index=codes)
    for field in ['name', 'ChiName', 'SecuAbbr', 'ChiNameAbbr']:
        if field in current:
            name = name.mask(name.eq(''), current[field].fillna('').astype(str))
    rankings = pd.DataFrame({'code': codes, 'name': name.values, 'score': score.values,
                             'coverage': coverage.values, 'close': close.values,
                             'eligible': reasons.eq('').values, 'reason': reasons.values})
    rankings = rankings.sort_values(['eligible', 'score', 'code'], ascending=[False, False, True], kind='mergesort').reset_index(drop=True)
    eligible_count = int(rankings['eligible'].sum())
    rankings['rank'] = np.nan
    rankings.loc[rankings['eligible'], 'rank'] = np.arange(1, eligible_count + 1)
    rankings['selected'] = rankings['eligible'] & rankings['rank'].le(top_n)
    rankings.loc[rankings['eligible'] & ~rankings['selected'], 'reason'] = 'outside_top_n'
    rankings = rankings[['code', 'name', 'score', 'rank', 'coverage', 'close', 'eligible', 'selected', 'reason']]
    formed = _date(snapshot['formed_at'], 'formed_at')
    research_end = snapshot.get('research_end')
    retrospective = bool(formed >= actual or research_end is None or snapshot.get('provenance_warnings') or (research_end is not None and _date(research_end, 'research_end') >= actual))
    if retrospective:
        warnings.append('历史回看预览：策略形成或研究时间不早于评分日，或时间记录不完整；本次结果不属于样本外选股。')
    if research_end is None:
        warnings.append('研究截止日期未知，无法确认样本外状态。')
    if eligible_count < top_n:
        warnings.append(f'仅 {eligible_count} 只股票通过筛选，少于请求的 Top {top_n}。')
    created = datetime.now()
    selection_id = created.strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8]
    root = Path(outputs_root).expanduser().resolve()
    output = root / selection_id
    metadata = {
        'schema_version': 1, 'selection_id': selection_id, 'created_at': created.isoformat(timespec='seconds'),
        'strategy_name': snapshot['name'], 'strategy_fingerprint': snapshot['fingerprint'],
        'pool_id': snapshot['pool_id'], 'requested_date': requested.strftime('%Y-%m-%d'),
        'as_of_date': actual.strftime('%Y-%m-%d'), 'cache_max_date': cache_max.strftime('%Y-%m-%d'),
        'selected_count': int(rankings['selected'].sum()), 'eligible_count': eligible_count,
        'total_count': len(codes), 'retrospective': retrospective, 'warnings': warnings,
        'research_end': research_end, 'formed_at': snapshot['formed_at'], 'top_n': int(top_n),
        'min_factor_coverage': float(min_factor_coverage), 'exclude_suspended': bool(exclude_suspended),
        'active_factor_count': len(active), 'source_signature': meta.get('source_signature'),
        'master_store': str(Path(master_store).expanduser().resolve()), 'output_dir': str(output),
    }
    root.mkdir(parents=True, exist_ok=True)
    staging = root / ('.partial-' + selection_id)
    staging.mkdir()
    (staging / 'strategy.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    rankings.to_csv(staging / 'rankings.csv', index=False, encoding='utf-8-sig')
    rankings.loc[rankings['selected']].to_csv(staging / 'candidates.csv', index=False, encoding='utf-8-sig')
    pd.concat(contributions, ignore_index=True).to_csv(staging / 'contributions.csv', index=False, encoding='utf-8-sig')
    (staging / 'selection.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    staging.rename(output)
    return metadata


def list_selections(outputs_root: str | Path) -> list[dict[str, Any]]:
    """Discover only complete, atomically published stock-selection runs."""
    root = Path(outputs_root).expanduser().resolve()
    records = []
    for path in sorted(root.glob('*/selection.json'), reverse=True):
        directory = path.parent
        if directory.name.startswith('.') or not all((directory / name).is_file() for name in ['strategy.json', 'rankings.csv', 'candidates.csv', 'contributions.csv']):
            continue
        try:
            record = _read_json(path)
            if record.get('schema_version') != 1 or not record.get('selection_id'):
                continue
        except (OSError, ValueError, AttributeError):
            continue
        records.append({**record, 'path': str(directory)})
    return records
