"""Shared forms, persistent drafts, local task feedback and result navigation."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from app.workbench_state import choose_id, copy_manual_run, jobs_for, list_jobs, read_json, validate_backtest

MODULES = ['表达式回测', 'PPO 因子研究', '因子组合', '股票筛选', '数据管理', '结果中心', '任务中心', '系统设置']
OPERATIONS = {'manual': '表达式回测', 'generate_factors': 'PPO 生成', 'backtest_factors': '因子批量回测',
              'compose_factors': '因子组合', 'select_stocks': '股票筛选', 'prepare_master': '数据导入', 'create_pool': '创建股票池'}
ORIGINS = {'manual': '表达式回测', 'factor': 'PPO / 候选因子', 'composite': '因子组合'}


def _remember(key, widget_key):
    st.session_state[key] = st.session_state[widget_key]


def control(kind, label, scope, name, default=None, options=None, **kwargs):
    """Durable values survive Streamlit's cleanup of hidden widget keys."""
    key = 'draft:' + scope + ':' + name
    widget = 'widget:' + scope + ':' + name
    value = st.session_state.get(key, default)
    if kind == 'number_input' and value is not None:
        value = float(value) if isinstance(default, float) else int(value)
    if kind in {'text_input', 'text_area'} and value is not None:
        value = str(value)
    if options is not None:
        options = list(options)
        if not options:
            return None
        value = choose_id(options, value)
    if widget not in st.session_state or (options is not None and st.session_state[widget] not in options):
        st.session_state[widget] = value
    st.session_state.setdefault(key, value)
    fn = getattr(st, kind)
    args = {'key': widget, 'on_change': _remember, 'args': (key, widget)}
    args.update(kwargs)
    if options is not None:
        args['options'] = options
    result = fn(label, **args)
    st.session_state[key] = result
    return result


def put(scope, name, value):
    st.session_state['draft:' + scope + ':' + name] = value
    st.session_state.pop('widget:' + scope + ':' + name, None)


def go(module, **values):
    for key, value in values.items():
        st.session_state[key] = value
    st.session_state['navigate-to'] = module
    st.rerun()


def pool_names(ctx):
    return {str(row['pool_id']): '{} · {} 只'.format(row.get('name') or row['pool_id'], row.get('n_stocks', '—'))
            for row in ctx.pools.to_dict('records')}


def pool_select(ctx, scope, name='pool', default=None, allow_all=False):
    names = pool_names(ctx)
    if allow_all:
        names = {'': '全量数据（不限制股票池）', **names}
    return control('selectbox', '表达式回测股票池' if scope == 'manual' else '股票池', scope, name,
                   default, options=list(names), format_func=lambda value: names.get(value, value))


def source_caption(ctx, pool_id=None):
    name = pool_names(ctx).get(str(pool_id), str(pool_id or '全量数据'))
    st.caption('数据源：{}　｜　股票池：{}　｜　{} 至 {}'.format(
        '主缓存' if ctx.store == ctx.master else '兼容缓存', name,
        ctx.meta.get('date_min', '—'), ctx.meta.get('date_max', '—')))


def backtest_form(ctx, scope):
    defaults = ctx.defaults
    result = dict(defaults)
    result.update(st.session_state.get('backtest-snapshot:' + scope, {}))
    c1, c2, c3 = st.columns(3)
    with c1:
        result['start_date'] = control('text_input', '开始日期', scope, 'start_date', str(defaults['start_date']), help='YYYY-MM-DD')
    with c2:
        result['end_date'] = control('text_input', '结束日期', scope, 'end_date', str(defaults['end_date']), help='YYYY-MM-DD')
    with c3:
        result['top_k'] = control('number_input', '持仓数量 TopK', scope, 'top_k', int(defaults['top_k']), min_value=1)
    with st.expander('资金与交易成本（高级参数）'):
        left, right = st.columns(2)
        for idx, (key, label) in enumerate([
            ('initial_cash', '初始资金'), ('max_weight_per_stock', '单票最大权重'),
            ('buy_cost', '买入成本率'), ('sell_cost', '卖出成本率'), ('slippage', '滑点'), ('min_cost', '最低手续费'),
        ]):
            with left if idx % 2 == 0 else right:
                result[key] = control('number_input', label, scope, key, float(defaults[key]), min_value=0.0,
                                      format='%.5f' if key not in {'initial_cash', 'min_cost'} else '%.2f')
    return result


def check_config(config, ctx):
    errors = validate_backtest(config, ctx.meta)
    for error in errors:
        st.error(error)
    return not errors


def all_jobs(ctx):
    return list_jobs([ctx.jobs, ctx.root / 'jobs', ctx.root / 'outputs/jobs'])


def active_job(ctx, scope):
    path = st.session_state.get('task:' + scope)
    return bool(path and read_json(Path(path) / 'status.json').get('status') in {'queued', 'running'})


