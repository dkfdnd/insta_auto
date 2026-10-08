/* A simple, consistent detail workspace. Rendering never selects a script,
   voice or source; existing production actions remain the state boundary. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pick=(t,list,id)=>(t[list]||[]).find(v=>v.id===id);
  function icon(name){
    const paths={bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',chevron:'<path d="m6 9 6 6 6-6"/>',text:'<path d="M4 5h16M4 12h16M4 19h10"/>',voice:'<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M6 11v2a6 6 0 0 0 12 0v-2M12 19v3"/>',check:'<path d="m5 12 4 4L19 6"/>',edit:'<path d="m15 4 5 5-11 11H4v-5ZM13 6l5 5"/>',settings:'<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>'};
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.info}</svg>`;
  }
  const key=(t,name)=>'sd-'+String(t.id).replace(/[^\w-]/g,'-')+'-'+name;
  const footageNeed=t=>t.shortcode==='DeEau5JxJfy'||/마늘/.test(t.title||'')?'다진 마늘을 준비·보관하거나 한 스푼 떠 쓰는 영상이 필요합니다.':'대본에서 말하는 핵심 동작이 담긴 영상이 필요합니다.';
  function disclosure(t,name,label,content,{open=false,kind='info'}={}){
    const id=key(t,name);
    return `<div class="sd-disclosure"><button type="button" class="sd-details-button" data-detail-toggle="${id}" aria-controls="${id}" aria-expanded="${open}">${icon(kind)}<span>${esc(label)}</span>${icon('chevron')}</button><div id="${id}" class="sd-disclosed" data-detail-panel="${id}" ${open?'':'hidden'}>${content}</div></div>`;
  }
  function view(t){
    const d=window.StudioBoard.describe(t),blockers=t.production_blockers||[];
    if(t.creation_mode==='self_shot'&&!t.self_shot?.started)return {kind:'waiting',title:'촬영 영상을 넣고 제작을 시작하세요',body:'최대 20개까지 추가한 뒤 사용할 영상을 선택하세요. 내 복제 목소리로 완성 초안까지 자동 제작합니다.',action:'sources',label:'촬영 영상 추가·선택'};
    if(d.complete)return {kind:'completed',title:'영상이 완성됐습니다',body:'완성 영상에서 재생하거나 내려받으세요.',action:null};
    if(d.state==='running')return {kind:'running',title:d.stageName+' 작업 중',body:'지금은 기다리시면 됩니다. 완료되면 결과가 자동으로 나타납니다.',action:null};
    if(d.state==='queued')return {kind:'queued',title:'제작 순서를 기다리고 있습니다',body:'지금은 따로 누를 버튼이 없습니다. 작업이 시작되면 움직이는 표시가 나타납니다.',action:null};
    if(t.source_acquisition?.hold||t.source_search?.hold)return {kind:'blocked',title:'소스 자동 수집을 중지했습니다',body:t.source_search?.message||t.message,action:'sources',label:'중지 사유·검색 조건 확인'};
    if(blockers.includes('personal_clone_unavailable'))return {kind:'blocked',title:'내 목소리를 먼저 준비해 주세요',body:'아직 내 목소리로 읽을 수 없어 제작이 멈춰 있습니다.',action:'voice-help',label:'내 목소리 준비 방법'};
    if(blockers.includes('core_footage_gap'))return {kind:'waiting',title:'핵심 장면을 자동으로 추가 확보합니다',body:'플랫폼 합산 최소 10개와 핵심 장면을 준비합니다. 대본·음성은 함께 진행할 수 있어요.',action:'sources',label:'소스 확보 현황 보기'};
    if(d.state==='error')return {kind:'error',title:d.stageName+' 작업이 멈췄습니다',body:window.StudioBoard.message(t.error),action:'retry',label:d.stageName+' 다시 시도'};
    if(d.state==='paused'||t.automation?.protocol===2&&!t.automation.active)return {kind:'paused',title:'자동 제작이 잠시 멈춰 있습니다',body:'현재 선택한 대본과 설정으로 계속 만들 수 있습니다.',action:'resume-auto',label:'이어서 영상 만들기'};
    if(!t.sources?.length)return {kind:'waiting',title:'사용할 영상을 추가해 주세요',body:'영상을 넣으면 다음 제작 단계로 이어갈 수 있습니다.',action:'sources',label:'영상 추가하기'};
    return {kind:'waiting',title:'다음 제작을 준비하고 있습니다',body:'아래에서 현재 결과를 확인할 수 있습니다.',action:null};
  }
  function scriptCard(t,{text,name='selected-script',label='내 영상에서 읽을 대본',buttonLabel='내 영상의 대본 보기',edit=true}={}){
    const script=pick(t,'scripts',t.script_id),value=text??script?.text;
    if(!value)return '';
    const content=`<article class="sd-script-card" aria-label="${esc(label)}"><header>${icon('text')}<h4>${esc(label)}</h4></header><p class="sd-script-text">${esc(value)}</p>${edit?'<button type="button" class="sd-secondary" data-pf-tab="script">대본 수정하기</button>':''}</article>`;
    return disclosure(t,name,buttonLabel,content,{kind:'text'});
  }
  function voiceHelp(t,scope){
    return disclosure(t,scope+'-voice-help','내 목소리 준비 방법 자세히 보기',`<div class="sd-help-card"><h4>한 번 준비한 내 목소리를 계속 사용합니다</h4><ol><li>본인이 말하는 녹음 파일을 준비하세요.</li><li>목소리 관리 화면의 ‘목소리 보관함’에서 녹음을 등록하세요.</li><li>자동 제작에 사용할 기본 복제 목소리 연결까지 마친 뒤 돌아오세요.</li></ol><p>등록한 녹음을 자동 제작의 기본 목소리에 연결해야 합니다. 녹음 등록 후에도 복제 기능이 준비되지 않았다면 제작은 계속 멈춰 있습니다. 기본 목소리는 임의로 다른 목소리로 바꾸지 않습니다.</p></div>`);
  }
  function status(t,scope='status'){
    const v=view(t),blocked=t.production_blockers||[];
    let action='';
    if(v.action==='voice-help')action=`<div class="sd-required-actions"><a class="sd-primary" href="http://127.0.0.1:8765/" target="_blank" rel="noopener">내 목소리 등록 화면 열기 <span class="sd-new-window">새 창</span></a><p>‘목소리 보관함’에서 본인 녹음을 등록하고 기본 복제 목소리 연결을 마쳐주세요.</p><button type="button" class="sd-secondary" data-pf="resume-auto">준비 후 제작 다시 확인</button></div>${voiceHelp(t,scope)}`;
    else if(v.action==='sources')action='<button type="button" class="sd-primary" data-pf-tab="sources">'+esc(v.label)+'</button>';
    else if(v.action)action=`<button type="button" class="sd-primary" data-pf="${v.action}">${esc(v.label)}</button>`;
    const footage=footageNeed(t);
    const secondary=blocked.includes('core_footage_gap')&&v.action!=='sources'&&!t.source_acquisition?.hold?'<div class="sd-next-task"><p>핵심 장면은 자동으로 추가 확보합니다.</p><button type="button" class="sd-secondary" data-pf-tab="sources">소스 확보 현황 보기</button></div>':'';
    const technical=window.StudioWorkspace.guidance(t);
    const extra=technical.items?.length?disclosure(t,scope+'-reason','멈춘 이유 자세히 보기',`<ul>${technical.items.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><p>${esc(technical.footer||'')}</p>`):'';
    return `<section class="sd-status" data-kind="${v.kind}" aria-label="지금 할 일"><div class="sd-status-copy"><strong>${esc(v.title)}</strong><p>${esc(v.body)}</p></div>${action}${secondary}${extra}</section>`;
  }
  function scriptSection(t,h){
    if(t.creation_mode==='self_shot'&&!t.self_shot?.started)return `<section data-pf-section="script" class="sd-stage"><h3>제작할 대본</h3><p class="sd-script-text">${esc(t.self_shot.script_mode==='manual'?t.self_shot.text:'촬영 영상을 선택하고 제작을 시작하면 제품 정보로 대본을 자동 집필합니다.')}</p><button type="button" class="sd-secondary" data-self-shot-edit>제작 정보 수정</button><button type="button" class="sd-primary" data-pf-tab="sources">촬영 영상 추가·제작 시작</button></section>`;
    const s=pick(t,'scripts',t.script_id),f=t.feedback||{},text=f.script_text??s?.text??'';
    const ai=`<label>어떻게 고칠까요?<textarea data-field="script-request" placeholder="예: 첫 문장을 더 궁금하게 바꾸고 짧게 써 주세요"></textarea></label><button type="button" class="sd-secondary" data-pf="propose-script" ${s?'':'disabled'}>수정안 만들기</button><div data-ai-status="proposal" class="pf-ai-status" role="status">${h.aiStatus(t,'proposal')}</div><div data-proposals>${(t.proposals||[]).slice().reverse().map(p=>`<details><summary>AI 수정안 보기</summary><div class="pf-compare"><div><h4>지금 대본</h4><p class="sd-script-text">${esc(p.base_text||s?.text||'')}</p></div><div><h4>수정안</h4><p class="sd-script-text">${esc(p.text)}</p></div></div><button type="button" data-pf="proposal" data-id="${esc(p.id)}">이 수정안으로 바꾸기</button></details>`).join('')}</div>`;
    const candidates=`<div class="sd-script-candidates"><h4>대본 후보</h4>${(t.script_candidates||[]).map((c,i)=>`<article class="sd-script-card"><h4>후보 ${i+1}${i===t.selected_candidate?' · 선택됨':''}</h4><p class="sd-script-text">${esc(c.text)}</p><button type="button" class="sd-secondary" data-pf="candidate" data-index="${i}">${i===t.selected_candidate?'이 대본 다시 선택':'이 대본으로 바꾸기'}</button></article>`).join('')||'<p>대본 후보가 준비되면 여기에 표시됩니다.</p>'}</div>`;
    return `<section data-pf-section="script" class="sd-stage"><header class="sd-section-title"><h3>내 대본</h3><p>아래 대본을 고친 뒤 ‘수정 내용으로 영상 만들기’를 누르면 반영됩니다.</p></header><div class="glass-writing"><div class="pf-script-state"><span class="pf-count">${f.script_text!==undefined?'수정 중 · 영상에 아직 반영 전':'선택된 대본'}</span></div><label class="sd-main-label">대본 내용<textarea maxlength="3000" data-field="script" placeholder="영상에서 읽을 대본을 입력하세요">${esc(text)}</textarea></label></div>${disclosure(t,'ai-rewrite','AI에게 대본 수정 맡기기',ai,{kind:'edit'})}${candidates}</section><section data-pf-section="original" class="sd-stage sd-reference-section">${disclosure(t,'reference',t.creation_mode==='self_shot'?'제품 정보와 집필 근거 보기':'참고할 원본 영상과 대본 보기',h.originalPanel(t,true))}</section>`;
  }
  function voiceSection(t){
    const f=t.feedback||{},run=(t.pipeline||[]).find(r=>r.id===t.run_id),inputs=run?.inputs||{};
    const voice=pick(t,'voices',t.voice_id),profile=f.voice_profile_id??inputs.voice_profile_id??voice?.voice_profile_id??'';
    const v=view(t),text=f.script_text??pick(t,'scripts',t.script_id)?.text??'';
    const audio=voice?`<div class="pf-audio-card sd-audio-card"><h4>현재 음성</h4><p>재생 버튼을 눌러 들어보세요.</p><audio controls preload="metadata" aria-label="현재 제작 음성 재생" src="${esc(voice.path_url)}"></audio></div>`:`<div class="sd-empty"><span class="sd-empty-icon">${icon('voice')}</span><h4>${v.kind==='running'&&window.StudioBoard.describe(t).stage==='voice'?'내 목소리로 읽고 있습니다':'아직 들을 음성이 없습니다'}</h4><p>음성이 완성되면 여기에서 들을 수 있습니다.</p></div>`;
    const editScript=disclosure(t,'voice-script-edit','수정하기',`<p>아래 대본을 고친 뒤 ‘수정 내용으로 영상 만들기’를 누르면 새 음성과 영상에 반영됩니다.</p><label>대본 내용<textarea maxlength="3000" data-field="script" placeholder="영상에서 읽을 대본을 입력하세요">${esc(text)}</textarea></label>`,{kind:'edit'});
    const settings=`<div data-voice-picker class="voice-picker"><div><span>읽어줄 목소리</span><strong data-current-voice></strong></div><input type="text" hidden data-field="voice-profile" value="${esc(profile)}"><button type="button" class="sd-secondary" data-choose-voice>다른 목소리 들어보고 선택</button></div><label>읽는 속도 <input data-field="speed" type="number" min="0.8" max="1.25" step="0.05" value="${f.speed??inputs.speed??1}"> 배</label>`;
    return `<section data-pf-section="voice" class="sd-stage"><header class="sd-section-title"><h3>내 목소리</h3></header>${audio}${editScript}${disclosure(t,'voice-options','목소리·속도 바꾸기',settings,{kind:'settings'})}</section>`;
  }
  function sourceNotice(t,h){
    const search=h.sourceSearchState(t),visible=search.busy||search.failed||search.missing||search.hold,id=key(t,'source-notice');
    return `<div class="sd-notification" data-source-alert ${visible?'':'hidden'}><button type="button" class="sd-notification-button" data-detail-toggle="${id}" aria-controls="${id}" aria-expanded="false" aria-label="영상 준비 알림">${icon('bell')}<span class="sd-notification-dot"></span></button><div id="${id}" class="sd-notice-popover" data-detail-panel="${id}" hidden><h4>영상 준비 알림</h4><div data-search-status>${visible?h.sourceSearchStatus(t):''}</div></div></div>`;
  }
  function editor(t,h){
    const e=pick(t,'edits',t.edit_id),f=t.feedback||{};
    const search=h.sourceSearchState(t);
    if(t.creation_mode==='self_shot'&&!t.self_shot?.started)return `<div class="pf-editor sd-editor"><section data-pf-section="sources" class="sd-stage"><header class="sd-section-title"><h3>내 촬영 영상</h3><p>최대 20개에서 장면을 고릅니다. 분량이 부족하면 촬영 장면을 재사용하고 결과에 표시합니다.</p></header><div class="self-shot-brief"><h4>${t.self_shot.script_mode==='manual'?'내 대본 그대로 사용':'AI가 제품 대본 집필'}</h4><p>${esc(t.self_shot.product||t.title)}</p><button type="button" class="sd-secondary" data-self-shot-edit>제작 정보 수정</button></div>${h.sourceLibrary(t)}</section>${scriptSection(t,h)}${voiceSection(t)}</div>`;
    return `<div class="pf-editor sd-editor"><section data-pf-section="sources" class="sd-stage sd-source-stage">${sourceNotice(t,h)}<header class="sd-section-title"><h3>영상 재료 준비</h3><p>이번 영상에 사용할 장면을 고르거나 새 영상을 추가하세요.</p></header>${h.sourceLibrary(t)}${t.creation_mode==='self_shot'?'':disclosure(t,'source-search','필요한 영상 검색하기 · 검색 기록',h.sourceSearchPanel(t))}</section>${scriptSection(t,h)}${voiceSection(t)}${window.CaptionEditor?window.CaptionEditor.markup(t,e):''}<div class="pf-actionbar sd-actionbar"><div data-change-status>${h.changeStatus(t)}</div><p class="pf-impact">${h.impact(f)}</p><p data-action-notice role="status" hidden></p><button type="button" class="sd-secondary" data-pf="discard-feedback" ${!Object.keys(f).length?'disabled':''}>이번 수정 취소</button><button type="button" class="sd-primary" data-pf="make-video" ${t.pending_reproduction||!Object.keys(f).length?'disabled':''}>${t.pending_reproduction?'수정 영상 제작 대기':'수정 내용으로 영상 만들기'}</button></div></div>`;
  }
  function bind(root){
    if(root._detailBound)return;root._detailBound=true;
    root.addEventListener('click',event=>{
      for(const notice of root.querySelectorAll('.sd-notification'))if(!notice.contains(event.target)){
        const toggle=notice.querySelector('[data-detail-toggle]'),panel=notice.querySelector('[data-detail-panel]');
        if(toggle&&panel){toggle.setAttribute('aria-expanded','false');panel.hidden=true;root._detailOpens??={};root._detailOpens[toggle.dataset.detailToggle]=false;}
      }
      if(event._studioDetailHandled)return;
      const button=event.target.closest('[data-detail-toggle]');if(!button||!root.contains(button))return;
      const panel=[...root.querySelectorAll('[data-detail-panel]')].find(p=>p.dataset.detailPanel===button.dataset.detailToggle);
      if(!panel)return;
      event._studioDetailHandled=true;
      const open=button.getAttribute('aria-expanded')!=='true';
      button.setAttribute('aria-expanded',String(open));panel.hidden=!open;
      root._detailOpens??={};root._detailOpens[button.dataset.detailToggle]=open;
      fitScriptInputs(root);
    });
  }
  function fitScriptInputs(root){
    for(const field of root.querySelectorAll('textarea[data-field="script"]')){
      if(!field.getClientRects().length)continue;
      field.style.height='auto';field.style.height=(field.scrollHeight+2)+'px';
    }
  }
  function restore(root){
    window.StudioSourceView?.bindPreviews(root);
    for(const button of root.querySelectorAll('[data-detail-toggle]')){
      const open=root._detailOpens?.[button.dataset.detailToggle];if(open===undefined)continue;
      const panel=[...root.querySelectorAll('[data-detail-panel]')].find(p=>p.dataset.detailPanel===button.dataset.detailToggle);
      if(panel){panel.hidden=!open;button.setAttribute('aria-expanded',String(open));}
    }
    fitScriptInputs(root);
  }
  function simplifyLegacy(root,t){
    const fold=(node,label)=>{
      if(!node)return;const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=label;node.before(details);details.append(summary,node);return details;
    };
    for(const section of root.querySelectorAll('[data-legacy-section]')){
      const tab=section.dataset.legacySection;
      if(tab==='original')section.innerHTML=disclosure(t,'legacy-reference','참고한 원본 영상과 대본 보기',section.innerHTML);
      if(tab==='results')fold(section.firstElementChild,'자동 제작 기록 더 보기');
      if(tab==='sources')fold(section.querySelector('.notice'),'필요한 영상 검색하기 · 검색 기록');
      if(['script','voice'].includes(tab)){
        const grid=section.querySelector('.detail-grid'),first=grid?.firstElementChild,main=first?.nextElementSibling;
        if(first&&main){grid.prepend(main);const details=fold(first,tab==='script'?'원본·이전 대본 보기':'읽는 대본·이전 음성 보기');if(details)details.className='sd-legacy-reference';}
        const sub=main?.querySelector('.subsection');fold(sub,tab==='script'?'AI에게 대본 수정 맡기기':'읽는 속도 바꾸기');
        main?.querySelector('.waveform')?.remove();
        const check=main?.querySelector('[data-action="check-script"]');if(check){const tools=fold(check,'문장 검사 도구');tools.append(main.querySelector('#script-review'));}
      }
      if(tab==='edit'){
        const panel=section.querySelector('.preview-grid>.panel');
        for(const sub of panel?.querySelectorAll(':scope>.subsection')||[])fold(sub,sub.querySelector('h3')?.textContent||'자세한 편집 도구');
      }
    }
    for(const [selector,label] of [['[data-action="approve-script"]','이 대본으로 음성 만들기'],['[data-action="approve-voice"]','이 음성으로 영상 만들기'],['[data-action="save-script"]','대본 저장'],['[data-action="regenerate-voice"]','선택한 속도로 음성 만들기']]){
      const button=root.querySelector(selector);if(button)button.textContent=label;
    }
    bind(root);restore(root);
  }
  window.StudioDetail={fitScriptInputs,esc,icon,disclosure,view,scriptCard,status,editor,bind,restore,simplifyLegacy};
})();
