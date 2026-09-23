"""Fixed-composition stock screening and persistent, explainable shortlists."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

from app.workbench_components import active_job, control, go, pool_names, put, submit, task_feedback
from app.workbench_state import read_json
from custom_bt.stock_selection import list_selections, load_strategy


def render(ctx):
    st.caption('固定组合 → 计算股票得分 → 筛选候选名单。沿用组合的因子权重，每次选股独立保存。')
    view = control('radio', '选股工作区', 'selection', 'view', '开始选股',
                   options=['开始选股', '选股记录'], horizontal=True, label_visibility='collapsed')
    if view == '选股记录':
        render_history(ctx)
        st.divider()
        task_feedback(ctx, 'selection', operation='select_stocks')
        return
    task_feedback(ctx, 'selection', operation='select_stocks')
    runs = {str(run['path']): run for run in ctx.h.list_runs(ctx.outputs)
            if run.get('result_type') == 'composite' and (Path(run['path']) / 'factor_weights.json').is_file()}
    if not runs:
        st.info('还没有可用于选股的组合。请先完成因子组合，再从组合详情点击「用于选股」。')
        if st.button('前往因子组合', key='selection-to-composition', type='primary'):
            go('因子组合')
        return
    st.subheader('1. 选择组合策略')
    selected = control('selectbox', '组合版本', 'selection', 'strategy', options=list(runs),
                       format_func=lambda path: '{} · {} 个因子 · {}'.format(
                           runs[path].get('run_name', Path(path).name), runs[path].get('max_factors', '—'),
                           runs[path].get('created_at', '')))
    try:
        strategy = load_strategy(selected, ctx.pools_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error('该组合暂时不能用于选股：{}'.format(exc))
        st.info('可以切换其他组合版本，或重新生成带有完整评分规则的组合。')
        if st.button('前往因子组合', key='selection-to-composition'):
            go('因子组合')
        return
    with st.container(border=True):
        st.markdown('**{}**'.format(strategy.get('name', runs[selected].get('run_name', '组合策略'))))
        st.caption('股票池：{}　｜　固定股票数：{}　｜　研究数据截止：{}'.format(
            pool_names(ctx).get(strategy.get('pool_id'), strategy.get('pool_id', '—')),
            len(strategy.get('codes', [])), strategy.get('research_end') or '未记录'))
        st.caption('策略形成时间：{}　｜　版本：{}'.format(strategy.get('formed_at') or '未记录',
                                                       strategy.get('fingerprint', '')[:12]))
        with st.expander('查看因子与固定权重'):
            components = pd.DataFrame(strategy['components'])
            columns = [key for key in ['factor_id', 'expression', 'weight'] if key in components]
            st.dataframe(components[columns].rename(columns={'factor_id': '因子', 'expression': '表达式', 'weight': '评分权重'}),
                         hide_index=True, use_container_width=True)
            st.caption('权重用于合成股票得分，不代表股票仓位。')
    if not ctx.master_ready:
        st.warning('需要可用主缓存才能计算股票得分。')
        if st.button('前往数据管理', key='selection-to-data'):
            go('数据管理')
        return
    st.subheader('2. 设置选股条件')
    available_end = str(ctx.meta.get('date_max') or '')[:10]
    st.caption('数据缓存截止：{}。按收盘数据评分；非交易日采用此前最近的可用交易日。'.format(available_end or '未记录'))
    left, right = st.columns(2)
    with left:
        requested = control('text_input', '评分日期', 'selection', 'date', available_end,
                            help='YYYY-MM-DD；结果会显示实际使用的数据日期。')
    with right:
        top_n = control('number_input', '选股数量 Top N', 'selection', 'top_n', 20, min_value=1, max_value=10000)
    fields = set(ctx.meta.get('fields') or []) | {field['name'] for field in ctx.meta.get('field_catalog', [])}
    with st.expander('数据完整性与停牌过滤'):
        coverage = control('number_input', '最低有效因子比例', 'selection', 'coverage', 1.0,
                           min_value=0.0, max_value=1.0, step=0.1,
                           help='默认要求所有非零权重因子都有有效值。降低比例后，缺失因子的贡献按组合原规则计为零。')
        exclude = control('checkbox', '排除评分日停牌股票', 'selection', 'exclude_suspended', 'Ifsuspend' in fields)
        if 'Ifsuspend' not in fields:
            st.caption('缓存未声明停牌字段；若开启此条件，计算时必须有 Ifsuspend 数据。')
        st.caption('自动排除评分日缺少行情、收盘价无效或所有因子缺失的股票。筛选不会改变组合的标准化股票池。')
    try:
        date = pd.Timestamp(datetime.strptime(requested.strip(), '%Y-%m-%d'))
        if pd.isna(date):
            raise ValueError('请填写评分日期。')
        end = pd.Timestamp(available_end) if available_end else None
        if end is not None and date > end:
            raise ValueError('评分日期不能晚于缓存截止日期 {}。请先更新数据。'.format(available_end))
        research_end = pd.to_datetime(strategy.get('research_end'), errors='coerce')
        formed_at = pd.to_datetime(strategy.get('formed_at'), errors='coerce')
        retrospective = bool(strategy.get('provenance_warnings')) or pd.isna(research_end) or pd.isna(formed_at) or date <= research_end or date.normalize() <= formed_at.normalize()
        if retrospective:
            st.warning('此日期将作为历史评分预览：策略形成时间或研究数据范围晚于该日期，或来源日期不完整。结果不属于样本外验证。')
        date_error = None
    except (ValueError, TypeError) as exc:
        date_error = '请使用有效的 YYYY-MM-DD 日期。' if 'does not match format' in str(exc) else str(exc)
    st.caption('下一步将生成候选名单和逐因子评分解释，并保存本次策略快照。得分是相对排名依据。')
    if st.button('开始选股', type='primary', key='selection-submit', disabled=active_job(ctx, 'selection')):
        if date_error:
            st.error(date_error)
        else:
            submit(ctx, 'selection', 'select_stocks', {
                'master_store': str(ctx.master), 'strategy': strategy,
                'outputs_root': str(ctx.outputs.parent / 'stock_selections'),
                'as_of_date': date.strftime('%Y-%m-%d'), 'top_n': top_n,
                'min_factor_coverage': coverage, 'exclude_suspended': exclude,
            })


def _read_csv(path):
    return pd.read_csv(path, dtype={'code': str, 'factor_id': str})


def render_history(ctx):
    records = list_selections(ctx.outputs.parent / 'stock_selections')
    if not records:
        st.info('还没有选股记录。选择组合并点击「开始选股」后，名单会保存在这里。')
        if st.button('开始一次选股', key='selection-new'):
            put('selection', 'view', '开始选股')
            st.rerun()
        return
    by_path = {str(Path(item['path']).resolve()): item for item in records}
    selected = control('selectbox', '查看选股记录', 'selection-history', 'record', options=list(by_path),
                       format_func=lambda path: '{} · {} · {}'.format(
                           by_path[path].get('as_of_date', ''), by_path[path].get('strategy_name', ''),
                           by_path[path].get('created_at', Path(path).name)))
    path = Path(selected)
    record = by_path[selected]
    st.subheader('策略候选股票')
    st.caption('实际数据日期：{}　｜　请求日期：{}　｜　策略：{}'.format(
        record.get('as_of_date', '—'), record.get('requested_date', '—'), record.get('strategy_name', '—')))
    if record.get('retrospective'):
        st.warning('历史评分预览：这份名单不能作为当时可用策略的样本外验证。')
    for warning in record.get('warnings') or []:
        if not (record.get('retrospective') and str(warning).startswith('历史回看预览')):
            st.warning(str(warning))
    columns = st.columns(3)
    for column, label, key in zip(columns, ['入选股票', '符合条件', '股票池总数'], ['selected_count', 'eligible_count', 'total_count']):
        column.metric(label, record.get(key, '—'))
    names = {'code': '股票代码', 'name': '股票名称', 'score': '综合得分', 'rank': '排名',
             'coverage': '有效因子比例', 'close': '收盘价', 'reason': '未入选原因', 'selected': '入选', 'eligible': '符合条件'}
    try:
        candidates = _read_csv(path / 'candidates.csv')
        ranking = _read_csv(path / 'rankings.csv')
        if 'reason' in ranking:
            reasons = {'missing_as_of_date': '评分日没有行情', 'invalid_close': '收盘价无效',
                       'suspended': '评分日停牌', 'all_factors_missing': '全部因子缺失',
                       'suspension_status_unknown': '停牌状态缺失，无法确认', 'outside_top_n': '排名未进入 Top N',
                       'insufficient_factor_coverage': '有效因子比例不足', 'invalid_score': '综合得分无效'}
            ranking['reason'] = ranking['reason'].fillna('').map(lambda value: reasons.get(value, value))
            if 'selected' in ranking and 'eligible' in ranking:
                ranking.loc[ranking['eligible'] & ~ranking['selected'], 'reason'] = '排名未进入 Top N'
        if candidates.empty:
            st.info('本次没有股票满足条件。请查看未入选原因，再调整条件或数据。')
        else:
            visible = [key for key in ['rank', 'code', 'name', 'score', 'coverage', 'close'] if key in candidates]
            if 'name' in visible and candidates['name'].fillna('').eq('').all():
                visible.remove('name')
                st.caption('当前缓存未提供股票名称，名单按股票代码展示。')
            st.dataframe(candidates[visible].rename(columns=names), hide_index=True, use_container_width=True,
                         column_config={'综合得分': st.column_config.NumberColumn(format='%.6f'),
                                        '收盘价': st.column_config.NumberColumn(format='%.2f')})
            code = control('selectbox', '查看入选理由', 'selection-detail:' + path.name, 'code',
                           options=candidates['code'].tolist())
            details = _read_csv(path / 'contributions.csv')
            details = details[details['code'] == code]
            snapshot = read_json(path / 'strategy.json')
            expressions = {item['factor_id']: item.get('expression', '') for item in snapshot.get('components', [])}
            details = details.assign(expression=details['factor_id'].map(expressions).fillna(''))
            st.caption('综合得分 = 各因子标准化得分 × 固定权重的合计。')
            st.dataframe(details.rename(columns={'code': '股票代码', 'factor_id': '因子', 'raw_value': '原始值',
                         'standardized_value': '标准化得分', 'weight': '权重', 'contribution': '得分贡献', 'expression': '因子表达式'}),
                         hide_index=True, use_container_width=True,
                         column_config={label: st.column_config.NumberColumn(format='%.6f')
                                        for label in ['标准化得分', '权重', '得分贡献']})
        with st.expander('查看全股票池评分及未入选原因'):
            st.dataframe(ranking.rename(columns=names), hide_index=True, use_container_width=True)
    except (OSError, ValueError, KeyError) as exc:
        st.error('选股记录读取失败：{}'.format(exc))
    for filename, label in [('candidates.csv', '下载候选名单'), ('rankings.csv', '下载全量评分'),
                            ('contributions.csv', '下载因子贡献'), ('strategy.json', '下载策略快照')]:
        ctx.h._download_button(path / filename, label, 'selection-download:' + path.name + ':' + filename)
    with st.expander('策略快照与筛选参数'):
        st.json(read_json(path / 'strategy.json'), expanded=False)
        st.json(record, expanded=False)
