/* Read-only research charts. Values come from persisted evidence, never estimates. */
globalThis.ResearchUI = (() => {
  const escape = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
  const format = (v, kind='number') => !finite(v)?'未记录':kind==='percent'?`${(Number(v)*100).toLocaleString('zh-CN',{maximumFractionDigits:2})}%`:Number(v).toLocaleString('zh-CN',{maximumFractionDigits:kind==='money'?2:5});
  const stage = code => ({F:'训练期 · 搜索组合',E:'反馈期 · 检验改进',V:'验证期 · 选择模型',T:'测试期 · 冻结后检验'}[code]||'研究记录');
  function lineChart(points,options={}) {
    const rows=points.filter(p=>finite(p.y));
    if(!rows.length)return '<div class="research-no-chart">暂无可绘制的记录</div>';
    let low=Math.min(...rows.map(p=>Number(p.y))),high=Math.max(...rows.map(p=>Number(p.y)));
    if(finite(options.baseline)){low=Math.min(low,Number(options.baseline));high=Math.max(high,Number(options.baseline));}
    const pad=(high-low||Math.max(Math.abs(high)*.05,.01))*.09;low-=pad;high+=pad;
    const x=i=>76+i*744/Math.max(1,rows.length-1),y=v=>210-(Number(v)-low)/(high-low)*182;
    const coords=rows.map((p,i)=>`${x(i)},${y(p.y)}`).join(' '),color=options.color||'#246ee9';
    const ticks=Array.from({length:5},(_,i)=>low+(high-low)*i/4);
    const grid=ticks.map(v=>`<line x1="76" x2="820" y1="${y(v)}" y2="${y(v)}" class="research-chart-grid"/><text x="65" y="${y(v)+4}" text-anchor="end">${escape(format(v,options.format))}</text>`).join('');
    const indices=[...new Set([0,Math.floor((rows.length-1)/2),rows.length-1])];
    const dates=indices.map(i=>`<text x="${x(i)}" y="237" text-anchor="${i===0?'start':i===rows.length-1?'end':'middle'}">${escape(rows[i].x)}</text>`).join('');
    return `<figure class="research-figure"><figcaption>${escape(options.title||'实际记录曲线')}</figcaption><svg viewBox="0 0 850 252" role="img" aria-label="${escape(options.title||'实际记录曲线')}，${escape(rows[0].x)}至${escape(rows.at(-1).x)}"><title>${escape(options.title)}；共${rows.length}个点，最低${escape(format(Math.min(...rows.map(p=>Number(p.y))),options.format))}，最高${escape(format(Math.max(...rows.map(p=>Number(p.y))),options.format))}</title>${grid}${finite(options.baseline)?`<line x1="76" x2="820" y1="${y(options.baseline)}" y2="${y(options.baseline)}" stroke="#91a4bf" stroke-dasharray="5 5"/>`:''}<polyline points="${coords}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round"/>${rows.map((p,i)=>`<circle cx="${x(i)}" cy="${y(p.y)}" r="5" fill="${color}" fill-opacity="0" class="research-chart-point"><title>${escape(p.x)}：${escape(format(p.y,options.format))}</title></circle>`).join('')}${dates}</svg><p class="chart-label">${rows.length}个实际记录点 · 指向曲线查看数值${options.note?' · '+escape(options.note):''}</p></figure>`;
  }
  function bars(items,options={}) {
    const rows=items.filter(x=>finite(x.value));
    if(!rows.length)return '<div class="research-no-chart">暂无可比较的记录</div>';
    const low=Math.min(0,...rows.map(x=>Number(x.value))),high=Math.max(0,...rows.map(x=>Number(x.value))),span=high-low||1,zero=-low/span*100;
    return `<figure class="research-bars"><figcaption>${escape(options.title||'记录对比')}</figcaption>${rows.map(x=>{const pos=(Number(x.value)-low)/span*100;return `<div class="research-bar-row ${x.selected?'chosen':''}"><span class="research-bar-label">${escape(x.label)}${x.selected?' · 已选中':''}</span><div class="research-bar-track"><i class="research-bar-zero" style="left:${zero}%"></i><i class="research-bar-fill ${Number(x.value)<0?'negative':''}" style="left:${Math.min(zero,pos)}%;width:${Math.max(.25,Math.abs(pos-zero))}%"></i></div><strong>${escape(format(x.value,options.format))}</strong></div>`;}).join('')}</figure>`;
  }
  function metrics(m={}) {
    const keys=[['累计净收益','total_return','percent'],['最大回撤','max_drawdown','percent'],['年化收益','annual_return','percent'],['年化波动','annual_volatility','percent'],['手续费合计','total_fees','money'],['滑点成本','total_slippage','money']];
    return `<div class="research-metrics">${keys.map(([label,key,kind])=>`<div><span>${label}</span><strong class="${finite(m[key])&&Number(m[key])<0?'negative-text':''}">${escape(format(m[key],kind))}</strong></div>`).join('')}</div>`;
  }
  function monthly(daily) {
    const groups=new Map();
    for(const d of daily){if(!finite(d.net_return))continue;const key=String(d.date).slice(0,7);groups.set(key,(groups.get(key)??1)*(1+Number(d.net_return)));}
    return [...groups].map(([label,value])=>({label,value:value-1}));
  }
  return {lineChart,bars,metrics,monthly,stage,pct:v=>format(v,'percent'),format,finite};
})();
