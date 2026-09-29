const {test}=require('node:test');
const assert=require('node:assert/strict');
const {describe,matches}=require('../web/studio-board.js');

test('queued and externally blocked tasks are not animated as running',()=>{
  for(const status of ['preparing','waiting_capcut','retry_wait','paused']){
    const d=describe({status,jobs:[{kind:'prepare',status:'queued'}]});
    assert.equal(d.running,false);
    assert.notEqual(d.state,'running');
  }
});
test('only a real running job enables activity',()=>{
  assert.equal(describe({status:'voice_generating',jobs:[]}).running,false);
  assert.equal(describe({status:'voice_generating',jobs:[{kind:'voice',status:'running'}]}).running,true);
});
test('an error stays at its failed stage, including manual tasks',()=>{
  assert.equal(describe({status:'attention',automation:{stage:'voice'},error:'failed'}).stage,'voice');
  assert.equal(describe({status:'attention',jobs:[{kind:'voice',status:'failed',updated:5},{kind:'prepare',status:'done',updated:1}]}).stage,'voice');
  assert.equal(describe({status:'waiting_capcut',automation:{stage:'export'}}).stage,'export');
});
test('completed export is distinct from review and reproduction shows old output',()=>{
  assert.equal(describe({status:'completed'}).review,false);
  assert.equal(describe({status:'draft_review'}).stage,'edit');
  const d=describe({status:'voice_generating',run_id:'v2',latest_completed_run_id:'v1',pipeline:[{id:'v1',number:1},{id:'v2',number:2}]});
  assert.equal(d.stage,'voice');assert.match(d.versions,/V2/);assert.match(d.previous,/V1/);
});
test('source refresh does not move an already completed video backward',()=>{
  const d=describe({status:'completed',jobs:[{kind:'refresh_sources',status:'running'}]});
  assert.equal(d.stage,'export');assert.equal(d.complete,true);assert.equal(d.state,'completed');assert.equal(d.running,true);
});
test('source errors remain discoverable without losing the primary stage',()=>{
  const t={title:'책상',shortcode:'DESK',status:'voice_review',source_search:{status:'failed',message:'source failed'}};
  assert.equal(describe(t).stage,'voice');assert.equal(matches(t,'attention','desk'),true);
  assert.equal(matches(t,'running',''),false);assert.equal(matches(t,'review','책상'),true);
});

test('voice is step four of six with three verified milestones complete',()=>{
  const d=describe({status:'voice_generating',run_id:'new',automation:{protocol:2},jobs:[{kind:'voice',status:'running'}],pipeline:[{id:'new',steps:['sources','transcript','script','voice','project','export'].map((key,i)=>({key,status:i<3?'completed':i===3?'running':'pending'}))}]});
  assert.equal(d.phase,'4 / 6 단계');assert.equal(d.done,3);assert.equal(d.total,6);
  assert.deepEqual(d.steps.map(s=>s.state),['done','done','done','current','pending','pending']);
});
test('preparation moves to original speech only with current-run source evidence',()=>{
  const d=describe({status:'preparing',run_id:'new',automation:{protocol:2},pipeline:[{id:'new',steps:[{key:'sources',status:'completed'},{key:'transcript',status:'running'}]}]});
  assert.equal(d.stage,'transcript');assert.equal(d.phase,'2 / 6 단계');assert.equal(d.done,1);
});
test('an older export cannot fill a reproduction progress bar',()=>{
  const d=describe({status:'voice_generating',run_id:'new',latest_completed_run_id:'old',automation:{protocol:2},pipeline:[{id:'old',number:1,steps:['sources','transcript','script','voice','project','export'].map(key=>({key,status:'completed'}))},{id:'new',number:2,steps:[{key:'sources',status:'completed'}]}]});
  assert.equal(d.done,1);assert.equal(d.steps[5].state,'pending');assert.match(d.previous,/V1/);
});
test('error and review leave the current milestone unfinished; completion fills six',()=>{
  for(const status of ['voice_review','attention']){
    const d=describe({status,error:status==='attention'?'error':'',automation:{protocol:2,stage:'voice'},run_id:'new',pipeline:[{id:'new',steps:[{key:'voice',status:'completed'}]}]});
    assert.equal(d.steps[3].state,'current');assert.equal(d.done,0);
  }
  const d=describe({status:'completed'});assert.equal(d.done,6);assert.equal(d.phase,'6 / 6 단계 완료');
  assert.equal(d.steps.every(s=>s.state==='done'),true);
});

test('user-facing failures are Korean and source recovery explains the next action',()=>{
  const {message,title}=require('../web/studio-board.js');
  assert.match(message('Source manifest contains no selected local videos.'),/직접 영상을/);
  assert.match(message('Failed to fetch'),/연결/);
  assert.doesNotMatch(message('unknown exception in worker'),/[A-Za-z]/);
  assert.equal(title({title:'DdyQWlyKAv9',shortcode:'DdyQWlyKAv9'}),'새 쇼츠 제작');
  assert.equal(title({title:'주방 수납 #추천 https://example.test/abc',shortcode:'abc'}),'주방 수납');
  const d=describe({status:'attention',error:'Source manifest contains no selected local videos.',automation:{stage:'prepare'},sources:[{id:'upload'}]});
  assert.match(d.message,/1개가 준비/);
});

test('a user pause is explicit while an in-flight job still shows real activity',()=>{
  const t={status:'preparing',automation:{paused_by_user:true,stage:'prepare'},jobs:[{kind:'prepare',status:'paused'}]};
  assert.equal(describe(t).state,'paused');
  t.jobs[0].status='running';assert.equal(describe(t).state,'running');assert.match(describe(t).label,/중지 예약/);
});
