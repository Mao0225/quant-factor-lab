"""Isolated UI acceptance catalog using real, immutable production data/model.

No candidate is automatically made available; the browser exercises that action.
Production metadata, plans and results remain untouched.
"""
from pathlib import Path
import argparse
import uvicorn
from ..app.data_service import DataService
from ..app.models import ModelService
from ..app.web import create_app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('closed_loop_research/workspace/v1_ui_acceptance'))
    parser.add_argument('--data-root',type=Path,default=Path('closed_loop_research/workspace/system_v1'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--dataset',required=True)
    parser.add_argument('--port',type=int,default=8768)
    args=parser.parse_args()
    data=DataService(args.data_root)
    models=ModelService(args.root,data)
    model=models.register_run(args.run,args.dataset,'流程验收 · 固定因子基准')
    models.update_metadata(model['version_id'],dict(description='隔离验收目录中的真实冻结模型，用于测试操作流程。原型数据，不代表投资建议或方法有效性。',researcher='本地流程验收',tags=['流程验收','原型']))
    uvicorn.run(create_app(args.root,data,models),host='127.0.0.1',port=args.port,log_level='warning')


if __name__=='__main__': main()
