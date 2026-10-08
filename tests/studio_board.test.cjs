const {test}=require('node:test');
const assert=require('node:assert/strict');
const {describe,matches}=require('../web/studio-board.js');
const {listPage}=require('../web/studio-board.js');
const {boardPage}=require('../web/studio-board.js');

test('board keeps three distinct columns with independently bounded pages',()=>{
  const tasks=[{id:'live',created:40,status:'voice_generating',jobs:[{kind:'voice',status:'running'}]},
    ...Array.from({length:9},(_,i)=>({id:'waiting-'+i,created:i,status:'paused'})),
    {id:'done',created:20,status:'completed'}];
  const page=boardPage(tasks,{pages:{attention:2}});
  assert.deepEqual(page.lanes.map(l=>l.id),['working','attention','finished']);
  assert.equal(page.lanes[0].items[0].id,'live');assert.equal(page.lanes[1].items.length,4);
  assert.equal(page.lanes[1].page,2);assert.equal(page.lanes[2].items[0].id,'done');
  assert.equal(boardPage(tasks,{filter:'completed'}).total,1);
});

test('thumbnail list pages contain twelve newest tasks and clamp after shrinking',()=>{
  const tasks=Array.from({length:27},(_,i)=>({id:String(i).padStart(2,'0'),created:i,status:'completed',title:'영상 '+i}));
  const first=listPage(tasks,{filter:'all'});
  assert.equal(first.items.length,12);assert.equal(first.items[0].id,'26');assert.equal(first.pages,3);
  const last=listPage(tasks,{filter:'all',page:3});assert.deepEqual(last.items.map(t=>t.id),['02','01','00']);
  assert.equal(listPage(tasks.slice(0,2),{filter:'all',page:3}).page,1);
  assert.deepEqual(listPage(tasks,{filter:'all',query:'영상 26',page:3}).items.map(t=>t.id),['26']);
});

test('waiting and manual review tasks remain reachable through attention',()=>{
  for(const status of ['waiting_capcut','paused','script_review'])assert.equal(matches({status},'attention',''),true);
  assert.equal(matches({status:'completed',source_search:{status:'failed'}},'attention',''),false);
});

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
  assert.equal(d.stage,'voice');assert.equal(d.versions,'2번째 영상');assert.equal(d.previous,'1번째 완성본 보관 중');
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
  assert.equal(d.done,1);assert.equal(d.steps[5].state,'pending');assert.equal(d.previous,'1번째 완성본 보관 중');
});
test('error and review leave the current milestone unfinished; completion fills six',()=>{
  for(const status of ['voice_review','attention']){
    const d=describe({status,error:status==='attention'?'error':'',automation:{...(status==='attention'?{protocol:2}:{}),stage:'voice'},run_id:'new',pipeline:[{id:'new',steps:[{key:'voice',status:'completed'}]}]});
    assert.equal(d.steps[3].state,'current');assert.equal(d.done,0);
  }
  const d=describe({status:'completed'});assert.equal(d.done,6);assert.equal(d.phase,'6 / 6 단계 완료');
  assert.equal(d.steps.every(s=>s.state==='done'),true);
});

test('user-facing failures are Korean and source recovery explains the next action',()=>{
  const {message,title}=require('../web/studio-board.js');
  assert.match(message('Source manifest contains no selected local videos.'),/자동 추가 수집/);
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

test('corrected automatic script is complete; missing voice/footage is preparation, not review or running',()=>{
  const t={status:'script_review',run_id:'v1',automation:{protocol:2,stage:'voice',active:false},production_blockers:['personal_clone_unavailable','core_footage_gap'],jobs:[{kind:'rewrite',status:'done'}],pipeline:[{id:'v1',number:1,steps:['sources','transcript','script','voice','project','export'].map((key,i)=>({key,status:i<3?'completed':i===3?'blocked':'pending'}))}]};
  const d=describe(t);
  assert.equal(d.state,'blocked');assert.equal(d.review,false);assert.equal(d.primaryRunning,false);
  assert.equal(d.stage,'voice');assert.equal(d.done,3);assert.equal(d.steps[2].state,'done');
  assert.equal(d.label,'제작 준비 필요');assert.equal(d.attention,true);
});

test('automatic review checkpoint does not ask for human approval but manual review still does',()=>{
  const t={status:'script_review',automation:{protocol:2,active:false}};
  assert.equal(describe(t).review,false);assert.equal(describe(t).state,'waiting');
  delete t.automation;assert.equal(describe(t).review,true);
});

test('only the actually executing milestone receives step activity',()=>{
  const task={status:'rewriting',jobs:[{kind:'voice',status:'running'}]};
  const d=describe(task);
  assert.equal(d.stage,'voice');assert.equal(d.steps.filter(s=>s.live).length,1);
  assert.equal(d.steps[3].live,true);assert.equal(d.steps[2].live,false);
  task.jobs[0].status='queued';assert.equal(describe(task).steps.some(s=>s.live),false);
  task.jobs[0].status='paused';assert.equal(describe(task).steps.some(s=>s.live),false);
});

test('a real preparation worker can animate the transcription milestone after sources finish',()=>{
  const d=describe({status:'preparing',run_id:'one',jobs:[{kind:'prepare',status:'running'}],pipeline:[{id:'one',steps:[{key:'sources',status:'completed'}]}]});
  assert.equal(d.stage,'transcript');assert.equal(d.steps[1].live,true);assert.equal(d.steps[0].live,false);
});

test('background source search does not animate completed production milestones',()=>{
  const d=describe({status:'completed',jobs:[{kind:'refresh_sources',status:'running'}]});
  assert.equal(d.complete,true);assert.equal(d.steps.some(s=>s.live),false);
});
