const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../web/post-result.js'),'utf8');
function harness(document){const context={window:{},document,URL,Set,Map,Date};vm.runInNewContext(code,context);return context.window.PostResult;}
const api=harness({});
const clone=x=>JSON.parse(JSON.stringify(x));
function fixture(){return {id:'work-test',run_id:'new',automation:{protocol:2,active:true},scripts:[{id:'s1',text:'실제로 선택한 대본입니다.'}],script_id:'s1',voices:[],sources:[],jobs:[],
 source_goal:{count:3,target:10,platforms:{'틱톡':2,'유튜브':1},core_ready:true,ready:false},
 pipeline:[{id:'old',status:'completed',created:1,video_url:'/old.mp4',artifacts:{},steps:[{key:'export',status:'completed',download_url:'/download?run=old'}]},
 {id:'new',status:'queued',created:2,artifacts:{},steps:[]}], reference_url:'/reference.mp4'};}

test('all four stages are clickable and real independent jobs alone animate',()=>{
 const t=fixture();t.jobs=[{kind:'collect_sources',status:'running'},{kind:'voice',status:'running'}];
 const m=api.model(t);assert.equal(m.steps.sources.state,'running');assert.equal(m.steps.script.state,'completed');assert.equal(m.steps.voice.state,'running');
 const html=api.stageMarkup(t,m,'sources');assert.equal((html.match(/data-stage=/g)||[]).length,4);assert.doesNotMatch(html,/disabled/);assert.equal((html.match(/pr-spinner/g)||[]).length,2);
 t.jobs.forEach(j=>j.status='queued');assert.doesNotMatch(api.stageMarkup(t,api.model(t),null),/pr-spinner/);
});
test('old completion never completes a new run and stale voice cannot be played',()=>{
 const t=fixture();t.voice_id='v1';t.voices=[{id:'v1',script_id:'old-script',path_url:'/old.wav'}];
 const m=api.model(t);assert.equal(m.voice,null);assert.equal(m.steps.final.state,'waiting');assert.doesNotMatch(api.stepResult(t,m,'voice'),/<audio/);
});

test('a failed voice request stays red while clone setup guidance remains available',()=>{
 const t=fixture();t.production_blockers=['personal_clone_unavailable'];t.jobs=[{kind:'voice',status:'failed'}];
 const m=api.model(t);assert.equal(m.steps.voice.state,'failed');assert.equal(m.needsClone,true);
 assert.match(api.stepResult(t,m,'voice'),/내 목소리 등록·설정/);
});
test('sources show actual platform totals without requesting user footage',()=>{
 const t=fixture(),html=api.stepResult(t,api.model(t),'sources');
 assert.match(html,/총 3\/10개/);assert.match(html,/틱톡<\/dt><dd>2개/);assert.match(html,/유튜브<\/dt><dd>1개/);
 assert.doesNotMatch(html,/업로드|추가해|찾아주|직접.*영상/);
});

test('source summary exposes the mandatory TikTok count without completing an unmet goal',()=>{
 const t=fixture();t.source_goal={count:10,target:10,platforms:{'틱톡':4,'유튜브':6},core_ready:true,ready:false,platform_targets:{tiktok:{usable:4,target:5,status:'shortfall'}}};
 const m=api.model(t),html=api.stepResult(t,m,'sources');
 assert.equal(m.steps.sources.state,'waiting');assert.match(html,/필수 확보 기준 · 틱톡 4\/5개/);assert.doesNotMatch(html,/소스가 준비됐어요/);
});

