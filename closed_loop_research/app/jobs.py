"""One local compute lane, durable tasks, checkpoint-aware control requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import re

from ..storage import atomic_json, read_json


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', value):
        raise ValueError('invalid object ID')
    return value


class JobQueue:
    def __init__(self, root):
        self.root = Path(root)/'jobs'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='research-compute')
        for path in self.root.glob('*.json'):
            job = read_json(path)
            if job['status'] in {'queued', 'running', 'pause_requested', 'stop_requested'}:
                job.update(status='interrupted', error='服务中断；研究可从已保存检查点恢复，选股可重新提交。', updated_at=now())
                atomic_json(path, job)

    def list(self):
        return sorted([read_json(p) for p in self.root.glob('*.json')], key=lambda x:x.get('created_at',''), reverse=True)

    def get(self, job_id):
        return read_json(self.root/f'{safe_id(job_id)}.json')

    def update(self, job_id, **changes):
        with self.lock:
            job = self.get(job_id)
            job.update(changes, updated_at=now())
            atomic_json(self.root/f'{job_id}.json', job)
            return job

    def request(self, job_id, action):
        if action not in {'pause','stop'}:
            raise ValueError('invalid task action')
        with self.lock:
            job = self.get(job_id)
            if job['kind'] != 'research' or job['status'] not in {'queued','running','pause_requested','stop_requested'}:
                raise ValueError('此任务目前不能暂停/停止')
            return self.update(job_id, request=action, status=f'{action}_requested')

    def submit(self, kind, function, **metadata):
        job = dict(id=uuid4().hex, kind=kind, status='queued', created_at=now(), updated_at=now(), request=None, **metadata)
        atomic_json(self.root/f"{job['id']}.json", job)
        self.executor.submit(self._run, job['id'], function)
        return job

    def _run(self, job_id, function):
        try:
            self.update(job_id, status='running')
            result = function(job_id) or {}
            status = result.pop('job_status', 'succeeded')
            self.update(job_id, status=status, **result)
        except Exception as exc:
            self.update(job_id, status='failed', error=f'{type(exc).__name__}: {exc}')

    def close(self):
        self.executor.shutdown(wait=True)
