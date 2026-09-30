/* Both surfaces consume the same task and immutable run artifacts. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={pending:'대기',running:'진행 중',completed:'완료',failed:'확인 필요',waiting:'대기 중',superseded:'수정본으로 전환',legacy:'기존 작업'};
  const link=(url,label)=>url?`<a href="${esc(url)}" download>${esc(label)} ↓</a>`:'';
  const item=(t,c,id)=>t[c].find(v=>v.id===id);
  const storageKey=t=>'production-feedback-'+t.id;
  function sourceSearchState(t){
    const jobs=t.jobs||[],search=t.source_search||{};
    const busy=jobs.find(j=>['prepare','refresh_sources'].includes(j.kind)&&['queued','running'].includes(j.status));
    const latest=jobs.find(j=>j.kind==='refresh_sources');
    const failed=search.status==='failed'&&latest?.status==='failed'?latest:null;
    // A prepare failure may be transcription or rewriting; only an explicit missing-source error is actionable here.
    const missing=!t.sources?.length&&/Source manifest contains no selected local videos|제작에 사용할 소스 영상이 없습니다/.test(t.error||'');
    return {busy,failed,missing};
  }
  function sourceSearchStatus(t){
    const {busy,failed,missing}=sourceSearchState(t),search=t.source_search||{};
    if(busy)return `<div class="pf-search-notice" role="status"><strong>${busy.kind==='prepare'?'제작 자료 준비 중':busy.status==='queued'?'소스 검색 대기 중':'소스 검색 진행 중'}</strong><p>${esc(window.StudioBoard.message(busy.kind==='prepare'?t.message:search.message,'현재 요청을 처리하고 있습니다.'))}</p><small>현재 작업이 끝나면 추가 검색할 수 있어요.</small></div>`;
    if(failed||missing)return `<div class="pf-search-notice is-error" role="status"><strong>${failed?'소스 검색이 중단됐어요':'사용할 소스를 확보하지 못했어요'}</strong><p>${esc(window.StudioBoard.message(failed?search.message:t.error))}</p><button data-pf="retry-source-search" ${failed?`data-job-id="${esc(failed.id)}"`:''} ${failed&&!t.source_search_retry_supported?'disabled':''}>실패한 소스 검색 다시 시도</button><small>${failed&&!t.source_search_retry_supported?'서버 업데이트 적용이 필요합니다. 로컬 Hotpost 서버를 재시작한 뒤 새로고침하세요. 아래에서 검색 조건을 직접 입력해 추가 검색할 수도 있습니다.':(failed?'이전 검색 조건으로 다시 실행합니다.':'기본 검색을 다시 실행합니다. 확보 후 사용할 영상을 선택해 제작을 이어가세요.')+' 인증·연결 문제가 있었다면 먼저 해결해 주세요.'}</small></div>`;
    return search.status==='done'?`<p class="pf-help" role="status">${esc(window.StudioBoard.message(search.message,''))}</p>`:'';
  }
  function sourceSearchPanel(t){
    const {busy}=sourceSearchState(t);
    return `<section class="pf-source-search"><div data-search-status>${sourceSearchStatus(t)}</div><details class="pf-advanced" data-search-options ${!t.sources?.length&&!busy?'open':''}><summary>조건을 바꿔 추가 검색</summary><p class="pf-help">원하는 장면이 부족할 때 제품명·동작·촬영 장면을 구체적으로 입력하세요. 처음 소스 찾기와 같은 검색을 새 조건으로 다시 실행하며, 기존 영상은 유지합니다.</p><label>추가로 필요한 장면<textarea data-field="search" maxlength="1000" placeholder="예: 캠핑 수납 가방을 펼쳐 내부 칸막이를 보여주는 장면" aria-describedby="source-search-help"></textarea></label><p class="pf-help" id="source-search-help">새 영상이 발견되지 않을 수도 있습니다. 기존 결과의 다음 페이지를 가져오는 기능은 아닙니다.</p><button data-pf="search" ${busy?'disabled':''}>입력한 조건으로 추가 검색</button><p data-search-validation role="status"></p>${audit(t.source_audit)}</details></section>`;
  }
  function updateSourceSearch(root,t){
    const box=root.querySelector('[data-search-status]');
    if(box){const html=sourceSearchStatus(t);if(box.innerHTML!==html)box.innerHTML=html;}
    const button=root.querySelector('[data-pf="search"]');
    if(button)button.disabled=!!sourceSearchState(t).busy||!!root._saving;
  }
  function originalPanel(t, expanded=false){
    const evidence=t.original_evidence||{},speech=evidence.speech||[],screen=evidence.screen_text||[];
    return `<details class="pf-original" ${expanded?'open':''}><summary>원본 발화 확인 · 잘못 인식한 말 교정</summary><p class="pf-help">영상에서 실제로 들리는 말만 교정하세요. 자동 인식 원문은 보존됩니다. 교정본 저장은 제작 대본·음성을 바꾸지 않으며, 다음 AI 수정 요청과 문장 검사의 참고 자료로 사용됩니다.</p>
      ${evidence.speech_unavailable?'<p class="pf-version-note">원본 음성 전사를 완료하지 못했어요. 영상에서 음성이 들리는지 확인하고, 전사 도구 설치 상태를 점검한 뒤 중단 단계를 재시도하세요.</p>':''}<div class="pf-evidence-grid">${t.reference_url?`<video data-reference-preview controls playsinline preload="metadata" src="${esc(t.reference_url)}"></video>`:'<p>원본 영상 미리보기가 없습니다. 확보한 원본을 확인한 뒤 교정하세요.</p>'}<div>${speech.length?`<details><summary>시간별 자동 인식 발화</summary>${speech.map(row=>`<p><button data-reference-seek="${Number(row.start)||0}" ${t.reference_url?'':'disabled'}>${(Number(row.start)||0).toFixed(1)}초 ▷</button> ${esc(row.text)}</p>`).join('')}</details>`:''}<label>원본 발화 교정본<textarea data-field="original" maxlength="12000">${esc(t.reviewed_original_text??t.original_text??'')}</textarea></label><button data-pf="save-original">발화 교정본 저장</button><details><summary>자동 인식 원문 · 보존됨</summary><p class="pf-text">${esc(t.original_text||'아직 발화를 추출하지 못했어요.')}</p></details>${screen.length?`<details><summary>화면 속 글자 · 발화와 별도 자료</summary>${screen.map(row=>`<p>${esc(row.text)}</p>`).join('')}</details>`:''}</div></div></details>`;
  }
  function changeStatus(t){
    const f=t.feedback||{},local=JSON.parse(localStorage.getItem(storageKey(t))||'{}');
    const groups=[['script_text','대본'],['speed','속도'],['pronunciations','발음'],['regenerate_voice','새 음성'],['source_ids','사용 영상'],['changes','장면·자막']].filter(([k])=>k in f);
    const oldEdit=localStorage.getItem(storageKey(t)+'-edit');
    const staleEdit=oldEdit&&oldEdit!==t.edit_id&&Object.keys(local).some(k=>/^(shot|caption|start|end|emphasis):/.test(k));
    const conflict=f.changes?.length&&['script_text','speed','pronunciations','regenerate_voice','source_ids'].some(k=>k in f);
    if(!Object.keys(local).length&&!groups.length)return '<div class="pf-change-status"><strong>수정사항 없음 · 변경한 항목을 저장하면 재제작할 수 있어요</strong></div>';
    return `<div class="pf-change-status" role="status">${staleEdit?'<p>새 편집본이 준비되어 이전 구간 입력을 보관 중입니다. 내용을 복사한 뒤 구간 입력만 비우고 새 영상을 확인하세요.</p><details><summary>보관된 이전 구간 입력</summary><p class="pf-text">'+Object.entries(local).filter(([k])=>/^(caption|start|end):/.test(k)).map(([,v])=>esc(v)).join('<br>')+'</p></details><button data-pf="discard-local-edit">이전 구간 입력만 비우기</button>':''}<strong>${Object.keys(local).length?'● 저장하지 않은 입력이 있어요':groups.length?'● 저장됨 · 다음 제작에 반영 예정':'✓ 저장된 제작 내용'}</strong><div class="pf-change-chips">${groups.map(([,label])=>`<span>${label}</span>`).join('')}</div><p>${Object.keys(local).length?'수정한 항목의 저장 버튼을 눌러주세요. 다른 항목의 입력도 유지됩니다.':impact(f)}</p>${conflict?'<p>새 대본·음성·소스와 기존 구간 수정을 함께 적용할 수 없어요. 기존 완성본은 보존됩니다.</p><button data-pf="discard-edit-feedback">구간 수정만 초기화</button>':''}</div>`;
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
  async function api(path,body){const r=await fetch('/api/studio'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(window.StudioBoard.message(d.error,'요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.'));return d;}
  function progress(t,active){
    const d=window.StudioBoard.describe(t),live=d.state==='running';
    const assets=active?.steps||[],keys=['sources','transcript','script','voice','project','export'];
    const label=i=>assets.find(s=>s.key===keys[i])?.label||d.steps[i].label;
    const next=d.steps.find((s,i)=>i>d.currentIndex&&s.state!=='done');
    const nextText=d.complete?'모든 단계가 끝났습니다. 아래에서 완성 영상을 확인하세요.':next?`다음 단계 · ${next.number}. ${label(next.number-1)}`:'다음 · 최종 영상 확인';
    return `<div class="pf-progress" data-state="${d.state}">
      <div class="pf-current" role="status" aria-live="polite" aria-atomic="true">
        <div class="pf-current-title"><span class="pf-activity ${live?'pf-spinner':''}" aria-hidden="true">${live?'':d.complete?'✓':d.attention||d.review?'!':d.state==='paused'?'Ⅱ':'…'}</span><div><span class="pf-phase">${d.complete?'제작 완료':`현재 ${d.currentIndex+1} / 6 단계`} · ${esc(d.label)}</span><strong>${esc(d.complete?'최종 영상 제작 완료':label(d.currentIndex))}</strong></div></div>
        <p class="pf-current-message">${esc(d.message)}</p><p class="pf-next">${esc(nextText)}</p>
      </div>
      <div class="pf-progress-caption"><strong>${d.done} / 6 단계 완료</strong><span>완료 단계 기준 · 소요시간 비율 아님</span></div>
      <div class="pf-progress-track" role="progressbar" aria-label="자동 제작 완료 단계" aria-valuemin="0" aria-valuemax="6" aria-valuenow="${d.done}" aria-valuetext="${esc(`${d.done} / 6 단계 완료, ${d.complete?'제작 완료':label(d.currentIndex)+' '+d.label}`)}"><div style="width:${d.done/6*100}%"></div></div>
      <ol class="pf-steps" aria-label="자동 제작 순서">${d.steps.map((s,i)=>{
        const asset=assets.find(a=>a.key===keys[i]);
        return `<li class="${s.current?'current '+d.state:s.state==='done'?'completed':'pending'}" ${s.current?'aria-current="step"':''}><span class="pf-step-number" aria-hidden="true">${s.state==='done'?'✓':s.number}</span><div class="pf-step-content"><b>${s.number}. ${esc(label(i))}</b><span class="pf-step-status">${s.current&&live?'<i class="pf-spinner" aria-hidden="true"></i>':''}${s.current?esc(d.label):s.state==='done'?'완료':'예정'}</span>${link(asset?.download_url,'다운로드')}</div>${i<5?'<span class="pf-connector" aria-hidden="true">→</span>':''}</li>`;
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
      ['voice','TTS 음성','이 버전의 내레이션','WAV',url('voice'),'voice'],
      ['project','CapCut 프로젝트','다시 편집할 수 있는 파일','ZIP',url('project'),'project']
    ];
    const final=url('export');
    return `<section class="pf-downloads" aria-label="다운로드"><header class="pf-download-heading"><div><span class="pf-download-mark">${fileIcon('download')}</span><div><h4>다운로드</h4><p>완성 영상과 제작 자료를 받아보세요</p></div></div><span class="pf-download-version">V${esc(run.number)} 자료</span></header>
      ${final?`<a class="pf-download-final" href="${esc(final)}" download aria-label="완성 영상 MP4 다운로드"><span class="pf-file-icon">${fileIcon('video')}</span><span class="pf-file-copy"><strong>완성 영상</strong><small>편집이 끝난 최종 영상 · MP4</small></span><span class="pf-final-cta">영상 저장 ${fileIcon('download')}</span></a>`:'<div class="pf-download-pending"><span class="pf-file-icon">'+fileIcon('video')+'</span><span><strong>완성 영상이 아직 없어요</strong><small>내보내기가 완료되면 받을 수 있어요</small></span></div>'}
      <div class="pf-download-grid">${files.map(([key,title,description,format,href,icon])=>{const content=`<span class="pf-file-icon">${fileIcon(icon)}</span><span class="pf-file-copy"><strong>${title}</strong><small>${description}</small><span class="pf-file-format">${href?format:'아직 없음'}</span></span><span class="pf-file-save">${href?fileIcon('download'):''}</span>`;return href?`<a class="pf-file-card" data-download-asset="${key}" href="${esc(href)}" download aria-label="${title} ${format} 다운로드">${content}</a>`:`<div class="pf-file-card is-unavailable" data-download-asset="${key}" aria-disabled="true">${content}</div>`;}).join('')}</div>
      ${url('project')?`<footer class="pf-download-edit"><span>장면이나 자막을 더 다듬고 싶다면</span><button data-pf="open-capcut" data-edit-id="${esc(run.artifacts.edit_id)}">CapCut에서 편집하기 <span aria-hidden="true">↗</span></button></footer>`:''}</section>`;
  }
  function summary(t,selected){
    const runs=t.pipeline||[], active=runs.find(r=>r.id===t.run_id)||runs.at(-1);
    const display=runs.find(r=>r.id===selected)||runs.find(r=>r.id===t.latest_completed_run_id)||active;
    if(!display)return '';
    return `<div class="pf-summary"><div class="pf-heading"><h3>자동 제작 진행</h3></div>
      ${progress(t,active)}
      <div class="pf-heading"><h4>완성 영상을 확인하세요</h4><select data-pf-version aria-label="제작 결과 버전">${runs.slice().reverse().map(r=>`<option value="${r.id}" ${r.id===display.id?'selected':''}>V${r.number} · ${names[r.status]||'상태 확인'}${r.id===t.latest_completed_run_id?' · 최신 완료':''}</option>`).join('')}</select></div>
      ${Object.keys(t.feedback||{}).length||t.pending_reproduction?'<p class="pf-version-note">저장한 변경사항은 이 결과물에 아직 반영되지 않았어요. 새 버전이 완성되면 비교해 주세요.</p>':''}${display.id!==t.run_id?'<p class="pf-version-note">이전 제작 버전을 보고 있어요. 진행 중인 수정은 이 영상에 반영되지 않았습니다.</p>':''}${display.video_url?`<video controls playsinline preload="metadata" src="${esc(display.video_url)}"></video>`:display.preview_url?`<p>리뷰 미리보기 · CapCut 최종 내보내기 전</p><video controls playsinline preload="metadata" src="${esc(display.preview_url)}"></video>`:'<p>완료되는 단계부터 결과물을 다운로드할 수 있습니다.</p>'}
      ${resultReview(t,display)}${downloads(t,display)}
      <div class="pf-heading"><a href="studio.html?work=${encodeURIComponent(t.id)}">제작실에서 피드백·재제작 →</a>${t.automation?.protocol!==2?'<button data-pf="start-auto">자동 제작 이어서 시작</button>':t.automation?.active&&t.status!=='completed'?'<button data-pf="pause-auto">자동 진행 중지</button>':t.automation?.active?'':'<button data-pf="resume-auto">자동 진행 재개</button>'}</div></div>`;
  }
  function audit(a){
    if(!a)return '';
    const reasons={download_failed:'다운로드 실패',invalid_duration:'영상 길이 확인 필요',heavy_text_overlay:'자막이 많은 영상',low_product_or_scene_similarity:'주제·장면 불일치',title_query_mismatch:'검색어 불일치',low_resolution:'해상도 부족',not_probed:'영상 확인 대기',verification_failed:'영상 검증 실패',platform_budget_exhausted:'검색 시간 종료',platform_cooldown:'검색 서비스 휴식 중'};
    const statuses={timeout:'시간 초과',results:'후보 발견',no_results:'결과 없음',login_required:'로그인 필요',captcha:'사람 확인 필요',rate_limited:'요청 제한',cooldown:'재시도 대기',error:'검색 실패',http_error:'응답 오류',started:'검색 시작'};
    return `<details><summary>소스 검색 내역</summary><p>채택 ${a.selected||0}개 · 제작 가능 ${a.usable??'확인 중'}개</p>${Object.entries(a.platforms||{}).map(([p,n])=>`<p>${esc(p)}: 후보 ${n.candidates} → 다운로드 ${n.received} → 채택 ${n.selected}</p>`).join('')}<p>${Object.entries(a.rejections||{}).map(([r,n])=>esc(reasons[r]||'추가 검토 필요')+': '+n).join(' · ')}</p><details><summary>검색어와 실행 기록</summary>${(a.searches||a.planned_queries||[]).map(q=>`<p>${esc(q.provider||'')} · ${esc({ko:'한국어',en:'영어',zh:'중국어',image:'이미지'}[q.language]||'검색')} · ${esc(q.query)} · ${esc(statuses[q.status]||'확인 중')}</p>`).join('')}</details></details>`;
  }
  function sourceLibrary(t){
    const f=t.feedback||{},run=t.pipeline?.find(r=>r.id===t.run_id);
    const delivered=t.pipeline?.find(r=>r.id===t.latest_completed_run_id);
    // A saved selection is a future edit, not evidence of what the completed video used.
    const baseline=delivered||run;
    const usedIds=baseline?.artifacts?.sources?.map(v=>v.id)??baseline?.inputs?.source_ids??[];
    const selected=f.source_ids??run?.inputs?.source_ids??(usedIds.length?usedIds:t.sources.map(v=>v.id));
    const local=JSON.parse(localStorage.getItem(storageKey(t))||'{}');
    const checked=v=>('source:'+v.id) in local?local['source:'+v.id]:selected.includes(v.id);
    const count=t.sources.filter(checked).length;
    const preparing=['sources','transcript'].includes(window.StudioBoard.describe(t).stage);
    const busy=(t.jobs||[]).some(j=>j.status==='running'&&!['proposal','suggest_edit'].includes(j.kind));
    const used=t.sources.filter(v=>usedIds.includes(v.id));
    const added=t.sources.filter(v=>!usedIds.includes(v.id)&&(v.rights==='user_supplied'||v.original_name));
    const other=t.sources.filter(v=>!usedIds.includes(v.id)&&!added.includes(v));
    const cards=items=>`<div class="pf-sources">${items.map(v=>`<div class="pf-source-card"><video controls preload="metadata" src="${esc(v.url)}"></video><label><input type="checkbox" data-field="source:${v.id}" ${checked(v)?'checked':''}> ${esc(v.original_name||v.title||'소스 영상 '+(t.sources.indexOf(v)+1))}</label><small class="pf-source-usage">${usedIds.includes(v.id)?'현재 제작본에 사용됨':'아직 제작본에 사용하지 않음'}</small>${link(v.url,'영상 다운로드')}</div>`).join('')}</div>`;
    return `<div class="pf-source-library"><div class="pf-source-selection"><span class="pf-count">${t.sources.length}개 보유 · 다음 제작에 <b data-selected-count>${count}</b>개 선택</span>${t.sources.length?'<div class="pf-source-tools"><button type="button" data-pf="select-all-sources">전체 선택</button><button type="button" data-pf="clear-sources">선택 해제</button></div>':''}</div>
      <section class="pf-source-group pf-source-used" data-source-group="used"><div class="pf-section-title"><h4>현재 사용 중인 영상 <span>${used.length}</span></h4><span class="pf-count">${delivered?'완성본 V'+esc(delivered.number)+' 기준':used.length?'현재 제작 기준':'첫 제작 준비'}</span></div><p class="pf-help">체크를 해제하면 다음 제작에서 제외합니다. 현재 영상과 원본 파일은 유지됩니다.</p>${used.length?cards(used):'<p class="pf-empty">아직 제작본에 사용한 영상이 없습니다. 아래에서 영상을 추가하고 선택하세요.</p>'}</section><div class="pf-source-upload"><h4>새 영상 추가</h4><div data-upload-widget></div></div>
      <section class="pf-source-group pf-source-added" data-source-group="added"><div class="pf-section-title"><h4>추가 업로드 영상 <span>${added.length}</span></h4><span class="pf-count">사용 여부 선택</span></div><p class="pf-help">추가한 파일은 현재 사용 중인 영상과 구분해 보관합니다. 체크한 영상만 다음 제작에 포함됩니다.</p>${added.length?cards(added):'<p class="pf-empty">새로 업로드한 영상이 여기에 표시됩니다.</p>'}</section>
      ${other.length?`<details class="pf-source-other" data-source-group="other"><summary>보관 중인 다른 영상 · ${other.length}개</summary>${cards(other)}</details>`:''}
      <div class="pf-source-save">${preparing?`<button class="pf-primary-next" data-pf="use-sources" ${!count||busy?'disabled':''}>선택한 영상으로 제작 이어가기 →</button><p class="pf-help">${busy?'현재 자료 작업이 끝나면 업로드한 영상으로 이어갈 수 있어요.':'선택한 영상을 사용하고, 원본 대본 확인부터 이어서 진행합니다.'}</p>`:`<button data-pf="save-sources" ${!count?'disabled':''}>소스 선택 저장</button><p class="pf-help">저장 후 ‘변경사항 반영해 재제작’을 누르면 선택한 영상으로 새 버전을 만듭니다.</p>`}</div></div>`;
  }
  function editor(t){
    const f=t.feedback||{},run=t.pipeline.find(r=>r.id===t.run_id),inputs=run?.inputs||{};
    const s=item(t,'scripts',t.script_id),e=item(t,'edits',t.edit_id),voice=item(t,'voices',t.voice_id);
    const currentText=f.script_text??s?.text??'';
    return `<div class="pf-editor">
      <details open data-pf-section="sources"><summary>영상 소스 준비</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">↥</span><div><h3>${t.sources.length?'지금 쓰는 영상부터 확인하세요':'영상부터 넣고 시작해 볼까요?'}</h3><p>현재 영상을 빼거나 유지하고, 새 영상을 추가해 다음 제작 구성을 정하세요.</p></div></div>${sourceLibrary(t)}
      ${sourceSearchPanel(t)}</details>
      <details open data-pf-section="original"><summary>원본 발화 확인</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">${fileIcon("voice")}</span><div><h3>듣고 확인하는 원본의 이야기</h3><p>실제 발화를 교정하고, 제작 대본을 위한 참고 자료로 보관하세요.</p></div></div>${originalPanel(t,true)}</details><details open data-pf-section="script"><summary>대본 다듬기</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">✎</span><div><h3>우리 영상의 이야기를 완성하세요</h3><p>직접 고치거나 AI에게 수정할 방향을 알려주세요. 원본과 후보 대본은 아래에서 비교할 수 있어요.</p></div></div>
      <div class="glass-script-grid"><div class="glass-writing"><div class="pf-script-state"><span class="pf-count">${f.script_text!==undefined?'수정 대본 · 반영 대기':'현재 제작 대본'}</span><p>저장 → 변경사항 반영해 재제작 순서로 진행합니다. 기존 음성과 완성본은 새 버전이 준비될 때까지 보존됩니다.</p></div><label>제작에 사용할 대본<textarea maxlength="3000" data-field="script" placeholder="제작할 대본을 입력하세요">${esc(currentText)}</textarea></label><div class="pf-button-row"><button data-pf="save-script">대본 저장</button><button class="pf-secondary" data-pf="check-script">문장 검사</button></div><details class="pf-advanced"><summary>문장 검사 결과</summary><div data-script-review aria-live="polite">${scriptReview((t.script_candidates||[]).find(c=>c.text===currentText))}</div></details>
      </div><div class="pf-tool-card glass-assistant"><div class="glass-card-kicker">WRITING ASSISTANT</div><h4>다른 표현이 필요할 때</h4><label>AI에게 수정 요청<textarea data-field="script-request" placeholder="예: 시작을 질문으로 바꾸고 설명을 짧게 해줘"></textarea></label><button data-pf="propose-script" ${s?'':'disabled'}>수정안 만들기</button>${!s?'<p class="pf-help">제작 대본이 준비되면 AI 수정안을 만들 수 있어요.</p>':''}
      <div class="pf-ai-status" data-ai-status="proposal" role="status">${aiStatus(t,'proposal')}</div><div data-proposals>${t.proposals.slice().reverse().map(p=>`<details><summary>수정안 · ${esc(p.summary)}</summary><div class="pf-compare"><div><b>요청 당시 대본</b><p class="pf-text">${esc(p.base_text||s?.text||'')}</p></div><div><b>AI 수정안</b><p class="pf-text">${esc(p.text)}</p></div></div><button data-pf="proposal" data-id="${p.id}">이 수정안 선택</button></details>`).join('')}</div></div>
      </div><details class="pf-advanced"><summary>이전 제작 대본 복원</summary>${t.scripts.slice().reverse().map((v,i)=>`<details><summary>대본 ${t.scripts.length-i}${v.id===t.script_id?' · 현재 제작 기준':''}</summary><p class="pf-text">${esc(v.text)}</p><button data-pf="restore-script" data-script-id="${v.id}">이 대본을 수정본으로 가져오기</button></details>`).join('')}</details><details class="pf-advanced"><summary>원본 · 후보 대본 비교</summary><h4>원본 발화</h4><p class="pf-text">${esc(t.original_text||'원본 영상의 대본을 준비하고 있어요.')}</p><p>${esc(t.selection_reason||'')}</p>
      ${(t.script_candidates||[]).map((c,i)=>`<details><summary>후보 ${i+1}${i===t.selected_candidate?' · 추천':''}</summary><p>${esc(c.text)}</p><button data-pf="candidate" data-index="${i}">이 대본 선택</button></details>`).join('')}</details></details>
      <details open data-pf-section="voice"><summary>목소리와 읽는 속도</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">♫</span><div><h3>들어보고 자연스럽게 다듬으세요</h3><p>속도와 발음을 조절하고 저장하면 다음 음성 제작에 적용됩니다.</p></div></div>${voice?`<div class="pf-audio-card"><b>현재 제작 음성 · ${Number(voice.speed||1).toFixed(2)}배 · ${Number(voice.duration||0).toFixed(1)}초</b>${['script_text','speed','pronunciations','regenerate_voice'].some(k=>k in f)?'<p class="pf-version-note">수정사항 반영 전 음성입니다. 재제작 후 새 음성을 확인하세요.</p>':''}<details><summary>이 음성이 읽는 대본</summary><p class="pf-text">${esc(voice.spoken_text||item(t,'scripts',voice.script_id)?.text||'기록된 대본이 없습니다.')}</p></details><audio controls src="${esc(voice.path_url)}"></audio></div>`:'<div class="pf-empty"><b>음성을 아직 만들지 않았어요</b><p>소스와 대본을 준비하면 음성 제작으로 이어집니다.</p><button data-pf-tab="script">대본 확인하기 →</button></div>'}<div class="pf-tool-card"><label>읽는 속도 <input data-field="speed" type="number" min="0.8" max="1.25" step="0.05" value="${f.speed??inputs.speed??1}"> 배</label><details class="pf-advanced"><summary>발음 교정 · 어려운 단어가 있을 때</summary><label>한 줄에 ‘원문=읽을 발음’<textarea data-field="pronunciation" placeholder="USB=유에스비">${esc((f.pronunciations??inputs.pronunciations??[]).map(p=>p.from+'='+p.to).join('\n'))}</textarea></label><p class="pf-help">자막은 그대로 두고 읽는 발음만 바꿉니다.</p></details><button data-pf="save-voice">음성 설정 저장</button><button class="pf-secondary" data-pf="regenerate-voice" ${voice?'':'disabled'}>음성 다시 만들기 예약</button></div></details>
      <details open data-pf-section="edit"><summary>장면과 자막 편집</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">▣</span><div><h3>장면을 고르고 자막을 맞추세요</h3><p>여기서는 장면 교체와 자막 문구·타이밍을 간단히 고칩니다. 정밀 편집은 CapCut에서 진행하세요. 저장한 수정은 재제작 후 영상에 반영됩니다.</p></div></div>${e?.plan?`<div class="pf-edit-layout"><aside class="pf-edit-preview">${e.preview_url?`<video data-edit-preview controls playsinline preload="metadata" src="${esc(e.preview_url)}"></video>`:'<p>미리보기 준비 중</p>'}<p>현재 미리보기 · 저장한 수정은 재제작 후 보입니다.</p><button class="pf-capcut-launch" data-pf="open-capcut" data-edit-id="${e.id}"><span aria-hidden="true">↗</span> CapCut에서 직접 편집</button><p class="pf-capcut-help">타임라인 · 파형 · 프레임 단위 정밀 편집</p><div class="pf-sync-preview"><small>싱크 확인용 대사</small><strong data-sync-caption>오른쪽에서 구간 반복 듣기를 누르세요.</strong><span data-sync-range></span></div></aside><div class="pf-edit-timeline"><details class="pf-advanced"><summary>AI에게 구간 수정 요청</summary><label>구간 수정 요청<textarea data-field="edit-request" placeholder="예: 첫 장면을 교체하고 마지막 자막을 강조해줘"></textarea></label><label>시작 초 <input data-field="edit-start" type="number" value="0" min="0" step="0.01"></label><label>끝 초 <input data-field="edit-end" type="number" value="${e.duration}" min="0" step="0.01"></label><button data-pf="request-edit">수정안 준비</button><div class="pf-ai-status" data-ai-status="suggest_edit" role="status">${aiStatus(t,'suggest_edit')}</div></details>
      ${e.plan.beats.map(b=>{const c=e.plan.cues.find(v=>v.id===b.cue_id),draft=f.changes?.find(v=>v.beat_id===b.id)||{};return `<div class="pf-beat" data-sync-beat="${esc(b.id)}"><button class="pf-secondary pf-time" data-pf-seek="${b.start}">▷ ${b.start.toFixed(2)}–${b.end.toFixed(2)}초</button>${b.needs_review||t.candidate_requests?.includes(b.id)?'<span class="pf-count">장면 확인 필요</span>':''}<details class="pf-advanced"><summary>장면 선택 이유</summary><p>${esc(b.reason)}</p></details><p class="pf-narration"><b>이 구간의 대사</b> ${esc(b.text)}</p><label>장면 <select data-field="shot:${b.id}">${b.options.map((o,i)=>`<option value="${o.shot_id}" ${(draft.shot_id||b.selected_shot_id)===o.shot_id?'selected':''}>${esc('장면 '+(i+1)+' · '+o.reason)}</option>`).join('')}</select></label><details><summary>장면 후보 영상 보기</summary><div class="pf-sources">${b.options.map(o=>{const shot=e.plan.shots.find(s=>s.id===o.shot_id);return `<div><video controls preload="none" src="${esc(shot.video_url)}#t=${shot.start},${shot.end}"></video><small>${esc(shot.observation)}</small></div>`;}).join('')}</div></details>
      <label>자막 <input data-field="caption:${b.id}" value="${esc(draft.text??c.text)}"></label><div class="pf-sync-tools"><div class="pf-sync-main"><button type="button" data-sync="loop" data-beat="${b.id}" aria-pressed="false">▷ 이 구간 반복 듣기</button><span class="pf-help">듣고 시작·끝을 맞춰보세요</span></div><div class="pf-sync-marks"><button type="button" data-sync="start" data-beat="${b.id}">현재 위치를 시작으로</button><button type="button" data-sync="end" data-beat="${b.id}">현재 위치를 끝으로</button></div><div class="pf-sync-shift"><span>자막 전체 이동</span><button type="button" data-sync="earlier" data-beat="${b.id}" aria-label="이 자막을 0.1초 앞당기기">−0.1초</button><button type="button" data-sync="later" data-beat="${b.id}" aria-label="이 자막을 0.1초 늦추기">＋0.1초</button><output data-sync-times>${Number(draft.start??c.start).toFixed(2)}–${Number(draft.end??c.end).toFixed(2)}초</output></div><p class="pf-sync-feedback" role="status"></p></div><details class="pf-advanced"><summary>정밀 시간 입력 · 강조 설정</summary><label>시작 <input type="number" step="0.01" data-field="start:${b.id}" value="${draft.start??c.start}"></label><label>끝 <input type="number" step="0.01" data-field="end:${b.id}" value="${draft.end??c.end}"></label><label>강조 <select data-field="emphasis:${b.id}">${[0,1,2].map(n=>`<option value="${n}" ${(draft.emphasis??b.emphasis)===n?'selected':''}>${['없음','분명하게','강하게'][n]}</option>`).join('')}</select></label></details><button data-pf="save-beat" data-beat="${b.id}">이 구간 피드백 저장</button></div>`;}).join('')}</div></div>`:'<div class="pf-empty"><b>편집할 영상이 아직 없어요</b><p>음성 제작이 끝나면 장면과 자막을 준비합니다.</p><button data-pf-tab="voice">음성 준비 상태 보기 →</button></div>'}</details><div class="pf-actionbar"><div data-change-status>${changeStatus(t)}</div><p class="pf-impact">${impact(f)}</p><button data-pf="discard-feedback">변경사항 초기화</button><button data-pf="reproduce" ${t.pending_reproduction||!Object.keys(f).length?'disabled':''}>${t.pending_reproduction?'현재 단계 종료 후 재제작 대기':'변경사항 반영해 재제작 →'}</button></div></div>`;
  }
  function aiStatus(t,kind){
    const job=(t.jobs||[]).find(j=>j.kind===kind);if(!job)return '';
    if(['queued','running'].includes(job.status))return '<span class="pf-spinner" aria-hidden="true"></span><strong>AI 수정안을 준비하고 있어요</strong><p>완료되면 이곳에 표시됩니다. 현재 영상과 입력은 유지됩니다.</p>';
    if(job.status==='failed')return '<strong>수정안을 만들지 못했어요</strong><p>'+esc(window.StudioBoard.message(job.error))+'</p><p>요청 내용을 구체화해 다시 보내거나 직접 수정할 수 있어요.</p>';
    if(job.status==='done'){
      if(kind==='proposal')return '<strong>수정안 준비 완료</strong><p>아래에서 변경 전후를 비교하고 사용할 수정안을 선택하세요.</p>';
      return t.feedback?.changes?'<strong>구간 수정안 저장됨 · 영상 반영 대기</strong><p>'+esc((t.jobs||[]).find(j=>['proposal','suggest_edit'].includes(j.kind))?.id===job.id?t.feedback_message||'':'')+'</p><p>하단의 변경사항 반영해 재제작을 누르면 새 영상에 적용됩니다.</p>':'<strong>이전 수정 요청 처리 완료</strong><p>새 영상에서 추가로 수정할 구간을 선택할 수 있어요.</p>';
    }
    return '';
  }
  function impact(f){if(!Object.keys(f).length)return '수정한 항목을 저장하면 새 버전을 만들 수 있어요';if(['script_text','speed','pronunciations','regenerate_voice'].some(k=>k in f))return '다음 제작: 음성 → 장면·자막 → 최종 영상 · 기존 완료본 보존';if('source_ids' in f||f.changes)return '다음 제작: 장면·자막 → 최종 영상 · 기존 음성 재사용';return '피드백 저장됨';}
  function runtime(t){
    const action=t.error?'<button data-pf="retry">중단 단계 재시도</button>':t.automation?.active&&t.status!=='completed'?'<button data-pf="pause-auto">자동 진행 중지</button>':!t.automation?.active&&t.status!=='completed'?'<button data-pf="resume-auto">자동 진행 재개</button>':'';
    return `<div class="pf-runtime">${action}<p>${esc(window.StudioBoard.message(t.error||t.message))}</p></div>`;
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
    if(root._syncSelected===id){root.querySelector('[data-sync-caption]').textContent=f.caption.value;root.querySelector('[data-sync-range]').textContent=range+' · 기존 영상 자막은 재제작 후 바뀝니다';}
  }
  function stopSync(root){
    root._syncLoop=null;
    root.querySelectorAll('[data-sync="loop"]').forEach(b=>{b.textContent='▷ 이 구간 반복 듣기';b.setAttribute('aria-pressed','false');});
  }
  function bindSyncPreview(root){
    stopSync(root);root._syncSelected=null;root.querySelectorAll('[data-sync-beat]').forEach(card=>syncReadout(root,card.dataset.syncBeat));const video=root.querySelector('[data-edit-preview]');if(!video)return;
    video.ontimeupdate=()=>{
      if(!root._syncLoop||video.paused)return;
      const f=syncFields(root,root._syncLoop),start=Number(f.start?.value),end=Number(f.end?.value);
      if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>video.duration){video.pause();return;}
      if(video.currentTime>=end||video.currentTime<start-.05)video.currentTime=start;
    };
    video.onpause=()=>{if(!video.ended)stopSync(root);};
    video.onended=()=>{
      if(!root._syncLoop)return;
      const f=syncFields(root,root._syncLoop);video.currentTime=Number(f.start.value);
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
    if(action==='earlier'||action==='later'){const shift=action==='earlier'?-.1:.1;start=Math.round((start+shift)*100)/100;end=Math.round((end+shift)*100)/100;}
    if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>video.duration){note.textContent='시작은 0초 이상, 끝은 시작보다 뒤여야 해요. 영상 길이 '+video.duration.toFixed(2)+'초 안에서 지정하세요.';return;}
    root._syncSelected=id;
    if(action==='loop'){
      stopSync(root);root._syncLoop=id;button.textContent='Ⅱ 반복 듣기 중지';button.setAttribute('aria-pressed','true');syncReadout(root,id);
      video.currentTime=start;
      video.play().catch(()=>{stopSync(root);note.textContent='영상의 재생 버튼을 눌러 재생 상태를 확인하세요.';});
      note.textContent='이 구간을 반복 재생합니다. 수정 자막의 최종 영상 반영은 저장 후 재제작으로 진행하세요.';
    }else{
      for(const [field,value] of [[f.start,start],[f.end,end]]){if(Number(field.value)!==value){field.value=value.toFixed(2);field.dispatchEvent(new Event('input',{bubbles:true}));}}
      syncReadout(root,id);note.textContent='타이밍 수정됨 · 이 구간 피드백 저장을 눌러주세요.';
    }
  }
  function mount(root,t,options={}){
    root._task=t;root._options=options;
    const bindUploads=()=>window.SourceUpload?.bind(root,t,result=>{options.onUpdate?.(result);mount(root,result,options);},()=>{root._renderedRevision=null;mount(root,root._task,options);});
    if(root._taskId!==t.id){root._taskId=t.id;root._selected=null;root._dirty=false;root._feedbackBaseRevision=null;root._renderedRevision=null;root.innerHTML='';}
    updateSourceSearch(root,t);
    const status=root.querySelector('[data-change-status]');if(status)status.innerHTML=changeStatus(t);
    const runningNote=root.querySelector('.pf-runtime');
    if(runningNote){const temp=document.createElement('div');temp.innerHTML=runtime(t);const content=temp.firstElementChild.innerHTML;if(runningNote.innerHTML!==content)runningNote.innerHTML=content;}
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
          if(old.outerHTML!==next.outerHTML){
            if(selector==='.pf-current')old.innerHTML=next.innerHTML;
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
          if(before&&after){if(before.innerHTML!==after.innerHTML)before.innerHTML=after.innerHTML;}
          else if(before)before.remove();
          else if(after)library.insertBefore(after,library.querySelector('.pf-source-save'));
        }
        if(focusedField&&!library.contains(document.activeElement))[...library.querySelectorAll('[data-field]')].find(e=>e.dataset.field===focusedField)?.focus({preventScroll:true});
      }
      bindUploads();
      options.onRender?.();return;
    }
    if(root._renderedRevision===t.revision && root._renderedSelected===root._selected && root.querySelector('.production-flow')){options.onRender?.();return;}
    root._renderedRevision=t.revision;root._renderedSelected=root._selected;root._renderedEditId=t.edit_id;
    const mediaPositions=new Map([...root.querySelectorAll('video,audio')].map(m=>[m.getAttribute('src'),m.currentTime]));
    const opens=[...root.querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent);
    const searchOpen=root.querySelector('[data-search-options]')?.open;
    root.innerHTML=`<section class="production-flow">${options.editor&&t.automation?.protocol===2?runtime(t):''}${summary(t,root._selected)}${options.editor&&t.automation?.protocol===2?editor(t):''}<p class="pf-message" role="status"></p></section>`;
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
    root.oninput=event=>{const e=event.target;if(e.dataset.reviewCheck){const id=e.closest('[data-review-run]').dataset.reviewRun;root._reviewChecks??={};root._reviewChecks[id]??={};root._reviewChecks[id][e.dataset.reviewCheck]=e.checked;return;}if(!e.dataset.field)return;if(/^(caption|start|end):/.test(e.dataset.field))syncReadout(root,e.dataset.field.split(':')[1]);if(e.dataset.field==='script'){const review=root.querySelector('[data-script-review]');if(review)review.textContent='대본이 바뀌었어요. 다시 검사해 주세요.';}if(!root._dirty){root._feedbackBaseRevision=root._task.feedback_revision||0;localStorage.setItem(storageKey(root._task)+'-revision',String(root._feedbackBaseRevision));}root._dirty=true;const draft=JSON.parse(localStorage.getItem(storageKey(root._task))||'{}');draft[e.dataset.field]=e.type==='checkbox'?e.checked:e.value;if(/^(shot|caption|start|end|emphasis):/.test(e.dataset.field)&&!localStorage.getItem(storageKey(root._task)+'-edit'))localStorage.setItem(storageKey(root._task)+'-edit',root._renderedEditId||'');localStorage.setItem(storageKey(root._task),JSON.stringify(draft));const status=root.querySelector('[data-change-status]');if(status)status.innerHTML=changeStatus(root._task);if(e.dataset.field.startsWith('source:')){const n=root.querySelectorAll('[data-field^="source:"]:checked').length;root.querySelector('[data-selected-count]').textContent=n;for(const button of root.querySelectorAll('[data-pf="use-sources"],[data-pf="save-sources"]'))button.disabled=!n||button.dataset.pf==='use-sources'&&(root._uploading||(root._task.jobs||[]).some(j=>j.status==='running'&&!['proposal','suggest_edit'].includes(j.kind)));}};
    bindSyncPreview(root);
    root.onchange=async event=>{
      if(event.target.matches('[data-pf-version]')){
        root._selected=event.target.value;root._dirty=false;
        // An explicit version switch must bypass the focus/playback refresh guard.
        event.target.blur();root.querySelectorAll('video,audio').forEach(v=>v.pause());
        mount(root,root._task,options);
      }
    };
    const message=text=>{const m=root.querySelector('.pf-message');if(m)m.textContent=text;};
    const field=name=>[...root.querySelectorAll('[data-field]')].find(e=>e.dataset.field===name);
    const value=name=>field(name)?.value||'';
    root.onclick=async event=>{
      const sync=event.target.closest('[data-sync]');if(sync){adjustSync(root,sync);return;}
      const ref=event.target.closest('[data-reference-seek]');if(ref){const video=root.querySelector('[data-reference-preview]');if(video)video.currentTime=Number(ref.dataset.referenceSeek);return;}
      const seek=event.target.closest('[data-pf-seek]');if(seek){const video=root.querySelector('[data-edit-preview]');if(video)video.currentTime=Number(seek.dataset.pfSeek);return;}
      const tab=event.target.closest('[data-pf-tab]');if(tab){options.onTab?.(tab.dataset.pfTab);return;}
      const button=event.target.closest('[data-pf]');if(!button)return;
      if(root._saving)return;
      const action=button.dataset.pf, task=root._task;let kind=action,body={};
      const submitted=JSON.parse(localStorage.getItem(storageKey(task))||'{}');
      if(action==='discard-local-edit'){for(const k of Object.keys(submitted))if(/^(shot|caption|start|end|emphasis):/.test(k))delete submitted[k];localStorage.setItem(storageKey(task),JSON.stringify(submitted));localStorage.removeItem(storageKey(task)+'-edit');root._dirty=false;root._renderedRevision=null;document.activeElement.blur();mount(root,task,options);return;}
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
        body={speed:Number(value('speed')),pronunciations:value('pronunciation').split('\n').filter(v=>v.trim()).map(v=>{const pos=v.indexOf('=');return {from:pos<0?'':v.slice(0,pos).trim(),to:pos<0?'':v.slice(pos+1).trim()};})};
      }
      if(action==='propose-script')body={request:value('script-request'),base_text:value('script')};
      if(['candidate','restore-script'].includes(action)&&'script' in submitted){message('직접 수정한 대본을 먼저 저장하세요. 저장 후 다른 대본을 선택할 수 있습니다.');return;}
      if(['propose-script','check-script'].includes(action)&&'original' in submitted){message('교정한 원본 발화를 먼저 저장하세요.');return;}
      if(action==='request-edit')body={edit_id:root._renderedEditId,request:value('edit-request'),start:Number(value('edit-start')),end:Number(value('edit-end'))};
      if(action==='open-capcut')body={edit_id:button.dataset.editId};
      if(action==='save-beat'){kind='revise-edit';const id=button.dataset.beat;body={edit_id:root._renderedEditId,changes:[{beat_id:id,shot_id:value('shot:'+id),text:value('caption:'+id),start:Number(value('start:'+id)),end:Number(value('end:'+id)),emphasis:Number(value('emphasis:'+id))}]};}
      if(action==='reproduce'&&root._dirty){message('입력한 항목의 피드백 저장 버튼을 먼저 눌러주세요.');return;}
      root._saving=true;button.disabled=true;message('저장·요청 중…');
      try{
        if(action==='check-script'){
          const text=value('script'),result=await api('/'+task.id+'/check-script',{text});
          if(root._task.id===task.id&&value('script')===text){root.querySelector('[data-script-review]').innerHTML=scriptReview(result);message('현재 입력한 대본 검사 완료');}
          else message('검사 중 대본이 바뀌었어요. 다시 검사해 주세요.');
          return;
        }
        const fresh=await api('/'+task.id);
        if(body.retry_job_id&&!fresh.source_search_retry_supported)throw new Error('로컬 Hotpost 서버를 재시작한 뒤 새로고침해 주세요. 이전 검색 조건을 복원하려면 서버 업데이트 적용이 필요합니다.');
        const feedbackActions=['save-feedback','save-script','restore-script','apply-proposal','regenerate-voice','revise-edit','request-edit','reproduce','discard-feedback','select-candidate','discard-edit-feedback'];
        const result=await api('/'+task.id+'/'+kind,{revision:fresh.revision,...(feedbackActions.includes(kind)?{feedback_revision:root._feedbackBaseRevision??task.feedback_revision??0}:{}),...body});
        // Preserve unsaved fields in other sections; clear only fields saved here.
        const local=JSON.parse(localStorage.getItem(storageKey(task))||'{}');
        const prefixes=action==='save-original'?['original']:action==='save-script'?['script']:action==='save-voice'||action==='regenerate-voice'?['speed','pronunciation']:['save-sources','use-sources'].includes(action)?['source:']:action==='save-beat'?['shot:'+button.dataset.beat,'caption:'+button.dataset.beat,'start:'+button.dataset.beat,'end:'+button.dataset.beat,'emphasis:'+button.dataset.beat]:action==='search'?['search']:action==='propose-script'?['script-request']:action==='request-edit'?['edit-request','edit-start','edit-end']:[];
        for(const k of Object.keys(local))if(local[k]===submitted[k]&&prefixes.some(p=>k===p||p.endsWith(':')&&k.startsWith(p)))delete local[k];
        if(['candidate','proposal','restore-script'].includes(action)&&local.script===submitted.script)delete local.script;
        if(action==='discard-feedback')for(const k of Object.keys(local))if(local[k]===submitted[k])delete local[k];
        if(action==='discard-edit-feedback')for(const k of Object.keys(local))if(/^(shot|caption|start|end|emphasis):/.test(k)&&local[k]===submitted[k])delete local[k];
        if(!Object.keys(local).some(k=>/^(shot|caption|start|end|emphasis):/.test(k)))localStorage.removeItem(storageKey(task)+'-edit');
        if(Object.keys(local).length){localStorage.setItem(storageKey(task),JSON.stringify(local));localStorage.setItem(storageKey(task)+'-revision',String(result.feedback_revision||0));}else{localStorage.removeItem(storageKey(task));localStorage.removeItem(storageKey(task)+'-revision');}root._feedbackBaseRevision=null;
        if(root._task.id!==task.id){options.onUpdate?.(result);return;}
        root._dirty=false;root._renderedRevision=null;document.activeElement.blur();options.onUpdate?.(result);mount(root,result,options);
        message(({'save-original':'교정본을 저장했습니다. 제작 대본은 그대로이며, 다음 AI 수정 요청에 교정본을 사용합니다.','review-result':'이 버전의 사용자 검토를 완료했습니다.','discard-feedback':'저장한 변경사항을 초기화했습니다.','discard-edit-feedback':'구간 수정만 초기화했습니다. 대본·음성·소스 변경은 유지됩니다.','propose-script':'지금 입력한 대본으로 AI 수정안을 요청했습니다. 완료되면 변경 전후를 비교하세요.','search':'추가 검색을 요청했습니다. 확보된 영상은 목록에서 선택해 다음 제작에 사용하세요.','retry-source-search':'소스 검색 재시도를 요청했습니다. 현재 검색 상태를 확인하세요.','use-sources':'선택한 영상으로 제작을 이어갑니다. 현재 단계에서 진행 상황을 확인하세요.',retry:'재시도 요청을 접수했습니다. 위 현재 단계에서 실행 상태를 확인하세요.','start-auto':'자동 제작 요청을 접수했습니다.','resume-auto':'자동 진행 재개를 요청했습니다.','pause-auto':'자동 진행 중지를 요청했습니다. 현재 실행 중인 작업은 마무리될 수 있습니다.',reproduce:'재제작 요청 완료'})[action]||'저장했습니다. 변경사항 반영은 재제작 버튼으로 실행합니다.');
      }catch(e){message(window.StudioBoard.message(e.message));}finally{root._saving=false;button.disabled=false;updateSourceSearch(root,root._task);}
    };
    bindUploads();options.onRender?.();
  }
  window.ProductionFlow={mount,api,scriptReview,originalPanel};
})();
