"""Batch-oriented PPO research and composition experiments."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import streamlit as st

from app.workbench_components import active_job, all_jobs, backtest_form, check_config, control, go, pool_names, pool_select, put, result_history, source_caption, submit, task_feedback, unique_name
from app.workbench_state import jobs_for, read_json, validate_backtest


def render_ppo(ctx):
    st.caption('每个生成批次集中保存因子、批量回测和运行日志。')
    view = control('radio', 'PPO 工作区', 'ppo', 'view', '生成批次', options=['生成批次', '新建生成'], horizontal=True, label_visibility='collapsed')
    if view == '新建生成':
        generation_form(ctx)
        task_feedback(ctx, 'ppo-generate', operation='generate_factors')
        return
    # Include submitted jobs even before the worker creates its batch manifest.
    records = {str(row['run_id']): row for row in ctx.batches.to_dict('records')}
    for job in jobs_for(all_jobs(ctx), operation='generate_factors'):
        payload = job.get('payload', {})
        run_id = payload.get('generation_config', {}).get('run_id')
        if run_id:
            records.setdefault(run_id, {'run_id': run_id, 'pool_id': payload.get('pool_id'), 'accepted_count': 0})
            records[run_id]['status'] = job.get('status')
    if not records:
        st.info('还没有生成批次。先在数据管理中创建股票池，再点击「新建生成」。')
        return
    labels = pool_names(ctx)
    st.dataframe(pd.DataFrame([{'生成批次': row['run_id'], '股票池': labels.get(str(row.get('pool_id')), row.get('pool_id')),
                               '合格因子': row.get('accepted_count', 0), '状态': ctx.h.STATUS_LABELS.get(row.get('status'), '已有记录')}
                              for row in records.values()]), hide_index=True, use_container_width=True)
    batch_id = control('selectbox', '打开生成批次', 'ppo', 'batch', options=list(records))
    record = records[batch_id]
    st.caption('当前批次：{}　｜　绑定股票池：{}'.format(batch_id, labels.get(str(record.get('pool_id')), record.get('pool_id', '—'))))
    section = control('radio', '批次内容', 'ppo', 'section', '因子列表', options=['因子列表', '批量回测', '配置与日志'], horizontal=True)
    batch_dir = ctx.factors / batch_id
    factors = ctx.h._load_accepted_factor_table(batch_dir)
    if section == '因子列表':
        task_feedback(ctx, 'ppo-generation:' + batch_id, operation='generate_factors', factor_run_id=batch_id)
        if factors.empty:
            st.info('本批次暂时没有合格因子。生成任务运行时，可在上方查看当前进度。')
        else:
            st.metric('合格因子', len(factors))
            st.dataframe(factors, use_container_width=True, hide_index=True)
            left, right = st.columns(2)
            with left:
                if st.button('回测本批次合格因子', type='primary', key='ppo-to-backtest'):
                    put('ppo', 'section', '批量回测')
                    st.rerun()
            with right:
                if st.button('用于因子组合', key='ppo-to-composition'):
                    put('composition', 'pool', str(record.get('pool_id', '')))
                    put('composition', 'batch', batch_id)
                    put('composition', 'view', '新建组合')
                    go('因子组合')
    elif section == '批量回测':
        scope = 'ppo-bt:' + batch_id
        st.caption('回测范围：当前批次的全部合格因子。每次执行均保留独立结果。')
        config = backtest_form(ctx, scope)
        if factors.empty:
            st.info('需要本批次至少生成一个合格因子后才能回测。')
        if not ctx.master_ready:
            st.warning('请先在数据管理中准备主缓存。')
        if st.button('启动合格因子批量回测', key='ppo-backtest-submit', type='primary',
                     disabled=factors.empty or not ctx.master_ready or active_job(ctx, scope)):
            if check_config(config, ctx):
                submit(ctx, scope, 'backtest_factors', {'master_store': str(ctx.master), 'pools_root': str(ctx.pools_dir),
                       'factor_run_dir': str(batch_dir), 'outputs_root': str(ctx.outputs), 'expected_pool_id': record.get('pool_id'),
                       'backtest_config': config, 'experiment_id': unique_name('backtest')})
        task_feedback(ctx, scope, operation='backtest_factors', factor_run_id=batch_id)
        st.subheader('本批次回测结果')
        result_history(ctx, 'ppo-results:' + batch_id, result_type='factor', factor_run_id=batch_id)
    else:
        st.json(read_json(batch_dir / 'factor_run.json'), expanded=False)
        task_feedback(ctx, 'ppo-log-generation:' + batch_id, operation='generate_factors', factor_run_id=batch_id)
        task_feedback(ctx, 'ppo-log-backtest:' + batch_id, operation='backtest_factors', factor_run_id=batch_id)


def generation_form(ctx):
    if not ctx.master_ready or ctx.pools.empty:
        st.warning('请先在「数据管理」准备主缓存并创建股票池。')
        if st.button('前往数据管理', key='ppo-to-data'):
            go('数据管理')
        return
    name = control('text_input', '生成批次名称', 'generate', 'name', 'PPO研究')
    pool = pool_select(ctx, 'generate')
    source_caption(ctx, pool)
    cfg = deepcopy(ctx.generation)
    fields_text = control('text_area', '用于生成的字段', 'generate', 'fields',
                          '\n'.join(cfg.get('fields', ctx.platform.get('factor_fields', ['close']))), height=120)
    st.subheader('训练、验证与测试区间')
    st.caption('训练用于学习，验证用于筛选，测试用于样本外评估。日期采用 YYYY-MM-DD。')
    splits = {}
    columns = st.columns(3)
    for column, (key, label) in zip(columns, [('train', '训练'), ('valid', '验证'), ('test', '测试')]):
        with column:
            default = cfg.get('splits', {}).get(key, {})
            start = control('text_input', label + '开始', 'generate', key + '_start', str(default.get('cache_start', ctx.defaults['start_date'])))
            end = control('text_input', label + '结束', 'generate', key + '_end', str(default.get('cache_end', ctx.defaults['end_date'])))
            splits[key] = {'cache_start': start, 'cache_end': end}
    target = control('number_input', '目标合格因子数', 'generate', 'target', int(cfg.get('target_factor_count', 50)), min_value=1)
    with st.expander('高级生成参数'):
        attempts = control('number_input', '最大尝试次数', 'generate', 'attempts', int(cfg.get('max_attempts', 100000)), min_value=1)
        st.caption('其他算法参数沿用 configs/factor_generation.yaml。')
    if st.button('启动 PPO 因子生成', key='ppo-generate-submit', type='primary', disabled=active_job(ctx, 'ppo-generate')):
        fields = ctx.h._parse_multiline_values(fields_text)
        errors = []
        if not name.strip():
            errors.append('请填写生成批次名称。')
        if not fields:
            errors.append('至少选择一个生成字段。')
        available = {field['name'] for field in ctx.meta.get('field_catalog', [])}
        if available and set(fields) - available:
            errors.append('主缓存缺少字段：' + '、'.join(sorted(set(fields) - available)))
        for split, values in splits.items():
            errors += [split + '：' + error for error in validate_backtest({'start_date': values['cache_start'], 'end_date': values['cache_end']}, ctx.meta)]
        if errors:
            for error in errors:
                st.error(error)
            return
        cfg.update({'run_id': unique_name(name), 'fields': fields, 'splits': splits, 'target_factor_count': target, 'max_attempts': attempts})
        submit(ctx, 'ppo-generate', 'generate_factors', {'master_store': str(ctx.master), 'pools_root': str(ctx.pools_dir),
               'pool_id': pool, 'runtime_root': str(ctx.root / 'data_cache/factor_runtime'), 'factor_runs_root': str(ctx.factors),
               'fields': fields, 'splits': splits, 'max_backtrack_days': int(cfg.get('max_backtrack_days', 100)),
               'target_horizon': int(cfg.get('target_horizon', 20)), 'max_future_days': int(cfg.get('max_future_days', 20)),
               'generation_config': cfg})


def render_composition(ctx):
    st.caption('选择合格因子，筛选去重并优化权重，在本模块查看不同组合规模的表现。')
    view = control('radio', '组合工作区', 'composition', 'view', '组合实验', options=['组合实验', '新建组合'], horizontal=True, label_visibility='collapsed')
    if view == '组合实验':
        task_feedback(ctx, 'composition', operation='compose_factors')
        runs = [run for run in ctx.h.list_runs(ctx.outputs) if run.get('result_type') == 'composite']
        groups = {}
        for run in runs:
            groups.setdefault(str(run.get('composition_id') or 'legacy'), []).append(run)
        if not groups:
            st.info('还没有组合实验。点击「新建组合」，从已有合格因子开始。')
            return
        labels = pool_names(ctx)
        st.dataframe(pd.DataFrame([{'实验': key, '股票池': labels.get(str(items[0].get('pool_id')), items[0].get('pool_id')),
                                   '已保存规模数': len(items), '创建时间': items[0].get('created_at', '')}
                                  for key, items in groups.items()]), use_container_width=True, hide_index=True)
        experiment = control('selectbox', '打开组合实验', 'composition', 'experiment', options=list(groups))
        st.subheader('本实验各规模的回测表现')
        result_history(ctx, 'composition-history', result_type='composite', composition_id=experiment)
        return
    if not ctx.master_ready or ctx.pools.empty or ctx.batches.empty:
        st.warning('组合需要可用主缓存、股票池和合格因子批次。请先完成 PPO 因子生成。')
        return
    pool = pool_select(ctx, 'composition')
    source_caption(ctx, pool)
    candidates = ctx.batches[ctx.batches['pool_id'].astype(str) == str(pool)] if 'pool_id' in ctx.batches else pd.DataFrame()
    if candidates.empty:
        st.info('当前股票池没有可用生成批次，请切换股票池或生成因子。')
        return
    batch = control('selectbox', '来源因子批次', 'composition', 'batch', options=candidates['run_id'].astype(str).tolist())
    st.subheader('筛选与去重')
    metric = control('selectbox', '组合排序指标', 'composition', 'metric', 'score', options=['score', 'ic', 'rank_ic', 'icir', 'coverage', 'backtest_sharpe'])
    threshold = control('number_input', 'mutual IC 阈值', 'composition', 'mutual', 0.99, min_value=0.0, max_value=1.0, format='%.4f')
    optional = {}
    with st.expander('最低指标与边际贡献要求'):
        pairs = [('min_score', '最低 Score', '0'), ('min_ic', '最低 IC', ''), ('min_rank_ic', '最低 Rank IC', ''),
                 ('min_coverage', '最低 Coverage', '0'), ('min_backtest_sharpe', '最低单因子回测 Sharpe', ''),
                 ('min_marginal_ic_improvement', '最低边际 IC 改善', '0'),
                 ('min_marginal_rank_ic_improvement', '最低边际 Rank IC 改善', ''),
                 ('min_marginal_icir_improvement', '最低边际 ICIR 改善', ''),
                 ('min_marginal_rank_icir_improvement', '最低边际 Rank ICIR 改善', '')]
        cols = st.columns(2)
        for idx, (key, label, value) in enumerate(pairs):
            with cols[idx % 2]:
                optional[key] = control('text_input', label + '（空表示不限制）', 'composition', key, value)
    st.subheader('组合设置')
    sweep = control('text_input', '组合规模扫描', 'composition', 'sweep', '10,20,30,40,50,60,70,80,90,100', help='用逗号分隔，例如 10,20,50')
    left, right = st.columns(2)
    with left:
        maximum = control('number_input', '最多组合因子数', 'composition', 'maximum', 100, min_value=1, max_value=100)
    with right:
        horizon = control('number_input', '组合 IC 目标周期', 'composition', 'horizon', int(ctx.generation.get('target_horizon', 20)), min_value=1)
    st.subheader('组合回测参数')
    config = backtest_form(ctx, 'composition-bt')
    if st.button('启动因子组合', key='composition-submit', type='primary', disabled=active_job(ctx, 'composition')):
        if not check_config(config, ctx):
            return
        try:
            sizes = ctx.h._parse_int_values(sweep)
            if not sizes or any(size < 1 or size > maximum for size in sizes):
                raise ValueError('组合规模需为正整数，且不得超过最多组合因子数。')
            filters = {key: ctx.h._parse_optional_float(value) for key, value in optional.items()}
            import math
            if any(value is not None and not math.isfinite(value) for value in filters.values()):
                raise ValueError('指标阈值必须为有限数值。')
        except ValueError as exc:
            st.error('组合参数错误：{}'.format(exc))
            return
        submit(ctx, 'composition', 'compose_factors', {'master_store': str(ctx.master), 'pools_root': str(ctx.pools_dir),
               'pool_id': pool, 'factor_run_dirs': [str(ctx.factors / batch)], 'outputs_root': str(ctx.outputs),
               'backtest_config': config, 'selection_metric': metric, 'mutual_ic_threshold': threshold,
               'sweep_sizes': sizes, 'max_factors': maximum, 'objective_type': 'mse', 'target_horizon': horizon,
               'experiment_id': unique_name('composition'), **filters})
    task_feedback(ctx, 'composition', operation='compose_factors')
