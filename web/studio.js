/* Production studio: manual reviews and automatic top-two jobs share durable versions. */
(() => {
  'use strict';
  const $ = (s, p=document) => p.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.HotpostDisplay.theme($('#theme-toggle'));
  if(!document.documentElement.dataset.theme)document.documentElement.dataset.theme=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
  let tasks=[], selectedId=null, requestedId=new URLSearchParams(location.search).get('work'), filter='all', tab='script', dirty=false, saving=false, timer, saveTimer, lastRevision=-1, activeEditId=null;
  const current=()=>tasks.find(t=>t.id===selectedId);
  const board=window.StudioBoard.mount($('#work-list'),$('#overview'));
  const updateJourney=window.StudioBoard.mountJourney($('#drawer-journey'));
  $('#board-stages').innerHTML=[['attention','내가 확인할 영상'],['working','제작 중'],['finished','완성 영상']].map(([id,title],i)=>`<button data-jump-stage="${id}"><span>${String(i+1).padStart(2,'0')}</span>${title}</button>`).join('');
  const panels=new Map(), memories=new Map();
  let selecting=false;
  const description=t=>window.StudioBoard.describe(t);
  const workspaceTab=value=>['original','script','voice'].includes(value)?'script':['edit','results','export'].includes(value)?'edit':value;
  document.addEventListener('production-draft',()=>{if(current())renderHero(current(),description(current()));});
  function updateDrawerHeader(){
    const t=current();if(!t)return;
    $('#drawer-title').textContent=window.StudioBoard.title(t);
    $('#drawer-code').textContent='터진게시물 → 우리 영상 제작';
    const d=description(t);
    $('#drawer-status').textContent=`${d.phase} · ${d.stageName} · ${d.label}`;
    updateJourney(t);applyDetailTab();$('#journey-current').textContent=d.phase;renderHero(t,d);
  }
  function renderHero(t,d){
    const local=JSON.parse(localStorage.getItem('production-feedback-'+t.id)||'{}');const pending=Object.keys(local).some(k=>/^(script$|speed$|pronunciation$|source:|caption:|start:|end:)/.test(k))||Object.keys(t.feedback||{}).length;
    const next=d.steps.find((s,i)=>i>d.currentIndex&&s.state!=='done');
    const empty=d.stage==='sources'&&!t.sources.length;
    const title=d.complete&&pending?'기존 영상 완성 · 수정 내용 반영 전':d.complete?'완성 영상을 확인하세요':empty?'영상만 넣으면, 다음 단계로':d.stage==='sources'?'준비된 영상으로 이어가세요':d.stage==='script'?'우리만의 대본을 다듬을 차례':d.stage==='voice'?'목소리와 발음을 확인할 차례':d.stage==='edit'?'장면과 자막을 완성할 차례':d.stage==='export'?'완성 영상을 준비하고 있어요':'원본 내용을 확인하고 있어요';
    const action=empty?'＋ 직접 영상 넣기':d.complete?'완성 영상 보기 →':d.stage==='sources'?'영상 선택하고 이어가기 →':'현재 단계 작업하기 →';
    const html=`<div class="hero-stage-ring" style="--stage-angle:${d.done/6*360}deg" aria-label="6단계 중 ${d.done}단계 완료"><span><strong>${d.complete?'✓':{sources:1,script:2,edit:3}[workspaceTab(d.tab)]}</strong><small>${d.complete?'제작 완료':'/ 3 작업'}</small></span></div><div class="hero-copy"><div class="hero-state"><span class="hero-status ${d.state}">${d.state==='running'?'<i class="activity-dot" aria-hidden="true"></i>':''}${esc(d.complete&&pending?'수정 중 · 이전 영상 보관됨':d.label)}</span><span>${esc(d.stageName)}</span></div><h3>${title}</h3><p role="status">${esc(d.message)}</p><div class="hero-actions"><button class="primary" data-focus-current>${action}</button>${t.error&&!empty?'<button class="secondary" data-action="retry">다시 시도</button>':''}<span class="hero-next">${next?'다음 → '+esc(next.label):'마지막 단계 · 완성본 확인'}</span></div></div><details class="hero-controls"><summary aria-label="제작 제어">⋯</summary>${t.automation&&t.status!=='completed'?`<button class="secondary" data-action="${t.automation.active?'pause-auto':'resume-auto'}">${t.automation.active?'자동 진행 중지':'자동 진행 재개'}</button>`:'<span>제작 완료</span>'}</details>`;
    const hero=$('#work-hero');
    if(hero._markup!==html){const open=hero.querySelector('.hero-controls')?.open;hero.innerHTML=html;hero._markup=html;if(open)hero.querySelector('.hero-controls').open=true;}
  }
  function applyDetailTab(panel=$('#detail')){
    if(panel!==$('#detail'))return;
    tab=workspaceTab(tab);
    const stage=description(current());
    $('#detail-tabs').querySelectorAll('button').forEach((b,i)=>{
      b.setAttribute('aria-pressed',String(b.dataset.detailTab===tab));
      const steps=stage.steps.filter(s=>workspaceTab(s.tab)===b.dataset.detailTab),active=steps.some(s=>s.current),done=steps.every(s=>s.state==='done');
      b.dataset.state=active?'current':done?'done':'pending';b.dataset.activity=active?stage.state:'';
      if(active)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');
      const status=b.querySelector('.glass-step-status');if(status)status.textContent=active?stage.label:done?'완료':'예정';
    });
    $('#work-drawer').dataset.view=tab;
    panel.querySelectorAll('[data-pf-section], [data-legacy-section]').forEach(el=>{el.hidden=workspaceTab(el.dataset.pfSection||el.dataset.legacySection)!==tab;});
    if(current()?.automation?.protocol===2){
      const summary=panel.querySelector('.pf-summary'), editor=panel.querySelector('.pf-editor');
      if(summary)summary.hidden=tab!=='edit';if(editor)editor.hidden=false;
      const actionbar=panel.querySelector('.pf-actionbar');if(actionbar)actionbar.hidden=tab==='edit'||tab==='sources'&&['sources','transcript'].includes(description(current()).stage);
    }
    const flow=panel.querySelector('#legacy-flow');if(flow)flow.hidden=tab!=='edit';
    panel.querySelectorAll('video,audio').forEach(m=>{if(m.closest('[hidden]'))m.pause();});
  }
  function rememberPanel(){
    if(!selectedId)return;
    const panel=$('#detail');panel.querySelectorAll('video,audio').forEach(m=>m.pause());
    panels.set(selectedId,panel);memories.set(selectedId,{tab,activeEditId,lastRevision,scroll:$('#drawer-scroll').scrollTop});
  }
  function showCompletedVideo(){
    tab='edit';applyDetailTab();
    const output=$('.pf-summary > video');if(output){output.scrollIntoView({block:'start'});output.focus({preventScroll:true});}
  }
  async function openWork(id){
    if(selecting||!tasks.some(t=>t.id===id))return;
    selecting=true;
    try{
      if(dirty)await saveScript();
      let restoreScroll=null;
      if(selectedId!==id){
        rememberPanel();
        const old=$('#detail'),panel=panels.get(id)||document.createElement('section');
        panel.id='detail';panel.setAttribute('aria-label','작업 상세');old.replaceWith(panel);
        selectedId=id;const memory=memories.get(id);
        tab=memory?.tab||description(current()).tab;activeEditId=memory?.activeEditId||null;lastRevision=memory?.lastRevision??-1;dirty=false;
        if(!panel.childNodes.length||lastRevision!==current().revision&&!panel._legacyEditing)renderDetail();
        applyDetailTab();restoreScroll=memory?.scroll||0;
      }
      $('#work-drawer').hidden=false;$('#journey-panel').open=!matchMedia('(max-width:750px)').matches;updateDrawerHeader();syncDrawerMode();
      if(restoreScroll!==null)$('#drawer-scroll').scrollTop=restoreScroll;
      const url=new URL(location.href);url.searchParams.set('work',id);history.replaceState(null,'',url);
      renderList();$('#drawer-title').focus({preventScroll:true});
    }catch(e){toast(e.message);}finally{selecting=false;}
  }
  async function closeWork(){
    if(selecting)return;selecting=true;
    try{
      if(dirty)await saveScript();rememberPanel();const id=selectedId;selectedId=null;
      $('#work-drawer').hidden=true;syncDrawerMode();
      const url=new URL(location.href);url.searchParams.delete('work');history.replaceState(null,'',url);
      renderList();const button=[...$('#work-list').querySelectorAll('[data-work]')].find(b=>b.dataset.work===id);
      (button||$('#search')).focus({preventScroll:true});
    }catch(e){toast(e.message);}finally{selecting=false;}
  }
  function syncDrawerMode(){
    const drawer=$('#work-drawer'),modal=!drawer.hidden&&(drawer.classList.contains('expanded')||matchMedia('(max-width:750px)').matches);
    $('main').inert=modal;$('.rail').inert=modal;
    document.body.style.overflow=modal?'hidden':'';
    drawer.setAttribute('role',modal?'dialog':'complementary');
    if(modal)drawer.setAttribute('aria-modal','true');else drawer.removeAttribute('aria-modal');
  }
  const revision=(t, collection, id)=>t[collection].find(r=>r.id===id);
  const time = n => `${Math.floor(n/60).toString().padStart(2,'0')}:${(n%60).toFixed(1).padStart(4,'0')}`;
  const date = n => new Date(n*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'});
  function toast(message){$('#toast').textContent=window.StudioBoard.message(message);$('#toast').hidden=false;clearTimeout(timer);timer=setTimeout(()=>$('#toast').hidden=true,4500);}
  async function api(path,body){const r=await fetch('/api/studio'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});const data=await r.json();if(!r.ok)throw new Error(window.StudioBoard.message(data.error,'요청을 처리하지 못했어요. 잠시 후 다시 시도하세요.'));return data;}
  function updateTask(t){const index=tasks.findIndex(x=>x.id===t.id);if(index>=0)tasks[index]=t;else tasks.unshift(t);renderList();updateDrawerHeader();}
  async function action(kind,data={},options={}){
    const t=current();if(!t)return;
    try{const result=await api(`/${t.id}/${kind}`,{revision:t.revision,...data});updateTask(result);if(!options.quiet){toast(options.message||'저장했습니다.');renderDetail();}return result;}
    catch(e){toast(e.message);if(!options.quiet)await refresh();throw e;}
  }
  function renderList(){
    $('#total-count').textContent=tasks.length;$('#rail-count').textContent=tasks.length;
    const n=board.render(tasks,{selectedId,filter,query:$('#search').value});
    $('#board-empty').hidden=n>0;
    $('#board-empty').textContent=tasks.length?'조건에 맞는 작업이 없습니다. 검색어나 필터를 바꿔보세요.':'아직 제작 중인 영상이 없습니다. 소재 탐색에서 영상을 추가하세요.';
  }
  function renderDetail(){
    const t=current();const panel=$('#detail');panel.hidden=!t;if(!t)return;
    if(t.automation?.protocol===2){lastRevision=t.revision;window.ProductionFlow.mount(panel,t,{editor:true,onUpdate:updateTask,onRender:()=>applyDetailTab(panel),onTab:next=>{tab=next;applyDetailTab(panel);$('#drawer-scroll').scrollTop=0;}});applyDetailTab(panel);return;}
    panel._legacyEditing=false;
    const openDetails=Array.from(panel.querySelectorAll('details[open]')).map(d=>d.querySelector('summary')?.textContent);
    lastRevision=t.revision;
    const selectedEdit=revision(t,'edits',activeEditId)||revision(t,'edits',t.edit_id);
    panel.innerHTML=`<div class="detail-head"><div><div class="eyebrow">우리 영상 제작</div><h2>${esc(window.StudioBoard.title(t))}</h2><p>작업과 모든 버전이 자동 저장됩니다 · 마지막 저장 ${date(t.updated)}</p></div><div class="detail-actions"><button class="secondary" data-action="capcut" ${selectedEdit?'':'disabled'}>${selectedEdit?'CapCut에서 직접 편집 ↗':'CapCut · 초안 생성 후 이용'}</button></div></div>
    <div class="stepper"><button data-tab="script" class="${tab==='script'?'on':''}">1. 대본 검토 ${t.approved_script_id?'✓':''}</button><span class="connector">→</span><button data-tab="voice" class="${tab==='voice'?'on':''}">2. 음성 검토 ${t.approved_voice_id?'✓':''}</button><span class="connector">→</span><button data-tab="edit" class="${tab==='edit'?'on':''}">3. 초안 검토</button></div>
    ${t.error?`<div class="notice error">${esc(window.StudioBoard.message(t.error))} <button class="quiet" data-action="retry">중단 단계부터 재시도</button></div>`:''}
    <div id="legacy-flow"></div><div data-legacy-section="results">${automationPanel(t)}</div>
    <div data-legacy-section="sources"><div class="panel"><h3>직접 영상 넣기</h3><div data-upload-widget></div><button class="primary" data-action="use-sources" ${t.sources.length&&['sources','transcript'].includes(description(t).stage)?'':'disabled'}>보유 영상으로 제작 이어가기 →</button></div>${sourceSearchPanel(t)}<div class="panel"><h3>확보한 소스 ${t.sources.length}개</h3><div class="source-strip">${t.sources.map(src=>`<video src="${esc(src.url)}" controls preload="none"></video>`).join('')}</div></div></div>
    <div data-legacy-section="original" class="panel">${window.ProductionFlow.originalPanel(t,true).replace('data-pf="save-original"','data-action="save-original"')}</div><div data-legacy-section="script">${scriptPanel(t)}</div><div data-legacy-section="voice">${voicePanel(t)}</div><div data-legacy-section="edit">${editPanel(t,selectedEdit)}</div>`;
    window.ProductionFlow.mount($('#legacy-flow'),t,{onUpdate:updateTask});
    window.SourceUpload.bind(panel,t,result=>{updateTask(result);},()=>{panel._legacyEditing=false;renderDetail();});
    panel.querySelectorAll('details').forEach(d=>{if(openDetails.includes(d.querySelector('summary')?.textContent))d.open=true;});
    const original=$('[data-field=original]',panel);if(original){const draft=localStorage.getItem('studio-original-'+t.id);if(draft!==null){original.value=draft;panel._legacyEditing=true;}}
    const textarea=$('#script-editor');
    if(textarea){const local=JSON.parse(localStorage.getItem('studio-draft-'+t.id)||'null');if(local&&local.base===t.script_id&&local.text!==textarea.value){textarea.value=local.text;dirty=true;$('#save-status').textContent='이 기기에 저장된 수정 내용 복구됨';}}
    applyDetailTab(panel);
    const video=$('#preview-video');if(video)video.addEventListener('timeupdate',()=>{const n=video.currentTime;panel.querySelectorAll('.beat').forEach(b=>b.classList.toggle('active',n>=Number(b.dataset.start)&&n<Number(b.dataset.end)));});
  }
  function automationPanel(t){
    if(!t.automation)return '';
    const a=t.automation, names={refresh_sources:'소스 추가 수집',prepare:'자료 확보',rewrite:'대본 재가공',voice:'음성 생성',edit:'리뷰 영상 편집',register:'CapCut 프로젝트 등록',completed:'영상 리뷰 준비 완료'};
    return `<div class="notice"><b>자동 제작 · 선정 ${a.rank}위</b> · ${esc(a.policy)}<p>${esc(window.StudioBoard.message(t.message))}${t.progress?' · '+Math.round(t.progress)+'%':''}</p><p>대본·음성을 자동 선택해 진행합니다. 사람의 최종 검토 전입니다. ${a.assessment?.status==='provisional'?'성과 판정: 잠정 후보':''}</p>${a.stage==='completed'?'<b>CapCut 프로젝트: '+esc(revision(t,'edits',t.edit_id)?.draft_name||'')+'</b>':`<button class="quiet" data-action="${a.active?'pause-auto':'resume-auto'}">${a.active?'자동 진행 중지':'자동 진행 재개'}</button>`}<details><summary>단계별 진행 기록</summary>${(t.events||[]).filter(e=>['created','automatic_stage','failed'].includes(e.kind)||e.kind.endsWith('_finished')).slice().reverse().map(e=>`<p>${date(e.created)} · ${esc(e.detail.message||names[e.kind.replace('_finished','')]||({created:'제작실 등록',failed:'확인 필요'})[e.kind]||e.kind)} ${esc(window.StudioBoard.message(e.detail.error,''))}</p>`).join('')}</details></div>`;
  }
  function sourceSearchPanel(t){
    const a=t.source_audit, run=t.source_search, busy=(t.jobs||[]).some(j=>['prepare','refresh_sources'].includes(j.kind)&&['running','queued'].includes(j.status));
    const names={ko:'한국어',en:'영어',zh:'중국어',image:'이미지'}, statuses={timeout:'시간 초과',results:'후보 발견',no_results:'결과 없음',login_required:'로그인 필요',captcha:'사람 확인 필요',rate_limited:'요청 제한',cooldown:'재시도 대기',error:'실패',http_error:'응답 오류',started:'시도 중'};
    const rejects={download_failed:'다운로드 실패',invalid_duration:'길이 기준 미충족',heavy_text_overlay:'과도한 자막',low_product_or_scene_similarity:'주제·장면 유사도 부족',title_query_mismatch:'제목·검색어 불일치',low_resolution:'해상도 부족',not_probed:'검사 예산 소진',verification_failed:'검사 실패',platform_budget_exhausted:'플랫폼 시간 예산 소진',platform_cooldown:'플랫폼 요청 제한'};
    return `<div class="notice"><div class="row"><b>소스 영상 · 보유 ${t.sources.length}개</b><button class="quiet" data-action="refresh-sources" ${busy?'disabled':''}>${busy?'자료 수집 중':'다국어 추가 수집'}</button></div>${run?`<p>${esc(window.StudioBoard.message(run.message))} · ${Math.round(run.progress||0)}%</p>`:''}${a?`<details><summary>검색 언어·플랫폼·선택 결과 확인</summary><p>최근 수집 분류 통과 ${a.selected}개${a.usable!==undefined?` · 제작 가능 ${a.usable}개 / 추가 확인 ${a.needs_review}개`:""}${a.target?' / 목표 '+a.target+'개':''}${a.stop_reason?' · 중단 사유: '+esc(({time_limit:'전체 시간 예산 소진',attempt_limit:'다운로드 시도 상한',probe_limit:'다운로드 검사 상한'})[a.stop_reason]||a.stop_reason):''}</p><p>${Object.entries(a.platforms).map(([name,n])=>`${esc(name)}: 후보 ${n.candidates} → 다운로드 ${n.received} → 채택 ${n.selected}`).join('<br>')}</p><p>${Object.entries(a.rejections).map(([reason,n])=>`${esc(rejects[reason]||(reason.startsWith('duplicate_of:')?'중복 영상':reason))} ${n}건`).join(' · ')}</p><p>${Object.entries(a.download_errors||{}).map(([reason,n])=>`${esc(reason)} ${n}건`).join(' · ')}</p><details><summary>계획한 검색어 ${(a.planned_queries||[]).length}개</summary>${(a.planned_queries||[]).map(q=>`<p>${esc(names[q.language]||q.language)} · ${esc(q.query)}</p>`).join('')}</details><details><summary>실제 검색 실행 기록</summary>${a.execution_audit_available?(a.searches||[]).map(q=>`<p>${esc(q.provider==='browser-worker'?'브라우저 검색':q.provider)} · ${esc(names[q.language]||q.language)} · ${esc(q.query)} → ${esc(statuses[q.status]||q.status)} (${q.candidates||0}개)</p>`).join(''):'이전 수집에는 개별 검색 실행 기록이 없습니다.'}</details>${a.notes?.length?`<details><summary>수집 진단</summary>${a.notes.map(n=>`<p>${esc(n)}</p>`).join('')}</details>`:''}</details>`:''}</div>`;
  }
  function scriptPanel(t){
    const s=revision(t,'scripts',t.script_id);
    if(!s)return `<div class="panel pending"><span class="spinner"></span><h3>자료와 추천 대본을 준비하고 있어요</h3>자료 확보가 완료되면 여기에서 대본을 검토할 수 있습니다.</div>`;
    const proposals=t.proposals.filter(p=>p.script_id===s.id);
    return `<div class="detail-grid"><div class="panel"><h3>원본과 참고 자료</h3><p class="muted">원본의 매력을 참고하되 새로운 문장으로 구성합니다.</p><p>원본 발화는 2단계에서 확인하고 교정할 수 있어요.</p><div class="source-strip">${t.sources.map((src,i)=>`<video src="${esc(src.url)}#t=1" controls preload="metadata" title="소스 ${i+1}"></video>`).join('')}</div><a class="muted" href="https://www.instagram.com/p/${encodeURIComponent(t.shortcode)}/" target="_blank" rel="noopener">원본 게시물 보기 ↗</a><div class="subsection"><h3>대본 버전</h3><div class="version-list">${t.scripts.slice().reverse().map((v,i)=>`<div class="version-item"><div>버전 ${t.scripts.length-i} ${v.id===s.id?'<span class="pill draft_review">현재</span>':''}<br><small>${date(v.created)} · ${{manual:'직접 수정',recommended:'AI 추천',automatic_script_auto:'자동 선택 대본',ai_proposal:'AI 수정',restored:'이전 버전 복원'}[v.origin]||v.origin}</small></div><button data-restore="${v.id}" ${v.id===s.id?'disabled':''}>복원</button></div>`).join('')}</div></div></div>
    <div class="panel"><div class="row"><h3>추천 대본</h3><span class="pill ${t.approved_script_id===s.id?'draft_review':'script_review'}">${t.approved_script_id===s.id?(t.automation?.script_selection?.script_id===s.id?'자동 선택':'승인 완료'):'검토 대기'}</span></div><p class="muted">대본을 수정하면 음성과 편집을 다시 만들어야 합니다. 이전 대본은 버전 목록에 보존됩니다.</p><textarea id="script-editor" aria-label="대본 편집">${esc(s.text)}</textarea><div class="editor-footer"><small id="save-status">저장됨 · ${s.text.length}자</small><button class="quiet" data-action="save-script">저장</button><button class="primary" data-action="approve-script" ${t.approved_script_id===s.id?'disabled':''}>대본 승인 · 음성 생성 →</button></div>
    <button class="quiet" data-action="check-script">현재 문장 검사</button><div id="script-review" aria-live="polite"></div>
    <div class="subsection"><h3>AI와 함께 다듬기</h3><p class="muted">수정안을 비교한 뒤 적용합니다. 직접 고친 대본은 보존됩니다.</p><textarea class="request" id="script-request" placeholder="예: 첫 문장을 더 궁금하게, 설명은 자연스러운 말투로 바꿔줘" aria-label="대본 AI 수정 요청"></textarea><div class="editor-footer"><small>${t.jobs.some(j=>j.kind==='proposal'&&['queued','running'].includes(j.status))?'AI가 수정안을 준비 중입니다…':''}</small><button class="secondary" data-action="propose-script">수정안 만들기</button></div></div>
    ${proposals.slice().reverse().map(p=>`<div class="proposal"><h3>${esc(p.summary)}</h3><div class="editor-footer"><small>직접 비교한 뒤 적용합니다</small><button class="secondary" data-compare="${p.id}">변경안 비교</button></div></div>`).join('')}</div></div>`;
  }
  function voicePanel(t){
    const s=revision(t,'scripts',t.script_id),v=revision(t,'voices',t.voice_id);
    const busy=t.status==='voice_generating';
    return `<div class="detail-grid"><div class="panel"><h3>${t.automation?.script_selection?.script_id===s?.id?"자동 선택 대본":"승인 대본"}</h3><p class="muted">이 버전의 대본으로 생성한 음성입니다.</p><div class="reference-box">${esc(s?.text||'대본을 먼저 승인해 주세요.')}</div><div class="subsection"><h3>음성 이력 · 전후 비교</h3><div class="version-list">${t.voices.slice().reverse().map((a,i)=>`<div class="version-item" style="display:block"><div class="row"><b>음성 ${t.voices.length-i}</b><small>${a.script_id===t.script_id?'현재 대본':'이전 대본'} · ${a.duration.toFixed(1)}초</small></div><audio controls preload="none" src="${esc(a.path_url)}" style="width:100%;height:34px;margin-top:10px"></audio></div>`).join('')||'<p class="muted">생성된 음성이 여기에 보관됩니다.</p>'}</div></div></div>
    <div class="panel"><div class="row"><h3>내 목소리 확인하기</h3><span class="pill voice_review">${busy?'음성 생성 중':v?(t.automation?.voice_selection?.voice_id===v.id?'자동 선택 · 청취 가능':'청취 후 승인'):'대본 준비 대기'}</span></div><p class="muted">목소리와 발음, 문장 사이의 호흡을 확인해 주세요.</p>
    ${busy?'<div class="pending"><span class="spinner"></span><h3>내 목소리로 읽고 있어요</h3>창을 닫아도 작업은 계속됩니다. 다른 대본을 먼저 검토해도 됩니다.</div>':v?`<div class="voice-player"><div class="waveform">${Array.from({length:42},(_,i)=>`<i style="height:${10+Math.abs(Math.sin(i*1.8))*34}px"></i>`).join('')}</div><audio id="voice-player" controls preload="metadata" src="${esc(v.path_url)}"></audio><h4>음성 ${t.voices.indexOf(v)+1} · ${v.duration.toFixed(1)}초</h4><p>최종 사용 음성 · ${v.speed.toFixed(2)}배속 · 선택한 음성 속도로 편집합니다</p></div><div class="editor-footer"><small>${t.approved_voice_id===v.id?'이 음성으로 편집 중이거나 초안이 준비되었습니다.':'괜찮다면 영상 편집을 시작하세요.'}</small><button class="primary" data-action="approve-voice" ${t.approved_voice_id===v.id?'disabled':''}>음성 승인 · 영상 편집 →</button></div>`:'<div class="pending">대본을 승인하면 음성 생성이 시작됩니다.</div>'}
    <div class="subsection"><h3>다시 만들어 듣기</h3><p class="muted">기존 VoiceBench 목소리·엔진 설정을 유지합니다. 속도는 승인 전 음성에 적용됩니다. 동일 대본은 기존 생성 결과를 재사용할 수 있습니다. 구간별 재생성·감정 지시는 현재 제공하지 않습니다.</p><div class="editor-footer"><label>말하기 속도 <select id="voice-speed"><option value="1">기본 1.00×</option><option value=".95">여유롭게 0.95×</option><option value="1.05">조금 빠르게 1.05×</option><option value="1.12">빠르게 1.12×</option></select></label><button class="secondary" data-action="regenerate-voice" ${busy||!t.approved_script_id?'disabled':''}>속도 적용 · 음성 다시 준비</button></div></div></div></div>`;
  }
  function editPanel(t,e){
    if(!e)return `<div class="panel pending">${t.status==='editing'?'<span class="spinner"></span><h3>자막과 장면을 맞추고 있어요</h3>선택한 음성에 맞춰 싱크와 강조를 구성합니다.':'<h3>음성을 승인하면 초안을 만들어요</h3>대본과 음성 검토를 먼저 완료해 주세요.'}</div>`;
    const p=e.plan,busy=t.status==='editing',historical=e.id!==t.edit_id;
    return `<div class="preview-grid"><div class="preview-player"><video id="preview-video" src="${esc(e.preview_url)}" controls playsinline preload="metadata" poster="${esc(e.cover_url)}"></video><p>첫 프레임 썸네일 포함 · ${e.duration.toFixed(1)}초<br>초안 ${t.edits.indexOf(e)+1} / ${t.edits.length} · ${e.review_count}개 장면 확인 필요</p><a class="button secondary" href="${esc(e.preview_url)}" download="shorts-preview.mp4" style="display:block;text-align:center">영상 다운로드 ↓</a></div><div class="panel"><div class="row"><h3>초안 검토</h3><select id="edit-version" aria-label="편집 버전">${t.edits.map((a,i)=>`<option value="${a.id}" ${a.id===e.id?'selected':''}>초안 ${i+1} · ${date(a.created)} ${a.id===t.edit_id?'(현재)':'(이전)'}</option>`).join('')}</select></div>
    ${historical?'<div class="notice">이전 버전을 보고 있습니다. 구간 수정은 현재 버전에서 할 수 있습니다.</div>':''}
    ${busy?'<div class="notice"><span class="spinner"></span> 새 버전을 만드는 동안 현재 초안을 계속 볼 수 있습니다.</div>':''}
    ${t.candidate_requests?.length?`<div class="notice">장면 교체 요청을 확인했습니다. 아래 표시된 구간의 후보를 비교해 선택하세요.</div>`:''}${p.warnings.map(w=>`<div class="notice">${esc(w)}</div>`).join('')}
    <p class="muted">${esc(p.preview_limitations.join(' '))}</p>
    <div class="subsection"><h3>이 구간, 이렇게 바꿔주세요</h3><div class="timing"><label>시작 <input id="selection-start" type="number" min="0" step=".01" value="0"></label><label>끝 <input id="selection-end" type="number" min="0" max="${p.duration}" step=".01" value="${p.duration.toFixed(2)}"></label><button class="quiet" data-action="select-playing">현재 장면 선택</button></div><textarea class="request" id="edit-request" placeholder="예: 이 장면은 다른 후보를 보여주고, 마지막 대박이에요 부분은 더 강하게 강조해줘" aria-label="영상 구간 수정 요청"></textarea><div class="editor-footer"><small>장면 교체는 후보를 보고 직접 선택합니다</small><button class="secondary" data-action="request-edit" ${busy||historical?'disabled':''}>수정 요청</button></div></div>
    <div class="subsection"><div class="row"><h3>장면 · 자막 · 강조</h3><span class="muted">시간을 누르면 해당 구간으로 이동</span></div>
    ${p.beats.map(b=>{const c=p.cues.find(c=>c.id===b.cue_id);return `<article class="beat ${t.candidate_requests?.includes(b.id)?'requested':''}" data-beat="${b.id}" data-start="${b.start}" data-end="${b.end}"><div class="beat-head"><button class="time-button" data-seek="${b.start}">${time(b.start)} – ${time(b.end)}</button>${b.needs_review?'<span class="pill review">대체 장면 · 확인 필요</span>':'<span class="pill draft_review">대사와 대응</span>'}</div><h4>${esc(c.text)}</h4><p>${esc(b.reason)}${t.candidate_requests?.includes(b.id)?'<br><b>장면 교체 요청 · 후보를 선택해 주세요</b>':''}</p><div class="beat-controls"><label class="muted">강조 <select data-emphasis="${b.id}" ${busy||historical?'disabled':''}><option value="0" ${b.emphasis===0?'selected':''}>없음</option><option value="1" ${b.emphasis===1?'selected':''}>분명하게</option><option value="2" ${b.emphasis===2?'selected':''}>강하게</option></select></label><button class="secondary" data-candidates="${b.id}" ${busy||historical?'disabled':''}>장면 후보 ${b.options.length}개 보기</button></div><details><summary class="muted" style="margin-top:12px;cursor:pointer">자막 문구·싱크 미세 조정 ${c.needs_review?'· 정렬 확인 필요':''}</summary><div class="timing"><input class="caption" data-cue-text="${b.id}" value="${esc(c.text)}" aria-label="자막 문구"></div><div class="timing"><label>시작 <input data-cue-start="${b.id}" type="number" step=".01" value="${c.start.toFixed(2)}"></label><label>끝 <input data-cue-end="${b.id}" type="number" step=".01" value="${c.end.toFixed(2)}"></label><button class="quiet" data-cue-save="${b.id}" ${busy||historical?'disabled':''}>구간 저장</button></div></details></article>`;}).join('')}</div></div></div>`;
  }
  async function saveScript(){const t=current(),input=$('#script-editor');if(!t||!input||!dirty)return;if(saving){await saving;if(dirty)return saveScript();return;}const text=input.value;saving=(async()=>{const saved=await action('save-script',{text},{quiet:true});dirty=input.value!==text;if(dirty){localStorage.setItem('studio-draft-'+t.id,JSON.stringify({base:saved.script_id,text:input.value}));}else{localStorage.removeItem('studio-draft-'+t.id);}$('#save-status').textContent=dirty?'수정 중…':`저장됨 · ${text.length}자`;})();try{await saving;}finally{saving=false;}}
  function showCandidates(beatId){const t=current(),e=revision(t,'edits',t.edit_id),b=e.plan.beats.find(b=>b.id===beatId);$('#candidate-caption').textContent=`“${b.text}” · 실제 확보된 장면 중에서 선택하세요.`;$('#candidates').innerHTML=b.options.map((o,i)=>{const s=e.plan.shots.find(s=>s.id===o.shot_id);return `<article class="candidate"><video src="${esc(s.video_url)}#t=${s.start},${s.end}" poster="${esc(s.thumbnail_url)}" controls preload="none"></video><h4>후보 ${i+1} <span class="pill ${o.relation==='direct'?'draft_review':'review'}">${{direct:'직접 대응',context:'제품 맥락',illustration:'대체 장면'}[o.relation]}</span></h4><p>${esc(s.observation)}<br>${esc(o.reason)}</p><button class="primary" data-choose-shot="${s.id}" data-for-beat="${b.id}">${b.selected_shot_id===s.id?'현재 장면':'이 장면 사용'}</button></article>`;}).join('');$('#candidate-dialog').showModal();}
  document.addEventListener('click',async event=>{const el=event.target.closest('button');
    if(!el){const card=event.target.closest('[data-work-card]');if(card&&!event.target.closest('a,input,select,video,audio,details'))await openWork(card.dataset.workCard);return;}
    try{
    if(el.hasAttribute('data-focus-current')){tab=description(current()).tab;applyDetailTab();$('#drawer-scroll').scrollTop=0;if(description(current()).complete){const output=$('.pf-summary > video');if(output){output.scrollIntoView({block:'start'});output.focus({preventScroll:true});}return;}const upload=$('[data-upload-open]');if(tab==='sources'&&upload){const choice=$('[data-field^="source:"]');if(current().sources.length&&choice)choice.focus();else upload.focus();}else $('#detail').querySelector('[data-pf-section="'+tab+'"] textarea, [data-pf-section="'+tab+'"] button')?.focus();return;}
    if(el.dataset.jumpStage){const lane=$(`[data-stage="${el.dataset.jumpStage}"]`);$('#work-list').scrollTo({left:lane.getBoundingClientRect().left-$('#work-list').getBoundingClientRect().left+$('#work-list').scrollLeft,behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});return;}
    if(el.dataset.work){await openWork(el.dataset.work);if(current()&&description(current()).complete)showCompletedVideo();return;}
    if(el.id==='close-work'){await closeWork();return;}
    if(el.id==='expand-work'){$('#work-drawer').classList.toggle('expanded');const full=$('#work-drawer').classList.contains('expanded');el.textContent=full?'패널로 축소':'전체화면';el.setAttribute('aria-pressed',String(full));syncDrawerMode();return;}
    if(el.dataset.filter){filter=el.dataset.filter;$('#filters').querySelectorAll('button').forEach(b=>b.classList.toggle('selected',b===el));renderList();return;}
    if(el.dataset.detailTab||el.dataset.tab){if(dirty)await saveScript();tab=el.dataset.detailTab||el.dataset.tab;applyDetailTab();$('#drawer-scroll').scrollTop=0;return;}
    if(el.dataset.referenceSeek){const video=$('[data-reference-preview]');if(video)video.currentTime=Number(el.dataset.referenceSeek);return;}
    if(el.dataset.seek){$('#preview-video').currentTime=Math.ceil(Number(el.dataset.seek)*30)/30+.001;}
    if(el.dataset.candidates)showCandidates(el.dataset.candidates);
    if(el.dataset.restore){await saveScript();await action('restore-script',{script_id:el.dataset.restore});dirty=false;}
    if(el.dataset.compare){const t=current(),s=revision(t,'scripts',t.script_id),p=t.proposals.find(p=>p.id===el.dataset.compare);$('#script-comparison').innerHTML=`<p class="muted">${esc(p.summary)}</p><div class="compare"><div><b>현재 대본</b><br>${esc(s.text)}</div><div><b>AI 수정안</b><br>${esc(p.text)}</div></div><div class="editor-footer"><small>적용하면 새 버전으로 저장됩니다. 이전 대본은 복원할 수 있습니다.</small><button class="primary" data-proposal="${p.id}">이 수정안 적용</button></div>`;$('#script-dialog').showModal();}
    if(el.dataset.proposal){$('#script-dialog').close();await saveScript();await action('apply-proposal',{proposal_id:el.dataset.proposal});}
    if(el.dataset.chooseShot){$('#candidate-dialog').close();await action('revise-edit',{edit_id:current().edit_id,changes:[{beat_id:el.dataset.forBeat,shot_id:el.dataset.chooseShot}]},{message:'선택한 장면으로 새 초안을 만듭니다.'});}
    if(el.dataset.cueSave){const id=el.dataset.cueSave;await action('revise-edit',{edit_id:current().edit_id,changes:[{beat_id:id,text:$(`[data-cue-text="${id}"]`).value,start:Number($(`[data-cue-start="${id}"]`).value),end:Number($(`[data-cue-end="${id}"]`).value)}]});}
    const kind=el.dataset.action;if(!kind)return;el.disabled=true;
    if(['check-script','propose-script'].includes(kind)&&localStorage.getItem('studio-original-'+current().id)!==null){toast('원본 발화 교정본을 먼저 저장하세요.');el.disabled=false;return;}
    if(kind==='save-original'){const t=current(),input=$('[data-field=original]'),text=input.value;await action(kind,{text,base_text:t.reviewed_original_text??t.original_text??''},{quiet:true});if(input.value===text)localStorage.removeItem('studio-original-'+t.id);toast('교정본을 저장했습니다. 다음 AI 수정 요청에 사용됩니다.');}
    else if(kind==='check-script'){
      const taskId=current().id,text=$('#script-editor').value;
      const result=await api('/'+taskId+'/check-script',{text});
      if(current()?.id===taskId&&$('#script-editor')?.value===text)$('#script-review').innerHTML=window.ProductionFlow.scriptReview(result);
      else toast('검사 중 대본이 바뀌었어요. 다시 검사해 주세요.');
    }
    else if(kind==='save-script'){await saveScript();renderDetail();}
    else if(kind==='approve-script'){await saveScript();await action(kind,{script_id:current().script_id});tab='voice';renderDetail();}
    else if(kind==='propose-script'){const request=$('#script-request').value;await saveScript();await action(kind,{request},{message:'AI 수정안을 준비합니다.'});}
    else if(kind==='approve-voice'){await action(kind,{voice_id:current().voice_id});tab='edit';renderDetail();}
    else if(kind==='regenerate-voice')await action(kind,{script_id:current().script_id,speed:Number($('#voice-speed').value)});
    else if(kind==='use-sources')await action(kind,{source_ids:current().sources.map(s=>s.id)},{message:'업로드한 영상으로 제작을 이어갑니다.'});
    else if(kind==='retry')await action(kind,{}, {message:'중단된 단계를 이어서 실행합니다.'});
    else if(kind==='refresh-sources')await action(kind,{}, {message:'추가 수집을 시작합니다. 검색 진행 상황은 제작실에 표시됩니다.'});
    else if(kind==='pause-auto'||kind==='resume-auto')await action(kind);
    else if(kind==='capcut')await action('open-capcut',{edit_id:activeEditId||current().edit_id},{message:'CapCut 초안을 준비합니다. 기존 손편집본은 보존됩니다.'});
    else if(kind==='select-playing'){const e=revision(current(),'edits',activeEditId||current().edit_id);const n=Math.min($('#preview-video').currentTime,e.plan.duration-.001);const b=e.plan.beats.find(b=>b.start<=n&&n<b.end);if(b){$('#selection-start').value=b.start.toFixed(2);$('#selection-end').value=b.end.toFixed(2);}}
    else if(kind==='request-edit')await action(kind,{edit_id:current().edit_id,request:$('#edit-request').value,start:Number($('#selection-start').value),end:Number($('#selection-end').value)},{message:'선택한 구간의 수정 요청을 처리합니다.'});
    el.disabled=false;
  }catch(_){el.disabled=false;}});
  document.addEventListener('input',event=>{if(event.target.dataset.field==='original'&&current()?.automation?.protocol!==2)localStorage.setItem('studio-original-'+current().id,event.target.value);if(event.target.closest('#detail')&&current()?.automation?.protocol!==2&&event.target.id!=='script-editor')$('#detail')._legacyEditing=true;if(event.target.id==='script-editor'){if($('#script-review'))$('#script-review').textContent='대본이 바뀌었어요. 다시 검사해 주세요.';dirty=true;const t=current();localStorage.setItem('studio-draft-'+t.id,JSON.stringify({base:t.script_id,text:event.target.value}));$('#save-status').textContent='수정 중 · 자동 저장 대기';$('[data-action="approve-script"]').disabled=false;clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveScript().catch(()=>{}),1200);}if(event.target.id==='search')renderList();});
  document.addEventListener('change',async event=>{try{if(event.target.dataset.emphasis)await action('revise-edit',{edit_id:current().edit_id,changes:[{beat_id:event.target.dataset.emphasis,emphasis:Number(event.target.value)}]});if(event.target.id==='edit-version'){activeEditId=event.target.value;renderDetail();}}catch(_){}});
  $('#close-candidates').onclick=()=>$('#candidate-dialog').close();$('#close-script-dialog').onclick=()=>$('#script-dialog').close();
  document.addEventListener('dragover',event=>{if(event.dataTransfer?.types.includes('Files'))event.preventDefault();});
  document.addEventListener('drop',event=>{if(event.dataTransfer?.types.includes('Files')&&!event.target.closest('[data-upload-widget]')){event.preventDefault();toast($('#work-drawer').hidden?'영상을 만들 작업을 먼저 선택해 주세요.':'소스 탭의 영상 업로드 영역에 파일을 놓아주세요.');}});
  window.addEventListener('beforeunload',event=>{if(tasks.some(t=>localStorage.getItem('studio-original-'+t.id)!==null)||dirty||$('#detail')._dirty||$('#detail')._uploading||[...panels.values()].some(p=>p._dirty||p._uploading)){event.preventDefault();event.returnValue='';}});
  document.addEventListener('keydown',event=>{
    if($('#work-drawer').hidden||document.querySelector('dialog[open]'))return;
    if(event.key==='Escape'){event.preventDefault();closeWork();}
    if(event.key==='Tab'&&$('#work-drawer').getAttribute('aria-modal')==='true'){
      const all=[...$('#work-drawer').querySelectorAll('button,a[href],input,textarea,select,summary,video[controls],audio[controls]')].filter(e=>!e.disabled&&e.getClientRects().length&&!e.closest('[hidden]'));
      const first=all[0],last=all.at(-1);
      if(event.shiftKey&&(document.activeElement===first||document.activeElement===$('#drawer-title'))){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  });
  window.addEventListener('resize',syncDrawerMode);
  matchMedia('(max-width:750px)').addEventListener('change',e=>{if(e.matches)$('#journey-panel').open=false;});
  let refreshing=false;
  async function refresh(){
    if(refreshing)return;refreshing=true;
    try{
      const data=await api('');tasks=data.tasks;$('#connection').hidden=true;$('#work-list').classList.remove('board-stale');renderList();updateDrawerHeader();
      if(requestedId){const id=requestedId;requestedId=null;if(tasks.some(t=>t.id===id))await openWork(id);else toast('요청한 작업을 찾을 수 없습니다.');}
      const t=current();
      if(t&&(t.automation?.protocol===2||t.revision!==lastRevision&&!dirty&&!document.activeElement.matches('textarea,input,select')&&!$('#detail')._legacyEditing&&!$('#detail')._uploading&&![...$('#detail').querySelectorAll('video,audio')].some(m=>!m.paused)))renderDetail();
      if(selectedId&&!t)await closeWork();
    }catch(e){$('#work-list').classList.add('board-stale');$('#connection').textContent='서버와 연결되지 않았습니다. 마지막으로 확인한 상태이며 입력 내용은 보존됩니다. ';$('#connection').hidden=false;}
    finally{refreshing=false;}
  }
  refresh();setInterval(refresh,3000);
})();
