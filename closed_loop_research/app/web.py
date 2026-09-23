"""Loopback-only HTTP application. No arbitrary paths or file serving APIs."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
import csv
import io
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..storage import atomic_json, read_json
from ..data import DataIntegrityError
from .jobs import JobQueue, safe_id
from .research import ResearchService


DEFAULT_ROOT = Path(__file__).resolve().parents[1]/'workspace'/'system_v1'


def create_app(root=DEFAULT_ROOT, data_service=None, model_service=None):
    root=Path(root)
    if data_service is None:
        from .data_service import DataService
        data_service=DataService(root)
    if model_service is None:
        from .models import ModelService
        model_service=ModelService(root,data_service)
    jobs=JobQueue(root)
    research=ResearchService(root,data_service,model_service,jobs)

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()

    app=FastAPI(title='因子研究与选股',docs_url=None,redoc_url=None,lifespan=lifespan)
    app.state.data,app.state.models,app.state.jobs,app.state.research=data_service,model_service,jobs,research

    @app.middleware('http')
    async def local_only(request:Request,call_next):
        hostname=request.url.hostname
        if hostname not in {'127.0.0.1','localhost','::1','testserver'}:
            return JSONResponse({'detail':'仅允许本机访问'},status_code=403)
        origin=request.headers.get('origin')
        if request.method not in {'GET','HEAD','OPTIONS'} and origin:
            parsed=urlparse(origin)
            if parsed.netloc!=request.url.netloc or parsed.scheme!=request.url.scheme:
                return JSONResponse({'detail':'拒绝跨来源写操作'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=400)

    @app.exception_handler(PermissionError)
    async def forbidden(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=409)

    @app.exception_handler(DataIntegrityError)
    async def integrity(request,exc):
        return JSONResponse({'detail':f'数据完整性校验失败：{exc}'},status_code=409)

    @app.exception_handler(FileNotFoundError)
    async def missing(request,exc):
        return JSONResponse({'detail':'请求的对象不存在'},status_code=404)

    @app.exception_handler(KeyError)
    async def incomplete(request,exc):
        return JSONResponse({'detail':f'缺少必要字段：{exc}'},status_code=400)

    @app.get('/api/overview')
    def overview():
        datasets=data_service.list_datasets()
        models=model_service.list_models()
        experiments=research.list_experiments()
        active=[j for j in jobs.list() if j['status'] in {'running','queued','pause_requested','stop_requested'}]
        return dict(datasets=datasets,models=models,experiments=experiments,jobs=active,
                    counts=dict(datasets=len(datasets),models=len(models),experiments=len(experiments),jobs=len(active)))

    @app.get('/api/datasets')
    def datasets(): return data_service.list_datasets()

    @app.post('/api/datasets/import')
    def import_data():
        from .data_service import import_raw_500
        workspace=Path(__file__).resolve().parents[2]
        source=workspace.parent/'数据'/'daily_with_maindata_v2.csv'
        codes=workspace/'single_factor'/'data'/'selected_500_liquid_processed'/'panel.parquet'
        if not source.exists() or not codes.exists():
            raise ValueError('已登记的原始文件或500股名单不存在，请按运行说明配置本机数据')
        active=next((j for j in jobs.list() if j['kind']=='data_import' and j['status'] in {'queued','running'}),None)
        if active: return active
        def work(jid):
            result=import_raw_500(source,codes,root,progress=lambda value:jobs.update(jid,progress=value))
            return dict(dataset_id=result['id'])
        return jobs.submit('data_import',work,name='导入已登记500股数据')

    @app.get('/api/datasets/{dataset_id}/protocol')
    def protocol(dataset_id:str): return data_service.protocol_template(safe_id(dataset_id))

    @app.get('/api/datasets/{dataset_id}')
    def dataset(dataset_id:str): return data_service.get_dataset(safe_id(dataset_id))

    @app.get('/api/projects')
    def projects(): return research.projects()

    @app.post('/api/projects')
    def create_project(body:dict): return research.create_project(body)

    @app.get('/api/experiments')
    def experiments(): return research.list_experiments()

    @app.post('/api/experiments')
    def create_experiment(body:dict): return research.create(body)

    @app.get('/api/experiments/{experiment_id}')
    def experiment(experiment_id:str): return research.detail(experiment_id)

    @app.get('/api/experiments/{experiment_id}/backtests')
    def backtests(experiment_id:str): return research.backtests(experiment_id)

    @app.get('/api/experiments/{experiment_id}/backtests/{artifact_id}')
    def backtest(experiment_id:str,artifact_id:str): return research.backtest(experiment_id,artifact_id)

    @app.post('/api/experiments/{experiment_id}/{action}')
    def experiment_action(experiment_id:str,action:str):
        if action in {'start','resume'}: return research.start(experiment_id,resume=action=='resume')
        if action in {'pause','stop'}: return research.control(experiment_id,action)
        if action=='test': return research.test(experiment_id)
        raise ValueError('未知实验操作')

    @app.get('/api/comparisons')
    def comparisons(): return research.comparisons()

    @app.post('/api/projects/{project_id}/comparison')
    def comparison(project_id:str,body:dict): return research.comparison(project_id,body)

    @app.get('/api/models')
    def models(): return [model_source(m) for m in model_service.list_models()]

    def model_source(model):
        source=next((e['id'] for e in research.list_experiments() if e.get('model_version')==model['version_id']),None)
        return dict(model,source_experiment_id=source)

    @app.get('/api/models/{version}')
    def model(version:str): return model_source(model_service.get_model(safe_id(version)))

    @app.patch('/api/models/{version}')
    def update_model(version:str,body:dict): return model_service.update_metadata(safe_id(version),body)

    @app.post('/api/models/{version}/status')
    def model_status(version:str,body:dict): return model_service.set_status(safe_id(version),body['status'])

    @app.post('/api/selections')
    def selection(body:dict):
        # Copy submitted input before enqueueing: later form edits cannot change this task.
        config=json.loads(json.dumps(body.get('config',body),allow_nan=False))
        def work(jid):
            result=model_service.select(config)
            return dict(result_id=result['id'])
        return jobs.submit('selection',work,config=config,name='条件选股')

    @app.get('/api/jobs')
    def tasks(): return jobs.list()

    @app.get('/api/jobs/{job_id}')
    def task(job_id:str): return jobs.get(job_id)

    @app.get('/api/plans')
    def plans(): return model_service.list_plans()

    @app.post('/api/plans')
    def save_plan(body:dict): return model_service.save_plan(body)

    @app.get('/api/plans/{plan_id}')
    def plan(plan_id:str): return model_service.get_plan(safe_id(plan_id))

    @app.get('/api/results')
    def results(): return model_service.list_results()

    @app.get('/api/results/{result_id}/csv')
    def export_result(result_id:str):
        result=model_service.get_result(safe_id(result_id))
        buffer=io.StringIO(newline='')
        fields=['rank','code','name','score','data_date','model_version','dataset_id','top_n','filters']
        writer=csv.DictWriter(buffer,fieldnames=fields)
        writer.writeheader()
        def safe_cell(value):
            return "'"+value if isinstance(value,str) and value.startswith(('=','+','-','@','\t','\r')) else value
        for row in result['rows']:
            record={k:row.get(k,'') for k in ['rank','code','name','score']}
            record.update(data_date=result['data_date'],model_version=result['model_version'],dataset_id=result['dataset_id'],
                          top_n=result['config']['top_n'],filters=json.dumps(result['config'].get('filters',{}),ensure_ascii=False))
            writer.writerow({k:safe_cell(v) for k,v in record.items()})
        return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="selection-{result_id}.csv"'})

    @app.get('/api/results/{result_id}')
    def result(result_id:str): return model_service.get_result(safe_id(result_id))

    @app.get('/api/settings')
    def settings():
        path=root/'settings.json'
        return read_json(path) if path.exists() else {'default_workspace':'research','page_size':50}

    @app.patch('/api/settings')
    def update_settings(body:dict):
        if set(body)-{'default_workspace','page_size'}:
            raise ValueError('未知设置项')
        value={**settings(),**body}
        if value['default_workspace'] not in {'research','selection'} or value['page_size'] not in {20,50,100}:
            raise ValueError('设置值无效')
        atomic_json(root/'settings.json',value)
        return value

    @app.get('/api/help')
    def help_page():
        return dict(title='研究与选股说明',items=[
            {'title':'F / E / V / T','text':'F 拟合组合；E 计算增量奖励；V 在预登记检查点选择；T 仅冻结后测试，不能反馈训练。'},
            {'title':'模型交接','text':'训练自动冻结候选。模型管理中人工设为可用后方能选股；停用不删除历史。'},
            {'title':'条件选股','text':'先对冻结范围的所有合格股票评分并标准化，再筛选和取前 N；条件变化的历史表现尚未评价。'},
            {'title':'数据限制','text':'财务未通过历史时点核验，隔离且禁用。当前500股为固定历史样本，复权/公司行动与样本选择偏差未解决，结果仅作原型诊断。'},
            {'title':'任务控制','text':'暂停/停止在完整批次检查点生效。中断恢复沿用原快照、协议和随机状态；服务重启后需显式恢复。'},
            {'title':'评分解释','text':'score 是多个标准化因子按冻结权重相加，不是上涨概率。缺失贡献按协议置零并标记。'},
        ])

    static=Path(__file__).parent/'static'
    if static.exists():
        app.mount('/',StaticFiles(directory=static,html=True),name='web')
    return app
