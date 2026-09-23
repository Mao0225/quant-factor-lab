"""Immutable model packages, explicit availability, plans, and selection records."""
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import uuid

import numpy as np
import pandas as pd

from ..expressions import ExpressionSpace
from ..data import DataIntegrityError
from ..protocol import Protocol
from ..scoring import quality
from ..storage import atomic_json, digest, read_json, writer_lock
from .model_scoring import compute_scores, scorer_identity, field_contract, validate_dataset_contract


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value):
        raise ValueError('invalid object id')
    return value


def _codes(dataset):
    universe = dataset.get('universe', {})
    codes = universe.get('codes', []) if isinstance(universe, dict) else universe
    result = sorted(str(c) for c in codes)
    if not result or len(set(result)) != len(result):
        raise ValueError('dataset requires a unique frozen universe')
    if isinstance(universe, dict) and universe.get('hash') and universe['hash'] != digest(result):
        raise ValueError('dataset universe identity mismatch')
    return result


def _field_names(dataset):
    names = set(dataset.get('signal_fields', []))
    fields = dataset.get('fields', {})
    if isinstance(fields, dict):
        names.update(fields)
    else:
        names.update(f.get('name', f.get('field')) if isinstance(f, dict) else f for f in fields)
    return names


def _number(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float, np.number)):
        return float(value) if math.isfinite(float(value)) else None
    return str(value)


