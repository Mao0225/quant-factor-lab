"""Application orchestration around the verified, unchanged research kernel."""
from pathlib import Path
from threading import RLock
from uuid import uuid4

from ..protocol import Protocol
from ..runner import run_experiment
from ..selection import select_model, test_model
from ..storage import read_json, atomic_json, digest
from .jobs import now, safe_id


class ResearchService:
    def __init__(self, root, data, models, jobs):
        self.root, self.data, self.models, self.jobs = Path(root), data, models, jobs
        self.lock = RLock()
        for path in (self.root/'experiments').glob('*/record.json'):
            record = read_json(path)
            if record['status'] in {'queued','running','preparing','pause_requested','stop_requested','selecting'}:
                record.update(status='interrupted', error='服务中断，可从检查点恢复。')
                atomic_json(path, record)

    def projects(self):
        return [read_json(p) for p in (self.root/'projects').glob('*.json')]

    def create_project(self, body):
        name = str(body.get('name','')).strip()
        if not name or len(name)>120:
            raise ValueError('请填写项目名称（最多120字符）')
        record = dict(id=uuid4().hex, name=name, question=str(body.get('question',''))[:3000], created_at=now())
        atomic_json(self.root/'projects'/f"{record['id']}.json", record)
        return record

    def _path(self, experiment_id):
        return self.root/'experiments'/safe_id(experiment_id)

    def list_experiments(self):
        return sorted([read_json(p) for p in (self.root/'experiments').glob('*/record.json')], key=lambda x:x['created_at'], reverse=True)

    def _record(self, experiment_id):
        return read_json(self._path(experiment_id)/'record.json')

    def _run_path(self, experiment_id):
        record=self._record(experiment_id)
        if record.get('comparison_id'):
            return self.root/'comparisons'/safe_id(record['comparison_id'])/'suite'/safe_id(record['comparison_member'])
        return self._path(experiment_id)/'run'

    def _update(self, experiment_id, **changes):
        with self.lock:
            record = self._record(experiment_id)
            record.update(changes, updated_at=now())
            atomic_json(self._path(experiment_id)/'record.json', record)
            return record

    def _validate_protocol(self, body):
        dataset = self.data.get_dataset(safe_id(body['dataset_id']))
        p = Protocol.from_dict(body['protocol'])
        # Price prototype data must not be promoted by editing the protocol JSON.
        if p.synthetic or p.data_mode != dataset['data_mode']:
            raise ValueError('协议数据模式与快照不一致')
        allowed = set(self.data.protocol_template(dataset['id'])['fields'])
        if not set(p.fields).issubset(allowed):
            raise ValueError('协议包含未核验字段；财务字段禁止用于历史训练')
        if p.holdout_status != 'previously_observed_historical':
            raise ValueError('当前历史已被观察，不能标为全新测试集')
        return dataset,p

    def create(self, body):
        dataset,p=self._validate_protocol(body)
        name = str(body.get('name',p.name)).strip()
        if not name or len(name)>120:
            raise ValueError('实验名称无效')
        project_id = body.get('project_id')
        if project_id:
            read_json(self.root/'projects'/f'{safe_id(project_id)}.json')
        else:
            projects = self.projects()
            project_id = (projects[0] if projects else self.create_project({'name':'500股原型研究','question':'检验组合交易增量反馈的程序机制'}))['id']
        record = dict(id=uuid4().hex, name=name, dataset_id=dataset['id'], project_id=project_id,
                      status='draft', created_at=now(), protocol=p.to_dict(), protocol_digest=p.digest,
                      model_version=None, job_id=None)
        atomic_json(self._path(record['id'])/'record.json', record)
        return record

    def detail(self, experiment_id):
        record = self._record(experiment_id)
        run = self._run_path(experiment_id)
        result = dict(record, run_status={}, trials=[], batches=[], pools=[], updates=[], selection=None, test=None)
        if (run/'status.json').exists():
            result['run_status'] = read_json(run/'status.json')
        for path in sorted((run/'batches').glob('*-committed.json')):
            batch = read_json(path)
            result['trials'].extend([dict(t,batch_id=batch['batch_id']) for t in batch['trials']])
            summary=batch.get('summary',{})
            brief={k:summary[k] for k in ('batch_id','seed','incumbent','incumbent_e','baseline_e') if k in summary}
            brief['baseline']={k:v for k,v in summary.get('baseline',{}).items() if k!='trials'}
            result['batches'].append(dict(batch_id=batch['batch_id'],
                loaded_pool_version=batch.get('loaded_pool_version'), next_pool_version=batch.get('next_pool_version'),
                decision=batch.get('decision',{}), summary=brief))
        result['pools'] = [read_json(p) for p in sorted((run/'pools').glob('*.json'))]
        result['updates'] = [read_json(p) for p in sorted((run/'batches').glob('*-ppo.json'))]
        for key, filename in [('selection','selection.json'),('test','test_result.json')]:
            if (run/filename).exists():
                result[key] = read_json(run/filename)
        return result

    def start(self, experiment_id, resume=False):
        with self.lock:
            record = self._record(experiment_id)
            allowed = {'paused','interrupted','failed'} if resume else {'draft'}
            if record['status'] not in allowed:
                raise ValueError('当前状态不能启动/恢复')
            self._update(experiment_id, status='queued', error=None)
            job = self.jobs.submit('research', lambda jid:self._train(experiment_id,jid), experiment_id=experiment_id, name=record['name'])
            self._update(experiment_id, job_id=job['id'])
            return job

    def control(self, experiment_id, action):
        with self.lock:
            record = self._record(experiment_id)
            if action == 'stop' and record['status'] in {'paused','interrupted','failed'}:
                return self._update(experiment_id,status='stopped')
            if record['status'] not in {'queued','preparing','running','pause_requested','stop_requested'}:
                raise ValueError('当前阶段不能暂停/停止；已冻结模型不会被改写')
            job = self.jobs.request(record['job_id'],action)
            self._update(experiment_id,status=f'{action}_requested')
            return job

    def _train(self, experiment_id, job_id):
        try:
            with self.lock:
                record = self._record(experiment_id)
                self._update(experiment_id,status='preparing')
            p = Protocol.from_dict(record['protocol'])
            if p.digest != record['protocol_digest']:
                raise ValueError('实验协议已被修改，拒绝恢复')
            base = self._path(experiment_id)
            snapshot = base/'snapshot'
            if not (snapshot/'manifest.json').exists():
                self.data.prepare_research_snapshot(record['dataset_id'],p,snapshot)
            self._update(experiment_id,status='running')
            while True:
                request = self.jobs.get(job_id).get('request')
                if request in {'pause','stop'}:
                    status = 'paused' if request=='pause' else 'stopped'
                    self._update(experiment_id,status=status)
                    return dict(job_status=status,experiment_id=experiment_id)
                state = run_experiment(p,snapshot,base/'run',max_batches_this_call=1,
                                       progress=lambda s:self.jobs.update(job_id,progress=s))
                request = self.jobs.get(job_id).get('request')
                if request in {'pause','stop'}:
                    status = 'paused' if request=='pause' else 'stopped'
                    self._update(experiment_id,status=status)
                    return dict(job_status=status,experiment_id=experiment_id)
                if state['phase'] == 'finished':
                    break
            self._update(experiment_id,status='selecting')
            select_model(base/'run')
            model = self.models.register_run(base/'run',record['dataset_id'],record['name'])
            self._update(experiment_id,status='finished',model_version=model['version_id'])
            return dict(experiment_id=experiment_id,model_version=model['version_id'])
        except Exception as exc:
            self._update(experiment_id,status='failed',error=f'{type(exc).__name__}: {exc}')
            raise

    def test(self, experiment_id):
        with self.lock:
            record = self._record(experiment_id)
            if record['status'] != 'finished' or not record['model_version']:
                raise ValueError('最终测试仅允许对完成选择并冻结的模型运行')
            if record.get('test_job_id'):
                old = self.jobs.get(record['test_job_id'])
                if old['status'] in {'queued','running','succeeded'}:
                    return old
            def work(jid):
                result = test_model(self._run_path(experiment_id))
                # Evaluation evidence is append-only and does not change the compute package.
                model = self.models.register_run(self._run_path(experiment_id),record['dataset_id'],record['name'])
                return dict(experiment_id=experiment_id,model_version=model['version_id'],test=result)
            job = self.jobs.submit('final_test',work,experiment_id=experiment_id,name=record['name'])
            self._update(experiment_id,test_job_id=job['id'])
            return job

    def comparison(self, project_id, body):
        """Register all methods/seeds together; freeze all before optional T."""
        from ..comparison import run_suite
        read_json(self.root/'projects'/f'{safe_id(project_id)}.json')
        dataset_id = safe_id(body['dataset_id'])
        seeds = body.get('seeds',[7,19])
        if len(seeds)<2 or len(seeds)>10 or any(type(s) is not int for s in seeds) or len(set(seeds))!=len(seeds):
            raise ValueError('比较需2至10个不同整数随机种子')
        # Reuse the same data/protocol checks as an ordinary experiment.
        _,p = self._validate_protocol(body)
        comparison_id = uuid4().hex
        base = self.root/'comparisons'/comparison_id
        config = dict(id=comparison_id,project_id=project_id,dataset_id=dataset_id,protocol=p.to_dict(),
                      seeds=seeds,groups=['A','B','C','E'],final_test=bool(body.get('final_test',False)),created_at=now())
        atomic_json(base/'record.json',config)
        def work(jid):
            p = Protocol.from_dict(config['protocol'])
            snap = base/'snapshot'
            self.data.prepare_research_snapshot(dataset_id,p,snap)
            result = run_suite(p,snap,base/'suite',seeds,groups=config['groups'],final_test=config['final_test'],workers=1)
            versions = []
            for row in result['runs']:
                model = self.models.register_run(row['run'],dataset_id,f"{p.name} · {row['group']} / {row['seed']}")
                versions.append(model['version_id'])
                member=Path(row['run']).name
                member_p=Protocol.from_dict(read_json(Path(row['run'])/'protocol.json'))
                record=dict(id=uuid4().hex,name=f"{p.name} · {row['group']} / {row['seed']}",
                            dataset_id=dataset_id,project_id=project_id,status='finished',created_at=now(),
                            protocol=member_p.to_dict(),protocol_digest=member_p.digest,model_version=model['version_id'],
                            job_id=jid,comparison_id=comparison_id,comparison_member=member)
                atomic_json(self._path(record['id'])/'record.json',record)
                row['experiment_id']=record['id']
            # Public comparison objects retain evidence but not filesystem paths.
            public = {**result,'runs':[{k:v for k,v in row.items() if k!='run'} for row in result['runs']]}
            atomic_json(base/'result.json',dict(public,model_versions=versions))
            return dict(comparison_id=comparison_id,model_versions=versions)
        job = self.jobs.submit('comparison',work,comparison_id=comparison_id,name='A/B/C/E 多种子对照')
        atomic_json(base/'record.json',dict(config,job_id=job['id']))
        return job

    def comparisons(self):
        rows=[]
        for path in (self.root/'comparisons').glob('*/record.json'):
            row=read_json(path)
            if row.get('job_id'):
                row['status']=self.jobs.get(row['job_id'])['status']
            if (path.parent/'result.json').exists():
                row['result']=read_json(path.parent/'result.json')
            rows.append(row)
        return rows

    def backtests(self, experiment_id):
        """Describe permitted, existing evidence without loading backtest payloads.

        Cache identity is not a purpose: a single artifact can serve several rounds
        and roles. Keep every reference and choose only its display label by priority.
        """
        self._record(experiment_id)
        run=self._run_path(experiment_id)
        entries={}
        directories={'F':'backtests','E':'backtests','V':'selection_backtests','T':'test_backtests'}
        priorities=['final_test','selected','validation','adopted','candidate','baseline','incumbent','search']

        def permit(artifact_id, segment):
            if not artifact_id or segment not in directories:
                return
            path=run/directories[segment]/f'{safe_id(artifact_id)}.json'
            if path.is_file() or path.with_suffix('.json.gz').is_file():
                entries.setdefault(artifact_id,dict(artifact_id=artifact_id,segment=segment,references=[]))

        def reference(artifact_id, role, segment, *, weights=None, objective=None, **context):
            entry=entries.get(artifact_id)
            if entry is None or entry['segment']!=segment:
                return
            row=dict(role=role,**{k:v for k,v in context.items() if v is not None})
            if weights is not None:
                row['factor_count']=sum(abs(v)>1e-12 for v in weights.values())
            if objective is not None:
                row['objective']=objective
            if row not in entry['references']:
                entry['references'].append(row)

        def search_references(search, **context):
            steps=search.get('trials',[])
            for position, step in enumerate(steps,1):
                reference(step.get('artifact_id'),'search','F',weights=step.get('proposal'),
                          objective=step.get('objective'),search_step=step.get('index',position-1)+1,**context)
            if not any(s.get('artifact_id')==search.get('artifact_id') for s in steps):
                reference(search.get('artifact_id'),'search','F',weights=search.get('weights'),
                          objective=search.get('objective'),**context)

        # Only these records grant access; batch references below cannot grant it.
        for path in sorted((run/'backtests'/'invocations').glob('*.json')):
            receipt=read_json(path)
            if receipt['status']=='completed' and receipt['segment'] in {'F','E'}:
                permit(receipt['artifact_id'],receipt['segment'])
        selection=read_json(run/'selection.json') if (run/'selection.json').exists() else {}
        frozen=read_json(run/'frozen_model.json') if (run/'frozen_model.json').exists() else {}
        for row in selection.get('checkpoints',[]):
            permit(row.get('artifact_id'),'V')
            reference(row.get('artifact_id'),'validation','V',batch_id=row.get('batch_id'),
                      weights=row.get('weights'),objective=row.get('objective'))
        if (frozen.get('model_id') and frozen.get('model_id')==selection.get('frozen_model_id')):
            reference(frozen.get('selection_artifact'),'selected','V',batch_id=frozen.get('selected_batch'),
                      weights=frozen.get('weights'),objective=frozen.get('selection_objective'))
        if (run/'test_result.json').is_file():
            row=read_json(run/'test_result.json')
            permit(row.get('artifact_id'),'T')
            reference(row.get('artifact_id'),'final_test','T',batch_id=frozen.get('selected_batch'),
                      weights=frozen.get('weights'),objective=row.get('objective'))

        for path in sorted((run/'batches').glob('*-committed.json')):
            batch=read_json(path)
            batch_id=batch['batch_id']
            summary=batch.get('summary',{})
            incumbent=summary.get('incumbent_e',{})
            baseline=summary.get('baseline_e',{})
            search=summary.get('baseline',{})
            reference(incumbent.get('artifact_id'),'incumbent','E',batch_id=batch_id,
                      weights=summary.get('incumbent'),objective=incumbent.get('objective'))
            reference(baseline.get('artifact_id'),'baseline','E',batch_id=batch_id,
                      weights=search.get('weights'),objective=baseline.get('objective'))
            search_references(search,batch_id=batch_id)
            for index, trial in enumerate(batch.get('trials',[]),1):
                context=dict(batch_id=batch_id,candidate_index=index,expression=trial.get('expression'))
                reference(trial.get('candidate_artifact'),'candidate','E',weights=trial.get('weights'),
                          objective=trial.get('candidate_objective'),**context)
                search_references(trial.get('search',{}),**context)
            chosen=batch.get('decision',{}).get('chosen',{})
            reference(chosen.get('artifact_id'),'adopted','E',batch_id=batch_id,weights=chosen.get('weights'))

        labels={'final_test':'冻结组合 · 最终测试', 'selected':'验证期已选中组合',
                'validation':'验证期候选组合','adopted':'当轮采用组合',
                'candidate':'候选组合','baseline':'重配权对照组合','incumbent':'当轮原组合',
                'search':'训练期权重搜索'}
        periods={'F':'训练期 F','E':'反馈期 E','V':'验证期 V','T':'最终测试 T'}
        fallback_counts={'F':0,'E':0,'V':0,'T':0}
        for entry in entries.values():
            refs=sorted(entry['references'],key=lambda r:priorities.index(r['role']))
            entry['references']=refs
            entry['roles']=[r for r in priorities if any(ref['role']==r for ref in refs)]
            for field in ['batch_id','factor_count','objective']:
                value=next((ref[field] for ref in refs if field in ref),None)
                if value is not None:
                    entry[field]=value
            if refs:
                primary=refs[0]
                prefix=f"第 {primary['batch_id']} 轮 · " if 'batch_id' in primary else ''
                candidate=f"候选 {primary['candidate_index']} · " if 'candidate_index' in primary else ''
                step=f" · 第 {primary['search_step']} 步" if 'search_step' in primary else ''
                entry['label']=f"{prefix}{candidate}{labels[primary['role']]}{step}（{periods[entry['segment']]}）"
            else:
                segment=entry['segment']
                fallback_counts[segment]+=1
                kind='训练期 · 中间权重方案' if segment=='F' else f'{periods[segment]} · 已运行组合'
                entry['label']=f'{kind} {fallback_counts[segment]}'
        return sorted(entries.values(),key=lambda e:(priorities.index(e['roles'][0]) if e['roles'] else len(priorities),
                                                    e.get('batch_id',0),e['label']))

    def backtest(self, experiment_id, artifact_id):
        entry=next((r for r in self.backtests(experiment_id) if r['artifact_id']==safe_id(artifact_id)),None)
        if entry is None:
            raise PermissionError('该回测尚未运行或当前无权访问')
        directory={'F':'backtests','E':'backtests','V':'selection_backtests','T':'test_backtests'}[entry['segment']]
        obj=read_json(self._run_path(experiment_id)/directory/f'{artifact_id}.json')
        if obj['identity']!=artifact_id or digest(obj['result'])!=obj['result_digest']:
            raise ValueError('回测产物完整性校验失败')
        return obj
