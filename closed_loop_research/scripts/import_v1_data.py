"""Run: python -m closed_loop_research.scripts.import_v1_data."""
import argparse
import json
import time
from pathlib import Path
from ..app.data_service import import_raw_500


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('F:/my_code_file/因子构建/数据/daily_with_maindata_v2.csv'))
    parser.add_argument('--codes-source', type=Path, default=Path('single_factor/data/selected_500_liquid_processed/panel.parquet'))
    parser.add_argument('--root', type=Path, default=Path('closed_loop_research/workspace/system_v1'))
    args = parser.parse_args()
    last = [0.]
    def progress(event):
        if time.monotonic() - last[0] > 15:
            print(json.dumps(event), flush=True)
            last[0] = time.monotonic()
    result = import_raw_500(args.source, args.codes_source, args.root, progress)
    print(json.dumps({k: result[k] for k in ['id', 'rows', 'start', 'end', 'latest_complete_date', 'quality']}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