test('in-flight platform authentication is visible before the search round finishes',()=>{
 const t=fixture();t.source_search={status:'running',message:'tiktok · CAPTCHA 인증 대기'};
 const html=api.stepResult(t,api.model(t),'sources');assert.match(html,/틱톡<small> · 인증 대기/);assert.match(html,/2개/);
});
test('saved search authentication problems include Google and distinguish Douyin login',()=>{
 const t=fixture();t.source_audit={searches:[{provider:'google-lens',status:'verification_required'},{provider:'douyin',status:'login_required'}]};
 const html=api.stepResult(t,api.model(t),'sources');assert.match(html,/Google 검색<small> · 인증 확인 필요/);assert.match(html,/더우인<small> · 로그인 필요/);
});
test('selected script is readable and untrusted text is escaped',()=>{
 const t=fixture();t.scripts[0].text='<script>bad()</script>\n선택 대본';
 const html=api.stepResult(t,api.model(t),'script');assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);assert.match(html,/선택 대본/);
});
test('download belongs to the displayed completed run; original stays left',()=>{
 const t=fixture(),html=api.compare(t,t.pipeline[0]);
 assert.ok(html.indexOf('원본 레퍼런스')<html.indexOf('우리 완성 영상'));assert.match(html,/download\?run=old/);assert.match(html,/tab=results&amp;run=old/);assert.doesNotMatch(html,/autoplay/);
});
test('completed historical output is never a newly enforced quota failure',()=>{
 const t=fixture();t.run_id='old';t.pipeline=t.pipeline.slice(0,1);
 const m=api.model(t);assert.equal(m.steps.sources.state,'completed');assert.doesNotMatch(api.stageMarkup(t,m,null),/3\/10개/);
});

test('four semantic status colors have readable text in light and dark themes',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../web/post-result.css'),'utf8');
 const luminance=hex=>{const c=hex.match(/\w\w/g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2];};
 const themes=[...css.matchAll(/--pr-green:[^}]+/g)].map(match=>match[0]);assert.equal(themes.length,3);
 assert.match(css,/:where\(:root\[data-theme="dark"\]\) \.post-result/);
 assert.match(css,/@media\(prefers-color-scheme:dark\)\{:where\(:root:not\(\[data-theme="light"\]\)\)/);
 for(const theme of themes)for(const color of ['green','gray','red','blue']){
   const fg=theme.match(new RegExp(`--pr-${color}:#([0-9a-f]{6})`)),bg=theme.match(new RegExp(`--pr-${color}-bg:#([0-9a-f]{6})`));
   assert.ok(fg&&bg);const a=luminance(fg[1]),b=luminance(bg[1]);assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,color);
 }
});

