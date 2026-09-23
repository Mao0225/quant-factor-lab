"""Self-contained, read-only research workbench backed exclusively by run artifacts."""
from html import escape
import json
from pathlib import Path

from .storage import read_json, atomic_bytes
from .runner import load_state


def _j(value):
    return escape(json.dumps(value, ensure_ascii=False, indent=2))


def _num(value):
    return "—" if value is None else f"{value:.5f}"


def _curve(series):
    if not series:
        return "<p>尚无回测曲线</p>"
    all_values = [r["nav"] for _, rows in series for r in rows]
    lo, hi = min(all_values), max(all_values)
    span = hi-lo or 1
    colors = ["#13685d", "#af7342"]
    paths = []
    for i, (label, rows) in enumerate(series):
        points = " ".join(f"{30+j*850/max(1,len(rows)-1):.1f},{210-(r['nav']-lo)/span*175:.1f}" for j, r in enumerate(rows))
        paths.append(f'<polyline fill="none" stroke="{colors[i%2]}" stroke-width="2.5" points="{points}"/><text x="{30+i*260}" y="245" fill="{colors[i%2]}">{escape(label)}</text>')
    return '<svg viewBox="0 0 920 265" role="img" aria-label="E 段独立建仓净值曲线">'+''.join(paths)+'</svg>'


