"""Immutable, projected raw-file imports; financial observations remain quarantined."""
import csv
import copy
import hashlib
import io
import re
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..data import DataIntegrityError, prepare_snapshot
from ..features import FEATURE_LOOKBACKS, RAW_FIELDS, engineer_features, feature_formula
from ..legacy import prototype_protocol
from ..protocol import Protocol
from ..storage import atomic_json, digest, file_digest, read_json, writer_lock
from .field_dictionary import enrich_catalog

MARKET_SOURCE = ['code', 'timestamps', 'open', 'close', 'high', 'low', 'ycp', 'vol',
                 'amount', 'ChangePCT', 'RangePCT', 'TurnoverRate', 'Ifsuspend',
                 'StockBoard', 'LimitBoard', 'SurgedLimit', 'DeclineLimit', 'market_code', 'category']
SECURITY_SOURCE = ['InnerCode', 'CompanyCode', 'ChiName', 'ChiNameAbbr', 'EngName', 'EngNameAbbr',
                   'SecuAbbr', 'ChiSpelling', 'SecuMarket', 'SecuCategory', 'ListedDate',
                   'ListedSector', 'ListedState', 'ISIN', 'ExtendedAbbr', 'ExtendedSpelling']
AUDIT_SOURCE = ['InfoPublDate', 'EndDate', 'InfoSource', 'InfoSourceCode', 'BulletinType',
                'AccountingStandards', 'Mark', 'ModifiedAuditOpinion', 'TotalShares', 'ROE',
                'TotalAssets', 'idx_InfoPublDate', 'idx_EndDate', 'idx_ROETTM', 'idx_DebtAssetsRatio']
PIPELINE_VERSION = 1
NOTE = ('Raw source prices, adjustment and corporate actions unverified; prototype only. '
        'No extra dividends/splits assumed; ycp is NOT used to infer corporate actions. '
        'Opening tradability uses observed positive open and daily suspension flag assumed all-day; '
        'no intraday liquidity or limit execution model. Missing marks carry strictly past closes. '
        'No delisting settlement. Static 500-stock sample selection bias unresolved.')
UNITS = {'open': 'CNY/share (inferred)', 'close': 'CNY/share (inferred)',
         'high': 'CNY/share (inferred)', 'low': 'CNY/share (inferred)',
         'volume': 'shares (inferred)', 'amount': 'CNY (inferred)', 'TurnoverRate': 'percent',
         'turnover': 'percent', 'listing_days': 'calendar days'}
SCORING_CONTRACT = {
    'version': 1,
    'feature_registry': 'causal-price-volume-24-v1',
    'feature_code_sha256': file_digest(Path(__file__).resolve().parents[1] / 'features.py'),
    'eligible': 'observed(open,close) and close>0 and open>0 and volume>0 and Ifsuspend==0',
    'padding': 'calendar x frozen_codes; missing raw rows cannot trade or provide signals',
    'availability': 'all features assumed available same session 15:00 Asia/Shanghai',
    'signal_prices': 'raw observations; never fill missing feature prices',
    'execution_prices': 'positive observed open else strictly prior known close; closing mark past-forward-filled',
    'open_tradable': 'observed open>0 and Ifsuspend==0; no same-day final volume/close dependency',
}


def _code(value):
    value = str(value).strip()
    if re.fullmatch(r'\d+\.0+', value):
        value = value.split('.')[0]
    if not re.fullmatch(r'\d{1,6}', value):
        raise ValueError(f'invalid security code: {value!r}')
    return value.zfill(6)


class _HashReader(io.RawIOBase):
    def __init__(self, path):
        super().__init__()
        self.stream = Path(path).open('rb')
        self.hasher = hashlib.sha256()
        self.bytes_read = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        n = self.stream.readinto(buffer)
        if n:
            self.hasher.update(memoryview(buffer)[:n])
            self.bytes_read += n
        return n

    def close(self):
        self.stream.close()
        super().close()


