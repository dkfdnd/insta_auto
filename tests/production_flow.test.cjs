const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
let parseHTML;try{({parseHTML}=require(process.env.HOTPOST_TEST_DOM||'linkedom'));}catch(_){}
function harness(){
  const {document}=parseHTML('<html><body><main id="root"></main></body></html>');
  const window={};
  const storage=new Map();
  const storageApi={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
  for(const file of ['studio-board.js','studio-workspace.js','studio-detail.js','studio/source-view.js','production-flow.js'])new Function('window','document','localStorage',fs.readFileSync(path.join(__dirname,'../web',file),'utf8'))(window,document,storageApi);
  const root=document.querySelector('#root');
  return {root,app:window.ProductionFlow};
}
function fixture(){return {id:'work',revision:1,status:'completed',run_id:'v2',latest_completed_run_id:'v2',automation:{protocol:2},sources:[],scripts:[],voices:[],edits:[],jobs:[],pipeline:['v1','v2'].map((id,i)=>({id,number:i+1,status:'completed',artifacts:{},video_url:`/${id}.mp4`,steps:['sources','transcript','script','voice','project','export'].map(key=>({key,status:'completed',download_url:`/download?run=${id}&asset=${key}`}))}))};}
test('first deep-linked mount displays and downloads the requested older complete run',{skip:!parseHTML},()=>{
  const {root,app}=harness(),t=fixture();app.mount(root,t,{selectedRun:'v1'});
  assert.equal(root._selected,'v1');assert.ok(root.querySelector('video[src="/v1.mp4"]'));
  assert.equal(!!root.querySelector('video[src="/v2.mp4"]'),false);
  assert.ok([...root.querySelectorAll('a[download]')].some(a=>a.getAttribute('href')==='/download?run=v1&asset=export'));
  // The collapsed current-job progress may link v2 assets; the displayed
  // result's prominent download must belong to v1.
  assert.equal(root.querySelector('.pf-downloads a').getAttribute('href'),'/download?run=v1&asset=export');
});
test('polling keeps a subsequent manual version choice instead of reapplying deep link',{skip:!parseHTML},()=>{
  const {root,app}=harness(),t=fixture();app.mount(root,t,{selectedRun:'v1'});
  root.querySelectorAll('video,audio').forEach(m=>{m.paused=true;});
  root._selected='v2';t.revision++;app.mount(root,t,{selectedRun:'v1'});
  assert.equal(root._selected,'v2');assert.ok(root.querySelector('video[src="/v2.mp4"]'));
});
test('unknown deep link falls back to the latest completed video',{skip:!parseHTML},()=>{
  const {root,app}=harness();app.mount(root,fixture(),{selectedRun:'absent'});
  assert.equal(root._selected,null);assert.ok(root.querySelector('video[src="/v2.mp4"]'));
});
