const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const memory=new Map(),context={window:{StudioBoard:require('../web/studio-board.js')},localStorage:{getItem:key=>memory.get(key)||null}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/studio/source-view.js'),'utf8'),context);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const view=context.window.StudioSourceView.create({esc,link:()=>'',item:(t,c,id)=>t[c].find(v=>v.id===id),storageKey:t=>'feedback-'+t.id});
function fixture(){return {id:'test',status:'completed',jobs:[],sources:[{id:'old',url:'/old.mp4'},{id:'new',url:'/new.mp4'}],edits:[],
  scripts:[],voices:[],pipeline:[{id:'v1',status:'completed',artifacts:{sources:[{id:'old'}]}}],run_id:'v1',latest_completed_run_id:'v1',feedback:{}};}

test('owned footage remains a candidate pool after completion instead of claiming every clip was used',()=>{
  const task=fixture();task.creation_mode='self_shot';task.self_shot={started:true};
  task.pipeline[0].artifacts.sources=[{id:'old'},{id:'new'}];
  task.edits=[{id:'edit',plan:{shots:[{id:'shot',source_id:'old'}],beats:[{selected_shot_id:'shot'}]}}];
  task.edit_id='edit';
  const html=view.sourceLibrary(task);
  assert.match(html,/완성본 제작에 고른 후보 영상/);
  assert.equal((html.match(/이번 제작 후보로 선택됨/g)||[]).length,2);
  assert.doesNotMatch(html,/현재 영상에 사용됨|완성 영상에 사용한 장면/);
  assert.match(html,/AI가 후보 중 일부 장면을 사용합니다/);
});

test('saved source selection changes future checkboxes while preserving completed source attribution',()=>{
  const task=fixture();task.feedback.source_ids=['new'];
  assert.equal(view.sourceBaseline(task,'old'),false);assert.equal(view.sourceBaseline(task,'new'),true);
  const html=view.sourceLibrary(task);
  assert.match(html,/aria-label="영상 1 사용" data-field="source:old" >/);
  assert.match(html,/data-field="source:new" checked/);
  assert.match(html,/data-source-group="used"[\s\S]*\/old.mp4/);
});

test('explicit empty selection stays empty; local unsaved choices remain visible',()=>{
  const task=fixture();task.feedback.source_ids=[];
  assert.equal(view.sourceBaseline(task,'old'),false);
  memory.set('feedback-test',JSON.stringify({'source:new':true}));
  try{assert.match(view.sourceLibrary(task),/data-field="source:new" checked/);}
  finally{memory.clear();}
});

test('source job status distinguishes a real running search from waiting for quota',()=>{
  const task=fixture();task.source_goal={count:3,target:10,platforms:{'유튜브':3},ready:false,core_ready:true};
  assert.match(view.sourceSearchStatus(task),/소스 자동 추가 수집 대기/);
  task.jobs=[{kind:'collect_sources',status:'running'}];
  assert.match(view.sourceSearchStatus(task),/소스 자동 추가 수집 중/);
  task.jobs[0].status='queued';assert.match(view.sourceSearchStatus(task),/소스 자동 추가 수집 대기/);
});

test('total source count cannot hide a missing TikTok quota; legacy output has no new quota',()=>{
  const task=fixture();task.source_goal={count:10,target:10,platforms:{'유튜브':10},ready:false,core_ready:true,platform_targets:{tiktok:{usable:0,target:5,status:'shortfall'}}};
  const html=view.sourceSearchStatus(task);
  assert.match(html,/필수 확보 기준 · 틱톡 0\/5개/);
  assert.doesNotMatch(html,/소스 준비 완료/);
  task.source_goal.platform_targets={};task.source_goal.ready=true;
  assert.doesNotMatch(view.sourceSearchStatus(task),/필수 확보 기준/);
});

test('audit distinguishes a saved authentication skip from a fresh failed attempt',()=>{
  const task=fixture();task.source_audit={platform_outcomes:{tiktok:{search_attempts:0,download_attempts:0,skipped_searches:15,skipped_reasons:{verification_required:15},reasons:{not_attempted:1}}}};
  const html=view.sourceSearchPanel(task);
  assert.match(html,/실제 검색 0회 · 다운로드 시도 0회/);
  assert.match(html,/이전 인증 차단으로 검색 건너뜀 15/);
  assert.doesNotMatch(html,/인증 화면 확인/);
});

test('received footage awaiting review is explained as pending without a false failure label',()=>{
  const task=fixture();task.source_audit={platform_outcomes:{tiktok:{search_attempts:0,download_attempts:0,reasons:{review_pending:6}}}};
  const html=view.sourceSearchPanel(task);
  assert.match(html,/사용할 장면 검토 중 6/);
  assert.doesNotMatch(html,/review_pending|영상 검증 탈락/);
});

test('stopped acquisition displays the cause without promising continued automatic search',()=>{
  const task=fixture();task.source_goal={count:4,target:10,platforms:{},ready:false,core_ready:false};
  task.source_acquisition={hold:{reason:'no_progress'}};
  task.source_search={status:'blocked',message:'소스 자동 수집 중지 · 인증 필요: tiktok'};
  const html=view.sourceSearchStatus(task);
  assert.match(html,/소스 자동 수집 중지/);
  assert.match(html,/인증 필요: tiktok/);
  assert.match(html,/영상·대본·음성은 보존/);
  assert.doesNotMatch(html,/다른 검색어와 플랫폼으로 계속 확보/);
});

test('active search and audit explain the objective and route changes safely',()=>{
  const task=fixture();task.source_goal={count:4,target:10,platforms:{},ready:false,core_ready:true};
  task.jobs=[{kind:'collect_sources',status:'running'}];
  task.source_search={strategy_message:'검색 전략 · 원본 장면 검색 · 검증 탈락'};
  assert.match(view.sourceSearchStatus(task),/검색 전략 · 원본 장면 검색 · 검증 탈락/);
  task.source_audit={strategy:{label:'무자막 행동 검색',reasons:['이전 검증 탈락'],skipped_routes:{duckduckgo:'후보 없음 <script>'},vendor_search:false},
    searches:[{provider:'duckduckgo',query:'',status:'strategy_skipped',reason:'이전 결과 없음'}]};
  const html=view.sourceSearchPanel(task);
  assert.match(html,/검색 전략 · 무자막 행동 검색/);
  assert.match(html,/이전 실패에 따라 다른 경로로 전환/);
  assert.match(html,/이전 결과 없음/);
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<script>/);
});

test('candidate priority and time slices never claim title-based approval or confuse readiness with login',()=>{
  const task=fixture();task.source_audit={inspection:[{title:'<clip>',reasons:['제목의 핵심 행동 일치'],duration:12,download_budget_seconds:37.5,rejections:[]}],
    searches:[{provider:'tiktok',status:'readiness_blocked'}]};
  const html=view.sourceSearchPanel(task);
  assert.match(html,/제목의 핵심 행동 일치/);
  assert.match(html,/다운로드 시간 배분 37.5초/);
  assert.match(html,/실제 장면 검사로 판단/);
  assert.match(html,/페이지 판독 실패로 재검색 중지/);
  assert.match(html,/&lt;clip&gt;/);
  assert.doesNotMatch(html,/<clip>|로그인 필요|사람 확인 필요/);
});
