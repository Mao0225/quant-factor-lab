/* Read-only research presentation. All decisions and metrics come from saved evidence. */
(() => {
 'use strict';
 const list = x => Array.isArray(x) ? x : [];
 const finite = x => typeof x === 'number' && Number.isFinite(x);
 const sourceNames = {incumbent:'保留原组合',refit_baseline:'原有因子重新调权',candidate:'正式采纳新因子',old_factors_refit:'采纳候选试算中的原有因子调权'};
 const searchNames = {initial:'初始权重',sign_flip:'整体反转方向',coordinate:'调整单个权重',disable:'移除一个因子',replace:'替换因子位置',perturb:'小幅扰动权重',restart:'重新选择搜索起点'};
 const reasons = {coverage_or_degeneracy:'覆盖不足，或因子在过多日期无法区分股票','all-zero proposal':'全部权重为零，无法形成组合','no valid proposal in F budget':'本次搜索预算内没有有效组合',improvement_over_incumbent:'扣除复杂度代价后，评价优于原组合',below_threshold:'改善未超过预设门槛',no_improvement:'未优于原组合'};
 const card = (title, body, actions='') => `<section class="card research-process"><div class="card-head"><h3>${title}</h3>${actions?`<div class="actions">${actions}</div>`:''}</div><div class="card-body">${body}</div></section>`;
 const pill = (text, kind='') => `<span class="pill ${kind}">${text}</span>`;
 function artifact(id,label,h){return id?h.btn(label,'inspect-backtest',`data-id="${h.esc(id)}"`,'link'):'<span class="subtle">未记录回测</span>';}
 function fmt(x,h){return finite(x)?h.num(x,6):'未记录';}
 function reasonText(reason){return reasons[reason] || (reason ? '检查未通过；具体错误见高级原始证据' : '未记录具体原因');}
 function adoption(trial,index,batch){
  if(typeof trial.adopted==='boolean')return trial.adopted?'正式采纳新因子':'未正式采纳';
  const decision=batch?.decision;
  if(!decision)return '未记录采纳决策';
  if(!decision.changed)return '未正式采纳';
  const chosen=decision.chosen||{};
  if(chosen.candidate_index!==index)return '未正式采纳';
  return chosen.source==='candidate'?'正式采纳新因子':chosen.source==='old_factors_refit'?'仅采纳原有因子调权':'未正式采纳';
 }
 function trialStatus(t,h){
  if(t.status==='quality_failure')return pill('质量失败','red');
  if(t.status==='duplicate')return pill('重复公式');
  if(t.status==='evaluated')return pill('已完成评价','blue');
  return pill(h.esc(t.status?'其他状态 · 见详情':'尚未评价'));
 }
 function qualityTable(quality,h){
  const rows=Object.entries(quality||{}).map(([segment,q])=>h.td([h.esc(h.R.stage(segment)),q.passed===true?'通过':q.passed===false?'不通过':'未记录',h.R.pct(q.low_coverage_fraction),h.R.pct(q.degenerate_fraction)]));
  return rows.length?h.table(['检查区间','质量结论','覆盖不足的日期占比','无法区分股票的日期占比'],rows):'<p class="subtle">未记录质量检查明细。</p>';
 }
 function searchTable(search,h){
  const trials=list(search?.trials);
  if(!trials.length)return '<p class="subtle">此候选未记录组合搜索步骤。</p>';
  return `<p class="subtle">下列步骤只在权重拟合区间（F）挑选试算权重。“保留”只表示成为当时的搜索最优，不代表正式因子池已经采纳。</p>${h.table(['步骤','尝试内容','F 评价分数','搜索决定','原因与回测'],trials.map((r,i)=>h.td([i+1,h.esc(searchNames[r.action]||'其他搜索动作'),fmt(r.objective,h),r.accepted?'保留为当前最优':'沿用此前最优',`${r.reason?h.esc(reasonText(r.reason)):r.accepted?(i===0?'建立有效起点':'评价优于此前最优'):'未优于此前最优'}<br>${artifact(r.artifact_id,'查看该步骤回测',h)}`])))}`;
 }
 function trialDetail(t,h){
  const evidence={...t,quality:Object.fromEntries(Object.entries(t.quality||{}).map(([key,value])=>[key,Object.fromEntries(Object.entries(value).filter(([k])=>k!=='days'))])),search:t.search?{artifact_id:t.search.artifact_id,objective:t.search.objective,weights:t.search.weights}:undefined};
  const explanation=t.status==='duplicate'?'公式已在当前组合中，不作为新因子重复计奖。':t.status==='quality_failure'?reasonText(t.reason):t.candidate_used===false?'搜索后的试算组合没有给新因子非零权重；它不因此获得新增因子的交易增量奖励。':t.candidate_used===true?'新因子在试算组合中获得了非零权重。是否进入下一批正式组合，仍由本批评价决策决定。':'未记录新因子在试算组合中是否被使用。';
  return `<details class="rp-detail"><summary>查看评价依据与搜索过程</summary><p>${h.esc(explanation)}</p><div class="metric-row">${h.metric('基准组合 E 分数',fmt(t.baseline_objective,h))}${h.metric('候选组合 E 分数',fmt(t.candidate_objective,h))}${h.metric('记录的有效增量',fmt(t.delta,h))}${h.metric('训练奖励',fmt(t.reward,h))}</div><p class="subtle">分数和奖励均不是收益率；负奖励保留供训练使用，不等于程序出错。</p><div class="actions">${artifact(t.baseline_artifact,'查看基准组合回测',h)}${artifact(t.candidate_artifact,'查看候选组合回测',h)}</div><h4>因子质量</h4>${qualityTable(t.quality,h)}${t.weights?`<h4>本次试算组合</h4>${h.factorWeightsTable(t.weights)}`:''}<details><summary>权重拟合区间（F）的搜索步骤</summary>${searchTable(t.search,h)}</details>${h.json('高级原始证据摘要 · 本次候选',evidence)}</details>`;
 }
 function run(e,h){
  const p=e.protocol||{},rs=e.run_status||{},trials=list(e.trials),pools=list(e.pools),updates=list(e.updates),batches=list(e.batches),activeUpdates=updates.filter(u=>!u.skipped);
  const done=rs.completed_batches??rs.batch??0,total=p.batches,negative=trials.filter(t=>finite(t.reward)&&t.reward<0).length,failed=trials.filter(t=>t.status==='quality_failure').length;
  const running=['running','preparing','queued','pause_requested','stop_requested'].includes(e.status);
  const actions=h.btn('启动实验','experiment-action','data-op="start"','primary',e.status!=='draft')+h.btn('检查点暂停','experiment-action','data-op="pause"','',!running)+h.btn('恢复','experiment-action','data-op="resume"','',!['paused','interrupted','failed'].includes(e.status))+h.btn('停止','experiment-action','data-op="stop"','danger',!running&&!['paused','interrupted','failed'].includes(e.status));
  let previous=h.initialPool(p),changes=0;
  const rows=pools.map(pool=>{const changed=h.poolChange(previous,pool.weights)!=='因子与权重均相同';if(changed)changes++;previous=pool.weights;return pool;});
  const progress=finite(done)&&finite(total)&&total>0?Math.min(100,Math.max(0,done/total*100)):0;
  let html=card('研究运行进度',`${h.badge(e.status)}<div class="metric-row">${h.metric('批次进度',`${done} / ${total??'未登记'}`)}${h.metric('候选尝试',trials.length)}${h.metric('正式组合变化',changes)}${h.metric('实际 PPO 更新',activeUpdates.length)}</div><div class="progress" role="progressbar" aria-label="已完成批次" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100"><span style="width:${progress}%"></span></div><p class="subtle">每批先试算候选，再决定下一批采用的组合。暂停和停止会在完整批次检查点生效。</p>${e.error?h.notice(e.error,'error'):''}`,actions);
  const rewardPoints=trials.map((t,i)=>({x:`候选 ${i+1}`,y:t.reward})).filter(x=>finite(x.y));
  html+=card('候选反馈一览',`<div class="metric-row">${h.metric('正奖励',trials.filter(t=>finite(t.reward)&&t.reward>0).length)}${h.metric('零奖励',trials.filter(t=>t.reward===0).length)}${h.metric('负奖励',negative)}${h.metric('质量失败',failed)}</div>${rewardPoints.length?h.R.lineChart(rewardPoints,{title:'候选奖励轨迹',format:'number'}):h.empty('尚无候选奖励',p.generator==='fixed'?'本实验是固定因子基准，不生成新候选。':'候选完成评价后会显示在这里。')}<p class="subtle">质量失败可产生负奖励，因此上述类别有重叠。奖励衡量本次训练反馈，不能直接解释为投资收益。</p>`);
  const ids=[...new Set([...rows.map(x=>x.batch_id),...trials.map(x=>x.batch_id),...batches.map(x=>x.batch_id)])].sort((a,b)=>a-b);
  previous=h.initialPool(p);
  html+=card('每一批做了什么',ids.length?`<div class="rp-batches">${ids.map(id=>{
   const batch=batches.find(b=>b.batch_id===id),pool=rows.find(x=>x.batch_id===id),items=trials.filter(t=>t.batch_id===id),d=batch?.decision,chosen=d?.chosen,change=pool?h.poolChange(previous,pool.weights):'尚未记录批次组合';
   if(pool)previous=pool.weights;
   const decision=d?(d.changed?(sourceNames[chosen?.source]||'已更新组合'):'保留原组合'):'未记录采纳决策';
   const count=pool?Object.keys(h.activePool(pool.weights)).length:null;
   return `<article class="rp-batch"><div class="rp-batch-heading"><div><span class="rp-step">${h.esc(id)}</span><strong>第 ${h.esc(id)} 批</strong></div>${pill(h.esc(decision),d?.changed?'blue':'')}</div><p>${items.length} 次候选尝试 · ${count===null?'组合尚未提交':`${count} 个实际因子`} · ${h.esc(change)}</p>${d?`<p class="subtle">${d.changed?'评价后选出的组合超过原组合及预设改善门槛。':'本批没有组合超过原组合及预设改善门槛。'}${finite(d.threshold)?`门槛：${h.num(d.threshold,10)}。`:''}</p><div class="actions">${artifact(chosen?.artifact_id,'查看本批采用的组合回测',h)}</div>`:''}${items.length?h.table(['候选公式','评价状态','训练奖励','试算使用 / 正式采纳','查看依据'],items.map((t,i)=>h.td([`<code class="factor-expression">${h.esc(t.expression||'未记录公式')}</code>`,trialStatus(t,h),fmt(t.reward,h),`${t.candidate_used===true?'试算中使用':t.candidate_used===false?'试算未使用':'试算使用情况未记录'}<br>${h.esc(adoption(t,i,batch))}`,trialDetail(t,h)]))):h.empty('本批无新候选','固定基准可以只评价原有组合。')}${pool?`<details><summary>查看本批正式组合的 ${count} 个因子</summary>${h.factorWeightsTable(pool.weights)}</details>`:''}</article>`;
  }).join('')}</div>`:h.empty('尚未完成第一批','启动后这里会说明每批尝试了什么、最后采用了什么。'));
  html+=card('PPO 学到了什么',updates.length?`<p class="subtle">参数发生变化只代表训练执行过。策略是否更好，需要结合候选、正式组合和验证结果判断。</p>${h.table(['批次','更新状态','训练候选数','负奖励候选数','参数变化幅度','训练过程'],updates.map(u=>h.td([`第 ${h.esc(u.batch_id)} 批`,u.skipped?'未执行 · 本方法不训练 PPO':'已执行',u.skipped?'—':h.num(u.episodes),u.skipped?'—':h.num(u.negative_episodes),u.skipped?'—':fmt(u.parameter_l2_change,h),u.skipped?'固定或随机方法不更新生成器':`<details><summary>查看各轮训练损失</summary><p class="subtle">损失值用于检查训练过程，不是回测收益或模型评分。</p>${h.table(['训练轮次','总损失','策略损失','价值损失','探索熵'],list(u.losses).map((l,i)=>h.td([i+1,fmt(l.loss,h),fmt(l.policy_loss,h),fmt(l.value_loss,h),fmt(l.entropy,h)])))}</details>`])))}`:h.empty('尚无 PPO 更新记录',p.generator!=='ppo'?'本方法不使用 PPO 训练。':'候选完成后才会更新生成器。'));
  html+=card('运行资源与留档',`<div class="metric-row">${h.metric('实际执行回测',rs.budget?.completed_backtests??'未记录')}${h.metric('复用已有结果',rs.budget?.cache_hits??'未记录')}${h.metric('累计运行秒数',fmt(rs.budget?.wall_seconds,h))}</div>${h.json('高级原始证据 · 运行检查点与决策',{run_status:rs,batches:batches.map(b=>({batch_id:b.batch_id,decision:b.decision})),updates})}`);
  return html;
 }
 function validation(e,h){
  const p=e.protocol||{},selection=e.selection,checkpoints=list(selection?.checkpoints),knownRule=selection?.rule==='max_V_J_earliest_tie_no_refit';
  const valid=checkpoints.filter(c=>finite(c.objective));
  const selected=knownRule&&selection?.frozen_model_id?valid.reduce((best,c)=>!best||c.objective>best.objective||(c.objective===best.objective&&c.batch_id<best.batch_id)?c:best,null):null;
  const names={F:'寻找组合权重',E:'评价候选与反馈',V:'选择并冻结模型',T:'检验冻结模型'};
  const descriptions={F:'搜索因子的取舍与权重。',E:'给候选奖励，并决定下一批保留什么组合。',V:'比较预先登记的批次组合，不重新调权。',T:'模型冻结后单独执行，不用于挑选模型。'};
  const done=Number(e.run_status?.batch)>0;
  let html=card('验证流程与数据分工',`<div class="rp-stages">${['F','E','V','T'].map(code=>{const dates=p.segments?.[code],status=code==='T'?(e.test?'已完成':'尚未运行'):code==='V'?(selection?'已记录验证':'等待开发结束'):(done?'已有运行记录':'尚未完成首批');return `<article class="rp-stage"><span class="rp-stage-code">${code}</span><h4>${names[code]}</h4><p>${descriptions[code]}</p><p class="rp-dates">${dates?h.esc(dates.join(' → ')):'日期未登记'}</p>${pill(status,(code==='T'?e.test:code==='V'?selection:done)?'blue':'')}</article>`;}).join('')}</div>`);
  let vbody=`<p class="subtle">验证评价分数越高越好；它是考虑风险后的年化对数收益目标，不是收益率。风险惩罚系数为 ${h.num(p.risk_lambda)}。只比较实验开始前登记的批次。</p>`;
  if(!selection)vbody+=h.empty('尚未进行模型选择','开发批次完成后，系统才比较已登记的验证检查点。');
  else {
   vbody+=knownRule?(selected?h.notice(`已冻结第 ${selected.batch_id} 批组合：验证评价分数最高，并列时选择最早批次；选中后保持原权重，不重新拟合。`):h.notice('记录了验证规则，但缺少完整冻结证据，暂不判断选中批次。','warning')):h.notice('选择规则尚未识别；保留原始证据，暂不推断选中批次。','warning');
   vbody+=valid.length?h.R.bars(valid.map(c=>({label:`第 ${c.batch_id} 批`,value:c.objective,selected:c===selected})),{title:'各批次验证评价分数',format:'number'}):h.empty('未记录有效验证分数');
   vbody+=checkpoints.length?h.table(['批次','实际因子数','验证评价分数','选择结果','查看回测'],checkpoints.map(c=>h.td([`第 ${h.esc(c.batch_id)} 批`,c.weights?Object.keys(h.activePool(c.weights)).length:'未记录',fmt(c.objective,h),selected?(c===selected?pill('已选择并冻结','blue'):c.objective===selected.objective?'分数并列，选择更早批次':'未选中'):'未确定',artifact(c.artifact_id,'查看此批验证回测',h)]))):'';
   if(selected)vbody+=`<details><summary>查看冻结组合的因子与权重</summary>${h.factorWeightsTable(selected.weights)}</details>`;
  }
  html+=card('验证区间（V）· 为什么选择这个模型',vbody);
  const actions=h.btn('启动多种子对照','new-comparison')+h.btn('运行冻结模型 T 测试','experiment-action','data-op="test"','primary',!e.model_version||!!e.test||!!h.S.testPending);
  html+=card('最终测试（T）· 冻结以后表现如何',e.test?`${h.notice(p.holdout_status==='previously_observed_historical'?'本次使用此前已观察过的历史区间，属于历史诊断，不能称为全新留出检验。':'以下为已保存的最终测试结果。')}${e.test.metrics?h.R.metrics(e.test.metrics):h.empty('未记录最终测试指标','有测试记录，但没有可展示的指标。')}<div class="actions">${artifact(e.test.artifact_id,'查看最终测试净值与交易明细',h)}</div>`:h.empty('最终测试尚未运行',e.model_version?'模型已冻结，可通过上方按钮单独执行最终测试。':'需要先完成开发与验证选择，冻结模型后才能运行。'),actions);
  const constraints=[];
  if(p.synthetic)constraints.push('使用合成数据，适合检查流程，不代表真实市场效果。');
  if(p.data_mode==='legacy_prototype')constraints.push('当前为历史数据原型口径；结果用于研究诊断。');
  if(p.holdout_status==='previously_observed_historical')constraints.push('历史测试区间此前已被观察，不作为全新的未见数据。');
  const execution=p.execution_note||'',universe=p.universe_note||'';
  if(/adjustment and corporate actions unverified/i.test(execution))constraints.push('原始价格的复权和公司行动尚未核验，没有额外推算分红或拆股。');
  if(/no intraday liquidity or limit execution model/i.test(execution))constraints.push('开盘成交可用性依赖日线与停牌标记，尚未模拟盘中流动性和涨跌停成交约束。');
  if(/no delisting settlement/i.test(execution))constraints.push('尚未处理退市清算；缺失估值只沿用过去可获得的收盘价。');
  if(/selection bias unresolved/i.test(universe)||/static 500-stock/i.test(execution))constraints.push('固定股票样本的选择偏差尚未解决，不能直接代表全市场。');
  if(!constraints.length)constraints.push('未记录可识别的数据或执行约束说明，请查看高级原始证据。');
  html+=card('这份报告的适用范围',`<ul class="rp-constraints">${constraints.map(x=>`<li>${h.esc(x)}</li>`).join('')}</ul><p class="subtle">上述信息解释本实验的验证边界；训练参数和历史记录保持原样。</p>${h.json('高级原始证据 · 数据约束、验证与测试',{data_mode:p.data_mode,holdout_status:p.holdout_status,universe:p.universe_note,execution:p.execution_note,selection,test:e.test})}`);
  return html;
 }
 globalThis.ResearchProcess={run,validation};
})();