class ModelService:
    def __init__(self, root, data_service):
        self.root, self.data_service = Path(root), data_service
        self.models = self.root/'models'
        self._score_cache = {}

    def _bundle(self, version_id):
        path = self.models/'versions'/f'{_id(version_id)}.json'
        if not path.exists():
            raise ValueError('unknown model version')
        bundle = read_json(path)
        body = {k: v for k, v in bundle.items() if k != 'version_id'}
        if bundle.get('version_id') != version_id or version_id != 'model_'+digest(body):
            raise ValueError('model package identity mismatch')
        return bundle

    def _meta(self, version_id):
        return read_json(self.models/'metadata'/f'{_id(version_id)}.json')

    def _group(self, model_id):
        path = self.models/'groups'/f'{_id(model_id)}.json'
        if not path.exists():
            raise ValueError('unknown model group')
        return read_json(path)

    def _audit(self, version_id, action, before, after, actor='local_user'):
        atomic_json(self.models/'audit'/f'{uuid.uuid4().hex}.json',
                    dict(version_id=version_id, action=action, actor=actor, created_at=_now(), before=before, after=after))

    def _readiness(self, bundle, dataset_id=None):
        dataset = None
        try:
            dataset = self.data_service.get_dataset(dataset_id) if dataset_id else self._latest_dataset(bundle)
            if bundle['scorer_identity'] != scorer_identity():
                raise ValueError('model scorer identity changed')
            if dataset.get('status') not in {'ready', 'available', 'complete', 'completed'}:
                raise ValueError('dataset is not ready')
            if not dataset.get('latest_complete_date'):
                raise ValueError('no complete usable data date')
            if digest(_codes(dataset)) != bundle['universe']['hash']:
                raise ValueError('dataset differs from frozen model universe')
            if not set(bundle['required_fields']).issubset(_field_names(dataset)):
                raise ValueError('required model fields are unavailable')
            validate_dataset_contract(bundle, dataset)
            scored = self._current_scores(bundle, dataset)
            p = Protocol.from_dict(bundle['protocol'])
            for expression in bundle['weights']:
                checks = quality(scored, scored[f'raw:{expression}'].to_numpy(), p)
                if not checks['passed']:
                    raise ValueError(f'current factor coverage/degeneracy requirements failed: {expression}')
            # Availability is separate from the manual candidate/available status.
            return dataset, None
        except (ValueError, KeyError, FileNotFoundError, DataIntegrityError) as exc:
            return dataset, str(exc)

    def _latest_dataset(self, bundle):
        compatible, reasons = [], []
        for dataset in self.data_service.list_datasets():
            try:
                if digest(_codes(dataset)) != bundle['universe']['hash']:
                    raise ValueError('different universe')
                validate_dataset_contract(bundle, dataset)
                if dataset.get('status') not in {'ready', 'available', 'complete', 'completed'} or not dataset.get('latest_complete_date'):
                    raise ValueError('no complete usable data date')
                compatible.append(dataset)
            except (ValueError, KeyError) as exc:
                reasons.append(str(exc))
        if not compatible:
            raise ValueError('no compatible current dataset: '+('; '.join(sorted(set(reasons))) or 'none imported'))
        # Do not silently fall back to an older date if scoring on this date fails.
        return max(compatible, key=lambda d: (d['latest_complete_date'], d['id']))

    def _current_scores(self, bundle, dataset):
        # Immutable datasets permit caching; anonymous/test frames are always checked.
        key = (bundle['version_id'], dataset['id'], dataset.get('market_sha256'),
               dataset.get('manifest_digest'), dataset['latest_complete_date'])
        if not dataset.get('market_sha256') or key not in self._score_cache:
            scored = compute_scores(bundle, self.data_service.load_market(dataset['id']), dataset['latest_complete_date'])
            if dataset.get('market_sha256'):
                self._score_cache[key] = scored
            return scored
        return self._score_cache[key]

    def get_model(self, version_id):
        bundle = self._bundle(version_id)
        meta = self._meta(version_id)
        group = self._group(meta['model_id'])
        dataset, reason = self._readiness(bundle)
        return dict(version_id=version_id, model_id=meta['model_id'], default_version=group['default_version'],
                    is_default=group['default_version'] == version_id,
                    name=meta['name'], description=meta.get('description', ''),
                    tags=meta.get('tags', []), researcher=meta.get('researcher', ''), status=meta['status'], evaluation=meta['evaluation'],
                    data_ready=reason is None, blocked_reason=reason, weights=bundle['weights'],
                    dataset_id=dataset['id'] if dataset else None, source_dataset_id=bundle['dataset_id'],
                    data_date=dataset['latest_complete_date'] if dataset else None,
                    source=bundle['source'], required_fields=bundle['required_fields'],
                    default_top_k=bundle['protocol']['top_k'], universe_count=len(bundle['universe']['codes']),
                    created_at=meta['created_at'], updated_at=meta['updated_at'], data_mode=bundle['protocol']['data_mode'])

    def list_models(self):
        return sorted([self.get_model(p.stem) for p in (self.models/'versions').glob('*.json')],
                      key=lambda m: (m['created_at'], m['version_id']), reverse=True)

    def register_run(self, run_root, dataset_id, name=None):
        # Registration may inspect research evidence; new-date scoring never does.
        from ..runner import code_identity, load_state
        run = Path(run_root)
        dataset = self.data_service.get_dataset(_id(dataset_id))
        p = Protocol.from_dict(read_json(run/'protocol.json'))
        frozen = read_json(run/'frozen_model.json')
        if digest({k: v for k, v in frozen.items() if k != 'model_id'}) != frozen.get('model_id'):
            raise ValueError('frozen model was modified: hash identity mismatch')
        experiment, saved = read_json(run/'experiment.json'), load_state(run)
        identity = saved['identity']
        if saved['state']['phase'] != 'finished':
            raise ValueError('research must finish before registering a model')
        if any(obj.get('protocol_digest') != p.digest for obj in (frozen, experiment, identity)):
            raise ValueError('source protocol identity mismatch')
        if any(obj.get('code_identity') != code_identity() for obj in (frozen, experiment, identity)):
            raise ValueError('source code identity differs from the current kernel')
        manifest = read_json(Path(experiment['snapshot_path'])/'manifest.json')
        if digest({k: v for k, v in manifest.items() if k != 'snapshot_id'}) != manifest['snapshot_id']:
            raise ValueError('source snapshot identity mismatch')
        if any(obj.get('snapshot_id') != manifest['snapshot_id'] for obj in (frozen, experiment, identity)):
            raise ValueError('source snapshot differs from the frozen model')
        origin = manifest.get('source_metadata', {}).get('dataset_id')
        if origin != dataset_id:
            raise ValueError('research snapshot must identify the selected source dataset')
        selection = read_json(run/'selection.json')
        if selection['frozen_model_id'] != frozen['model_id']:
            raise ValueError('selection/frozen model identity mismatch')
        artifact = read_json(run/'selection_backtests'/f"{frozen['selection_artifact']}.json")
        if (artifact.get('identity') != frozen['selection_artifact'] or
                digest(artifact['result']) != artifact.get('result_digest') or
                artifact.get('protocol_digest') != p.digest or artifact.get('snapshot_id') != manifest['snapshot_id'] or
                artifact.get('weights') != frozen['weights'] or artifact.get('segment') != 'V'):
            raise ValueError('selection evidence identity mismatch')
        space = ExpressionSpace(p)
        weights = dict(sorted(frozen['weights'].items()))
        if (not weights or len(weights) > p.max_factors or
                any(not math.isfinite(float(w)) or abs(float(w)) <= 1e-12 for w in weights.values()) or
                not math.isclose(sum(abs(w) for w in weights.values()), 1., rel_tol=1e-7)):
            raise ValueError('invalid frozen weights')
        nodes = [space.parse(expr) for expr in weights]
        required = sorted({t for node in nodes for t in node.tokens if t in p.fields})
        codes = _codes(dataset)
        source_universe = manifest.get('source_metadata', {}).get('universe')
        if source_universe and source_universe.get('hash') != digest(codes):
            raise ValueError('source and chosen dataset universe identity mismatch')
        # This source is a calculation package, not a mutable path back to a run.
        bundle = dict(schema=1, protocol=p.to_dict(), weights=weights, dataset_id=dataset_id,
                      universe=dict(codes=codes, hash=digest(codes)), required_fields=required,
                      field_contracts={f: field_contract(manifest['fields'][f]) for f in required},
                      dataset_scoring_contract=dataset.get('scoring_contract'),
                      scoring_policy=dict(standardization='finite basic-eligible values, population ddof=0',
                          epsilon=p.epsilon, constant_section='zero', sparse_missing='zero contribution with flag',
                          all_active_missing='reject calculation', filters='after full-universe scoring',
                          ranking='descending score, ascending code'),
                      lookback=max(space.lookback(node) for node in nodes), scorer_identity=scorer_identity(),
                      source=dict(experiment_id=run.parent.name, frozen_model_id=frozen['model_id'],
                                  protocol_digest=p.digest, snapshot_id=manifest['snapshot_id'],
                                  code_identity=identity['code_identity'], selected_batch=frozen['selected_batch'],
                                  selection_artifact=frozen['selection_artifact']))
        version_id = 'model_'+digest(bundle)
        bundle['version_id'] = version_id
        evaluation = dict(status='completed', selection=dict(segment='V', bounds=list(p.bounds('V')),
                          objective=frozen['selection_objective'], metrics=artifact['result']['metrics']), test=None,
                          data_mode=p.data_mode, synthetic=p.synthetic, holdout_status=p.holdout_status,
                          interpretation='prototype diagnostic only' if p.synthetic or p.data_mode == 'legacy_prototype' else 'research evaluation')
        if (run/'test_result.json').exists():
            test = read_json(run/'test_result.json')
            if test['frozen_model_id'] != frozen['model_id']:
                raise ValueError('test/frozen model identity mismatch')
            evaluation['test'] = dict(segment='T', bounds=list(p.bounds('T')), objective=test['objective'],
                                      metrics=test['metrics'], holdout_status=p.holdout_status)
        with writer_lock(self.models):
            path = self.models/'versions'/f'{version_id}.json'
            if path.exists():
                self._bundle(version_id)
                meta = self._meta(version_id)
                if meta['evaluation'] != evaluation:
                    before = meta['evaluation']
                    meta['evaluation'], meta['updated_at'] = evaluation, _now()
                    self._audit(version_id, 'research_evidence', before, evaluation, 'research')
                    atomic_json(self.models/'metadata'/f'{version_id}.json', meta)
            else:
                atomic_json(path, bundle)
                now = _now()
                model_id = 'group_'+digest(version_id)[:24]
                meta = dict(name=name or p.name, description='', tags=[], researcher='', status='candidate',
                            model_id=model_id, evaluation=evaluation, created_at=now, updated_at=now)
                atomic_json(self.models/'groups'/f'{model_id}.json',
                            dict(model_id=model_id, default_version=version_id, created_at=now))
                atomic_json(self.models/'metadata'/f'{version_id}.json', meta)
                self._audit(version_id, 'registered', None, meta, 'research')
        return self.get_model(version_id)

    def update_metadata(self, version_id, changes):
        if not isinstance(changes, dict) or set(changes)-{'name', 'description', 'tags', 'researcher', 'model_id', 'default_version'}:
            raise ValueError('only model display metadata may be edited')
        if 'name' in changes and (not isinstance(changes['name'], str) or not changes['name'].strip()):
            raise ValueError('model name must not be empty')
        if 'description' in changes and not isinstance(changes['description'], str):
            raise ValueError('description must be text')
        if 'researcher' in changes and not isinstance(changes['researcher'], str):
            raise ValueError('researcher must be text')
        if 'tags' in changes and (not isinstance(changes['tags'], list) or any(not isinstance(t, str) for t in changes['tags'])):
            raise ValueError('tags must be text values')
        with writer_lock(self.models):
            self._bundle(version_id)
            meta = self._meta(version_id)
            model_id = changes.get('model_id', meta['model_id'])
            group = self._group(model_id)
            if 'default_version' in changes:
                default = changes['default_version']
                self._bundle(default)
                if default != version_id and self._meta(default)['model_id'] != model_id:
                    raise ValueError('default version must belong to this model')
                group = {**group, 'default_version': default}
            if model_id != meta['model_id']:
                old_group = self._group(meta['model_id'])
                if old_group['default_version'] == version_id:
                    old_group['default_version'] = None
                    atomic_json(self.models/'groups'/f"{meta['model_id']}.json", old_group)
            after = {**meta, **{k: v for k, v in changes.items() if k != 'default_version'}, 'updated_at': _now()}
            self._audit(version_id, 'model_group', self._group(model_id), group)
            atomic_json(self.models/'groups'/f'{model_id}.json', group)
            self._audit(version_id, 'metadata', meta, after)
            atomic_json(self.models/'metadata'/f'{version_id}.json', after)
        return self.get_model(version_id)

    def set_status(self, version_id, status):
        if status not in {'candidate', 'available', 'disabled'}:
            raise ValueError('unknown model status')
        with writer_lock(self.models):
            bundle = self._bundle(version_id)
            meta = self._meta(version_id)
            if status == 'available':
                _, reason = self._readiness(bundle)
                if reason:
                    raise ValueError(f'model data unavailable: {reason}')
                if meta['evaluation']['status'] != 'completed':
                    raise ValueError('model evaluation incomplete')
            previous = meta['status']
            meta['status'], meta['updated_at'] = status, _now()
            self._audit(version_id, 'status', previous, status)
            atomic_json(self.models/'metadata'/f'{version_id}.json', meta)
        return self.get_model(version_id)

    def _config(self, config, require_available=False):
        if not isinstance(config, dict) or set(config)-{'model_version', 'dataset_id', 'filters', 'top_n'}:
            raise ValueError('invalid selection configuration')
        version = _id(config.get('model_version'))
        bundle = self._bundle(version)
        if require_available and self._meta(version)['status'] != 'available':
            raise ValueError('model version must be available / 可用')
        dataset_id = _id(config['dataset_id']) if config.get('dataset_id') else None
        dataset, reason = self._readiness(bundle, dataset_id)
        if reason:
            raise ValueError(f'data unavailable: {reason}')
        dataset_id = dataset['id']
        top_n = config.get('top_n', bundle['protocol']['top_k'])
        if type(top_n) is not int or top_n < 1:
            raise ValueError('top_n must be a positive integer')
        filters = config.get('filters') or {}
        if not isinstance(filters, dict) or set(filters)-{'board', 'listing_days', 'amount', 'turnover'}:
            raise ValueError('unknown selection filter / 过滤')
        normalized = {}
        for name, condition in filters.items():
            enabled = dataset.get('filters', {}).get(name, {})
            if not enabled.get('enabled'):
                raise ValueError(f'filter {name} unavailable: {enabled.get("reason", "not verified")}')
            if name == 'board':
                if not isinstance(condition, list) or any(not isinstance(c, (str, int)) or isinstance(c, bool) for c in condition):
                    raise ValueError('board filter must be a list')
                if condition:
                    normalized[name] = sorted(set(str(c) for c in condition))
            else:
                if not isinstance(condition, dict) or set(condition)-{'min', 'max'}:
                    raise ValueError(f'invalid {name} filter range')
                bounds = {}
                for key, number in condition.items():
                    if number is None:
                        continue
                    if type(number) not in (int, float) or not math.isfinite(number):
                        raise ValueError(f'invalid {name} filter bound')
                    bounds[key] = number
                if bounds.get('min', -math.inf) > bounds.get('max', math.inf):
                    raise ValueError(f'inverted {name} filter range')
                if bounds:
                    normalized[name] = bounds
        return dict(model_version=version, dataset_id=dataset_id, filters=normalized, top_n=top_n), bundle, dataset

    def select(self, config):
        # The lock fixes availability and display metadata throughout one calculation.
        with writer_lock(self.models):
            config, bundle, dataset = self._config(config, require_available=True)
            scored = self._current_scores(bundle, dataset)
            eligible = scored.eligible.to_numpy(dtype=bool)
            keep = eligible.copy()
            for field, condition in config['filters'].items():
                if field not in scored:
                    raise ValueError(f'filter field unavailable: {field}')
                col = scored[field]
                if field == 'board':
                    keep &= (col.notna() & col.astype(str).isin(condition)).to_numpy()
                else:
                    number = pd.to_numeric(col, errors='coerce')
                    keep &= np.isfinite(number.to_numpy())
                    if 'min' in condition:
                        keep &= (number >= condition['min']).to_numpy()
                    if 'max' in condition:
                        keep &= (number <= condition['max']).to_numpy()
            candidates = scored.loc[keep].sort_values(['score', 'code'], ascending=[False, True], kind='stable')
            rows = []
            for rank, (_, stock) in enumerate(candidates.head(config['top_n']).iterrows(), 1):
                contributions = []
                for expr, weight in bundle['weights'].items():
                    contribution = float(stock[f'contribution:{expr}'])
                    contributions.append(dict(expression=expr, weight=weight, raw=_number(stock[f'raw:{expr}']),
                                              standardized=contribution/weight, contribution=contribution,
                                              missing=bool(stock[f'missing:{expr}'])))
                row = dict(code=str(stock.code), name=_number(stock.get('name')) or str(stock.code),
                           score=float(stock.score), rank=rank, contributions=contributions)
                row['attribute_status'] = {}
                for attr in ('board', 'listing_days', 'amount', 'turnover'):
                    if attr in stock:
                        metadata = dataset.get('filters', {}).get(attr, {})
                        available = bool(metadata.get('enabled'))
                        row[attr] = _number(stock[attr]) if available else None
                        row['attribute_status'][attr] = dict(available=available, unit=metadata.get('unit'),
                                                             reason=metadata.get('reason'), date=dataset['latest_complete_date'])
                rows.append(row)
            observed = np.zeros(len(scored), dtype=bool)
            for expr in bundle['weights']:
                observed |= ~scored[f'missing:{expr}'].to_numpy(dtype=bool)
            custom = bool(config['filters']) or config['top_n'] != bundle['protocol']['top_k']
            note = '自定义方案，尚无对应历史评价；不继承模型原配置收益。' if custom else '沿用模型评分范围与 Top K；研究评价只对应原研究区间，不代表本次名单收益。'
            if bundle['protocol']['data_mode'] == 'legacy_prototype' or bundle['protocol']['synthetic']:
                note += ' 数据与执行口径为 prototype，未验证为正式历史收益。'
            result = dict(id='result_'+uuid.uuid4().hex, created_at=_now(), model_version=bundle['version_id'],
                          model_name=self._meta(bundle['version_id'])['name'], dataset_id=config['dataset_id'],
                          data_date=dataset['latest_complete_date'], config=config,
                          counts=dict(scoring_universe=len(scored), basic_eligible=int(eligible.sum()),
                                      coverage=int((observed & eligible).sum()), after_filter=len(candidates), selected=len(rows)),
                          rows=rows, evaluation_note=note, source=bundle['source'],
                          input_snapshot=dict(dataset_id=config['dataset_id'], universe_hash=bundle['universe']['hash'],
                                              manifest_digest=dataset.get('manifest_digest'),
                                              market_sha256=dataset.get('market_sha256'),
                                              source_sha256=dataset.get('source_sha256') or dataset.get('source', {}).get('sha256')),
                          scorer_identity=bundle['scorer_identity'])
            atomic_json(self.root/'results'/f"{result['id']}.json", result)
            return result

    def list_results(self):
        return sorted([read_json(p) for p in (self.root/'results').glob('*.json')], key=lambda r: r['created_at'], reverse=True)

    def get_result(self, result_id):
        path = self.root/'results'/f'{_id(result_id)}.json'
        if not path.exists():
            raise ValueError('unknown result')
        return read_json(path)

    def save_plan(self, body):
        if not isinstance(body, dict) or set(body)-{'id', 'parent_id', 'name', 'config'}:
            raise ValueError('invalid plan')
        if not isinstance(body.get('name'), str) or not body['name'].strip():
            raise ValueError('plan name is required')
        config, _, _ = self._config(body.get('config'))
        # Plans bind computation, filters and N. Each execution fixes fresh data.
        config.pop('dataset_id')
        with writer_lock(self.root/'plans'):
            parent_id = body.get('parent_id') or body.get('id')
            previous = self.get_plan(parent_id) if parent_id else None
            plan = dict(id='plan_'+uuid.uuid4().hex, name=body['name'].strip(),
                        revision=previous['revision']+1 if previous else 1,
                        config=config, created_at=_now())
            if parent_id:
                plan['parent_id'] = parent_id
            atomic_json(self.root/'plans'/f"{plan['id']}.json", plan)
        return plan

    def list_plans(self):
        return sorted([read_json(p) for p in (self.root/'plans').glob('*.json')], key=lambda p: p['created_at'], reverse=True)

    def get_plan(self, plan_id):
        path = self.root/'plans'/f'{_id(plan_id)}.json'
        if not path.exists():
            raise ValueError('unknown plan')
        return read_json(path)
