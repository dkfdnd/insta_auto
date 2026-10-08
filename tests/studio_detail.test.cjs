const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const memory=new Map(),context={window:{StudioBoard:require('../web/studio-board.js')},localStorage:{getItem:k=>memory.get(k)||null}};
vm.createContext(context);
for(const name of ['studio-workspace.js','studio-detail.js','caption-editor.js','studio/source-view.js','production-flow.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',name),'utf8'),context);
const detail=context.window.StudioDetail,flow=context.window.ProductionFlow;
const task=()=>({id:'test-work',revision:1,status:'script_review',automation:{protocol:2,active:false},jobs:[],sources:[],scripts:[{id:'script1',text:'내가 직접 쓴 대본 <script>bad</script>'}],script_id:'script1',voices:[],edits:[],pipeline:[],proposals:[],feedback:{}});

test('source acquisition stops are explained outside collapsed search history',()=>{
 const t=task();t.status='source_wait';t.automation.active=true;t.source_acquisition={hold:{reason:'no_progress'}};
 t.source_search={status:'blocked',message:'인증 필요: tiktok'};
 const html=detail.status(t);
 assert.equal(detail.view(t).kind,'blocked');
 assert.match(html,/소스 자동 수집을 중지/);assert.match(html,/인증 필요: tiktok/);
 assert.match(html,/중지 사유·검색 조건 확인/);
 assert.equal(context.window.StudioBoard.describe(t).attention,true);
});

test('required clone registration and recheck are visible outside hidden help panels',()=>{
 const t=task();t.production_blockers=['personal_clone_unavailable','core_footage_gap'];t.shortcode='DeEau5JxJfy';
 const html=flow.runtime(t),beforeHelp=html.slice(0,html.indexOf('data-detail-panel'));
 assert.match(beforeHelp,/href="http:\/\/127\.0\.0\.1:8765\/"/);assert.match(beforeHelp,/target="_blank" rel="noopener"/);
 assert.match(beforeHelp,/data-pf="resume-auto"/);assert.match(html,/핵심 장면은 자동으로 추가 확보/);
 assert.doesNotMatch(html,/승인 불필요|전사 도구 설치/);
 t.production_blockers=['core_footage_gap'];assert.match(detail.view(t).body,/플랫폼 합산 최소 10개/);assert.equal(detail.view(t).action,'sources');
});

test('running, queued, paused and failed views expose different truthful next actions',()=>{
 const t=task();t.status='voice_generating';t.automation.active=true;t.jobs=[{kind:'voice',status:'running'}];
 assert.equal(detail.view(t).kind,'running');assert.equal(detail.view(t).action,null);
 t.jobs[0].status='queued';assert.equal(detail.view(t).kind,'queued');assert.equal(detail.view(t).action,null);
 t.jobs=[];t.status='paused';t.automation.active=false;assert.equal(detail.view(t).action,'resume-auto');
 t.status='attention';t.error='연결 실패';assert.equal(detail.view(t).action,'retry');
});

test('script viewing is a real accessible button, with isolated escaped card and edit navigation',()=>{
 const html=detail.scriptCard(task());
 assert.match(html,/<button type="button"[^>]+aria-controls="[^"]+" aria-expanded="false"/);
 assert.match(html,/class="sd-script-card"/);assert.match(html,/data-pf-tab="script"/);
 assert.match(html,/&lt;script&gt;bad&lt;\/script&gt;/);assert.doesNotMatch(html,/<script>/);
});

test('current audio remains unchanged while the inline editor holds the next script',()=>{
 const t=task();t.voice_id='voice1';t.voices=[{id:'voice1',script_id:'old',spoken_text:'이전 음성이 읽는 실제 문장',path_url:'/old.wav'}];t.feedback={script_text:'새로 고친 대본'};
 const html=flow.editor(t);assert.match(html,/<h4>현재 음성<\/h4>/);assert.match(html,/>수정하기<\/span>/);
 assert.doesNotMatch(html,/수정 전 음성|새로 읽을 대본 보기/);assert.match(html,/새로 고친 대본/);assert.match(html,/src="\/old.wav"/);
});