// Optional DOM-only harness. It never launches a browser or contacts the app.
// Set HOTPOST_TEST_DOM to an installed linkedom directory to run these cases.
let parseHTML;try{({parseHTML}=require(process.env.HOTPOST_TEST_DOM||'linkedom'));}catch(_){}
function dom(){const {document,window}=parseHTML('<html><body><main id="root"></main></body></html>');return {document,window,root:document.querySelector('#root'),app:harness(document)};}
test('parallel source collection cannot animate a failed voice setup notice',{skip:!parseHTML},()=>{
 const {root,app}=dom(),t=fixture();t.production_blockers=['personal_clone_unavailable'];
 t.jobs=[{kind:'collect_sources',status:'running'},{kind:'voice',status:'failed'}];app.mount(root,t);
 const notice=root.querySelector('.pr-waiting');
 assert.equal(root.querySelectorAll('[data-stage="sources"] .pr-spinner').length,1);
 assert.equal(root.querySelectorAll('[data-stage="voice"] .pr-spinner').length,0);
 assert.equal(notice.querySelector('.pr-spinner'),null);
 assert.match(notice.textContent,/음성 제작이 멈춰 있어요/);
 assert.match(notice.textContent,/소스 영상 작업은 별도로 진행 중/);
 t.jobs[0].status='done';app.mount(root,t);
 assert.equal(root.querySelectorAll('.pr-spinner').length,0);
 assert.doesNotMatch(root.querySelector('.pr-waiting').textContent,/별도로 진행 중/);
});
test('a real voice retry replaces stale setup guidance with actual running feedback',{skip:!parseHTML},()=>{
 const {root,app}=dom(),t=fixture();t.production_blockers=['personal_clone_unavailable'];
 t.jobs=[{kind:'voice',status:'running'}];app.mount(root,t);
 assert.equal(app.model(t).needsClone,false);
 assert.ok(root.querySelector('.pr-waiting .pr-spinner'));
 assert.match(root.querySelector('.pr-waiting').textContent,/음성 작업을 진행/);
 assert.doesNotMatch(root.querySelector('.pr-waiting').textContent,/녹음과 복제 설정/);
});
test('polling preserves live player identity, position and open history even if download changes',{skip:!parseHTML},()=>{
 const {root,app}=dom(),t=fixture();app.mount(root,t);
 const player=root.querySelector('video[src="/old.mp4"]');player.currentTime=8;
 t.pipeline[0].steps[0].download_url='/download?run=old&updated=1';t.jobs=[{kind:'voice',status:'running'}];app.mount(root,t);
 assert.equal(root.querySelector('video[src="/old.mp4"]'),player);assert.equal(player.currentTime,8);
 assert.equal(root.querySelector('.pr-card-body').hidden,false);
 root.onclick({target:root.querySelector('[data-collapse="old"]')});assert.equal(root.querySelector('.pr-card-body').hidden,true);
 app.mount(root,t);assert.equal(root.querySelector('.pr-card-body').hidden,true);
});
test('remake never reparents existing players and new completion inserts before old',{skip:!parseHTML},()=>{
 const {root,app}=dom(),t=fixture();t.run_id='old';t.pipeline=t.pipeline.slice(0,1);app.mount(root,t);
 const card=root.querySelector('[data-run-id="old"]'),parent=card.parentElement,player=card.querySelector('video[src="/old.mp4"]');
 t.run_id='new';t.pipeline.push({id:'new',status:'queued',created:2,steps:[]});app.mount(root,t);
 assert.equal(card.parentElement,parent);assert.equal(card.querySelector('video[src="/old.mp4"]'),player);
 t.pipeline[1].video_url='/new.mp4';t.pipeline[1].status='completed';app.mount(root,t);
 assert.equal(parent.children[0].dataset.runId,'new');assert.equal(parent.children[1],card);assert.equal(card.querySelector('video[src="/old.mp4"]'),player);
});
test('read-only stage clicks retain selection across polls without replacing the final video',{skip:!parseHTML},()=>{
 const {root,app}=dom(),t=fixture();app.mount(root,t);const player=root.querySelector('video[src="/old.mp4"]');
 root.onclick({target:root.querySelector('[data-stage="script"]')});assert.equal(root.querySelector('.pr-step-result').hidden,false);assert.match(root.querySelector('.pr-script').textContent,/선택한 대본/);
 app.mount(root,t);assert.equal(root._selection,'script');assert.equal(root.querySelector('video[src="/old.mp4"]'),player);
 root.onclick({target:root.querySelector('[data-stage="final"]')});assert.equal(root.querySelector('.pr-step-result').hidden,true);assert.equal(root.querySelector('video[src="/old.mp4"]'),player);
});
test('one audio/video plays at a time and a failed remake is not titled running',{skip:!parseHTML},()=>{
 const {root,app,window}=dom(),t=fixture();t.jobs=[{kind:'voice',status:'failed',error:'unavailable'}];app.mount(root,t);
 assert.match(root.querySelector('[data-title]').textContent,/실패/);
 const videos=[...root.querySelectorAll('video')];let paused=0;videos.forEach(v=>{v.pause=()=>{paused++;};});
 videos[0].dispatchEvent(new window.Event('play',{bubbles:true}));assert.equal(paused,videos.length-1);
 const player=videos[1];app.connectionError(root);assert.equal(root.querySelectorAll('video')[1],player);assert.equal(root.querySelector('.pr-connection').hidden,false);
});
