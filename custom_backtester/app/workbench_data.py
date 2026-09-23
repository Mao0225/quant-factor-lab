"""Data overview, stock pools, catalog and background imports."""
from __future__ import annotations

import streamlit as st

from app.workbench_components import active_job, control, pool_names, submit, task_feedback
from app.workbench_state import read_json, validate_backtest


def render(ctx):
    section = control('radio', '数据管理视图', 'data', 'section', '数据概览',
                      options=['数据概览', '股票池', '字段与股票', '导入更新'], horizontal=True, label_visibility='collapsed')
    if section == '数据概览':
        if not ctx.meta:
            st.info('暂无可用缓存。请打开「导入更新」准备数据，或在系统设置中指定已有缓存。')
        else:
            st.caption('当前研究使用：{}'.format(ctx.store))
            columns = st.columns(3)
            columns[0].metric('股票数', ctx.meta.get('n_stocks', '—'))
            columns[1].metric('数据行数', ctx.meta.get('rows', '—'))
            columns[2].metric('字段数', len(ctx.meta.get('field_catalog', [])))
            st.info('覆盖区间：{} 至 {}'.format(ctx.meta.get('date_min', '—'), ctx.meta.get('date_max', '—')))
            st.caption('主缓存用于股票池、因子生成和组合研究；表达式回测在主缓存不可用时兼容旧缓存。')
            with st.expander('数据元信息'):
                st.json(ctx.meta, expanded=False)
        task_feedback(ctx, 'data-import', operation='prepare_master')
    elif section == '股票池':
        render_pools(ctx)
    elif section == '字段与股票':
        render_catalog(ctx)
    else:
        render_import(ctx)


def render_pools(ctx):
    if not ctx.pools.empty:
        columns = [name for name in ['name', 'pool_id', 'n_stocks', 'selection_start', 'selection_end'] if name in ctx.pools]
        st.dataframe(ctx.pools[columns].rename(columns={'name': '名称', 'pool_id': '股票池 ID', 'n_stocks': '股票数',
                     'selection_start': '筛选开始', 'selection_end': '筛选结束'}), hide_index=True, use_container_width=True)
        labels = pool_names(ctx)
        selected = control('selectbox', '查看股票池', 'data-pools', 'selected', options=list(labels), format_func=lambda value: labels[value])
        with st.expander('筛选条件与股票代码'):
            st.json(read_json(ctx.pools_dir / selected / 'manifest.json'), expanded=False)
            codes = ctx.pools_dir / selected / 'codes.txt'
            if codes.is_file():
                st.code(codes.read_text(encoding='utf-8'), language='text')
    else:
        st.info('还没有股票池。主缓存就绪后，可在下方创建。')
    with st.expander('新建股票池', expanded=ctx.pools.empty):
        cfg = ctx.h._load_yaml_defaults(ctx.root / 'configs/pools/liquid_500.yaml')
        name = control('text_input', '股票池名称', 'pool-new', 'name', str(cfg.get('name', 'liquid_500')))
        cols = st.columns(2)
        with cols[0]:
            start = control('text_input', '筛选开始日期', 'pool-new', 'start', str(cfg.get('selection_start', ctx.defaults['start_date'])))
            top_n = control('number_input', '股票池数量（0 表示不限制）', 'pool-new', 'top_n', int(cfg.get('top_n') or 500), min_value=0)
        with cols[1]:
            end = control('text_input', '筛选结束日期', 'pool-new', 'end', str(cfg.get('selection_end', ctx.defaults['end_date'])))
            min_days = control('number_input', '最少上市天数', 'pool-new', 'min_days', int(cfg.get('min_listed_days', 250)), min_value=0)
        coverage = control('number_input', '最小覆盖率', 'pool-new', 'coverage', float(cfg.get('min_coverage', 0.9)), min_value=0.0, max_value=1.0)
        category = control('text_input', '股票类别（可选）', 'pool-new', 'category', str(cfg.get('category') or ''))
        market = control('text_input', '市场代码（可选）', 'pool-new', 'market', str(cfg.get('market_code') or ''))
        suspended = control('checkbox', '排除停牌数据', 'pool-new', 'suspended', bool(cfg.get('exclude_suspended', True)))
        if not ctx.master_ready:
            st.warning('请先在「导入更新」完成主缓存准备。')
        if st.button('创建股票池', type='primary', key='pool-create', disabled=not ctx.master_ready or active_job(ctx, 'pool-create')):
            errors = validate_backtest({'start_date': start, 'end_date': end}, read_json(ctx.master / 'meta.json'))
            if not name.strip():
                errors.append('请填写股票池名称。')
            if errors:
                for error in errors:
                    st.error(error)
            else:
                submit(ctx, 'pool-create', 'create_pool', {'store_dir': str(ctx.master), 'pools_root': str(ctx.pools_dir),
                       'name': name.strip(), 'selection_start': start, 'selection_end': end, 'top_n': top_n or None,
                       'min_listed_days': min_days, 'min_coverage': coverage, 'exclude_suspended': suspended,
                       'category': category.strip() or None, 'market_code': market.strip() or None, 'overwrite': False})
    task_feedback(ctx, 'pool-create', operation='create_pool')


