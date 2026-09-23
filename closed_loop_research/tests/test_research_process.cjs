const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {};
const source = path.join(__dirname, '../app/static/research-process.js');
if (fs.existsSync(source)) vm.runInNewContext(fs.readFileSync(source, 'utf8'), context);
assert.ok(context.ResearchProcess, 'readable research process renderer must exist');
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const charts=[];
const h = {
 S:{models:[]}, esc, num:x=>x==null?'—':String(x),
 btn:(t,a,d='',c='',off=false)=>`<button data-action="${a}" ${d} ${off?'disabled':''}>${t}</button>`,
 table:(heads,rows)=>`<table><thead>${heads.join('|')}</thead>${rows.join('')}</table>`,td:cells=>`<tr>${cells.map(c=>`<td>${c}</td>`).join('')}</tr>`,
 json:(t,v)=>`<details><summary>${t}</summary><pre>${esc(JSON.stringify(v))}</pre></details>`,
 notice:x=>`<p>${esc(x)}</p>`,metric:(k,v)=>`<metric>${k}: ${v}</metric>`,empty:(t,m)=>`${t} ${m||''}`,badge:x=>`<badge>${x}</badge>`,when:x=>x,
 initialPool:p=>Object.fromEntries((p.initial_expressions||[]).map((x,i)=>[x,p.initial_weights[i]])),
 activePool:w=>Object.fromEntries(Object.entries(w||{}).filter(([,v])=>v!==0)),
 poolChange:(a,b)=>JSON.stringify(a)===JSON.stringify(b)?'因子与权重均相同':'因子组成已变化',
 frozenCombination:()=>null,factorWeightsTable:w=>`<weights>${esc(JSON.stringify(w))}</weights>`,
 R:{lineChart:(p,o)=>{charts.push({p,o});return `<chart>${o.title}</chart>`;},bars:(p,o)=>{charts.push({p,o});return `<chart>${o.title}</chart>`;},pct:x=>x==null?'—':`${x*100}%`,stage:x=>x,metrics:m=>`<metrics>${JSON.stringify(m)}</metrics>`}
};
const e={status:'finished',protocol:{generator:'ppo',batches:1,initial_expressions:['a'],initial_weights:[1],selection_batches:[1,2],segments:{F:['2020','2021'],E:['2022','2023'],V:['2024','2025'],T:['2026','2027']}},
 run_status:{batch:1},pools:[{batch_id:1,weights:{a:1}}],updates:[{batch_id:1,skipped:true},{batch_id:1,parameter_l2_change:.2,episodes:3,negative_episodes:1}],
 trials:[{batch_id:1,status:'evaluated',expression:'b',candidate_used:true,reward:0,delta:0,weights:{b:1}},{batch_id:1,status:'quality_failure',expression:'<img>',reward:-1,reason:'coverage_or_degeneracy'}],
 batches:[{batch_id:1,decision:{changed:true,chosen:{source:'refit_baseline',weights:{a:1}}}}]
};
let html=context.ResearchProcess.run(e,h);
assert.match(html,/实际 PPO 更新: 1/);
assert.match(html,/负奖励: 1/);
assert.match(html,/质量失败: 1/);
assert.match(html,/试算中使用/);
assert.match(html,/未正式采纳/);
assert.match(html,/原有因子重新调权/);
assert.ok(!html.includes('<img>'));
assert.equal(charts[0].p[0].y,0,'zero reward is retained, not treated as missing');
assert.ok(!html.includes('<details open'));
const verbose=structuredClone(e);verbose.trials[0].quality={F:{passed:true,days:[{date:'DAILY-EVIDENCE-SENTINEL'}]}};
const compact=context.ResearchProcess.run(verbose,h);
assert.ok(!compact.includes('DAILY-EVIDENCE-SENTINEL'),'daily raw arrays must not inflate presentation markup');
const adopted=structuredClone(e);adopted.batches[0].decision.chosen={source:'candidate',candidate_index:0};
assert.match(context.ResearchProcess.run(adopted,h),/正式采纳新因子/);
const unknown=structuredClone(e);delete unknown.batches;
assert.match(context.ResearchProcess.run(unknown,h),/未记录采纳决策/);
html=context.ResearchProcess.validation(e,h);
assert.match(html,/最终测试尚未运行/);
assert.ok(!html.includes('<metrics>'),'no fabricated T metrics');
const v={...e,model_version:'opaque-model',selection:{rule:'max_V_J_earliest_tie_no_refit',frozen_model_id:'opaque-freeze',checkpoints:[{batch_id:2,objective:.3,weights:{b:1},artifact_id:'v2'},{batch_id:1,objective:.3,weights:{a:1},artifact_id:'v1'}]},test:{artifact_id:'t1',metrics:{total_return:0}}};
html=context.ResearchProcess.validation(v,h);
assert.match(html,/第 1 批/);
assert.match(html,/并列时选择最早批次/);
assert.match(html,/不是收益率/);
assert.match(html,/data-id="t1"/);
assert.match(html,/<metrics>/);
const bars=charts.filter(c=>c.o.title.includes('验证')).at(-1);
assert.equal(bars.p.find(x=>x.selected).label,'第 1 批');
const unrecognized=structuredClone(v);unrecognized.selection.rule='unknown';
assert.match(context.ResearchProcess.validation(unrecognized,h),/选择规则尚未识别/);
console.log('Research process presentation tests passed');
