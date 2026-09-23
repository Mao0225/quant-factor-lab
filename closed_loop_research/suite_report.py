"""Small source-backed comparison report; no extra training or evaluation."""
from html import escape
from pathlib import Path
import json
import numpy as np
from .storage import read_json, atomic_json, atomic_bytes, digest
from .protocol import Protocol
from .runner import load_state
from .report import build_report


def annual_rows(result, segment):
    rows = []
    for year in sorted({d['date'][:4] for d in result['daily']}):
        days = [d for d in result['daily'] if d['date'].startswith(year)]
        growth = np.r_[1., np.cumprod([1+d['net_return'] for d in days])]
        rows.append(dict(segment=segment, year=year, sessions=len(days),
                         net_return=float(growth[-1]-1),
                         drawdown=float(np.min(growth/np.maximum.accumulate(growth)-1)),
                         fees=sum(d['fee'] for d in days), slippage=sum(d['slippage'] for d in days)))
    return rows


def build_suite_report(root):
    root = Path(root)
    suite, manifest = read_json(root/'comparison.json'), read_json(root/'suite_manifest.json')
    evidence, run_rows, annual = [], [], []
    for row in suite['runs']:
        run = Path(row['run'])
        state = load_state(run)['state']
        model = read_json(run/'frozen_model.json')
        protocol = Protocol.from_dict(read_json(run/'protocol.json'))
        chosen = read_json(run/'selection_backtests'/f"{model['selection_artifact']}.json")['result']
        years, unavailable = [], []
        for segment in 'FE':
            key = digest(dict(protocol=protocol.digest, snapshot=model['snapshot_id'], segment=segment,
                              bounds=list(protocol.bounds(segment)), weights=model['weights']))
            artifact = run/'backtests'/f'{key}.json'
            if artifact.exists() or artifact.with_suffix('.json.gz').exists():
                years += annual_rows(read_json(artifact)['result'], segment)
            else:
                unavailable.append(segment)
        years += annual_rows(chosen, 'V')
        if not row['test_locked']:
            test = read_json(run/'test_result.json')
            years += annual_rows(read_json(run/'test_backtests'/f"{test['artifact_id']}.json")['result'], 'T')
        build_report(run)
        item = dict(group=row['group'], seed=row['seed'], weights=model['weights'],
                    selected_batch=model['selected_batch'], pool_changes=state['pool_version'],
                    ppo_updates=state['ppo_updates'], years=years, unavailable_development_segments=unavailable,
                    positive_rewards=sum(t['reward']>0 for b in state['completed'] for t in b['trials']),
                    negative_rewards=row['negative_rewards'], candidates=row['candidates'])
        evidence.append(item)
        run_rows.append(f"<tr><td><a href='{run.name}/report.html'>{run.name}</a></td><td>{row['candidates']}</td><td>{state['pool_version']}</td><td>{state['ppo_updates']}</td><td>{row['failure_rate']:.1%}</td><td>{item['positive_rewards']} / {item['negative_rewards']}</td><td>{row['selection_objective']:.4f}</td><td>{row.get('test_objective',float('nan')):.4f}</td><td>{row['budget']['logical_f']+row['budget']['logical_e']} / {row['budget']['actual_f']+row['budget']['actual_e']}</td></tr>")
        for year in years:
            annual.append(f"<tr><td>{run.name}</td><td>{year['segment']}</td><td>{year['year']}</td><td>{year['sessions']}</td><td>{year['net_return']:.2%}</td><td>{year['drawdown']:.2%}</td><td>{year['fees']:.0f}</td><td>{year['slippage']:.0f}</td></tr>")
    atomic_json(root/'report_evidence.json', evidence)
    summary = []
    names = dict(A='固定初始因子', B='随机表达式', C='单因子 IC PPO', D='组合 IC PPO', E='交易增量奖励 PPO')
    for group, stats in suite['summary'].items():
        members = [r for r in suite['runs'] if r['group']==group and not r['test_locked']]
        returns = [r['test_metrics']['total_return'] for r in members]
        ret = f'{np.mean(returns):.2%} ± {np.std(returns):.2%}' if returns else '未执行'
        summary.append(f"<tr><td>{group} · {names[group]}</td><td>{stats['seeds']}</td><td>{stats['V_objective_mean']:.4f} ± {stats['V_objective_std']:.4f}</td><td>{ret}</td><td>{stats['failure_rate_mean']:.1%}</td></tr>")
    p = manifest['protocol']
    periods = ' · '.join(f'{s} {p["segments"][s][0]} 至 {p["segments"][s][1]}' for s in 'FEVT')
    seen = suite.get('holdout_status') == 'previously_observed_historical'
    label = '数据此前已查看，T 为历史比较，不是全新未接触留出集。' if seen else 'T 在模型冻结后独立执行。'
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>多年研究对照</title><style>
    body{font:15px/1.7 'Segoe UI','Microsoft YaHei',sans-serif;background:#f3f5f1;color:#233635;margin:0}header{background:#153b36;color:white;padding:30px 5vw}main{max-width:1400px;margin:auto;padding:28px}section{background:white;border:1px solid #dce3da;padding:22px;margin:20px 0;border-radius:8px;overflow:auto}h1{margin:4px 0}h2{font-size:21px}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{padding:11px;text-align:left;border-bottom:1px solid #e4e8e1}th{color:#637269;font-size:13px}a{color:#166752}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.notice{background:#fff7df;padding:18px}summary{cursor:pointer}</style>'''
    html += f'<header><small>CLOSED LOOP / MULTIYEAR RESEARCH</small><h1>500 股 · 多年研究对照</h1><p>{escape(periods)}</p></header><main><p class="notice">{label}静态 500 股样本及旧数据复权口径仍属原型假设。保留全部种子与负结果，三种子的描述统计不能证明 PPO 优于随机搜索。</p>'
    html += f'<p>每个生成组 {p["batches"]} 批 × {p["episodes_per_batch"]} 候选；每次组合搜索 Q={p["search_budget"]}。固定组只搜索一批，预算单独披露。± 为种子间总体标准差。</p>'
    html += '<section><h2>组间比较</h2><table><tr><th>方法</th><th>种子数</th><th>V 目标 J</th><th>T 区间净收益</th><th>质量失败率</th></tr>'+''.join(summary)+'</table></section>'
    html += '<section><h2>全部运行与闭环记录</h2><table><tr><th>运行 / 详细证据</th><th>候选</th><th>池提交</th><th>PPO 更新</th><th>失败率</th><th>正 / 负奖励</th><th>V J</th><th>T J</th><th>F/E 逻辑 / 实际回测</th></tr>'+''.join(run_rows)+'</table></section>'
    html += '<section><h2>冻结模型分年结果</h2><p>F/E 只展示已保存的训练内诊断，V 用于模型选择，T 用于历史比较。每段独立建仓；F 内跨年持仓连续。首末不足全年时显示区间收益，不年化冒充年度收益。回撤在所列年份重新计算。缺少相同冻结权重的开发账本时明确记录缺失，不补跑回测。</p><table><tr><th>运行</th><th>分段</th><th>年份</th><th>交易日</th><th>净收益</th><th>最大回撤</th><th>费用</th><th>滑点</th></tr>'+''.join(annual)+'</table></section>'
    html += '<section><h2>冻结表达式与可复核记录</h2>'+''.join(f'<details><summary>{e["group"]} seed {e["seed"]} · selected batch {e["selected_batch"]}</summary><pre>{escape(json.dumps(e,ensure_ascii=False,indent=2))}</pre></details>' for e in evidence)+'</section></main></html>'
    target = root/'report.html'
    atomic_bytes(target, html.encode('utf-8'))
    return target
