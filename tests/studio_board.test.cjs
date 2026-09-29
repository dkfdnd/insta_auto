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
  assert.equal(d.stage,'voice');assert.match(d.versions,/V2.*V1/);
});
test('source refresh does not move an already completed video backward',()=>{
  const d=describe({status:'completed',jobs:[{kind:'refresh_sources',status:'running'}]});
  assert.equal(d.stage,'completed');assert.equal(d.state,'completed');assert.equal(d.running,true);
});
test('source errors remain discoverable without losing the primary stage',()=>{
  const t={title:'책상',shortcode:'DESK',status:'voice_review',source_search:{status:'failed',message:'source failed'}};
  assert.equal(describe(t).stage,'voice');assert.equal(matches(t,'attention','desk'),true);
  assert.equal(matches(t,'running',''),false);assert.equal(matches(t,'review','책상'),true);
});
