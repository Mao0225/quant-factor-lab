"""python -m closed_loop_research.app --port 8767"""
import argparse
import uvicorn
from .web import create_app, DEFAULT_ROOT
from ..storage import writer_lock


def main():
    parser=argparse.ArgumentParser(description='独立研究与选股系统')
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--root',default=str(DEFAULT_ROOT))
    args=parser.parse_args()
    # A second server must not reset live job records or run concurrent training.
    with writer_lock(str(args.root)+'/server'):
        uvicorn.run(create_app(args.root),host='127.0.0.1',port=args.port,log_level='info')


if __name__=='__main__':
    main()