test('advanced voice tools do not suggest disabled regeneration before a voice exists',()=>{
 const html=flow.editor(task());assert.doesNotMatch(html,/data-pf="regenerate-voice"/);
 assert.doesNotMatch(html,/data-field="pronunciation"|data-pf="save-voice"|1.0배가 기본/);
 assert.match(html,/data-field="speed"/);
 assert.match(html,/data-field="voice-profile" value=""/);assert.doesNotMatch(html,/value="qwen-sohee"/);
});

test('caption edits explicitly change screen text, not narration, and keep export available',()=>{
 const t=task(),e={id:'e1',duration:2,clean_preview_url:'/clean.mp4',plan:{duration:2,beats:[{id:'b1',cue_id:'c1',start:0,end:2,text:'대사',selected_shot_id:'s1'}],cues:[{id:'c1',start:0,end:2,text:'화면 글자'}],shots:[{id:'s1',thumbnail_url:'/thumb.jpg'}]}};
 const html=context.window.CaptionEditor.markup(t,e);
 assert.match(html,/여기서는 화면 글자만 바뀝니다/);assert.match(html,/data-pf-tab="script">내 대본 수정하기/);
 assert.match(html,/data-pf="export-edit"/);assert.match(html,/<details class="ce-advanced-tools"><summary>저장·추가 편집 도구/);
 assert.match(html,/<details class="ce-timeline-disclosure"><summary>전체 장면·자막 흐름 보기/);
});

test('version labels include stored creation time and only evidence-supported changes',()=>{
 const old={id:'old',number:1,status:'completed',created:1791140006,artifacts:{script_id:'s1'},inputs:{voice_profile_id:'own'}},fresh={id:'new',number:2,status:'completed',created:1791140306,parent_id:'old',artifacts:{script_id:'s1'},inputs:{voice_profile_id:'own'}};
 const html=context.window.StudioWorkspace.versionPicker({pipeline:[old,fresh]},fresh);
 assert.match(html,/다시 제작/);assert.match(html,/10\. 5\./);assert.doesNotMatch(html,/자막 변경|대본 변경|목소리 설정 변경/);
 fresh.inputs.speed=1.1;assert.match(context.window.StudioWorkspace.versionPicker({pipeline:[old,fresh]},fresh),/목소리 설정 변경/);
});

test('an entire disclosure button toggles a panel, and polling restores its open state',()=>{
 let listener,count=0;
 const button={dataset:{detailToggle:'one'},attributes:{'aria-expanded':'false'},getAttribute(n){return this.attributes[n]},setAttribute(n,v){this.attributes[n]=v}};
 const panel={dataset:{detailPanel:'one'},hidden:true};
 const root={addEventListener(type,callback){assert.equal(type,'click');listener=callback;count++},contains:n=>n===button,querySelectorAll:s=>s==='[data-detail-panel]'?[panel]:s==='[data-detail-toggle]'?[button]:[]};
 detail.bind(root);detail.bind(root);assert.equal(count,1);
 listener({target:{closest:()=>button}});assert.equal(panel.hidden,false);assert.equal(button.attributes['aria-expanded'],'true');
 panel.hidden=true;button.attributes['aria-expanded']='false';detail.restore(root);assert.equal(panel.hidden,false);
 listener({target:{closest:()=>button}});assert.equal(panel.hidden,true);assert.equal(button.attributes['aria-expanded'],'false');
 const event={target:{closest:()=>button}};listener(event);assert.equal(panel.hidden,false);listener(event);assert.equal(panel.hidden,false,'a containing legacy root must not toggle a handled nested panel again');
});

function luminance(hex){const rgb=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
test('detail text, primary controls and focus outlines have measurable light/dark contrast',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../web/studio-detail.css'),'utf8');
 for(const block of [css.match(/:root\{([^}]+)\}/)[1],css.match(/\[data-theme=dark\]\{([^}]+)\}/)[1]]){
  const tokens=Object.fromEntries([...block.matchAll(/--(sd-[\w-]+):(#[a-f0-9]{6})/g)].map(m=>[m[1],m[2]]));
  for(const [a,b] of [['text','surface'],['muted','surface'],['text','bg'],['muted','bg'],['primary-text','primary'],['warning-text','warning'],['success-text','success'],['error-text','error']])assert.ok(contrast(tokens['sd-'+a],tokens['sd-'+b])>=4.5,a+'/'+b);
  assert.ok(contrast(tokens['sd-focus'],tokens['sd-surface'])>=3);
 }
});
