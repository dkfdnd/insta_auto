const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {describe}=require('../web/studio-board.js');
const context={window:{}};vm.createContext(context);
for(const name of ['studio-workspace.js','caption-editor.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',name),'utf8'),context);
const workspace=context.window.StudioWorkspace;

test('review stages keep voice, caption editing and completed output separate',()=>{
  for(const [status,expected] of [['preparing','sources'],['script_review','script'],['voice_review','voice'],['draft_review','edit'],['completed','results']]){
    assert.equal(workspace.route(describe({status}).tab),expected);
  }
  assert.equal(workspace.route('original'),'script');
});

test('an original transcription in progress marks script preparation as current',()=>{
  const d=describe({status:'preparing',automation:{protocol:2},run_id:'new',pipeline:[{id:'new',steps:[{key:'sources',status:'completed'}]}]});
  assert.equal(workspace.tabState(d.steps,'sources'),'done');
  assert.equal(workspace.tabState(d.steps,'script'),'current');
  assert.equal(workspace.tabState(d.steps,'voice'),'pending');
  assert.equal(workspace.tabState(d.steps,'unknown'),'pending');
});

test('old completed output does not mark new voice or new results complete',()=>{
  const d=describe({status:'voice_generating',automation:{protocol:2},run_id:'new',latest_completed_run_id:'old',pipeline:[{id:'old',steps:[{key:'export',status:'completed'}]},{id:'new',steps:[]}]});
  assert.equal(workspace.tabState(d.steps,'voice'),'current');
  assert.equal(workspace.tabState(d.steps,'results'),'pending');
});

test('timeline preserves real gaps, clips out of bounds and excludes invalid intervals',()=>{
  const r=workspace.range(3,5,10);assert.equal(r.left,30);assert.equal(r.width,20);
  assert.equal(workspace.range(-2,3,10).start,0);
  assert.equal(workspace.range(8,13,10).end,10);
  for(const args of [[4,4,10],[6,2,10],[11,14,10],[0,2,0],[NaN,2,10]])assert.equal(workspace.range(...args),null);
  const html=workspace.track([{text:'A',start:0,end:2},{text:'B',start:4,end:6}],10,'cue',1);
  assert.match(html,/data-timeline-cue="1"[^>]+aria-pressed="true"[^>]+left:40%;width:20%/);
  assert.equal((html.match(/data-timeline-cue=/g)||[]).length,2);
});

test('timeline captions escape user text and never allow markup injection',()=>{
  const html=workspace.track([{text:'<img onerror="bad">',start:0,end:2}],10,'cue',0);
  assert.doesNotMatch(html,/<img/);assert.match(html,/&lt;img/);assert.match(html,/&quot;bad&quot;/);
});

test('scrubbing pauses playback, clamps to loaded media and never seeks before metadata',()=>{
  let pauses=0;
  const video={readyState:0,duration:9,currentTime:3,pause(){pauses++;}};
  assert.equal(workspace.seek(video,5,10),false);assert.equal(video.currentTime,3);assert.equal(pauses,0);
  video.readyState=1;
  assert.equal(workspace.seek(video,20,10),true);assert.equal(video.currentTime,9);
  workspace.seek(video,-1,10);assert.equal(video.currentTime,0);
  workspace.seek(video,4.2,10);assert.equal(video.currentTime,4.2);assert.equal(pauses,3);
  assert.equal(workspace.seek(video,NaN,10),false);assert.equal(video.currentTime,4.2);
});

test('comparison uses exactly the selected output, including unfinished older previews',()=>{
  const task={reference_url:'/original.mp4',video_url:'/wrong-current.mp4'};
  const html=workspace.comparison(task,{number:1,preview_url:'/old-preview.mp4'});
  assert.match(html,/data-comparison-reference[^>]+src="\/original.mp4"/);
  assert.match(html,/data-result-preview[^>]+src="\/old-preview.mp4"/);
  assert.doesNotMatch(html,/wrong-current/);assert.match(html,/편집 미리보기/);
  assert.match(workspace.comparison(task,{number:2,video_url:'/final.mp4',preview_url:'/preview.mp4'}),/data-result-preview[^>]+src="\/final.mp4"/);
});

test('missing media yields explicit guidance and no empty video elements',()=>{
  const html=workspace.comparison({}, {number:1});
  assert.match(html,/원본 영상이 없습니다/);assert.match(html,/이 버전의 영상은 아직 없습니다/);
  assert.doesNotMatch(html,/<video/);
});

test('owned-only output shows the selected video without a missing benchmark panel',()=>{
  const task={creation_mode:'self_shot',reference_url:'/unused-reference.mp4'};
  const html=workspace.comparison(task,{number:1,video_url:'/own-final.mp4'});
  assert.match(html,/data-owned-output/);
  assert.match(html,/data-result-preview[^>]+src="\/own-final.mp4"/);
  assert.equal((html.match(/<video /g)||[]).length,1);
  assert.doesNotMatch(html,/data-comparison-reference|원본 영상이 없습니다|원본과 우리 영상 비교/);
});

test('caption workspace renders a real shot strip and usable seek control from the edit plan',()=>{
  const e={id:'e1',duration:10,clean_preview_url:'/base.mp4',plan:{duration:10,voice:{duration:9.5},cues:[{id:'c1',text:'대사',start:1,end:3}],beats:[{id:'b1',cue_id:'c1',text:'대사',start:0,end:5,selected_shot_id:'s1'}],shots:[{id:'s1',thumbnail_url:'/shot.jpg'}]}};
  const html=context.window.CaptionEditor.markup({feedback:{}},e);
  assert.match(html,/data-timeline-seek[^>]+max="10"/);
  assert.match(html,/data-timeline-scene="0"/);assert.match(html,/src="\/shot.jpg"/);
  assert.match(html,/사용된 TTS · 9.5초/);assert.doesNotMatch(html,/waveform/);
  assert.match(html,/data-field="caption:b1"/);assert.match(html,/data-pf="export-edit"/);
  assert.doesNotMatch(context.window.CaptionEditor.markup({},null),/data-timeline-seek/);
});
