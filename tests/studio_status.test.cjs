const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const context={window:{}};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/studio-workspace.js'),'utf8'),context);
const w=context.window.StudioWorkspace;
context.window.StudioBoard=require('../web/studio-board.js');
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/studio-detail.js'),'utf8'),context);
// Render the real production view as a pure HTML unit; no browser is launched.
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/studio/source-view.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/production-flow.js'),'utf8'),context);

test('network failure stops live feedback until a successful status refresh',async()=>{
  context.document={documentElement:{dataset:{studioConnection:'live'}}};
  context.fetch=async()=>{throw new Error('connection lost');};
  await assert.rejects(context.window.ProductionFlow.api(''),/connection lost/);
  assert.equal(context.document.documentElement.dataset.studioConnection,'stale');
  context.fetch=async()=>({ok:true,status:200,json:async()=>({tasks:[]})});
  await context.window.ProductionFlow.api('');
  assert.equal(context.document.documentElement.dataset.studioConnection,'live');
});

test('blocked production keeps truthful stages and exposes a labelled script card without approval',()=>{
  const run={id:'v1',number:1,status:'blocked',artifacts:{},steps:['sources','transcript','script','voice','project','export'].map((key,i)=>({key,status:i<3?'completed':i===3?'blocked':'pending'}))};
  const t={id:'garlic',shortcode:'DeEau5JxJfy',status:'script_review',run_id:'v1',script_id:'script1',automation:{protocol:2,active:false,stage:'voice'},production_blockers:['personal_clone_unavailable','core_footage_gap'],jobs:[],sources:[],voices:[],edits:[],scripts:[{id:'script1',text:'한 스푼이면 끝? <img src=x onerror=bad>'}],pipeline:[run]};
  const html=context.window.ProductionFlow.summary(t);
  assert.match(html,/3 \/ 6 단계 완료/);assert.equal((html.match(/<li class="completed"/g)||[]).length,3);
  assert.match(html,/현재 4 \/ 6 단계.*제작 준비 필요/);assert.doesNotMatch(html,/검토 필요|진행 중|<select|<img/);
  const status=context.window.ProductionFlow.runtime(t),script=context.window.StudioDetail.scriptCard(t);
  assert.match(status,/내 목소리를 먼저 준비해 주세요/);assert.match(status,/내 목소리 준비 방법/);
  assert.match(script,/aria-expanded="false"/);assert.match(script,/내 영상의 대본 보기/);assert.match(script,/한 스푼이면 끝\? &lt;img/);
  assert.doesNotMatch(status+script,/승인 불필요|선택된 제작 대본 바로 읽기/);
});

test('running to waiting transition removes every activity marker from the production view',()=>{
  const run={id:'one',number:1,status:'running',artifacts:{},steps:['sources','transcript','script','voice','project','export'].map((key,i)=>({key,status:i<3?'completed':i===3?'running':'pending'}))};
  const t={id:'voice',status:'voice_generating',run_id:'one',automation:{protocol:2,active:true},jobs:[{kind:'voice',status:'running'}],scripts:[],sources:[],voices:[],edits:[],pipeline:[run]};
  let html=context.window.ProductionFlow.progress(t,run);
  assert.equal((html.match(/data-live="true"/g)||[]).length,2);
  assert.match(html,/studio-working-dots/);assert.match(html,/aria-busy="true"/);
  t.jobs[0].status='done';t.production_blockers=['personal_clone_unavailable'];
  html=context.window.ProductionFlow.progress(t,run);
  assert.doesNotMatch(html,/data-live="true"|studio-working-dots|aria-busy="true"/);
  assert.match(html,/제작 준비 필요/);
});

test('garlic instructions name real missing inputs and do not demand download or approval',()=>{
  const g=w.guidance({shortcode:'DeEau5JxJfy',automation:{protocol:2,active:false},production_blockers:['personal_clone_unavailable','core_footage_gap']});
  assert.equal(g.kind,'blocked');assert.match(g.body,/대본 승인 때문에 멈춘 것이 아닙니다/);
  assert.match(g.items[0],/본인 참조 음성/);assert.match(g.items[1],/닭고기·샐러드/);
  assert.match(g.footer,/준비가 부족하면/);
});

test('other products get their own generic footage instructions',()=>{
  assert.doesNotMatch(w.guidance({title:'운동화',production_blockers:['core_footage_gap']}).items[0],/마늘|샐러드/);
});

test('saved correction explains resuming while normal top-pick runs without approval',()=>{
  const paused=w.guidance({status:'script_review',automation:{protocol:2,active:false,pause_reason:'save-script'}});
  assert.equal(paused.kind,'paused');assert.match(paused.body,/수정 내용을 보관/);assert.match(paused.footer,/검토는 선택 사항/);
  const auto=w.guidance({automation:{protocol:2,active:true}});
  assert.equal(auto.kind,'automatic');assert.match(auto.body,/대본 승인 없이/);
});

test('one unfinished version is plain text, not a dropdown implying more videos',()=>{
  const run={id:'one',number:1,status:'blocked'},html=w.versionPicker({pipeline:[run]},run);
  assert.doesNotMatch(html,/<select|진행 중/);assert.match(html,/제작 버전 v1 · 제작 준비 필요/);
  assert.match(html,/한 개/);assert.match(html,/<details class="pf-version-help"><summary>제작 버전이란/);
});

test('legacy API running checkpoint cannot claim active work when queue is idle',()=>{
  const run={id:'one',number:1,status:'running'};
  const html=w.versionPicker({status:'script_review',run_id:'one',pipeline:[run],automation:{protocol:2,active:false},production_blockers:['personal_clone_unavailable'],jobs:[]},run);
  assert.match(html,/v1 · 제작 준비 필요/);assert.doesNotMatch(html,/실제 제작 중/);
});

test('multiple versions distinguish preserved completion from active production and escape IDs',()=>{
  const old={id:'old',number:1,status:'completed'},fresh={id:'new"bad',number:2,status:'queued'};
  const html=w.versionPicker({pipeline:[old,fresh],latest_completed_run_id:'old'},old);
  assert.match(html,/<select/);assert.match(html,/v1 · 제작 완료 · 최신 완료/);assert.match(html,/v2 · 실행 대기/);
  assert.match(html,/new&quot;bad/);assert.doesNotMatch(html,/진행 중/);
});

function luminance(hex){
  const rgb=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
test('light and dark semantic status labels and checkmarks meet AA text contrast',()=>{
  const css=fs.readFileSync(path.join(__dirname,'../web/studio-status.css'),'utf8');
  const blocks=[css.match(/:root\s*\{([^}]+)\}/)[1],css.match(/\[data-theme=dark\]\s*\{([^}]+)\}/)[1]];
  for(const block of blocks){
    const tokens=Object.fromEntries([...block.matchAll(/--(status-[\w-]+):\s*(#[a-f0-9]{6})/g)].map(m=>[m[1],m[2]]));
    for(const kind of ['success','info','warning','error','pending'])assert.ok(contrast(tokens[`status-${kind}-fg`],tokens[`status-${kind}-bg`])>=4.5,kind);
    assert.ok(contrast(tokens['status-success-solid'],tokens['status-success-on'])>=4.5);
    assert.ok(contrast(tokens['status-success-solid'],tokens['status-success-bg'])>=3);
  }
});
