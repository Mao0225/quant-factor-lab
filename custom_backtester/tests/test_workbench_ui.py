import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from streamlit.testing.v1 import AppTest


class WorkbenchUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        master = self.root / 'data_cache/master'
        (master / 'stocks').mkdir(parents=True)
        (master / 'meta.json').write_text(json.dumps({
            'n_stocks': 2, 'rows': 60, 'date_min': '2021-01-01', 'date_max': '2026-12-31',
            'field_catalog': [{'name': 'close', 'dtype': 'float64'}, {'name': 'master_only', 'dtype': 'float64'}],
        }), encoding='utf-8')
        pool = self.root / 'data_cache/pools/pool_a'
        pool.mkdir(parents=True)
        (pool / 'manifest.json').write_text(json.dumps({'pool_id': 'pool_a', 'name': '示例股票池', 'n_stocks': 2}), encoding='utf-8')
        (pool / 'codes.txt').write_text('000001\n000002\n', encoding='utf-8')
        batch = self.root / 'factor_runs/batch_a'
        batch.mkdir(parents=True)
        (batch / 'factor_run.json').write_text(json.dumps({'run_id': 'batch_a', 'pool_id': 'pool_a', 'accepted_count': 1}), encoding='utf-8')
        (batch / 'accepted_factors.jsonl').write_text(json.dumps({'factor_id': 'f1', 'canonical_expression': 'rank(close)', 'ic': 0.02}) + '\n', encoding='utf-8')
        self.app = AppTest.from_string(
            'from pathlib import Path\nfrom app import streamlit_app as helpers\n'
            'from app.workbench import main\nmain(helpers, project_root=Path(' + repr(str(self.root)) + '))',
            default_timeout=30,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def assertHealthy(self):
        self.assertEqual(list(self.app.exception), [])

    def navigate(self, module):
        self.app.radio(key='workbench-nav').set_value(module).run()
        self.assertHealthy()

    def test_navigation_keeps_manual_draft_and_scopes_backtest_parameters(self):
        self.app.run()
        self.assertHealthy()
        self.app.text_area(key='widget:manual:expr').set_value('rank(master_only)').run()
        self.app.number_input(key='widget:manual:top_k').set_value(17).run()
        self.navigate('PPO 因子研究')
        self.navigate('因子组合')
        self.navigate('数据管理')
        self.navigate('结果中心')
        self.navigate('任务中心')
        self.navigate('系统设置')
        self.navigate('表达式回测')
        self.assertEqual(self.app.text_area(key='widget:manual:expr').value, 'rank(master_only)')
        self.assertEqual(self.app.number_input(key='widget:manual:top_k').value, 17)

    def _selection_composite(self):
        import pandas as pd
        from custom_bt.factor_composition import FACTOR_PREPROCESS
        run = self.root / 'outputs/saved_backtests/composite/pool_a/experiment/size_002'
        run.mkdir(parents=True)
        manifest = {'run_name': '双因子组合', 'result_type': 'composite', 'pool_id': 'pool_a',
                    'composition_id': 'experiment', 'created_at': '2025-01-01T12:00:00',
                    'factor_preprocess': FACTOR_PREPROCESS, 'max_factors': 2,
                    'config': {'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}}}
        (run / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (run / 'factor_weights.json').write_text(json.dumps([
            {'factor_id': 'f1', 'expression': 'close', 'weight': .7, 'preprocess': FACTOR_PREPROCESS},
            {'factor_id': 'f2', 'expression': 'rank(close)', 'weight': .3, 'preprocess': FACTOR_PREPROCESS},
        ]), encoding='utf-8')
        (run / 'summary.json').write_text('{"sharpe":1.2}', encoding='utf-8')
        pd.DataFrame({'date': ['2024-01-01', '2024-01-02'], 'account': [100., 101.],
                      'drawdown': [0., 0.]}).to_csv(run / 'daily_report.csv', index=False)
        return run

    def test_stock_selection_empty_state_has_composition_action(self):
        self.app.run()
        self.navigate('股票筛选')
        self.assertTrue(any('组合' in item.value for item in self.app.info))
        self.app.button(key='selection-to-composition').click().run()
        self.assertEqual(self.app.radio(key='workbench-nav').value, '因子组合')

    def test_composition_to_selection_submits_frozen_strategy(self):
        from app import streamlit_app as helpers
        run = self._selection_composite()
        self.app.run()
        self.navigate('因子组合')
        self.app.button(key='select-stocks:composition-history').click().run()
        self.assertHealthy()
        self.assertEqual(self.app.radio(key='workbench-nav').value, '股票筛选')
        self.assertEqual(self.app.selectbox(key='widget:selection:strategy').value, str(run.resolve()))
        self.app.number_input(key='widget:selection:top_n').set_value(7).run()
        with patch.object(helpers, '_start_platform_background_job'):
            self.app.button(key='selection-submit').click().run()
        self.assertHealthy()
        config = json.loads(next((self.root / 'outputs/jobs').glob('*/platform_job.json')).read_text(encoding='utf-8'))
        self.assertEqual(config['operation'], 'select_stocks')
        self.assertEqual(config['payload']['top_n'], 7)
        self.assertEqual(config['payload']['strategy']['codes'], ['000001', '000002'])
        self.assertEqual(len(config['payload']['strategy']['components']), 2)
        self.assertTrue(self.app.button(key='selection-submit').disabled)

    def test_stock_selection_rejects_future_and_invalid_dates(self):
        self._selection_composite()
        self.app.run()
        self.navigate('股票筛选')
        self.app.text_input(key='widget:selection:date').set_value('2099-01-01').run()
        self.app.button(key='selection-submit').click().run()
        self.assertHealthy()
        self.assertTrue(list(self.app.error))
        self.assertFalse((self.root / 'outputs/jobs').exists())
        self.app.text_input(key='widget:selection:date').set_value('wrong').run()
        self.app.button(key='selection-submit').click().run()
        self.assertHealthy()
        self.assertTrue(list(self.app.error))

    def test_selection_history_and_task_link_open_exact_record(self):
        import pandas as pd
        out = self.root / 'outputs/stock_selections/example'
        out.mkdir(parents=True)
        metadata = {'schema_version': 1, 'selection_id': 'example', 'created_at': '2026-09-20T10:00:00',
                    'strategy_name': '已保存策略', 'as_of_date': '2026-06-16', 'requested_date': '2026-06-16',
                    'selected_count': 1, 'eligible_count': 1, 'total_count': 2, 'retrospective': True}
        (out / 'selection.json').write_text(json.dumps(metadata), encoding='utf-8')
        (out / 'strategy.json').write_text('{"name":"snapshot"}', encoding='utf-8')
        candidate = {'code': ['000001'], 'score': [1.5], 'rank': [1], 'coverage': [1.0], 'close': [12.0]}
        pd.DataFrame(candidate).to_csv(out / 'candidates.csv', index=False)
        pd.DataFrame(candidate).to_csv(out / 'rankings.csv', index=False)
        pd.DataFrame({'code': ['000001'], 'factor_id': ['f1'], 'raw_value': [12.0],
                      'standardized_value': [1.5], 'weight': [1.0], 'contribution': [1.5]}).to_csv(out / 'contributions.csv', index=False)
        job = self.root / 'outputs/jobs/selection_job'
        job.mkdir(parents=True)
        (job / 'platform_job.json').write_text(json.dumps({'operation': 'select_stocks', 'payload': {}}), encoding='utf-8')
        (job / 'status.json').write_text(json.dumps({'status': 'finished', 'result': {'output_dir': str(out)}}), encoding='utf-8')
        self.app.run()
        self.navigate('任务中心')
        self.app.button(key='task-output:task-center').click().run()
        self.assertHealthy()
        self.assertEqual(self.app.radio(key='workbench-nav').value, '股票筛选')
        self.assertEqual(self.app.selectbox(key='widget:selection-history:record').value, str(out.resolve()))
        self.assertTrue(any('历史评分预览' in item.value for item in self.app.warning))
        self.assertEqual(self.app.selectbox(key='widget:selection-detail:example:code').value, '000001')

    def test_selection_job_scores_and_opens_persisted_candidates(self):
        import pandas as pd
        from app import streamlit_app as helpers
        from custom_bt.platform_jobs import run_platform_job
        self._selection_composite()
        master = self.root / 'data_cache/master'
        for code, price in [('000001', 10.), ('000002', 20.)]:
            pd.DataFrame({'date': pd.to_datetime(['2026-06-15', '2026-06-16']), 'code': [code] * 2,
                          'close': [price, price + 1], 'Ifsuspend': [0, 0]}).to_parquet(master / 'stocks' / (code + '.parquet'))
        self.app.run()
        self.navigate('股票筛选')
        self.app.text_input(key='widget:selection:date').set_value('2026-06-16').run()
        with patch.object(helpers, '_start_platform_background_job'):
            self.app.button(key='selection-submit').click().run()
        job = next((self.root / 'outputs/jobs').iterdir())
        result = run_platform_job(job)
        self.assertEqual(result['selected_count'], 2)
        self.app.run()
        self.app.button(key='task-output:selection').click().run()
        self.assertHealthy()
        self.assertEqual(self.app.selectbox(key='widget:selection-history:record').value, result['output_dir'])
        choices = self.app.selectbox(key='widget:selection-detail:' + Path(result['output_dir']).name + ':code')
        self.assertEqual(choices.value, '000002')

    def test_ppo_backtest_is_bound_to_selected_batch(self):
        self.app.run()
        self.navigate('PPO 因子研究')
        self.app.radio(key='widget:ppo:section').set_value('批量回测').run()
        self.assertHealthy()
        self.assertTrue(any('batch_a' in item.value for item in self.app.caption))
        self.assertTrue(any('示例股票池' in item.value for item in self.app.caption))
        self.assertTrue(any(button.label == '启动合格因子批量回测' for button in self.app.button))
        self.assertEqual(self.app.number_input(key='widget:ppo-bt:batch_a:top_k').value, 50)

    def test_missing_data_gives_actionable_state(self):
        (self.root / 'data_cache/master/meta.json').unlink()
        self.app.run()
        self.assertHealthy()
        self.assertTrue(any('数据管理' in item.value for item in self.app.warning))

    def test_validation_does_not_submit_invalid_expression(self):
        self.app.run()
        self.app.text_area(key='widget:manual:expr').set_value('unknown_field + 1').run()
        self.app.button(key='manual-submit').click().run()
        self.assertHealthy()
        self.assertTrue(any('unknown_field' in item.value for item in self.app.error))
        self.assertFalse((self.root / 'outputs/jobs').exists())

    def test_submission_writes_selected_configuration_and_keeps_task_local(self):
        import yaml
        from app import streamlit_app as helpers
        self.app.run()
        self.app.text_area(key='widget:manual:expr').set_value('rank(close)').run()
        self.app.number_input(key='widget:manual:top_k').set_value(7).run()
        with patch.object(helpers, '_start_background_job'):
            self.app.button(key='manual-submit').click().run()
        self.assertHealthy()
        files = list((self.root / 'outputs/jobs').glob('*/config.yaml'))
        self.assertEqual(len(files), 1)
        config = yaml.safe_load(files[0].read_text(encoding='utf-8'))
        self.assertEqual(config['backtest']['top_k'], 7)
        self.assertEqual(config['alphas'][0]['expr'], 'rank(close)')
        self.assertEqual(Path(config['data']), self.root / 'data_cache/master')
        self.assertTrue(self.app.button(key='manual-submit').disabled)
        self.navigate('PPO 因子研究')
        self.app.radio(key='widget:ppo:section').set_value('批量回测').run()
        self.assertEqual(self.app.number_input(key='widget:ppo-bt:batch_a:top_k').value, 50)
        self.assertFalse(any('表达式回测 · 排队中' in item.value for item in self.app.markdown))

    def test_ppo_submission_uses_current_batch_and_preserves_history(self):
        from app import streamlit_app as helpers
        self.app.run()
        self.navigate('PPO 因子研究')
        self.app.radio(key='widget:ppo:section').set_value('批量回测').run()
        with patch.object(helpers, '_start_platform_background_job'):
            self.app.button(key='ppo-backtest-submit').click().run()
        self.assertHealthy()
        files = list((self.root / 'outputs/jobs').glob('*/platform_job.json'))
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding='utf-8'))['payload']
        self.assertEqual(Path(payload['factor_run_dir']).name, 'batch_a')
        self.assertEqual(payload['expected_pool_id'], 'pool_a')
        self.assertTrue(payload['experiment_id'])

    def test_all_research_and_data_forms_render(self):
        self.app.run()
        self.navigate('PPO 因子研究')
        self.app.radio(key='widget:ppo:view').set_value('新建生成').run()
        self.assertHealthy()
        self.navigate('因子组合')
        self.app.radio(key='widget:composition:view').set_value('新建组合').run()
        self.assertHealthy()
        self.navigate('数据管理')
        for section in ['股票池', '字段与股票', '导入更新']:
            self.app.radio(key='widget:data:section').set_value(section).run()
            self.assertHealthy()

    def test_failed_batch_displays_failures_instead_of_success_link(self):
        job = self.root / 'outputs/jobs/failed_batch'
        job.mkdir(parents=True)
        out = self.root / 'outputs/failed_batch'
        out.mkdir(parents=True)
        (out / 'factor_backtest_failures.csv').write_text('factor_id,error\nf1,unknown field\n', encoding='utf-8')
        (job / 'platform_job.json').write_text(json.dumps({'operation': 'backtest_factors', 'payload': {
            'factor_run_dir': str(self.root / 'factor_runs/batch_a')}}), encoding='utf-8')
        (job / 'status.json').write_text(json.dumps({'status': 'finished', 'result': {
            'completed': 0, 'failed': 1, 'output_dir': str(out)}}), encoding='utf-8')
        self.app.run()
        self.navigate('PPO 因子研究')
        self.app.radio(key='widget:ppo:section').set_value('批量回测').run()
        self.assertHealthy()
        self.assertTrue(any('本次没有成功回测' in item.value for item in self.app.error))
        self.assertFalse(any(button.label == '查看本次结果' for button in self.app.button))

    def test_ppo_to_composition_carries_pool_and_batch(self):
        self.app.run()
        self.navigate('PPO 因子研究')
        self.app.button(key='ppo-to-composition').click().run()
        self.assertHealthy()
        self.assertEqual(self.app.radio(key='workbench-nav').value, '因子组合')
        self.assertEqual(self.app.selectbox(key='widget:composition:pool').value, 'pool_a')
        self.assertEqual(self.app.selectbox(key='widget:composition:batch').value, 'batch_a')

    def test_settings_save_preserves_existing_draft(self):
        self.app.run()
        self.app.number_input(key='widget:manual:top_k').set_value(17).run()
        self.navigate('系统设置')
        self.app.number_input(key='widget:settings-defaults:top_k').set_value(33).run()
        self.app.button(key='settings-save').click().run()
        self.assertHealthy()
        saved = json.loads((self.root / 'configs/workbench.local.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['backtest']['top_k'], 33)
        self.navigate('表达式回测')
        self.assertEqual(self.app.number_input(key='widget:manual:top_k').value, 17)

    def test_history_rerun_restores_snapshot_without_modifying_original(self):
        import pandas as pd
        run = self.root / 'outputs/saved_backtests/manual/example'
        run.mkdir(parents=True)
        manifest = {'run_name': 'example', 'result_type': 'manual', 'canonical_expression': 'rank(close)', 'pool_id': 'pool_a',
                    'config': {'alphas': [{'expr': 'rank(close)'}], 'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31', 'top_k': 9,
                     'price': 'close', 'rebalance_freq': '5D', 'exclude_limit_up_buy': False}}}
        original = json.dumps(manifest)
        (run / 'manifest.json').write_text(original, encoding='utf-8')
        (run / 'summary.json').write_text('{"sharpe":1.2}', encoding='utf-8')
        pd.DataFrame({'date': ['2024-01-01', '2024-01-02'], 'account': [100., 101.], 'drawdown': [0., 0.]}).to_csv(run / 'daily_report.csv', index=False)
        self.app.run()
        self.app.radio(key='widget:manual:section').set_value('历史记录').run()
        self.assertHealthy()
        self.app.button(key='rerun:manual-history').click().run()
        self.assertHealthy()
        self.assertEqual(self.app.text_area(key='widget:manual:expr').value, 'rank(close)')
        self.assertEqual(self.app.number_input(key='widget:manual:top_k').value, 9)
        self.assertEqual(self.app.selectbox(key='widget:manual:pool').value, 'pool_a')
        self.assertNotEqual(self.app.text_input(key='widget:manual:name').value, 'example')
        self.assertEqual((run / 'manifest.json').read_text(encoding='utf-8'), original)
        from app import streamlit_app as helpers
        import yaml
        with patch.object(helpers, '_start_background_job'):
            self.app.button(key='manual-submit').click().run()
        self.assertHealthy()
        saved = yaml.safe_load(next((self.root / 'outputs/jobs').glob('*/config.yaml')).read_text(encoding='utf-8'))
        self.assertEqual(saved['backtest']['price'], 'close')
        self.assertEqual(saved['backtest']['rebalance_freq'], '5D')
        self.assertFalse(saved['backtest']['exclude_limit_up_buy'])


if __name__ == '__main__':
    unittest.main()
