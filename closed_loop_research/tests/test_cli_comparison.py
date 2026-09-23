from .helpers import protocol, snapshot
from closed_loop_research.cli import main
from closed_loop_research.comparison import run_suite
from closed_loop_research.storage import atomic_json, read_json
import pytest


def test_cli_runs_existing_snapshot_resumes_and_reports(tmp_path, capsys):
    p, path = snapshot(tmp_path)
    atomic_json(tmp_path / "protocol.json", p.to_dict())
    run = tmp_path / "run"
    assert main(["train", "--data", str(tmp_path), "--run", str(run), "--batches-this-call", "1"]) == 0
    assert main(["resume", "--run", str(run)]) == 0
    assert main(["report", "--run", str(run)]) == 0
    assert (run / "report.html").exists()
    assert read_json(run / "status.json")["ppo_updates"] == p.batches


def test_suite_locks_groups_and_seeds_and_reports_all(tmp_path):
    p = protocol(batches=1, selection_batches=[1], episodes_per_batch=2, search_budget=3)
    p, path = snapshot(tmp_path, p)
    result = run_suite(p, path, tmp_path / "suite", seeds=[3, 9], groups=["A", "B", "C", "D", "E"])
    assert len(result["runs"]) == 10
    assert set(result["summary"]) == set("ABCDE")
    assert all(v["seeds"] == 2 for v in result["summary"].values())
    assert all(r["test_locked"] for r in result["runs"])
    assert result["summary"]["A"]["actual_backtests_mean"] > 0
    assert read_json(tmp_path / "suite" / "suite_manifest.json")["seeds"] == [3, 9]


def test_process_suite_matches_serial_and_labels_seen_history(tmp_path):
    from closed_loop_research.suite_report import build_suite_report
    p = protocol(batches=1, selection_batches=[1], episodes_per_batch=2, search_budget=3,
                 holdout_status='previously_observed_historical', compress_artifacts=True)
    p, path = snapshot(tmp_path, p)
    serial = run_suite(p, path, tmp_path/'serial', [7], ['B','E'], True)
    parallel = run_suite(p, path, tmp_path/'parallel', [7], ['B','E'], True, workers=2)
    for a,b in zip(serial['runs'], parallel['runs']):
        assert a['frozen_model_id'] == b['frozen_model_id']
        assert a['test_metrics'] == b['test_metrics']
    assert parallel['holdout_status'] == 'previously_observed_historical'
    assert read_json(tmp_path/'parallel/E-seed-7/frozen_model.json')['holdout_status'] == parallel['holdout_status']
    html = build_suite_report(tmp_path/'parallel').read_text(encoding='utf-8')
    assert '数据此前已查看' in html and 'E-seed-7' in html and '2020' in html
    evidence = read_json(tmp_path/'parallel/report_evidence.json')
    assert all({r['segment'] for r in e['years']} == set('FEVT') for e in evidence)


def test_suite_reentry_keeps_existing_test_without_unlocking_new_test(tmp_path):
    from closed_loop_research.suite_report import build_suite_report
    p, path = snapshot(tmp_path, protocol(batches=1, selection_batches=[1], search_budget=2))
    root = tmp_path/'suite'
    locked = run_suite(p,path,root,[7],['A'])
    assert locked['runs'][0]['test_locked']
    still_locked = run_suite(p,path,root,[7],['A'])
    assert still_locked['runs'][0]['test_locked']
    tested = run_suite(p,path,root,[7],['A'],final_test=True)
    again = run_suite(p,path,root,[7],['A'])
    assert again['runs'][0]['test_metrics'] == tested['runs'][0]['test_metrics']
    assert again['summary'] == tested['summary']
    assert build_suite_report(root).exists()


def test_annual_report_compounds_returns_and_preserves_cross_year_loss():
    from closed_loop_research.suite_report import annual_rows
    result = dict(daily=[dict(date=d,net_return=r,fee=2.,slippage=1.) for d,r in
                        [('2022-12-29',.1),('2022-12-30',.1),('2023-01-02',-.1),('2023-01-03',.2)]])
    years = annual_rows(result,'F')
    assert years[0]['net_return'] == pytest.approx(.21)
    assert years[1]['net_return'] == pytest.approx(.08)
    assert years[1]['drawdown'] == pytest.approx(-.1)
    assert years[1]['sessions']==2 and years[1]['fees']==4.
