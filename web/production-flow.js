/* Both surfaces consume the same task and immutable run artifacts. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={pending:'대기',running:'진행 중',queued:'실행 대기',completed:'완료',failed:'확인 필요',blocked:'제작 준비 필요',paused:'일시중지',waiting:'제작 대기',superseded:'수정본으로 전환',legacy:'기존 작업'};
  const link=(url,label)=>url?`<a href="${esc(url)}" download>${esc(label)} ↓</a>`:'';
  const item=(t,c,id)=>t[c].find(v=>v.id===id);
  const storageKey=t=>'production-feedback-'+t.id;
  const {sourceSearchState,sourceSearchStatus,sourceSearchPanel,updateSourceSearch,sourceLibrary,sourceBaseline}=
    window.StudioSourceView.create({esc,link,item,storageKey});
  function originalPanel(t, expanded=false){
    const visual=t.reference_kind==='screen_text',mixed=t.reference_kind==='mixed';
    const referenceLabel=visual?'원본 화면에서 확인한 문구':mixed?'원본 음성·화면 참고 내용':'원본에서 들리는 말';
    const referenceHelp=visual?'원본 화면에서 직접 읽고 검토한 문구입니다. 음성 전사와 별도로 보존하며, 화면 문구를 들리는 말로 표시하지 않습니다.':mixed?'원본의 짧은 발화와 화면 문구를 함께 참고합니다. 음성 전사와 화면 글자는 아래에서 따로 확인할 수 있습니다.':'영상에서 실제로 들리는 말만 교정하세요. 자동 인식 원문은 보존됩니다.';
    if(t.creation_mode==='self_shot'){
      const brief=t.self_shot||{},research=t.research||{};
      return `<div class="self-shot-brief"><h4>제품 정보와 집필 근거</h4><p>${esc(brief.product||t.title)}</p>${brief.details?`<p>${esc(brief.details)}</p>`:''}${brief.experience?`<p>직접 제공한 사용 경험: ${esc(brief.experience)}</p>`:''}${(research.facts||[]).map(f=>`<p>${esc(f.text)}<br><a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_title||'출처 확인')}</a></p>`).join('')}${(research.warnings||[]).map(w=>`<p class="pf-help">${esc(window.StudioBoard.message(w))}</p>`).join('')}${brief.script_mode==='manual'?'<p>직접 입력한 대본을 그대로 사용합니다.</p>':''}</div>`;
    }
    if(expanded)return `<div class="pf-original sd-reference"><div class="pf-evidence-grid"><div>${t.reference_url?`<video data-reference-preview controls playsinline preload="metadata" src="${esc(t.reference_url)}"></video>`:'<p>원본 영상 미리보기가 없습니다.</p>'}</div><article><h4>${esc(referenceLabel)}</h4><p class="sd-script-text">${esc(t.reviewed_original_text??t.original_text??'아직 원본 대본이 없습니다.')}</p></article></div></div>`;
    const evidence=t.original_evidence||{},speech=evidence.speech||[],screen=evidence.screen_text||[];
    return `${expanded?'<div class="pf-original">':`<details class="pf-original"><summary>${esc(referenceLabel)} 확인 · 필요할 때 교정</summary>`}<p class="pf-help">${esc(referenceHelp)} 교정본 저장은 제작 대본·음성을 바꾸지 않으며, 다음 AI 수정 요청과 문장 검사의 참고 자료로 사용됩니다.</p>
      ${evidence.speech_unavailable&&!visual&&!mixed?'<p class="pf-version-note">원본의 말을 자동으로 가져오지 못했습니다. 영상을 들으며 아래에 직접 입력하고 ‘참고 내용 저장’을 누를 수 있습니다.</p>':''}<div class="pf-evidence-grid">${t.reference_url?`<video data-reference-preview controls playsinline preload="metadata" src="${esc(t.reference_url)}"></video>`:'<p>원본 영상 미리보기가 없습니다. 확보한 원본을 확인한 뒤 교정하세요.</p>'}<div>${speech.length?`<details><summary>시간별 자동 인식 발화</summary>${speech.map(row=>`<p><button data-reference-seek="${Number(row.start)||0}" ${t.reference_url?'':'disabled'}>${(Number(row.start)||0).toFixed(1)}초 ▷</button> ${esc(row.text)}</p>`).join('')}</details>`:''}<label>${esc(referenceLabel)} · 필요할 때 교정<textarea data-field="original" maxlength="12000">${esc(t.reviewed_original_text??t.original_text??'')}</textarea></label><button data-pf="save-original">참고 내용 저장</button><details><summary>자동 인식 원문 · 보존됨</summary><p class="pf-text">${esc(t.reference_speech_text??t.original_text??'아직 발화를 추출하지 못했어요.')}</p></details>${screen.length?`<details><summary>화면 속 글자 · 발화와 별도 자료</summary>${screen.map(row=>`<p>${esc(row.text)}</p>`).join('')}</details>`:''}</div></div>${expanded?'</div>':'</details>'}`;
  }
  function changeStatus(t){
    const f=t.feedback||{},local=JSON.parse(localStorage.getItem(storageKey(t))||'{}');
    const groups=[['script_text','대본'],['voice_profile_id','목소리'],['speed','속도'],['pronunciations','발음'],['regenerate_voice','새 음성'],['source_ids','사용 영상'],['changes','장면·자막']].filter(([k])=>k in f);
    const oldEdit=localStorage.getItem(storageKey(t)+'-edit');
    const staleEdit=oldEdit&&oldEdit!==t.edit_id&&Object.keys(local).some(k=>/^(shot|caption|start|end|emphasis):/.test(k));
    const conflict=f.changes?.length&&['script_text','speed','pronunciations','voice_profile_id','regenerate_voice','source_ids'].some(k=>k in f);
    if(!Object.keys(local).length&&!groups.length)return '<div class="pf-change-status"><strong>수정사항 없음 · 대본이나 설정을 바꾸면 새 영상을 만들 수 있어요</strong></div>';
    return `<div class="pf-change-status" role="status">${staleEdit?'<p>새 편집본이 준비되어 이전 구간 입력을 보관 중입니다. 내용을 복사한 뒤 구간 입력만 비우고 새 영상을 확인하세요.</p><details><summary>보관된 이전 구간 입력</summary><p class="pf-text">'+Object.entries(local).filter(([k])=>/^(caption|start|end):/.test(k)).map(([,v])=>esc(v)).join('<br>')+'</p></details><button data-pf="discard-local-edit">이전 구간 입력만 비우기</button>':''}<strong>${Object.keys(local).length?'● 저장하지 않은 입력이 있어요':groups.length?'● 저장됨 · 다음 제작에 반영 예정':'✓ 저장된 제작 내용'}</strong><div class="pf-change-chips">${groups.map(([,label])=>`<span>${label}</span>`).join('')}</div><p>${Object.keys(local).length?'이 기기에 임시 보관 중입니다. 아래 제작 버튼을 누르면 저장하고 영상에 반영합니다.':impact(f)}</p>${conflict?'<p>새 대본·음성·소스와 기존 구간 수정을 함께 적용할 수 없어요. 기존 완성본은 보존됩니다.</p><button data-pf="discard-edit-feedback">구간 수정만 초기화</button>':''}</div>`;
  }
  function resultReview(t,run){
    if(!run.video_url)return '';
    const reviewed=t.result_reviews?.[run.id];
    return `<div class="pf-result-review" data-review-run="${run.id}"><strong>${reviewed?'✓ 이 버전은 사용자 검토 완료':'마지막 확인, 세 가지만'}</strong>${reviewed?'':`<p>영상을 재생하며 대사, 자막, 장면을 확인해 주세요. 체크는 이 버전에만 기록됩니다.</p><div class="pf-review-checks">${[['speech','대사·발음'],['captions','자막·타이밍'],['scenes','장면·전환']].map(([key,label])=>`<label><input type="checkbox" data-review-check="${key}"> ${label}</label>`).join('')}</div><button data-pf="review-result" data-run-id="${run.id}">이 버전 검토 완료</button>`}</div>`;
  }
  function scriptReview(result){
    const n=result?.naturalness_review,r=result?.rewrite_review;
    if(!n&&!r)return '';
    const messages=[...(r?.reasons||[]),...(n?.issues||[]).map(i=>`${i.excerpt}: ${i.message}`)];
    return `<p>표현 참고 사항 ${n?.issues?.length??0}개</p><p>${messages.length?messages.map(esc).join('<br>'):'현재 표현 검사에서 지적된 항목이 없어요.'}</p><small>사실 근거와 관점·전개는 직접 확인하세요. 대본을 자동 수정하지 않습니다.</small>`;
  }
  async function api(path,body){
    let r;
    try{r=await fetch('/api/studio'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});}
    catch(error){document.documentElement.dataset.studioConnection='stale';throw error;}
    if(r.status>=500)document.documentElement.dataset.studioConnection='stale';
    const d=await r.json();if(!r.ok)throw Error(window.StudioBoard.message(d.error,'요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.'));
    if(!body)document.documentElement.dataset.studioConnection='live';
    return d;
  }
  function progress(t,active){
    const d=window.StudioBoard.describe(t),live=d.steps.some(s=>s.live);
    const assets=active?.steps||[],keys=['sources','transcript','script','voice','project','export'];
    const label=i=>assets.find(s=>s.key===keys[i])?.label||d.steps[i].label;
    const next=d.steps.find((s,i)=>i>d.currentIndex&&s.state!=='done');
    const nextText=d.complete?'모든 단계가 끝났습니다. 아래에서 완성 영상을 확인하세요.':next?`다음 단계 · ${next.number}. ${label(next.number-1)}`:'다음 · 최종 영상 확인';
    return `<div class="pf-progress" data-state="${d.state}">
      <div class="pf-current" data-live="${live}" role="status" aria-live="polite" aria-atomic="true">
        <div class="pf-current-title">${live?window.StudioBoard.activityMarkup(true):`<span class="pf-activity" aria-hidden="true">${d.complete?'✓':d.attention||d.review?'!':d.state==='paused'?'Ⅱ':'…'}</span>`}<div><span class="pf-phase">${d.complete?'제작 완료':`현재 ${d.currentIndex+1} / 6 단계`} · ${esc(d.label)}</span><strong>${esc(d.complete?'최종 영상 제작 완료':label(d.currentIndex))}</strong></div></div>
        <p class="pf-current-message">${esc(d.message)}</p><p class="pf-next">${esc(nextText)}</p>
      </div>
      <div class="pf-progress-caption"><strong>${d.done} / 6 단계 완료</strong><span>완료 단계 기준 · 소요시간 비율 아님</span></div>
      <div class="pf-progress-track" role="progressbar" aria-label="자동 제작 완료 단계" aria-valuemin="0" aria-valuemax="6" aria-valuenow="${d.done}" aria-valuetext="${esc(`${d.done} / 6 단계 완료, ${d.complete?'제작 완료':label(d.currentIndex)+' '+d.label}`)}"><div style="width:${d.done/6*100}%"></div></div>
      <ol class="pf-steps" aria-label="자동 제작 순서">${d.steps.map((s,i)=>{
        const asset=assets.find(a=>a.key===keys[i]);
        return `<li class="${s.live?'current running':s.current?'current '+d.state:s.state==='done'?'completed':'pending'}" data-live="${s.live}" aria-busy="${s.live}" ${s.current?'aria-current="step"':''}><span class="pf-step-number" aria-hidden="true">${s.state==='done'?'✓':s.number}</span><div class="pf-step-content"><b>${s.number}. ${esc(label(i))}</b><span class="pf-step-status">${s.live?'진행 중':s.current?esc(d.label):s.state==='done'?'완료':'예정'}</span>${link(asset?.download_url,'다운로드')}</div>${i<5?'<span class="pf-connector" aria-hidden="true">→</span>':''}</li>`;
      }).join('')}</ol>
      <div class="pf-recovery">${t.error?'<p class="pf-error">문제를 해결한 뒤 중단된 단계부터 다시 시도하세요. <button data-pf="retry">중단 단계 재시도</button></p>':''}</div>
    </div>`;
  }
  function fileIcon(kind){
    const paths={download:'<path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4"/>',video:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4Z"/>',sources:'<rect x="7" y="7" width="14" height="14" rx="3"/><path d="M17 7V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h3m5-6 5 3-5 3Z"/>',text:'<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Zm0 0v6h6M8 13h8m-8 4h5"/>',voice:'<path d="M4 10v4m4-8v12m4-15v18m4-15v12m4-8v4"/>',project:'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 9v12m4-8h4m-4 4h4"/>'};
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[kind]||paths.text}</svg>`;
  }
  function downloads(t,run){
    const url=key=>(run.steps||[]).find(s=>s.key===key)?.download_url;
    const files=[
      ['reference','원본 영상','벤치마킹 원본','MP4',t.reference_url,'video'],
      ['sources','소스 영상','제작에 사용한 영상 묶음','ZIP',url('sources'),'sources'],
      ['transcript','원본 대본','원본에서 추출한 발화','TXT',url('transcript'),'text'],
      ['script','제작 대본','이 버전에 사용한 대본','TXT',url('script'),'text'],
      ['voice','제작 음성','이 버전에서 읽는 목소리','WAV',url('voice'),'voice'],
      ['project','CapCut 프로젝트','다시 편집할 수 있는 파일','ZIP',url('project'),'project']
    ];
    if(t.creation_mode==='self_shot'){
      files.splice(0,1);
      const info=files.find(f=>f[0]==='transcript');info[1]='제작 정보';info[2]='제품 정보 또는 직접 입력한 대본';
    }
    const final=url('export');
    const materials=`<div class="pf-download-grid">${files.map(([key,title,description,format,href,icon])=>{const content=`<span class="pf-file-icon">${fileIcon(icon)}</span><span class="pf-file-copy"><strong>${title}</strong><small>${description}</small><span class="pf-file-format">${href?format:'아직 없음'}</span></span><span class="pf-file-save">${href?fileIcon('download'):''}</span>`;return href?`<a class="pf-file-card" data-download-asset="${key}" href="${esc(href)}" download aria-label="${title} ${format} 다운로드">${content}</a>`:`<div class="pf-file-card is-unavailable" data-download-asset="${key}" aria-disabled="true">${content}</div>`;}).join('')}</div>${url('project')?`<footer class="pf-download-edit"><p>CapCut에서 바꾼 내용은 이 화면에 자동 반영되지 않습니다.</p><button type="button" data-pf="open-capcut" data-edit-id="${esc(run.artifacts.edit_id)}">CapCut에서 편집하기 · 별도 앱</button></footer>`:''}`;
    return `<section class="pf-downloads" aria-label="영상과 제작 자료 받기">
      ${final?`<a class="pf-download-final" href="${esc(final)}" download><span class="pf-file-icon">${fileIcon('video')}</span><span class="pf-file-copy"><strong>완성 영상 내려받기</strong><small>지금 보고 있는 버전의 영상</small></span>${fileIcon('download')}</a>`:'<p class="sd-result-empty">아직 완성 영상이 없습니다. 제작이 끝나면 내려받기 버튼이 나타납니다.</p>'}
      ${window.StudioDetail.disclosure(t,'materials-'+run.id,'대본·음성 등 제작 자료 받기',materials)}</section>`;
  }
  function summary(t,selected){
    const runs=t.pipeline||[], active=runs.find(r=>r.id===t.run_id)||runs.at(-1);
    const display=runs.find(r=>r.id===selected)||runs.find(r=>r.id===t.latest_completed_run_id)||active;
    if(!display)return '';
    return `<div class="pf-summary"><div class="pf-heading"><h3>${display.video_url?'완성 영상':'제작 결과'}</h3></div>
      ${window.StudioWorkspace.versionPicker(t,display)}
      ${Object.keys(t.feedback||{}).length||t.pending_reproduction?'<p class="pf-version-note">저장한 변경사항은 이 결과물에 아직 반영되지 않았어요. 새 버전이 완성되면 비교해 주세요.</p>':''}${display.id!==t.run_id?'<p class="pf-version-note">이전 제작 버전을 보고 있어요. 진행 중인 수정은 이 영상에 반영되지 않았습니다.</p>':''}${window.StudioWorkspace.comparison(t,display)}
      ${t.creation_mode==='self_shot'?(item(t,'edits',display.artifacts.edit_id)?.plan?.warnings||[]).filter(w=>w.startsWith('촬영 장면 재사용:')).map(w=>`<p class="pf-version-note" data-owned-reuse>${esc(w)}</p>`).join(''):''}${downloads(t,display)}${display.video_url?window.StudioDetail.disclosure(t,'result-review-'+display.id,'영상 확인 체크리스트',resultReview(t,display)):''}
      <button type="button" class="sd-secondary" data-pf-tab="edit">장면·자막 수정하기</button>
      ${t.automation?.protocol!==2?'<details><summary>자동 제작 도구</summary><button type="button" data-pf="start-auto">이 작업을 자동 제작으로 이어가기</button></details>':''}<details class="pf-result-progress"><summary>이번 제작의 단계별 기록</summary>${progress(t,active)}</details></div>`;
  }
  function benchmarkAnalysis(a){
    if(!a?.features?.length)return '';
    const roles={hook:'훅',pain:'불편',feature:'핵심 기능',payoff:'생활 이득',curiosity:'궁금증',cta:'댓글 유도'};
    return `<details class="pf-tool-card"><summary>원본 대본에서 가져온 특징과 전개</summary><p>${esc(a.summary)}</p><p>${esc(a.structure)}</p>${a.features.map(f=>`<p><b>${esc(roles[f.role]||'특징')}${f.core?' · 핵심':''}</b> · ${esc(f.quote)}<br><span>${esc(f.adaptation)}</span>${['experience','narrator_claim'].includes(f.claim_type)?'<br><small>원본 화자의 경험·주장 · 별도 확인된 상품 사실은 아님</small>':''}</p>`).join('')}<p>정확한 상품 정체는 숨기고, 핵심 이득과 댓글 궁금증을 연결해요.</p></details>`;
  }
  function editor(t){
    return window.StudioDetail.editor(t,{sourceLibrary,sourceSearchPanel,sourceSearchStatus,sourceSearchState,originalPanel,aiStatus,scriptReview,benchmarkAnalysis,changeStatus,impact});
  }
  function aiStatus(t,kind){
    const job=(t.jobs||[]).find(j=>j.kind===kind);if(!job)return '';
    if(['queued','running'].includes(job.status))return '<span class="pf-spinner" aria-hidden="true"></span><strong>AI 수정안을 준비하고 있어요</strong><p>완료되면 이곳에 표시됩니다. 현재 영상과 입력은 유지됩니다.</p>';
    if(job.status==='failed')return '<strong>수정안을 만들지 못했어요</strong><p>'+esc(window.StudioBoard.message(job.error))+'</p><p>요청 내용을 구체화해 다시 보내거나 직접 수정할 수 있어요.</p>';
    if(job.status==='done'){
      if(kind==='proposal')return '<strong>수정안 준비 완료</strong><p>아래에서 변경 전후를 비교하고 사용할 수정안을 선택하세요.</p>';
      return t.feedback?.changes?'<strong>구간 수정안 저장됨 · 영상 반영 대기</strong><p>'+esc((t.jobs||[]).find(j=>['proposal','suggest_edit'].includes(j.kind))?.id===job.id?t.feedback_message||'':'')+'</p><p>하단의 수정한 영상 만들기를 누르면 새 영상에 적용됩니다.</p>':'<strong>이전 수정 요청 처리 완료</strong><p>새 영상에서 추가로 수정할 구간을 선택할 수 있어요.</p>';
    }
    return '';
  }
  function impact(f){return Object.keys(f).length?'아래 제작 버튼을 누르면 수정 내용을 영상에 반영합니다. 기존 완성 영상은 보관됩니다.':'대본이나 설정을 바꾸면 영상 만들기 버튼을 누를 수 있습니다.';}
  function runtime(t){
    const control=t.automation?.active&&t.status!=='completed'?window.StudioDetail.disclosure(t,'production-control','제작 제어 더 보기','<button type="button" class="sd-secondary" data-pf="pause-auto">자동 제작 잠시 멈추기</button><p>진행 중인 작업은 마무리될 수 있습니다.</p>'):'';
    return `<div class="pf-runtime">${window.StudioDetail.status(t,'runtime')}${control}</div>`;
  }
  function syncFields(root,id){
    const fields=[...root.querySelectorAll('[data-field]')];
    const find=name=>fields.find(e=>e.dataset.field===name+':'+id);
    return {start:find('start'),end:find('end'),caption:find('caption'),card:[...root.querySelectorAll('[data-sync-beat]')].find(e=>e.dataset.syncBeat===id)};
  }
  function syncReadout(root,id){
    const f=syncFields(root,id);if(!f.start||!f.end)return;
    const range=Number(f.start.value).toFixed(2)+'–'+Number(f.end.value).toFixed(2)+'초';
    const output=f.card?.querySelector('[data-sync-times]');if(output)output.textContent=range;
    if(root._syncSelected===id){root.querySelector('[data-sync-caption]').textContent=f.caption.value;root.querySelector('[data-sync-range]').textContent=range+' · 미리보기에 즉시 반영';}
  }
  function stopSync(root){
    root._syncLoop=null;
    root.querySelectorAll('[data-sync="loop"]').forEach(b=>{b.textContent='▷ 앞뒤 함께 듣기';b.setAttribute('aria-pressed','false');});
  }
  function bindSyncPreview(root){
    stopSync(root);root._syncSelected=null;root.querySelectorAll('[data-sync-beat]').forEach(card=>syncReadout(root,card.dataset.syncBeat));const video=root.querySelector('[data-edit-preview]');if(!video)return;
    video.ontimeupdate=()=>{
      if(!root._syncLoop||video.paused)return;
      const f=syncFields(root,root._syncLoop),start=Number(f.start?.value),end=Number(f.end?.value);
      if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>video.duration){video.pause();return;}
      if(video.currentTime>=Math.min(video.duration,end+.4)||video.currentTime<Math.max(0,start-.4)-.05)video.currentTime=Math.max(0,start-.4);
    };
    video.onpause=()=>{if(!video.ended)stopSync(root);};
    video.onended=()=>{
      if(!root._syncLoop)return;
      const f=syncFields(root,root._syncLoop);video.currentTime=Math.max(0,Number(f.start.value)-.4);
      video.play().catch(()=>stopSync(root));
    };
  }
  function adjustSync(root,button){
    const id=button.dataset.beat,f=syncFields(root,id),video=root.querySelector('[data-edit-preview]');
    if(!video||!f.start||!f.end)return;
    const note=f.card.querySelector('.pf-sync-feedback');
    const old=localStorage.getItem(storageKey(root._task)+'-edit');
    if(old&&old!==root._renderedEditId){note.textContent='이전 편집본의 입력이 보관되어 있어요. 내용을 확인하고 이전 구간 입력을 비운 뒤 수정하세요.';return;}
    if(button.dataset.sync==='loop'&&root._syncLoop===id){video.pause();stopSync(root);return;}
    let start=Number(f.start.value),end=Number(f.end.value);
    const action=button.dataset.sync;
    if(video.readyState<1||!Number.isFinite(video.duration)){note.textContent='미리보기 영상을 불러온 뒤 다시 눌러주세요.';return;}
    if(action==='start')start=Math.round(video.currentTime*100)/100;
    if(action==='end')end=Math.round(video.currentTime*100)/100;
    if(action==='earlier'||action==='later'){
      const field=f.card.querySelector('[data-caption-shift]'),amount=field?Number(field.value):.1;
      if(!Number.isFinite(amount)||amount<=0||(field&&(!field.value||!field.validity.valid))){note.textContent='이동 간격은 0.01초 이상의 숫자를 소수점 두 자리까지 입력하세요.';return;}
      const shift=action==='earlier'?-amount:amount;start=Math.round((start+shift)*100)/100;end=Math.round((end+shift)*100)/100;
    }
    if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>video.duration){note.textContent='시작은 0초 이상, 끝은 시작보다 뒤여야 해요. 영상 길이 '+video.duration.toFixed(2)+'초 안에서 지정하세요.';return;}
    root._syncSelected=id;
    if(action==='loop'){
      stopSync(root);root._syncLoop=id;button.textContent='Ⅱ 반복 듣기 중지';button.setAttribute('aria-pressed','true');syncReadout(root,id);
      video.currentTime=Math.max(0,start-.4);
      video.play().catch(()=>{stopSync(root);note.textContent='영상의 재생 버튼을 눌러 재생 상태를 확인하세요.';});
      note.textContent='대사 앞뒤를 함께 반복합니다. 바뀐 자막 시점을 영상에서 확인하세요.';
    }else{
      for(const [field,value] of [[f.start,start],[f.end,end]]){if(Number(field.value)!==value){field.value=value.toFixed(2);field.dispatchEvent(new Event('input',{bubbles:true}));}}
      syncReadout(root,id);note.textContent='미리보기 반영됨 · 편집 저장 또는 MP4 내보내기를 누르세요.';
    }
  }
  function refreshActions(root){
    const t=root._task,local=JSON.parse(localStorage.getItem(storageKey(t))||'{}'),f=t.feedback||{};
    const changed=Object.keys(local).some(k=>/^(script$|speed$|pronunciation$|voice-profile$|source:)/.test(k))||Object.keys(f).length>0;
    const button=root.querySelector('[data-pf="make-video"]');
    if(button)button.disabled=!changed||!!t.pending_reproduction||!!root._saving;
    const discard=root.querySelector('[data-pf="discard-feedback"]');if(discard)discard.disabled=!Object.keys(local).length&&!Object.keys(f).length||!!root._saving;
    const label=root.querySelector('.pf-script-state .pf-count');if(label)label.textContent='script' in local||f.script_text!==undefined?'수정 중인 대본 · 영상 반영 전':'선택된 대본';
    const impact=root.querySelector('.pf-impact');if(impact)impact.textContent=changed?'입력 내용을 저장하고 필요한 음성·영상을 새로 만듭니다. 기존 완성 영상은 보존됩니다.':'대본이나 설정을 바꾸면 영상 만들기 버튼을 누를 수 있습니다.';
  }
  function mount(root,t,options={}){
    root._task=t;root._options=options;window.StudioDetail.bind(root);refreshActions(root);window.CaptionEditor?.refresh(root,t);
    const bindUploads=()=>window.SourceUpload?.bind(root,t,result=>{options.onUpdate?.(result);mount(root,result,options);},()=>{root._renderedRevision=null;mount(root,root._task,options);});
    if(root._taskId!==t.id){root._taskId=t.id;root._selected=(t.pipeline||[]).some(r=>r.id===options.selectedRun)?options.selectedRun:null;root._dirty=false;root._feedbackBaseRevision=null;root._renderedRevision=null;root.innerHTML='';root._detailOpens={};}
    updateSourceSearch(root,t);
    const status=root.querySelector('[data-change-status]');if(status)status.innerHTML=changeStatus(t);
    const runningNote=root.querySelector('.pf-runtime');
    if(runningNote){const temp=document.createElement('div');temp.innerHTML=runtime(t);if(runningNote.querySelector('.pf-script-read')?.open&&temp.querySelector('.pf-script-read'))temp.querySelector('.pf-script-read').open=true;const content=temp.firstElementChild.innerHTML;if(runningNote.innerHTML!==content)runningNote.innerHTML=content;}
    for(const box of root.querySelectorAll('[data-ai-status]')){
      const kind=box.dataset.aiStatus,html=aiStatus(t,kind);if(box.innerHTML!==html)box.innerHTML=html;
      const button=root.querySelector('[data-pf="'+(kind==='proposal'?'propose-script':'request-edit')+'"]');
      if(button)button.disabled=['queued','running'].includes((t.jobs||[]).find(j=>j.kind===kind)?.status)||(kind==='proposal'&&!t.script_id);
    }
    const playing=[...root.querySelectorAll('video,audio')].some(v=>!v.paused||v.seeking);
    if(playing||root._dirty||root._uploading||root.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select')){
      const temp=document.createElement('div');temp.innerHTML=summary(t,root._selected);
      const panel=root.querySelector('.pf-progress'),fresh=temp.querySelector('.pf-progress');
      if(panel&&fresh){
        panel.dataset.state=fresh.dataset.state;
        // Update status independently, preserving media, unsaved inputs and spinners.
        for(const selector of ['.pf-current','.pf-progress-caption','.pf-progress-track','.pf-steps','.pf-recovery']){
          const old=panel.querySelector(selector),next=fresh.querySelector(selector);
          if(old.querySelector('.pf-script-read')?.open&&next.querySelector('.pf-script-read'))next.querySelector('.pf-script-read').open=true;
          if(old.outerHTML!==next.outerHTML){
            if(selector==='.pf-current'){old.innerHTML=next.innerHTML;old.dataset.live=next.dataset.live;}
            else old.replaceWith(next);
          }
        }
      }
      const proposals=root.querySelector('[data-proposals]');if(proposals&&proposals.dataset.count!==String(t.proposals?.length||0)){const temp=document.createElement('div');temp.innerHTML=editor(t);const fresh=temp.querySelector('[data-proposals]');if(fresh){proposals.innerHTML=fresh.innerHTML;proposals.dataset.count=String(t.proposals?.length||0);}}
      const library=root.querySelector('.pf-source-library');
      if(library&&![...library.querySelectorAll('video')].some(v=>!v.paused)){
        const tmp=document.createElement('div');tmp.innerHTML=sourceLibrary(t);
        const focusedField=library.contains(document.activeElement)?document.activeElement.dataset.field:null;
        // Update source groups around the stable upload widget; preserve its queue and file picker.
        for(const selector of ['.pf-source-selection','.pf-source-used','.pf-source-added','.pf-source-other','.pf-source-save']){
          const before=library.querySelector(selector),after=tmp.querySelector(selector);
          if(before&&after){
            const comparable=before.cloneNode(true);
            // Visibility loading changes preload, not the source inventory.
            comparable.querySelectorAll('video[data-source-preview]').forEach(v=>v.setAttribute('preload','none'));
            if(comparable.innerHTML!==after.innerHTML)before.innerHTML=after.innerHTML;
          }
          else if(before)before.remove();
          else if(after)library.insertBefore(after,library.querySelector('.pf-source-save'));
        }
        if(focusedField&&!library.contains(document.activeElement))[...library.querySelectorAll('[data-field]')].find(e=>e.dataset.field===focusedField)?.focus({preventScroll:true});
      }
      bindUploads();window.VoicePicker?.bind(root);window.CaptionEditor?.bind(root,t);
      window.StudioDetail.restore(root);options.onRender?.();return;
    }
    if(root._renderedRevision===t.revision && root._renderedSelected===root._selected && root.querySelector('.production-flow')){window.StudioDetail.restore(root);options.onRender?.();return;}
    root._renderedRevision=t.revision;root._renderedSelected=root._selected;root._renderedEditId=t.edit_id;
    const mediaPositions=new Map([...root.querySelectorAll('video,audio')].map(m=>[m.getAttribute('src'),m.currentTime]));
    const opens=[...root.querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent);
    const searchOpen=root.querySelector('[data-search-options]')?.open;
    root.innerHTML=`<section class="production-flow">${options.editor&&t.automation?.protocol===2?runtime(t):''}${options.editor&&t.automation?.protocol===2?editor(t):''}${summary(t,root._selected)}<p class="pf-message" role="status"></p></section>`;
    for(const kind of ['proposal','suggest_edit']){
      const button=root.querySelector('[data-pf="'+(kind==='proposal'?'propose-script':'request-edit')+'"]');
      if(button)button.disabled=['queued','running'].includes((t.jobs||[]).find(j=>j.kind===kind)?.status)||(kind==='proposal'&&!t.script_id);
    }
    root.querySelectorAll('video,audio').forEach(m=>{const position=mediaPositions.get(m.getAttribute('src'));if(position>0){const restore=()=>{m.currentTime=position;};if(m.readyState>=2)restore();else m.addEventListener('loadeddata',restore,{once:true});}});
    if(opens.length)root.querySelectorAll('details').forEach(d=>d.open=opens.includes(d.querySelector('summary')?.textContent));
    if(searchOpen!==undefined&&root.querySelector('[data-search-options]'))root.querySelector('[data-search-options]').open=searchOpen;
    const local=JSON.parse(localStorage.getItem(storageKey(t))||'null');
    if(options.editor&&local&&Object.keys(local).length){for(const field of root.querySelectorAll('[data-field]'))if(field.dataset.field in local){if(/^(shot|caption|start|end|emphasis):/.test(field.dataset.field)&&localStorage.getItem(storageKey(t)+'-edit')&&localStorage.getItem(storageKey(t)+'-edit')!==t.edit_id)continue;if(field.type==='checkbox')field.checked=local[field.dataset.field];else field.value=local[field.dataset.field];}root._dirty=true;root._feedbackBaseRevision=Number(localStorage.getItem(storageKey(t)+'-revision')??t.feedback_revision??0);}
    if(local&&'script' in local){const review=root.querySelector('[data-script-review]');if(review)review.textContent='불러온 편집 내용을 다시 검사해 주세요.';}
    root.querySelectorAll('[data-review-check]').forEach(e=>{e.checked=!!root._reviewChecks?.[e.closest('[data-review-run]').dataset.reviewRun]?.[e.dataset.reviewCheck];});
    root.oninput=event=>{const e=event.target;if(e.dataset.reviewCheck){const id=e.closest('[data-review-run]').dataset.reviewRun;root._reviewChecks??={};root._reviewChecks[id]??={};root._reviewChecks[id][e.dataset.reviewCheck]=e.checked;return;}if(!e.dataset.field)return;if(/^(caption|start|end):/.test(e.dataset.field))syncReadout(root,e.dataset.field.split(':')[1]);if(e.dataset.field==='script'){root.querySelectorAll('[data-field="script"]').forEach(field=>{if(field!==e)field.value=e.value;});window.StudioDetail.fitScriptInputs(root);const review=root.querySelector('[data-script-review]');if(review)review.textContent='대본이 바뀌었어요. 다시 검사해 주세요.';}if(!root._dirty){root._feedbackBaseRevision=root._task.feedback_revision||0;localStorage.setItem(storageKey(root._task)+'-revision',String(root._feedbackBaseRevision));}root._dirty=true;const draft=JSON.parse(localStorage.getItem(storageKey(root._task))||'{}');const value=e.type==='checkbox'?e.checked:e.value,base=e.type==='checkbox'&&e.dataset.field.startsWith('source:')?sourceBaseline(root._task,e.dataset.field.slice(7)):e.type==='checkbox'?e.defaultChecked:e.defaultValue;const equal=e.type==='number'?value!==''&&base!==''&&Number(value)===Number(base):value===base;if(equal)delete draft[e.dataset.field];else draft[e.dataset.field]=value;root._dirty=Object.keys(draft).length>0;if(/^(shot|caption|start|end|emphasis):/.test(e.dataset.field)&&!localStorage.getItem(storageKey(root._task)+'-edit'))localStorage.setItem(storageKey(root._task)+'-edit',root._renderedEditId||'');localStorage.setItem(storageKey(root._task),JSON.stringify(draft));refreshActions(root);window.CaptionEditor?.refresh(root,root._task);root.dispatchEvent(new CustomEvent('production-draft',{bubbles:true}));const status=root.querySelector('[data-change-status]');if(status)status.innerHTML=changeStatus(root._task);if(e.dataset.field.startsWith('source:')){const n=root.querySelectorAll('[data-field^="source:"]:checked').length;root.querySelector('[data-selected-count]').textContent=n;for(const button of root.querySelectorAll('[data-pf="use-sources"],[data-pf="save-sources"]'))button.disabled=!n||button.dataset.pf==='use-sources'&&(root._uploading||(root._task.jobs||[]).some(j=>j.status==='running'&&!['proposal','suggest_edit'].includes(j.kind)));}};
    bindSyncPreview(root);
    root.onchange=async event=>{
      if(event.target.matches('[data-pf-version]')){
        root._selected=event.target.value;root._dirty=false;
        // An explicit version switch must bypass the focus/playback refresh guard.
        event.target.blur();root.querySelectorAll('video,audio').forEach(v=>v.pause());
        mount(root,root._task,options);
      }
    };
    const message=text=>{const m=root.querySelector('.pf-message');if(m)m.textContent=text;const notice=root.querySelector('[data-action-notice]');if(notice){notice.hidden=!text;notice.textContent=text;}};
    const field=name=>[...root.querySelectorAll('[data-field]')].find(e=>e.dataset.field===name);
    const value=name=>field(name)?.value||'';
    root.onclick=async event=>{
      const sync=event.target.closest('[data-sync]');if(sync){if(sync.dataset.sync!=='loop')window.CaptionEditor?.remember(root);adjustSync(root,sync);window.CaptionEditor?.refresh(root,root._task);return;}
      const ref=event.target.closest('[data-reference-seek]');if(ref){const video=root.querySelector('[data-reference-preview]');if(video)video.currentTime=Number(ref.dataset.referenceSeek);return;}
      const seek=event.target.closest('[data-pf-seek]');if(seek){const video=root.querySelector('[data-edit-preview]');if(video)video.currentTime=Number(seek.dataset.pfSeek);return;}
      const tab=event.target.closest('[data-pf-tab]');if(tab){if(options.onTab)options.onTab(tab.dataset.pfTab);else location.href='studio.html?work='+encodeURIComponent(root._task.id)+'&tab='+encodeURIComponent(tab.dataset.pfTab);return;}
      const button=event.target.closest('[data-pf]');if(!button)return;
      if(root._saving)return;
      const action=button.dataset.pf, task=root._task;let kind=action,body={};
      if(action==='retry-automatic-sources'){kind='retry';body={job_id:button.dataset.jobId};}
      if(['save-captions','export-edit'].includes(action)){
        const issue=window.CaptionEditor.validate(root,task);if(issue){message(issue);return;}
        if(!window.CaptionEditor.ready(root,task)){message('편집 미리보기를 먼저 준비하세요.');return;}
        body={edit_id:root._renderedEditId,changes:window.CaptionEditor.collect(root)};
      }
      if(action==='prepare-caption-preview')body={edit_id:task.edit_id};
      const submitted=JSON.parse(localStorage.getItem(storageKey(task))||'{}');
      if(action==='discard-local-edit'){for(const k of Object.keys(submitted))if(/^(shot|caption|start|end|emphasis):/.test(k))delete submitted[k];localStorage.setItem(storageKey(task),JSON.stringify(submitted));localStorage.removeItem(storageKey(task)+'-edit');root._dirty=false;root._renderedRevision=null;document.activeElement.blur();root.querySelectorAll('video,audio').forEach(v=>v.pause());mount(root,task,options);return;}
      if(['save-beat','request-edit'].includes(action)&&localStorage.getItem(storageKey(task)+'-edit')&&localStorage.getItem(storageKey(task)+'-edit')!==task.edit_id){message('이전 구간 입력이 보관되어 있습니다. 하단에서 내용을 확인하고 이전 구간 입력만 비운 뒤 새 영상에서 수정하세요.');return;}
      if(action==='save-original')body={text:value('original'),base_text:task.reviewed_original_text??task.original_text??''};
      if(action==='restore-script')body={script_id:button.dataset.scriptId};
      if(action==='review-result')body={run_id:button.dataset.runId,checks:[...root.querySelectorAll('[data-review-check]:checked')].map(e=>e.dataset.reviewCheck)};
      if(action==='select-all-sources'||action==='clear-sources'){for(const field of root.querySelectorAll('[data-field^="source:"]')){field.checked=action==='select-all-sources';field.dispatchEvent(new Event('input',{bubbles:true}));}return;}
      if(action==='use-sources')body={source_ids:[...root.querySelectorAll('[data-field^="source:"]:checked')].map(e=>e.dataset.field.slice(7))};
      if(action==='save-script')body={text:value('script')};
      if(action==='candidate'){kind='select-candidate';body={index:Number(button.dataset.index)};}
      if(action==='proposal'){kind='apply-proposal';body={proposal_id:button.dataset.id,base_text:value('script')};}
      if(action==='save-sources'){kind='save-feedback';body={source_ids:[...root.querySelectorAll('[data-field^="source:"]:checked')].map(e=>e.dataset.field.slice(7))};}
      if(action==='search'||action==='retry-source-search'){
        if(sourceSearchState(task).busy)return;
        kind='refresh-sources';
        if(action==='search'){
          const request=value('search').trim();
          if(!request){root.querySelector('[data-search-validation]').textContent='추가로 필요한 장면이나 바꿀 검색 조건을 입력해 주세요.';field('search').focus();return;}
          root.querySelector('[data-search-validation]').textContent='';body={request};
        }else body=button.dataset.jobId?{retry_job_id:button.dataset.jobId}:{request:''};
      }
      if(action==='save-voice'||action==='regenerate-voice'){
        kind=action==='save-voice'?'save-feedback':action;
        body={voice_profile_id:value('voice-profile'),speed:Number(value('speed')),pronunciations:value('pronunciation').split('\n').filter(v=>v.trim()).map(v=>{const pos=v.indexOf('=');return {from:pos<0?'':v.slice(0,pos).trim(),to:pos<0?'':v.slice(pos+1).trim()};})};
      }
      if(action==='propose-script')body={request:value('script-request'),base_text:value('script')};
      if(action==='restore-script'&&'script' in submitted){message('직접 수정한 대본을 먼저 저장하세요. 저장 후 다른 대본을 선택할 수 있습니다.');return;}
      if(['propose-script','check-script'].includes(action)&&'original' in submitted){message('원본 영상에서 들리는 말을 교정했다면 먼저 참고 내용을 저장하세요.');return;}
      if(action==='request-edit')body={edit_id:root._renderedEditId,request:value('edit-request'),start:Number(value('edit-start')),end:Number(value('edit-end'))};
      if(action==='open-capcut')body={edit_id:button.dataset.editId};
      if(action==='save-beat'){kind='revise-edit';const id=button.dataset.beat;body={edit_id:root._renderedEditId,changes:[{beat_id:id,shot_id:value('shot:'+id),text:value('caption:'+id),start:Number(value('start:'+id)),end:Number(value('end:'+id)),emphasis:Number(value('emphasis:'+id))}]};}
      if(action==='make-video'){
        if(Object.keys(submitted).some(k=>/^(caption|start|end|shot|emphasis):/.test(k))){message('자막 수정과 대본 변경은 함께 제작할 수 없어요. 자막을 먼저 영상 파일로 저장하거나 실행 취소해 주세요.');return;}
        if('script' in submitted)body.text=value('script');
        if('voice-profile' in submitted)body.voice_profile_id=value('voice-profile');
        if('speed' in submitted)body.speed=Number(value('speed'));
        if('pronunciation' in submitted)body.pronunciations=value('pronunciation').split('\n').filter(v=>v.trim()).map(v=>{const pos=v.indexOf('=');return {from:pos<0?'':v.slice(0,pos).trim(),to:pos<0?'':v.slice(pos+1).trim()};});
        if(Object.keys(submitted).some(k=>k.startsWith('source:')))body.source_ids=[...root.querySelectorAll('[data-field^="source:"]:checked')].map(e=>e.dataset.field.slice(7));
      }
      if(action==='reproduce'&&root._dirty){message('입력한 항목의 피드백 저장 버튼을 먼저 눌러주세요.');return;}
      const originalLabel=button.textContent;root._captionError='';root._saving=true;button.disabled=true;button.setAttribute('aria-busy','true');button.textContent=action==='prepare-caption-preview'?'미리보기 준비 중…':'요청 처리 중…';window.CaptionEditor?.refresh(root,task);message(action==='prepare-caption-preview'?'편집 미리보기 준비 중…':'저장·요청 중…');
      try{
        if(action==='check-script'){
          const text=value('script'),result=await api('/'+task.id+'/check-script',{text});
          if(root._task.id===task.id&&value('script')===text){root.querySelector('[data-script-review]').innerHTML=scriptReview(result);message('현재 입력한 대본 검사 완료');}
          else message('검사 중 대본이 바뀌었어요. 다시 검사해 주세요.');
          return;
        }
        const fresh=await api('/'+task.id);
        if(body.retry_job_id&&!fresh.source_search_retry_supported)throw new Error('로컬 Hotpost 서버를 재시작한 뒤 새로고침해 주세요. 이전 검색 조건을 복원하려면 서버 업데이트 적용이 필요합니다.');
        const feedbackActions=['make-video','save-captions','export-edit','save-feedback','save-script','restore-script','apply-proposal','regenerate-voice','revise-edit','request-edit','reproduce','discard-feedback','select-candidate','discard-edit-feedback'];
        const result=await api('/'+task.id+'/'+kind,{revision:fresh.revision,...(feedbackActions.includes(kind)?{feedback_revision:root._feedbackBaseRevision??task.feedback_revision??0}:{}),...body});
        if(action==='export-edit'&&result.edit_id===body.edit_id&&!result.feedback?.changes?.length){
          const output=result.edits?.find(e=>e.id===result.edit_id)?.export_url;
          if(output){const a=document.createElement('a');a.href=output;a.download='shorts.mp4';a.click();}
        }
        // Preserve unsaved fields in other sections; clear only fields saved here.
        const local=JSON.parse(localStorage.getItem(storageKey(task))||'{}');
        const prefixes=action==='make-video'?['script','speed','pronunciation','voice-profile','source:']:['save-captions','export-edit'].includes(action)?['caption:','start:','end:']:action==='save-original'?['original']:action==='save-script'?['script']:action==='save-voice'||action==='regenerate-voice'?['speed','pronunciation','voice-profile']:['save-sources','use-sources'].includes(action)?['source:']:action==='save-beat'?['shot:'+button.dataset.beat,'caption:'+button.dataset.beat,'start:'+button.dataset.beat,'end:'+button.dataset.beat,'emphasis:'+button.dataset.beat]:action==='search'?['search']:action==='propose-script'?['script-request']:action==='request-edit'?['edit-request','edit-start','edit-end']:[];
        for(const k of Object.keys(local))if(local[k]===submitted[k]&&prefixes.some(p=>k===p||p.endsWith(':')&&k.startsWith(p)))delete local[k];
        if(['candidate','proposal','restore-script'].includes(action)&&local.script===submitted.script)delete local.script;
        if(action==='discard-feedback')for(const k of Object.keys(local))if(local[k]===submitted[k])delete local[k];
        if(action==='discard-edit-feedback')for(const k of Object.keys(local))if(/^(shot|caption|start|end|emphasis):/.test(k)&&local[k]===submitted[k])delete local[k];
        if(!Object.keys(local).some(k=>/^(shot|caption|start|end|emphasis):/.test(k)))localStorage.removeItem(storageKey(task)+'-edit');
        if(Object.keys(local).length){localStorage.setItem(storageKey(task),JSON.stringify(local));localStorage.setItem(storageKey(task)+'-revision',String(result.feedback_revision||0));}else{localStorage.removeItem(storageKey(task));localStorage.removeItem(storageKey(task)+'-revision');}root._feedbackBaseRevision=null;
        if(root._task.id!==task.id){options.onUpdate?.(result);return;}
        root._dirty=false;root._renderedRevision=null;document.activeElement.blur();options.onUpdate?.(result);mount(root,result,options);
        message(({'prepare-caption-preview':'실시간 자막 미리보기가 준비됐습니다.','save-captions':'편집 내용을 저장했습니다. 내보내기를 누르면 이 자막으로 MP4를 만듭니다.','export-edit':'마지막 편집 내용을 저장했습니다. 해당 버전의 내보내기 결과는 아래에서 확인하세요.','save-original':'교정본을 저장했습니다. 제작 대본은 그대로이며, 다음 AI 수정 요청에 교정본을 사용합니다.','review-result':'이 버전의 사용자 검토를 완료했습니다.','discard-feedback':'저장한 변경사항을 초기화했습니다.','discard-edit-feedback':'구간 수정만 초기화했습니다. 대본·음성·소스 변경은 유지됩니다.','propose-script':'지금 입력한 대본으로 AI 수정안을 요청했습니다. 완료되면 변경 전후를 비교하세요.','search':'추가 검색을 요청했습니다. 확보된 영상은 목록에서 선택해 다음 제작에 사용하세요.','retry-source-search':'소스 검색 재시도를 요청했습니다. 현재 검색 상태를 확인하세요.','use-sources':'선택한 영상으로 제작을 이어갑니다. 현재 단계에서 진행 상황을 확인하세요.',retry:'재시도 요청을 접수했습니다. 위 현재 단계에서 실행 상태를 확인하세요.','start-auto':'자동 제작 요청을 접수했습니다.','resume-auto':'자동 진행 재개를 요청했습니다.','pause-auto':'자동 진행 중지를 요청했습니다. 현재 실행 중인 작업은 마무리될 수 있습니다.','make-video':'수정사항을 저장하고 새 영상 제작을 시작했습니다. 진행 상황은 위에서 확인하세요.',reproduce:'재제작 요청 완료'})[action]||'보관했습니다. 수정한 영상 만들기를 누르면 영상에 반영합니다.');
      }catch(e){if(['save-captions','export-edit','prepare-caption-preview'].includes(action))root._captionError=window.StudioBoard.message(e.message);message(window.StudioBoard.message(e.message));}finally{root._saving=false;if(button.isConnected){button.textContent=originalLabel;button.removeAttribute('aria-busy');button.disabled=false;}updateSourceSearch(root,root._task);window.CaptionEditor?.refresh(root,root._task);refreshActions(root);}
    };
    bindUploads();window.VoicePicker?.bind(root);window.CaptionEditor?.bind(root,t);refreshActions(root);window.StudioDetail.restore(root);options.onRender?.();
  }
  window.ProductionFlow={mount,api,scriptReview,originalPanel,editor,runtime,summary,progress};
})();