def _stat(path):
    s = Path(path).stat()
    return (s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _catalog(header, selected):
    result = []
    for name in header:
        role = 'financial_quarantine' if name in AUDIT_SOURCE or name.startswith('idx_') or header.index(name) >= 84 else 'source_only'
        if name in SECURITY_SOURCE:
            role = 'security_attribute_unverified_history'
        if name in MARKET_SOURCE:
            role = 'market_observation'
        canonical = {'vol': 'volume', 'timestamps': 'date'}.get(name, name)
        result.append(dict(name=name, canonical_name=canonical, role=role,
                           imported=name in selected, training_allowed=canonical in RAW_FIELDS,
                           verified=False, unit=UNITS.get(canonical, 'unverified'),
                           source_name=name))
    return enrich_catalog(result)[0]


def _build_market(raw, codes):
    raw = raw.copy()
    raw['date'] = pd.to_datetime(raw.pop('timestamps'), errors='raise').dt.normalize()
    if raw.date.isna().any() or raw.duplicated(['date', 'code']).any():
        raise ValueError('missing date or duplicate raw date/code; import requires source repair')
    for col in ['open', 'close', 'high', 'low', 'vol', 'amount', 'ycp', 'TurnoverRate', 'Ifsuspend']:
        raw[col] = pd.to_numeric(raw.get(col), errors='coerce')
    raw = raw.rename(columns={'vol': 'volume', 'TurnoverRate': 'turnover', 'SecuAbbr': 'name'})
    observed = raw.groupby('date').code.nunique()
    usable = raw[list(RAW_FIELDS)].notna().all(axis=1) & (raw[['open', 'close', 'high', 'low']] > 0).all(axis=1)
    complete = raw.loc[usable].groupby('date').code.nunique()
    complete_dates = complete[complete.eq(len(codes))].index
    dates = sorted(raw.date.unique())
    index = pd.MultiIndex.from_product([dates, codes], names=['date', 'code'])
    data = raw.set_index(['date', 'code']).reindex(index)
    data['observed'] = data['close'].notna() & data['open'].notna()
    mark = data.close.where(data.close > 0).groupby(level='code').ffill()
    previous = mark.groupby(level='code').shift(1)
    data['exec_open'] = data.open.where(data.open > 0).fillna(previous)
    data['exec_close'] = mark
    data['eligible'] = data.observed & (data.close > 0) & (data.open > 0) & (data.volume > 0) & data.Ifsuspend.eq(0)
    data['can_buy_open'] = (data.open > 0) & data.Ifsuspend.eq(0)
    data['can_sell_open'] = data.can_buy_open
    data['share_multiplier'], data['cash_dividend'] = 1., 0.
    data = data.reset_index()
    if 'ListedDate' in data:
        listing = pd.to_datetime(data.ListedDate, errors='coerce')
        data['listing_days'] = (data.date - listing.dt.normalize()).dt.days
        data.loc[data.listing_days < 0, 'listing_days'] = np.nan
    else:
        data['listing_days'] = np.nan
    data = engineer_features(data)
    for field in FEATURE_LOOKBACKS:
        data[f'{field}__available_at'] = data.date + pd.Timedelta(hours=15)
    quality = dict(observed_rows=len(raw), padded_rows=len(data)-len(raw),
                   incomplete_sessions=int((observed < len(codes)).sum()),
                   complete_sessions=len(complete_dates),
                   missing_price_rows=int((~usable).sum()),
                   zero_volume_without_suspend=int((raw.volume.eq(0) & raw.Ifsuspend.eq(0)).sum()),
                   missing_fields=raw[list(RAW_FIELDS)].isna().sum().astype(int).to_dict(),
                   corporate_actions='unverified', financial_history='blocked_unverified',
                   calendar_basis='observed raw source sessions; exchange calendar not independently verified')
    return data, quality, (str(complete_dates.max().date()) if len(complete_dates) else None)


def import_raw_500(source, codes_source, root, progress=None):
    """Scan source once, hashing the exact bytes read and projecting needed columns."""
    started = time.monotonic()
    source, codes_source, root = Path(source).resolve(), Path(codes_source).resolve(), Path(root).resolve()
    codes = sorted({_code(x) for x in pd.read_parquet(codes_source, columns=['code']).code.unique()})
    if len(codes) != 500:
        raise ValueError('the registered universe must contain exactly 500 codes')
    source_stat = _stat(source)
    with source.open(encoding='utf-8-sig', newline='') as stream:
        header = next(csv.reader(stream, delimiter='\t'))
    if len(set(header)) != len(header):
        raise ValueError('duplicate source columns')
    required = {'code', 'timestamps', 'open', 'close', 'high', 'low', 'vol', 'amount', 'Ifsuspend'}
    if not required.issubset(header):
        raise ValueError(f'missing source columns: {sorted(required-set(header))}')
    selected = [c for c in MARKET_SOURCE + SECURITY_SOURCE + AUDIT_SOURCE if c in header]
    root.mkdir(parents=True, exist_ok=True)
    with writer_lock(root / 'datasets'):
        # Repeated CLI calls reuse an already verified import when source identity is unchanged.
        for path in (root / 'datasets').glob('*/manifest.json'):
            existing = read_json(path)
            if (existing.get('pipeline_version') == PIPELINE_VERSION and existing.get('scoring_contract') == SCORING_CONTRACT
                    and existing.get('source', {}).get('path') == str(source)
                    and existing['source'].get('stat') == list(source_stat)
                    and existing.get('universe', {}).get('codes') == codes):
                return DataService(root).get_dataset(existing['id'])
        stage = Path(tempfile.mkdtemp(prefix='.import-', dir=root / 'datasets'))
        try:
            (stage / 'audit').mkdir()
            market_parts, rows_read, selected_rows, invalid_source_codes = [], 0, 0, 0
            pit = {c: dict(known=0, future=0, unknown=0) for c in ['InfoPublDate', 'idx_InfoPublDate']}
            hashed = _HashReader(source)
            with io.BufferedReader(hashed, buffer_size=1024*1024) as stream:
                reader = pd.read_csv(stream, sep='\t', encoding='utf-8-sig', dtype=str,
                                     usecols=selected, chunksize=50000, keep_default_na=True,
                                     na_values=['NULL', 'null', 'nan'], low_memory=False)
                for number, chunk in enumerate(reader):
                    rows_read += len(chunk)
                    valid_code = chunk.code.str.fullmatch(r'\d{1,6}(?:\.0+)?', na=False)
                    invalid_source_codes += int((~valid_code).sum())
                    chunk = chunk.loc[valid_code].copy()
                    chunk['code'] = chunk.code.map(_code)
                    chunk = chunk[chunk.code.isin(codes)].copy()
                    if not chunk.empty:
                        selected_rows += len(chunk)
                        day = pd.to_datetime(chunk.timestamps, errors='coerce')
                        for col in pit:
                            dates = pd.to_datetime(chunk[col], errors='coerce') if col in chunk else pd.Series(pd.NaT, index=chunk.index)
                            pit[col]['known'] += int(dates.notna().sum())
                            pit[col]['unknown'] += int(dates.isna().sum())
                            pit[col]['future'] += int((dates > day).sum())
                        # Preserve imported source values, including financial audit values, as strings.
                        chunk.astype('string').to_parquet(stage / 'audit' / f'part-{number:05d}.parquet', index=False, compression='zstd')
                        market_columns = [c for c in MARKET_SOURCE + ['SecuAbbr', 'ListedDate', 'SecuMarket', 'ListedSector', 'ListedState'] if c in chunk]
                        market_parts.append(chunk[market_columns])
                    if progress:
                        progress(dict(rows_read=rows_read, selected_rows=selected_rows,
                                      bytes_read=hashed.bytes_read, total_bytes=source_stat[0]))
                source_hash = hashed.hasher.hexdigest()
                if hashed.bytes_read != source_stat[0]:
                    raise ValueError('source was not completely read')
            if _stat(source) != source_stat:
                raise ValueError('source changed during import')
            if not market_parts:
                raise ValueError('no matching source rows')
            raw = pd.concat(market_parts, ignore_index=True)
            del market_parts
            if sorted(raw.code.unique()) != codes:
                raise ValueError('raw source does not contain every registered universe code')
            market, quality, latest = _build_market(raw, codes)
            quality['financial_publication_audit'] = pit
            quality['source_rows_scanned'] = rows_read
            quality['invalid_source_codes_excluded'] = invalid_source_codes
            quality['market_memory_bytes'] = int(market.memory_usage(deep=True).sum())
            quality['import_seconds_to_materialization'] = round(time.monotonic()-started, 3)
            quality['unit_evidence'] = dict(turnover='field dictionary explicitly percent; unchanged values',
                amount='inferred CNY: amount/(vol*close) near 1 in old 500 panel; source dictionary does not state unit',
                market_code='provider label, not exchange; first 5000 source rows contain 新华财经')
            quality['warnings'] = [NOTE, 'Financial fields and current security names/status are not historical PIT inputs.',
                                   'Board, industry and market-cap filters unavailable; authoritative dictionaries/data absent.']
            market.to_parquet(stage / 'market.parquet', index=False, compression='zstd')
            identity = digest(dict(source_hash=source_hash, codes=codes, columns=selected,
                                   version=PIPELINE_VERSION, scoring_contract=SCORING_CONTRACT))
            identifier = f'raw500_{identity[:16]}'
            metadata = {f: dict(verified=False, source=f'raw TSV SHA256 {source_hash}',
                unit=UNITS.get(f, 'dimensionless'), description=feature_formula(f),
                availability='causal daily feature, assumed available at 15:00 Asia/Shanghai',
                adjustment='raw_source_unverified', history_sessions=FEATURE_LOOKBACKS[f],
                prototype_assumption=NOTE) for f in FEATURE_LOOKBACKS}
            filters = {name: dict(enabled=False, reason=reason, unit=None) for name, reason in {
                'board': 'ListedSector dictionary and historical transitions unverified',
                'industry': 'not present in source', 'market_cap': 'daily shares and price basis unverified',
                'finance': 'historical disclosure versions unavailable; quarantined'}.items()}
            for field in ['amount', 'turnover', 'listing_days']:
                filters[field] = dict(enabled=bool(market[field].notna().any()), unit=UNITS[field],
                    reason='prototype units/point-in-time assumptions recorded' if field == 'amount' else None)
            filters['amount'].update(enabled=False, unit_assumption=True,
                reason='Amount currency unit is inferred only; source dictionary/SQL verification required')
            catalog, dictionary = enrich_catalog(_catalog(header, selected))
            manifest = dict(schema=1, pipeline_version=PIPELINE_VERSION, id=identifier, name='原始数据 · 固定500股价量原型',
                start=str(market.date.min().date()), end=str(market.date.max().date()),
                latest_complete_date=latest, rows=len(market), code_count=len(codes),
                session_count=int(market.date.nunique()), data_mode='legacy_prototype',
                status='ready' if latest else 'incomplete', fields=catalog, field_dictionary=dictionary,
                signal_fields=list(FEATURE_LOOKBACKS), field_metadata=metadata,
                scoring_contract=SCORING_CONTRACT,
                filters=filters, quality=quality, universe=dict(codes=codes, hash=digest(codes)),
                calendar=[str(pd.Timestamp(d).date()) for d in sorted(market.date.unique())],
                source=dict(path=str(source), sha256=source_hash, stat=list(source_stat),
                            delimiter='tab', encoding='utf-8-sig', columns=header,
                            imported_columns=selected, codes_source=str(codes_source),
                            codes_source_sha256=file_digest(codes_source)),
                market_sha256=file_digest(stage / 'market.parquet'),
                files={str(p.relative_to(stage)).replace('\\', '/'): file_digest(p)
                       for p in sorted(stage.rglob('*.parquet'))})
            manifest['manifest_digest'] = digest(manifest)
            atomic_json(stage / 'manifest.json', manifest)
            final = root / 'datasets' / identifier
            if final.exists():
                raise FileExistsError(final)
            stage.rename(final)
            return manifest
        except BaseException:
            # Only remove this fresh, validated staging directory inside the dataset root.
            if stage.exists() and stage.parent.resolve() == (root / 'datasets').resolve() and stage.name.startswith('.import-'):
                shutil.rmtree(stage)
            raise


class DataService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._verified = {}
        self._market_cache = None
        self._latest_quality_cache = {}

    def _directory(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
            raise ValueError('invalid dataset id')
        return self.root / 'datasets' / identifier

    def list_datasets(self):
        directory = self.root / 'datasets'
        return [self.get_dataset(p.parent.name) for p in sorted(directory.glob('*/manifest.json')) if not p.parent.name.startswith('.')]

    def get_dataset(self, identifier):
        directory = self._directory(identifier)
        manifest = read_json(directory / 'manifest.json')
        if manifest.get('id') != identifier or digest({k: v for k, v in manifest.items() if k != 'manifest_digest'}) != manifest.get('manifest_digest'):
            raise DataIntegrityError('dataset manifest identity mismatch')
        if digest(manifest['universe']['codes']) != manifest['universe']['hash']:
            raise DataIntegrityError('universe identity mismatch')
        for filename, expected in manifest['files'].items():
            path = (directory / filename).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise DataIntegrityError('unsafe dataset file path')
            signature = _stat(path)
            key = (str(path), expected)
            if self._verified.get(key) != signature:
                if file_digest(path) != expected or _stat(path) != signature:
                    raise DataIntegrityError(f'dataset file changed: {filename}')
                self._verified[key] = signature
        # Application availability is evaluated for the actual selected day.  This is
        # an overlay, never a mutation of the frozen manifest or research data.
        result = self._apply_latest_filter_quality(manifest, directory)
        # Existing research snapshots retain their original identity. Descriptions
        # are a separately sourced presentation overlay, as is current filter QA.
        result['fields'], result['field_dictionary'] = enrich_catalog(result.get('fields', []))
        return result

    def _apply_latest_filter_quality(self, manifest, directory):
        path = directory / 'market.parquet'
        latest = manifest.get('latest_complete_date')
        signature = _stat(path)
        key = (manifest['id'], manifest.get('market_sha256'), signature, latest)
        if key not in self._latest_quality_cache:
            available = set(pq.read_schema(path).names)
            columns = [c for c in ['date', 'code', 'turnover', *RAW_FIELDS] if c in available]
            frame = (pd.read_parquet(path, columns=columns,
                       filters=[('date', '==', pd.Timestamp(latest))]) if latest else pd.DataFrame())
            if _stat(path) != signature:
                raise DataIntegrityError('market changed during latest-day field audit')
            statistics = {}
            for field in ['turnover', *RAW_FIELDS]:
                if field in frame:
                    values = pd.to_numeric(frame[field], errors='coerce')
                    statistics[field] = dict(finite=int(np.isfinite(values).sum()),
                        positive=int((values > 0).sum()), zero=int(values.eq(0).sum()))
            reason = None
            if frame.empty or statistics.get('turnover', {}).get('finite', 0) == 0:
                reason = f'{latest or "当前日期"}没有可用换手率数据，不能用于筛选。'
            elif 'volume' in frame and 'turnover' in frame:
                active = pd.to_numeric(frame.volume, errors='coerce') > 0
                turnover = pd.to_numeric(frame.loc[active, 'turnover'], errors='coerce')
                if active.any() and turnover.notna().all() and turnover.eq(0).all():
                    reason = (f'{latest}有{int(active.sum())}只股票成交量为正，但其换手率全部为0，'
                              '疑似缺失值占位，当前换手率筛选已禁用；历史非零值不能证明本日可用。')
            self._latest_quality_cache[key] = dict(date=latest, rows=len(frame), fields=statistics,
                turnover=dict(enabled=reason is None, reason=reason),
                audit_rule='latest-day-turnover-positive-volume-zero-placeholder-v1')
        quality = self._latest_quality_cache[key]
        result = copy.deepcopy(manifest)
        result['filter_quality'] = copy.deepcopy(quality)
        if not quality['turnover']['enabled'] and 'turnover' in result.get('filters', {}):
            result['filters']['turnover'].update(enabled=False, reason=quality['turnover']['reason'])
        return result

    def load_market(self, identifier):
        """Return a shared read-only-by-contract frame; callers must copy before modifying."""
        manifest = self.get_dataset(identifier)
        path = self._directory(identifier) / 'market.parquet'
        signature = (identifier, manifest['market_sha256'], _stat(path))
        if self._market_cache is not None and self._market_cache[0] == signature:
            return self._market_cache[1]
        # Audit-only strings/flags stay on disk; shared model cache holds calculation columns.
        wanted = {'date', 'code', 'name', 'listing_days', 'turnover', 'observed',
                  'eligible', 'exec_open', 'exec_close', 'can_buy_open', 'can_sell_open',
                  'share_multiplier', 'cash_dividend', *FEATURE_LOOKBACKS,
                  *(f'{f}__available_at' for f in FEATURE_LOOKBACKS)}
        columns = [name for name in pq.read_schema(path).names if name in wanted]
        frame = pd.read_parquet(path, columns=columns)
        if len(frame) != manifest['rows'] or sorted(frame.code.unique()) != manifest['universe']['codes']:
            raise DataIntegrityError('market shape/universe mismatch')
        if _stat(path) != signature[2]:
            raise DataIntegrityError('market changed while loading')
        self._market_cache = (signature, frame)
        return frame

    def protocol_template(self, identifier):
        info = self.get_dataset(identifier)
        dates = pd.to_datetime(info['calendar'])
        if len(dates) < 141:
            raise ValueError('at least 141 observed sessions required for 121-session warmup and F/E/V/T')
        p = prototype_protocol(dates[121:], name='raw500-v1-mechanism', fields=list(FEATURE_LOOKBACKS),
            windows=[1, 5, 10, 20, 60], max_tokens=15, max_factors=5,
            top_k=min(50, info['code_count']), max_lookback=120,
            field_lookbacks=FEATURE_LOOKBACKS, operator_profile='extended', require_feature=True,
            compress_artifacts=True, holdout_status='previously_observed_historical',
            initial_expressions=['return_20', 'neg(return_5)', 'neg(volatility_20)'],
            initial_weights=[.4, .3, .3], batches=2, episodes_per_batch=4,
            search_budget=6, selection_batches=[1, 2], max_backtests=1000,
            universe_note=f"Fixed raw-source 500-code sample; universe SHA256 {info['universe']['hash']}; selection bias unresolved.",
            execution_note=NOTE)
        return p.to_dict()

    def prepare_research_snapshot(self, identifier, protocol, destination):
        info = self.get_dataset(identifier)
        p = Protocol.from_dict(protocol) if isinstance(protocol, dict) else protocol
        p.validate()
        if p.data_mode != 'legacy_prototype' or p.synthetic:
            raise ValueError('raw source is only approved for non-synthetic legacy_prototype mode')
        if not set(p.fields).issubset(FEATURE_LOOKBACKS):
            raise ValueError('unverified/financial fields cannot enter historical research')
        if dict(p.field_lookbacks) != {f: FEATURE_LOOKBACKS[f] for f in p.fields}:
            raise ValueError('feature lookbacks must match the registered causal feature definitions')
        if p.holdout_status != 'previously_observed_historical':
            raise ValueError('these historical data have already been observed')
        return prepare_snapshot(self.load_market(identifier), destination, p,
            {f: info['field_metadata'][f] for f in p.fields},
            source_metadata=dict(dataset_id=identifier, source_sha256=info['source']['sha256'],
                                 market_sha256=info['market_sha256'],
                                 universe=info['universe'], quality=info['quality']))
