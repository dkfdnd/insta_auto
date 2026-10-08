const {test}=require('node:test');
const assert=require('node:assert/strict');
const {create}=require('../web/discovery/report-refresh.js');
const report=(stamp,count=1)=>({generated_at:stamp,criteria:{version:1,values:{}},settings:{},summary:{},posts:Array.from({length:count},(_,i)=>({shortcode:String(i)}))});

test('morning collection replaces a stale report even when criteria version is unchanged',async()=>{
  const before=report(1),after=report(2,12),seen=[];
  const refresh=create({initial:before,fetchReport:async()=>after,onReport:r=>seen.push(r)});
  assert.equal(await refresh.refresh(),true);
  assert.equal(seen[0],after);
  assert.equal(await refresh.refresh(),false);
  assert.equal(seen.length,1);
});

test('focus and visibility refreshes share one request and failures preserve the last snapshot',async()=>{
  let resolve,calls=0;
  const seen=[],refresh=create({initial:report(1),fetchReport:()=>{calls++;return new Promise(r=>{resolve=r;});},onReport:r=>seen.push(r)});
  const first=refresh.refresh(),second=refresh.refresh();
  assert.equal(first,second);assert.equal(calls,1);
  resolve({error:'unavailable'});await assert.rejects(first,/수집 결과/);assert.equal(seen.length,0);
  const retry=refresh.refresh();resolve(report(2));assert.equal(await retry,true);assert.equal(calls,2);
});

test('changed criteria with an unchanged collection timestamp still refreshes results',async()=>{
  const next=report(1);next.criteria.version=2;
  const seen=[],refresh=create({initial:report(1),fetchReport:async()=>next,onReport:r=>seen.push(r)});
  assert.equal(await refresh.refresh(),true);assert.equal(seen.length,1);
});
