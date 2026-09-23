import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from closed_loop_research.app.web import create_app
from closed_loop_research.tests.helpers import protocol
from closed_loop_research.storage import atomic_json


class Data:
    def get_dataset(self, key):
        assert key=='prices'
        return dict(id=key,data_mode='legacy_prototype')
    def list_datasets(self): return [self.get_dataset('prices')]
    def protocol_template(self,key): return p().to_dict()
    def prepare_research_snapshot(self,key,config,path):
        atomic_json(Path(path)/'manifest.json',{'snapshot_id':'fixture'})


def p(**changes):
    return protocol(**dict(dict(synthetic=False,data_mode='legacy_prototype',holdout_status='previously_observed_historical'),**changes))


class Models:
    def __init__(self): self.results={}
    def list_models(self): return []
    def register_run(self,*args): return {'version_id':'frozen-one'}
    def select(self,config):
        if config.get('fail'): raise ValueError('unavailable field')
        obj=dict(id='result-one',data_date='2020-01-24',model_version='frozen-one',dataset_id='prices',config=config,
                 rows=[dict(rank=1,code='000001',name='=test',score=.25)])
        self.results[obj['id']]=obj
        return obj
    def get_result(self,key): return self.results[key]
    def list_results(self): return list(self.results.values())


def finish(client,jid):
    for _ in range(200):
        job=client.get(f'/api/jobs/{jid}').json()
        if job['status'] in {'succeeded','failed','paused','stopped'}: return job
        time.sleep(.01)
    raise AssertionError('timeout')


def test_http_selection_history_csv_and_origin(tmp_path):
    app=create_app(tmp_path,Data(),Models())
    with TestClient(app) as c:
        assert c.post('/api/projects',json={'name':'x'},headers={'Origin':'https://evil.example'}).status_code==403
        good=c.post('/api/selections',json={'config':{'model_version':'frozen-one','top_n':1,'filters':{}}}).json()
        assert finish(c,good['id'])['result_id']=='result-one'
        bad=c.post('/api/selections',json={'config':{'fail':True}}).json()
        assert finish(c,bad['id'])['status']=='failed'
        assert len(c.get('/api/results').json())==1
        csv=c.get('/api/results/result-one/csv')
        assert '000001' in csv.text and "'=test" in csv.text and '2020-01-24' in csv.text
        assert c.get('/api/jobs/bad.id').status_code==400


def test_research_rejects_finance_and_false_audit_claims(tmp_path):
    with TestClient(create_app(tmp_path,Data(),Models())) as c:
        for raw in [p(fields=['close','ROE']).to_dict(),p(data_mode='audited').to_dict()]:
            res=c.post('/api/experiments',json=dict(name='x',dataset_id='prices',protocol=raw))
            assert res.status_code==400
        ok=c.post('/api/experiments',json=dict(name='x',dataset_id='prices',protocol=p().to_dict())).json()
        assert ok['status']=='draft'
        assert c.post(f"/api/experiments/{ok['id']}/test").status_code==400
        assert c.get(f"/api/experiments/{ok['id']}/backtests").json()==[]
        assert c.get(f"/api/experiments/{ok['id']}/backtests/secret").status_code==409


@pytest.mark.parametrize('first_phase',['committed','finished'])
def test_checkpoint_pause_resume_does_not_repeat_committed_work(tmp_path,monkeypatch,first_phase):
    calls=[]
    import closed_loop_research.app.research as module
    def train(protocol,snapshot,run,**kwargs):
        calls.append(len(calls)+1)
        time.sleep(.08)
        return {'phase':first_phase if len(calls)==1 else 'finished'}
    monkeypatch.setattr(module,'run_experiment',train)
    monkeypatch.setattr(module,'select_model',lambda path:{'model_id':'frozen-one'})
    app=create_app(tmp_path,Data(),Models())
    with TestClient(app) as c:
        exp=c.post('/api/experiments',json=dict(name='pause test',dataset_id='prices',protocol=p().to_dict())).json()
        eid=exp['id']
        job=c.post(f'/api/experiments/{eid}/start').json()
        for _ in range(100):
            if calls: break
            time.sleep(.005)
        c.post(f'/api/experiments/{eid}/pause').raise_for_status()
        assert finish(c,job['id'])['status']=='paused'
        assert len(calls)==1
        second=c.post(f'/api/experiments/{eid}/resume').json()
        assert finish(c,second['id'])['status']=='succeeded'
        assert len(calls)==2
        assert c.get(f'/api/experiments/{eid}').json()['model_version']=='frozen-one'