def build_report(run_root):
    root = Path(run_root)
    state = load_state(root)["state"]
    p, experiment = read_json(root / "protocol.json"), read_json(root / "experiment.json")
    test = read_json(root / "test_result.json") if (root / "test_result.json").exists() else None
    selection = read_json(root / "selection.json") if (root / "selection.json").exists() else None
    rows, cards, histories = [], [], []
    for batch in state["completed"]:
        update = batch["ppo_update"]
        cards.append(f'<tr><td>{batch["batch_id"]}</td><td>v{batch["loaded_pool_version"]} → v{batch["next_pool_version"]}</td><td>{_num(update.get("parameter_l2_change"))}</td><td>{"提交" if batch["decision"]["changed"] else "保留"}</td><td>{escape(batch["decision"]["reason"])}</td></tr>')
        for i, trial in enumerate(batch["trials"]):
            reward = trial["reward"]
            css = "negative" if reward < 0 else "positive" if reward > 0 else "muted"
            evidence = dict(candidate=trial, ppo_update=update, pool_decision=batch["decision"])
            rows.append(f'<tr><td>{batch["batch_id"]}.{i+1}</td><td><code>{escape(trial["expression"])}</code></td><td>{escape(trial["status"])}</td><td>{_num(trial.get("delta"))}</td><td class="{css}">{reward:.5f}</td><td>{"是" if trial["candidate_used"] else "否"}</td><td><details><summary>证据链</summary><pre>{_j(evidence)}</pre></details></td></tr>')
        histories.append(batch)
    last, baseline, curves = None, None, []
    if state["completed"]:
        b = state["completed"][-1]
        choice_id = b["decision"]["chosen"]["artifact_id"]
        base_id = b["summary"]["baseline_e"]["artifact_id"]
        last = read_json(root / "backtests" / f"{choice_id}.json")["result"]
        baseline = read_json(root / "backtests" / f"{base_id}.json")["result"]
        curves = [("当前组合 · E", last["daily"]), ("配对基线 · E", baseline["daily"])]
    weights = ''.join(f'<tr><td><code>{escape(k)}</code></td><td>{v:.6f}</td></tr>' for k, v in sorted(state["pool"].items()))
    budget = state["budget"]
    total = sum(len(b["trials"]) for b in state["completed"])
    negative = sum(t["reward"] < 0 for b in state["completed"] for t in b["trials"])
    mode = "旧 500 股数据 · 原型实验" if p["data_mode"] == "legacy_prototype" else "合成机制验证" if p["synthetic"] else "已核验数据实验"
    test_label = "最终测试已执行" if test else "最终测试尚未解锁"
    if p.get('holdout_status') == 'previously_observed_historical':
        test_label = '2026 历史比较已执行 · 数据此前已查看' if test else '2026 历史比较待执行 · 数据此前已查看'
    selections_json = json.dumps(last or {}, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = """<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>闭环研究 · 原型工作区</title><style>
    :root{font-family:'Segoe UI','Microsoft YaHei',sans-serif;color:#233635;background:#f3f5f1;font-size:14px}*{box-sizing:border-box}body{margin:0}header{padding:30px 4vw 24px;background:#153b36;color:#f4f5ec}h1{font-size:28px;margin:10px 0;font-weight:600}h2{font-size:20px;font-weight:600}h3{font-size:15px}p{line-height:1.7}.eyebrow{color:#acd5c4;letter-spacing:2px;font-size:12px}.subtitle{color:#c2d2cb}.tag{display:inline-block;padding:5px 9px;border:1px solid #81988d;border-radius:4px;font-size:12px}nav{display:flex;gap:8px;flex-wrap:wrap;padding:18px 4vw;background:white;border-bottom:1px solid #dce3da;position:sticky;top:0;z-index:2}button,select{font:inherit;background:white;color:#28443d;border:1px solid #cbd7ce;border-radius:5px;padding:9px 15px;cursor:pointer}button.active{background:#155d50;color:white}button:focus-visible,summary:focus-visible,select:focus-visible{outline:3px solid #ba7a31;outline-offset:3px}main{max-width:1500px;margin:auto;padding:25px 4vw}section{display:none}section.active{display:block}.cards{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:16px}.card,.panel{background:white;border:1px solid #dde3d9;border-radius:8px;padding:22px;margin-bottom:22px}.card b{display:block;font-size:29px;margin-top:12px;font-weight:500}.muted{color:#71817a}.negative{color:#a23737}.positive{color:#12634c}.grid{display:grid;grid-template-columns:2fr 1fr;gap:20px}.notice{border-left:4px solid #b2803c;background:#fcf9ee;padding:15px 20px;margin-bottom:22px}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left}td,th{border-bottom:1px solid #e5ebe3;padding:12px 9px;vertical-align:top}th{font-size:12px;color:#6b7b71}code{font-family:Consolas,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;max-height:550px;overflow:auto;background:#f4f7f2;padding:15px;min-width:260px}summary{cursor:pointer;color:#176858}svg{width:100%;font-size:13px}small{line-height:1.6}footer{padding:20px 4vw;color:#78887c;font-size:12px}@media(max-width:850px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}header{padding:22px}main{padding:18px}.panel{padding:16px}}
    </style></head><body>"""
    html += f'<header><div class="eyebrow">CLOSED LOOP / RESEARCH KERNEL 01</div><h1>因子生成与组合反馈</h1><div class="subtitle">{escape(p["name"])} · {escape(mode)} · 只读研究工作区</div><p><span class="tag">{test_label}</span> <span class="tag">池版本 v{state["pool_version"]}</span> <span class="tag">{escape(state["phase"])}</span></p></header>'
    tabs = [("overview", "研究概览"), ("protocol", "协议与数据"), ("trials", "迭代记录"), ("portfolio", "当前组合与选股"), ("validation", "验证报告")]
    html += '<nav aria-label="研究页签">'+''.join(f'<button type="button" data-tab="{key}" class="{"active" if i==0 else ""}" aria-pressed="{"true" if i==0 else "false"}">{label}</button>' for i, (key, label) in enumerate(tabs))+'</nav><main>'
    html += '<section id="overview" class="active"><div class="cards">'
    for label, value, foot in [("已完成批次", f'{state["batch"]} / {p["batches"]}', "完整表达式后更新"), ("候选表达式", total, f"其中 {negative} 个负奖励"), ("PPO 更新", state["ppo_updates"], "实际参数变化见下表"), ("实际交易回测", budget["actual_f"]+budget["actual_e"], f'逻辑预算 F {budget["logical_f"]} / E {budget["logical_e"]}')]:
        html += f'<div class="card"><span class="muted">{label}</span><b>{value}</b><small class="muted">{foot}</small></div>'
    html += f'</div><div class="notice">本页显示真实运行记录。E 段参与奖励和池提交，属于开发数据。原型结果用于核验程序闭环；不代表方法已验证有效。</div><div class="panel"><h2>配对净值 · 反馈段 E</h2>{_curve(curves)}</div><div class="panel"><h2>批次与更新证据</h2><div class="tablewrap"><table><thead><tr><th>批次</th><th>实际加载 → 下一批</th><th>参数 L2 变化</th><th>池决定</th><th>原因</th></tr></thead><tbody>{"".join(cards)}</tbody></table></div></div></section>'
    bounds = ''.join(f'<tr><td>{s}</td><td>{p["segments"][s][0]}</td><td>{p["segments"][s][1]}</td><td>{dict(F="仅组合拟合", E="奖励与池提交", V="预登记模型选择", T="冻结后独立执行")[s]}</td></tr>' for s in "FEVT")
    html += f'<section id="protocol"><div class="panel"><h2>固定研究协议</h2><p>Top {p["top_k"]} · 下一交易日开盘 · 股票等权 · 只做多 · 不足 K 留现金</p><table><tr><th>区间</th><th>起始</th><th>结束</th><th>用途</th></tr>{bounds}</table><h3>数据和执行假设</h3><p>{escape(p["universe_note"])}</p><p>{escape(p["execution_note"])}</p><details><summary>完整锁定协议</summary><pre>{_j(p)}</pre></details><details><summary>实验身份与运行环境</summary><pre>{_j(experiment)}</pre></details></div></section>'
    html += f'<section id="trials"><div class="panel"><h2>每个候选只获得一次终止奖励</h2><p class="muted">展开证据链可查看 F 搜索的每次提案、配对 E 回测、原始增量、PPO 更新和池决定。</p><div class="tablewrap"><table><thead><tr><th>编号</th><th>表达式</th><th>质量状态</th><th>Δ</th><th>奖励</th><th>候选被用</th><th>详情</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div></section>'
    html += f'<section id="portfolio"><div class="grid"><div class="panel"><h2>当前评分组合</h2><table><tr><th>因子</th><th>评分权重</th></tr>{weights}</table><p class="muted">权重绝对值和为 1；负评分权重不代表做空股票。</p></div><div class="panel"><h2>开发段选股核验</h2><label for="date">E 段执行日期</label><p><select id="date"></select></p><div id="day-summary"></div></div></div><div class="panel"><h2>Top K 名单与实际持仓</h2><p class="muted">选择日期查看实际名单、分数、持仓股数和现金。未成交不自动替补。</p><div class="tablewrap"><table><thead><tr><th>证券代码</th><th>Top K 排名</th><th>信号分数</th><th>实际股数</th><th>实际权重</th></tr></thead><tbody id="holdings"></tbody></table></div></div></section>'
    html += f'<section id="validation"><div class="panel"><h2>{test_label}</h2><p>V 只在预登记检查点间选择，冻结已有 F 拟合权重；T 通过单独命令执行一次，重复调用读取原结果。</p>'
    if selection: html += f'<details><summary>V 选择记录</summary><pre>{_j(selection)}</pre></details>'
    if test: html += f'<details open><summary>T 独立测试记录（原型口径）</summary><pre>{_j(test)}</pre></details>'
    html += f'<details><summary>训练数据访问审计</summary><pre>{_j(state["data_audit"])}</pre></details><details><summary>预算与参数指纹</summary><pre>{_j({"budget": budget,"parameter_digest":state["parameter_digest"]})}</pre></details><p class="muted">此页面不读取行情分区或重新运行评价。企业使用端不在本版范围内。</p></div></section></main><footer>Closed Loop Research · 所有显示来自当前实验的持久化证据</footer>'
    html += '<script>const artifact='+selections_json+""";
    document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('section').forEach(s=>s.classList.toggle('active',s.id===b.dataset.tab));document.querySelectorAll('[data-tab]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b))})}));
    const select=document.getElementById('date');(artifact.selections||[]).forEach(s=>{let o=document.createElement('option');o.value=s.date;o.textContent=s.date;select.appendChild(o)});
    function show(){let s=(artifact.selections||[]).find(s=>s.date===select.value);if(!s)return;let d=artifact.daily.find(d=>d.date===s.date);let positions=artifact.positions.filter(p=>p.date===s.date);document.getElementById('day-summary').textContent='信号 '+s.signal_date+' · 现金 '+d.cash.toFixed(2)+' · 持仓 '+d.holding_count;let body=document.getElementById('holdings');body.replaceChildren();let codes=[...new Set([...s.codes,...positions.map(p=>p.code)])];codes.forEach(c=>{let i=s.codes.indexOf(c),p=positions.find(p=>p.code===c),tr=document.createElement('tr');[c,i<0?'未在名单':i+1,i<0?'—':s.scores[i].toFixed(5),p?p.shares:0,p?(p.weight*100).toFixed(2)+'%':'0%'].forEach(v=>{let td=document.createElement('td');td.textContent=v;tr.appendChild(td)});body.appendChild(tr)})};select.addEventListener('change',show);if(select.options.length){select.selectedIndex=select.options.length-1;show()}
    </script></body></html>"""
    target = root / "report.html"
    atomic_bytes(target, html.encode("utf-8"))
    return target
