"""Manual expression research with local results and persistent configuration."""
from __future__ import annotations

import streamlit as st

from app.workbench_components import active_job, backtest_form, check_config, control, go, pool_select, put, result_history, source_caption, task_feedback, unique_name
from custom_bt.expressions import _validate_ast


def render(ctx):
    st.caption('编辑表达式、执行回测并查看结果。切换模块后，当前输入会保留。')
    section = control('radio', '表达式回测视图', 'manual', 'section', '回测工作区',
                      options=['回测工作区', '历史记录'], horizontal=True, label_visibility='collapsed')
    if section == '历史记录':
        result_history(ctx, 'manual-history', result_type='manual')
        return
    if not ctx.meta or not (ctx.store / 'stocks').is_dir():
        st.warning('没有可用数据，请前往「数据管理」导入或配置缓存目录。')
        if st.button('前往数据管理', key='manual-data'):
            go('数据管理')
        return
    name = control('text_input', '运行名称', 'manual', 'name', '表达式研究')
    pool_id = pool_select(ctx, 'manual', allow_all=True)
    source_caption(ctx, pool_id)
    # Only inspect catalog metadata; never load the entire stock panel for UI help.
    fields = ctx.meta.get('field_catalog') or []
    with st.expander('字段与算子帮助'):
        help_type = control('radio', '资料类型', 'manual-help', 'type', '字段', options=['字段', '算子'], horizontal=True)
        table = ctx.h._format_fields(fields) if help_type == '字段' else ctx.h._format_operators()
        query = control('text_input', '搜索说明或示例', 'manual-help', 'query', '')
        if query and not table.empty:
            table = table[table.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False, na=False)).any(axis=1)]
        st.dataframe(table, hide_index=True, use_container_width=True)
        if not table.empty:
            column = '字段名' if help_type == '字段' else '示例'
            sample = control('selectbox', '选择插入内容', 'manual-help', 'sample:' + help_type, options=table[column].tolist())
            if st.button('追加到表达式', key='manual-insert'):
                expr = st.session_state.get('draft:manual:expr', 'close / delay(close, 20) - 1')
                put('manual', 'expr', expr + ' ' + sample)
                st.rerun()
    expr = control('text_area', 'Alpha 表达式', 'manual', 'expr', 'close / delay(close, 20) - 1', height=135)
    config = backtest_form(ctx, 'manual')
    if st.button('提交后台回测任务', key='manual-submit', type='primary', disabled=active_job(ctx, 'manual')):
        valid = check_config(config, ctx)
        if not name.strip():
            st.error('请填写运行名称。')
            valid = False
        try:
            _validate_ast(expr.strip(), {**{field['name']: None for field in fields},
                                         'gaussian': 'gaussian', 'uniform': 'uniform', 'cauchy': 'cauchy'})
        except Exception as exc:
            st.error('表达式检查未通过：{}'.format(exc))
            valid = False
        if pool_id and not ctx.master_ready:
            st.error('股票池绑定主缓存，请先完成主缓存导入；兼容缓存可使用全量数据回测。')
            valid = False
        if valid:
            try:
                job = ctx.h.create_backtest_job(jobs_root=ctx.jobs, data_path=str(ctx.store), outputs_path=str(ctx.outputs),
                                               run_name=unique_name(name), expr=expr.strip(), backtest=config,
                                               pool_id=pool_id or None, pools_root=str(ctx.pools_dir))
                ctx.h._start_background_job(job)
                st.session_state['task:manual'] = str(job)
                st.session_state['notice'] = '回测已提交；下面会显示运行进度，完成后可查看结果。'
                st.rerun()
            except Exception as exc:
                st.error('提交失败：{}'.format(exc))
    task_feedback(ctx, 'manual', operation='manual')
    show_results = control('checkbox', '显示已完成回测', 'manual', 'show-results', False)
    if show_results or st.session_state.get('task:manual'):
        st.subheader('已完成回测')
        result_history(ctx, 'manual-latest', result_type='manual')