def render_catalog(ctx):
    source = control('selectbox', '查看数据源', 'catalog', 'source', '当前研究数据', options=['当前研究数据', '主缓存', '兼容缓存'])
    store = {'当前研究数据': ctx.store, '主缓存': ctx.master, '兼容缓存': ctx.legacy}[source]
    st.caption('实际读取：{}'.format(store))
    kind = control('radio', '内容', 'catalog', 'kind', '字段', options=['字段', '股票'], horizontal=True)
    if kind == '字段':
        table = ctx.h._format_fields(read_json(store / 'meta.json').get('field_catalog') or [])
    else:
        stock_path = ctx.h.stock_list_path(store)
        if not stock_path.is_file():
            st.info('当前缓存尚无股票信息索引。可在本机命令行生成索引后刷新此页。')
            st.code('python -m custom_bt.cli stock-list --data "{}"'.format(store), language='text')
            return
        table = ctx.h._load_stock_table_cached(str(store), stock_path.stat().st_mtime)
    query = control('text_input', '搜索字段或股票', 'catalog', 'query', '')
    if query and not table.empty:
        table = table[table.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False, na=False)).any(axis=1)]
    if table.empty:
        st.info('没有匹配条目。请检查数据源及搜索条件。')
    else:
        st.caption('共 {} 条'.format(len(table)))
        st.dataframe(table, hide_index=True, use_container_width=True)


def render_import(ctx):
    default = str(ctx.h._default_source_path())
    source = control('text_input', '主数据 CSV/TSV 路径', 'import', 'source', default)
    fields = control('text_area', '导入字段（每行一个，也支持逗号）', 'import', 'fields',
                     '\n'.join(ctx.platform.get('factor_fields', ['open', 'close', 'high', 'low', 'volume', 'amount'])), height=140)
    with st.expander('高级导入选项'):
        limit = control('text_input', '限制导入行数（留空全量）', 'import', 'limit', '')
        chunksize = control('number_input', '导入分块大小', 'import', 'chunksize', 200000, min_value=1000, step=1000)
        overwrite = control('checkbox', '覆盖已有主缓存', 'import', 'overwrite', False)
    st.caption('目标缓存：{}'.format(ctx.master))
    if overwrite:
        st.warning('覆盖模式会替换上面的主缓存，请确认路径及来源正确。')
    if st.button('构建 / 更新主数据缓存', key='import-submit', type='primary', disabled=active_job(ctx, 'data-import')):
        from pathlib import Path
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = ctx.root / path
        try:
            count = int(limit) if limit.strip() else None
            if count is not None and count < 1:
                raise ValueError('导入行数必须为正整数。')
            chosen = ctx.h._parse_multiline_values(fields)
            if not chosen:
                raise ValueError('至少选择一个导入字段。')
            if not path.is_file():
                raise ValueError('来源文件不存在，请检查路径。')
        except ValueError as exc:
            st.error(str(exc))
            return
        submit(ctx, 'data-import', 'prepare_master', {'csv_path': str(path), 'store_dir': str(ctx.master), 'fields': chosen,
               'chunksize': chunksize, 'limit_rows': count, 'overwrite': overwrite, 'delimiter': ctx.platform.get('delimiter')})
    task_feedback(ctx, 'data-import', operation='prepare_master')
