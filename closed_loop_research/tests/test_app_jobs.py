import time
import pytest
from closed_loop_research.app.jobs import JobQueue
from closed_loop_research.storage import atomic_json


def wait(queue, job_id):
    for _ in range(200):
        job = queue.get(job_id)
        if job['status'] in {'succeeded', 'failed', 'paused', 'stopped'}:
            return job
        time.sleep(.01)
    raise AssertionError('job failed to finish')


def test_jobs_persist_failure_without_overwriting_previous_success(tmp_path):
    q = JobQueue(tmp_path)
    a = q.submit('selection', lambda j: {'result_id': 'result-one'})
    assert wait(q, a['id'])['result_id'] == 'result-one'
    def fail(j):
        raise ValueError('missing required field')
    b = q.submit('selection', fail)
    assert wait(q, b['id'])['status'] == 'failed'
    assert q.get(a['id'])['result_id'] == 'result-one'
    q.close()


def test_restart_marks_unfinished_jobs_interrupted(tmp_path):
    atomic_json(tmp_path/'jobs'/'old.json', {'id':'old', 'status':'running','kind':'research'})
    q = JobQueue(tmp_path)
    assert q.get('old')['status'] == 'interrupted'
    with pytest.raises(ValueError):
        q.get('../old')
    q.close()
