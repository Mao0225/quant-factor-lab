"""Selected-page dispatch for the local factor research workbench."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st
import yaml

from app.workbench_components import MODULES, OPERATIONS, ORIGINS, all_jobs, backtest_form, control, go, result_history, task_feedback
from app.workbench_state import read_json, resolve_store

PATHS = {'legacy': ('兼容数据缓存', 'data_cache/stock_daily'), 'master': ('主数据缓存', 'data_cache/master'),
         'pools_dir': ('股票池目录', 'data_cache/pools'), 'factors': ('因子运行目录', 'factor_runs'),
         'outputs': ('统一结果目录', 'outputs/saved_backtests'), 'jobs': ('新任务目录', 'outputs/jobs')}
DEFAULTS = {'start_date': '2021-06-18', 'end_date': '2026-06-16', 'top_k': 50, 'initial_cash': 100000000.0,
            'buy_cost': 0.0015, 'sell_cost': 0.0015, 'slippage': 0.0005, 'min_cost': 5.0, 'max_weight_per_stock': 0.02}


def main(helpers, project_root=None):
    st.set_page_config(page_title='因子研究工作台', layout='wide', initial_sidebar_state='expanded')
    root = Path(project_root or helpers.PROJECT_ROOT)
    workspace_key = str(root.resolve())
    if st.session_state.get('workspace-root') != workspace_key:
        # Avoid reusing settings when a test / user intentionally opens another workspace.
        st.session_state['workspace-root'] = workspace_key
        st.session_state['settings'] = read_json(root / 'configs/workbench.local.json')
    settings = st.session_state['settings']
    paths = {}
    for key, (_, default) in PATHS.items():
        path = Path(settings.get('paths', {}).get(key, default)).expanduser()
        paths[key] = path if path.is_absolute() else root / path
    ctx = SimpleNamespace(root=root, h=helpers, **paths)
    # The generation backends normalize result roots to a saved_backtests folder.
    # Apply the same rule to manual results and the result browser.
    if ctx.outputs.name != 'saved_backtests':
        ctx.outputs = ctx.outputs / 'saved_backtests'
    ctx.defaults = dict(DEFAULTS)
    ctx.defaults.update(helpers._load_yaml_defaults(root / 'configs/default.yaml').get('backtest', {}))
    ctx.defaults.update(settings.get('backtest', {}))
    ctx.store = resolve_store(ctx.master, ctx.legacy)
    ctx.meta = read_json(ctx.store / 'meta.json')
    ctx.master_ready = helpers._master_store_ready(ctx.master)
    ctx.pools = helpers._load_pool_manifests(ctx.pools_dir)
    ctx.batches = helpers._load_factor_run_manifests(ctx.factors)
    ctx.platform = helpers._load_yaml_defaults(root / 'configs/platform.yaml')
    ctx.generation = helpers._load_yaml_defaults(root / 'configs/factor_generation.yaml')
    next_page = st.session_state.pop('navigate-to', None)
    if st.session_state.get('workbench-nav') == '手动回测':
        st.session_state['workbench-nav'] = '表达式回测'
    if next_page == '手动回测':
        next_page = '表达式回测'
    if next_page in MODULES:
        st.session_state['workbench-nav'] = next_page
    with st.sidebar:
        st.markdown('## 因子研究工作台')
        st.caption('构建 · 验证 · 组合 · 选股')
        page = st.radio('工作区', MODULES, key='workbench-nav', label_visibility='collapsed')
        st.divider()
        jobs = all_jobs(ctx)
        active = sum(item.get('status') in {'queued', 'running'} for item in jobs)
        st.caption('运行中任务：{}'.format(active))
        st.caption('主缓存已就绪' if ctx.master_ready else '主缓存未就绪')
    st.title(page)
    notice = st.session_state.pop('notice', None)
    if notice:
        st.success(notice)
    if page == '表达式回测':
        from app.workbench_manual import render
        render(ctx)
    elif page in {'PPO 因子研究', '因子组合'}:
        from app.workbench_research import render_ppo, render_composition
        (render_ppo if page == 'PPO 因子研究' else render_composition)(ctx)
    elif page == '股票筛选':
        from app.workbench_selection import render
        render(ctx)
    elif page == '数据管理':
        from app.workbench_data import render
        render(ctx)
    elif page == '结果中心':
        st.caption('统一查找表达式、生成因子与组合的回测结果。选股名单在「股票筛选 → 选股记录」查看。')
        source = control('selectbox', '结果来源', 'results', 'source', '全部', options=['全部'] + list(ORIGINS.values()))
        result_type = next((key for key, value in ORIGINS.items() if value == source), None)
        result_history(ctx, 'results', result_type=result_type)
    elif page == '任务中心':
        render_tasks(ctx)
    elif page == '系统设置':
        render_settings(ctx)


def render_tasks(ctx):
    st.caption('统一查看网页和 AI 研究产生的任务；不会移动已有任务文件。')
    status = control('selectbox', '状态筛选', 'tasks', 'status', '全部', options=['全部', '运行中', '已完成', '失败'])
    statuses = {'运行中': {'running', 'queued'}, '已完成': {'finished'}, '失败': {'failed'}}
    jobs = [item for item in all_jobs(ctx) if status == '全部' or item.get('status') in statuses[status]]
    if st.button('刷新任务列表', key='tasks-refresh'):
        st.rerun()
    if not jobs:
        st.info('当前筛选下没有任务。可以从表达式回测、PPO 因子研究或数据管理创建任务。')
        return
    st.dataframe(pd.DataFrame([{'任务': item.get('label', Path(item['path']).name),
                              '类型': OPERATIONS.get(item.get('operation'), item.get('operation', '未知')),
                              '状态': ctx.h.STATUS_LABELS.get(item.get('status'), '状态缺失'),
                              '更新时间': item.get('updated_at', '')} for item in jobs]), use_container_width=True, hide_index=True)
    by_path = {item['path']: item for item in jobs}
    selected = control('selectbox', '选择任务', 'tasks', 'selected', options=list(by_path),
                       format_func=lambda path: '{} · {}'.format(OPERATIONS.get(by_path[path].get('operation'), '任务'), Path(path).name))
    job = by_path[selected]
    st.session_state['task:task-center'] = selected
    task_feedback(ctx, 'task-center')
    destination = {'manual': '表达式回测', 'generate_factors': 'PPO 因子研究', 'backtest_factors': 'PPO 因子研究',
                   'compose_factors': '因子组合', 'select_stocks': '股票筛选', 'prepare_master': '数据管理', 'create_pool': '数据管理'}.get(job.get('operation'))
    if destination and st.button('返回' + destination, key='task-origin'):
        from app.workbench_components import open_task_output
        open_task_output(ctx, job)


def render_settings(ctx):
    st.caption('这里的默认值只用于新建配置，不修改已保存结果或当前研究草稿。')
    values = {}
    with st.expander('存储位置', expanded=True):
        for key, (label, default) in PATHS.items():
            values[key] = control('text_input', label, 'settings', key,
                                  st.session_state['settings'].get('paths', {}).get(key, default))
    st.subheader('新建回测的默认参数')
    config = backtest_form(ctx, 'settings-defaults')
    if st.button('保存设置', type='primary', key='settings-save'):
        from app.workbench_state import validate_backtest
        errors = validate_backtest(config)
        if any(not value.strip() for value in values.values()):
            errors.append('存储路径不能为空。')
        if errors:
            for error in errors:
                st.error(error)
            return
        settings = {'paths': values, 'backtest': config}
        path = ctx.root / 'configs/workbench.local.json'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            import json
            path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError as exc:
            st.error('设置保存失败：{}'.format(exc))
            return
        st.session_state['settings'] = settings
        st.session_state['notice'] = '设置已保存；现有研究草稿保持原值。'
        st.rerun()
