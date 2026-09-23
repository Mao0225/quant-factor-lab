// Regression: submitting while the last numeric field is being edited must
// capture the visible inputs, even if its change event has not fired yet.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/static/app.js'),'utf8');
const fn=source.match(/function captureConfig\(\)[\s\S]*?(?=\nasync function savePlan)/)[0];
const fields=[
 {dataset:{filter:'listing_days',bound:'min'},value:'365',disabled:false},
 {dataset:{filter:'turnover',bound:'max'},value:'3',disabled:false},
 {dataset:{filter:'amount',bound:'min'},value:'999',disabled:true},
 {dataset:{filter:'turnover',bound:'min'},value:'',disabled:false}
];
const S={config:{model_version:'frozen-version',dataset_id:'snapshot',filters:{turnover:{min:99}},top_n:50}};
const ctx={S,$:q=>q==='#top-n'?{value:'10'}:null,$$:()=>fields,persist:()=>{},structuredClone};
vm.createContext(ctx);vm.runInContext(fn,ctx);
const first=ctx.captureConfig();
assert.deepEqual(first.filters,{listing_days:{min:365},turnover:{max:3}});
assert.equal(first.top_n,10);
fields[0].value='900';ctx.captureConfig();
assert.equal(first.filters.listing_days.min,365,'subsequent form edits must not change submitted config');
fields[1].disabled=true;
assert.throws(()=>ctx.captureConfig(),/不可用/,'saved conditions must not be silently dropped after data availability changes');
console.log('frontend form snapshot regression passed');