def submit(ctx, scope, operation, payload):
    if active_job(ctx, scope):
        st.warning('本次任务仍在运行，请等待完成后再提交。')
        return
    try:
        job = ctx.h.create_platform_job(ctx.jobs, operation, payload)
        ctx.h._start_platform_background_job(job)
        st.session_state['task:' + scope] = str(job)
        if operation == 'generate_factors':
            saved = read_json(job / 'platform_job.json')
            run_id = saved.get('payload', {}).get('generation_config', {}).get('run_id')
            if run_id:
                put('ppo', 'batch', run_id)
        st.session_state['notice'] = '任务已提交，可在本模块查看进度。'
        st.rerun()
    except Exception as exc:
        st.error('提交失败：{}'.format(exc))


def open_task_output(ctx, job):
    """Carry the exact task's source and output into the corresponding workspace."""
    operation = job.get('operation')
    payload = job.get('payload', {})
    status = read_json(Path(job['path']) / 'status.json')
    result = status.get('result') or {}
    if operation == 'select_stocks':
        st.session_state['task:selection'] = job['path']
        if result.get('output_dir'):
            put('selection', 'view', '选股记录')
            put('selection-history', 'record', str(Path(result['output_dir']).resolve()))
        go('股票筛选')
    if operation == 'manual':
        st.session_state['task:manual'] = job['path']
        put('manual', 'section', '回测工作区')
        put('manual', 'show-results', True)
        put('manual-latest', 'search', '')
        if status.get('output_dir'):
            put('manual-latest', 'result', str(Path(status['output_dir']).resolve()))
        go('表达式回测')
    if operation in {'generate_factors', 'backtest_factors'}:
        batch = payload.get('generation_config', {}).get('run_id') or Path(payload.get('factor_run_dir', '')).name
        put('ppo', 'view', '生成批次')
        if batch:
            put('ppo', 'batch', batch)
            task_scope = 'ppo-generation:' if operation == 'generate_factors' else 'ppo-bt:'
            st.session_state['task:' + task_scope + batch] = job['path']
            put('ppo-results:' + batch, 'search', '')
        put('ppo', 'section', '因子列表' if operation == 'generate_factors' else '批量回测')
        if operation == 'backtest_factors' and batch:
            runs = [run for run in ctx.h.list_runs(ctx.outputs) if run.get('factor_run_id') == batch
                    and (not payload.get('experiment_id') or run.get('experiment_id') == payload['experiment_id'])]
            if runs:
                put('ppo-results:' + batch, 'result', runs[0]['path'])
        go('PPO 因子研究')
    if operation == 'compose_factors':
        st.session_state['task:composition'] = job['path']
        put('composition', 'view', '组合实验')
        put('composition-history', 'search', '')
        outputs = result.get('output_dirs') or result.get('positive_output_dirs') or []
        if outputs:
            put('composition-history', 'result', str(Path(outputs[0]).resolve()))
            manifest = read_json(Path(outputs[0]) / 'manifest.json')
            if manifest.get('composition_id'):
                put('composition', 'experiment', manifest['composition_id'])
        go('因子组合')
    if operation in {'prepare_master', 'create_pool'}:
        put('data', 'section', '数据概览' if operation == 'prepare_master' else '股票池')
        go('数据管理')


@st.fragment(run_every='4s')
def task_feedback(ctx, scope, operation=None, factor_run_id=None):
    jobs = jobs_for(all_jobs(ctx), operation=operation, factor_run_id=factor_run_id)
    tracked = st.session_state.get('task:' + scope)
    job = next((item for item in jobs if item['path'] == tracked), None)
    job = job or (jobs[0] if jobs else None)
    if not job:
        return
    path = Path(job['path'])
    status = read_json(path / 'status.json')
    if operation == 'select_stocks':
        state_key = 'selection-task-status:' + str(path)
        previous_status = st.session_state.get(state_key)
        st.session_state[state_key] = status.get('status')
        if previous_status in {'queued', 'running'} and status.get('status') in {'finished', 'failed'}:
            # Refresh the surrounding form as well as this polling fragment.
            st.rerun()
    result = status.get('result') or {}
    no_success = result.get('completed') == 0 and result.get('failed', 0) > 0
    label = ctx.h.STATUS_LABELS.get(status.get('status'), '状态缺失')
    with st.container(border=True):
        st.markdown('**{} · {}**'.format(OPERATIONS.get(job.get('operation'), '任务'), label))
        st.caption(status.get('message') or '等待任务更新')
        progress = status.get('progress') or ctx.h._load_factor_generation_progress(path)
        if progress:
            labels = {'rows_read': '已读行数', 'rows_written': '保留行数', 'stocks_touched': '股票数',
                      'accepted_count': '合格 / 入池因子', 'target_count': '目标数', 'attempts': '尝试次数',
                      'candidate_count': '候选数', 'current_size': '当前规模', 'completed_sizes': '已完成规模'}
            st.caption('　｜　'.join('{}：{}'.format(labels[k], v) for k, v in progress.items() if k in labels))
        if status.get('status') == 'failed':
            st.error(status.get('message', '任务失败，请展开日志查看原因。'))
        if status.get('status') == 'finished':
            if no_success:
                st.error('本次没有成功回测的因子：{} 个失败。请查看下方失败明细，调整后再试。'.format(result['failed']))
            elif result.get('failed', 0):
                st.warning('回测完成：{} 个成功，{} 个失败。'.format(result.get('completed', 0), result['failed']))
            else:
                st.success('任务已完成，可以查看对应结果。')
            if result.get('output_dir'):
                failures = Path(result['output_dir']) / 'factor_backtest_failures.csv'
                if failures.is_file() and result.get('failed', 0):
                    with st.expander('失败因子明细', expanded=no_success):
                        try:
                            st.dataframe(pd.read_csv(failures), hide_index=True, use_container_width=True)
                        except (OSError, pd.errors.EmptyDataError):
                            st.caption('失败明细尚未写完，请稍后刷新。')
                        ctx.h._download_button(failures, '下载失败明细', scope + ':failures')
        st.caption('更新时间：{} · 每 4 秒更新状态'.format(status.get('updated_at', '—')))
        with st.expander('查看日志与任务详情'):
            log_path = Path(status.get('log_path') or path / 'job.log')
            if log_path.is_file():
                with log_path.open('rb') as log:
                    log.seek(max(0, log_path.stat().st_size - 12000))
                    st.code(log.read().decode('utf-8', errors='replace'), language='text')
            if status.get('traceback'):
                st.code(status['traceback'], language='text')
            st.json(status, expanded=False)
        if status.get('status') == 'finished' and not no_success and st.button('查看本次结果', key='task-output:' + scope):
            open_task_output(ctx, job)
        if st.button('刷新本模块', key='task-refresh:' + scope):
            st.rerun()


def result_history(ctx, scope, result_type=None, factor_run_id=None, composition_id=None):
    runs = ctx.h.list_runs(ctx.outputs)
    if result_type:
        runs = [run for run in runs if run.get('result_type') == result_type]
    if factor_run_id:
        runs = [run for run in runs if run.get('factor_run_id') == factor_run_id]
    if composition_id:
        runs = [run for run in runs if str(run.get('composition_id') or 'legacy') == composition_id]
    query = control('text_input', '搜索记录', scope, 'search', '', placeholder='运行名称、表达式或股票池')
    if query:
        runs = [run for run in runs if query.lower() in ('{} {} {}'.format(
            run.get('run_name', ''), ctx.h._alpha_expr_from_run(run), run.get('pool_id', ''))).lower()]
    if not runs:
        st.info('暂无匹配记录。任务完成后，结果会显示在这里。')
        return
    frame = ctx.h._saved_runs_table(runs)
    columns = ['运行名称', 'pool_id', '开始日期', '结束日期', 'TopK', '年化收益', '夏普比', '最大回撤', '创建时间']
    if result_type == 'composite':
        columns.insert(1, '组合规模')
    frame = frame[columns].rename(columns={'pool_id': '股票池'})
    frame.insert(1, '来源', [ORIGINS.get(run.get('result_type'), '历史结果') for run in runs])
    names = pool_names(ctx)
    frame['股票池'] = frame['股票池'].map(lambda value: names.get(value, value or '全量数据'))
    st.dataframe(frame, use_container_width=True, hide_index=True, column_config={
        '年化收益': st.column_config.NumberColumn(format='%.2f%%'),
        '最大回撤': st.column_config.NumberColumn(format='%.2f%%'),
        '夏普比': st.column_config.NumberColumn(format='%.4f'),
    })
    by_path = {str(run['path']): run for run in runs}
    selected = control('selectbox', '查看结果详情', scope, 'result', options=list(by_path),
                       format_func=lambda value: '{} · {}'.format(by_path[value].get('run_name', Path(value).name),
                                                                 by_path[value].get('created_at', '')))
    run = by_path[selected]
    if run.get('result_type') == 'composite' and (Path(selected) / 'factor_weights.json').is_file():
        if st.button('用于选股', key='select-stocks:' + scope, type='primary'):
            put('selection', 'strategy', selected)
            put('selection', 'view', '开始选股')
            go('股票筛选')
    if run.get('result_type') == 'manual':
        if st.button('基于此结果再试一次', key='rerun:' + scope):
            copied = copy_manual_run(run)
            put('manual', 'name', copied['name'])
            put('manual', 'expr', copied['expr'])
            put('manual', 'pool', copied['pool_id'] or '')
            restored = {**ctx.defaults, **copied['backtest']}
            st.session_state['backtest-snapshot:manual'] = restored
            for key, value in restored.items():
                put('manual', key, value)
            put('manual', 'section', '回测工作区')
            go('表达式回测')
    import hashlib
    detail_scope = scope + ':' + hashlib.sha256(selected.encode('utf-8')).hexdigest()[:16]
    ctx.h._render_result_dir(Path(selected), detail_scope)


def unique_name(name):
    """Each submission has a distinct output directory, preserving prior results."""
    clean = ''.join(char if char.isalnum() or char in '-_' else '_' for char in name.strip())[:70]
    return (clean or 'experiment') + '_' + uuid4().hex[:8]
