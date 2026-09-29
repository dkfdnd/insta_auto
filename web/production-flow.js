/* Both surfaces consume the same task and immutable run artifacts. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={pending:'대기',running:'진행 중',completed:'완료',failed:'확인 필요',waiting:'대기 중',superseded:'수정본으로 전환',legacy:'기존 작업'};
  const link=(url,label)=>url?`<a href="${esc(url)}" download>${esc(label)} ↓</a>`:'';
  const item=(t,c,id)=>t[c].find(v=>v.id===id);
  const storageKey=t=>'production-feedback-'+t.id;
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
  function summary(t,selected){
    const runs=t.pipeline||[], active=runs.find(r=>r.id===t.run_id)||runs.at(-1);
    const display=runs.find(r=>r.id===selected)||runs.find(r=>r.id===t.latest_completed_run_id)||active;
    if(!display)return '';
    return `<div class="pf-summary"><div class="pf-heading"><h3>자동 제작 진행</h3></div>
      ${progress(t,active)}
      <div class="pf-heading"><h4>결과물 · 최신 완료본 우선</h4><select data-pf-version aria-label="제작 결과 버전">${runs.slice().reverse().map(r=>`<option value="${r.id}" ${r.id===display.id?'selected':''}>V${r.number} · ${names[r.status]||'상태 확인'}${r.id===t.latest_completed_run_id?' · 최신 완료':''}</option>`).join('')}</select></div>
      ${display.video_url?`<video controls playsinline preload="metadata" src="${esc(display.video_url)}"></video>`:display.preview_url?`<p>리뷰 미리보기 · CapCut 최종 내보내기 전</p><video controls playsinline preload="metadata" src="${esc(display.preview_url)}"></video>`:'<p>완료되는 단계부터 결과물을 다운로드할 수 있습니다.</p>'}
      <div class="pf-links">${display.steps.map(s=>link(s.download_url,s.label)).join('')}${display.steps.some(s=>s.key==='project'&&s.download_url)?`<button data-pf="open-capcut" data-edit-id="${display.artifacts.edit_id}">CapCut에서 직접 열기</button>`:''}</div>
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
    const selected=f.source_ids||run?.inputs?.source_ids||t.sources.map(v=>v.id);
    const local=JSON.parse(localStorage.getItem(storageKey(t))||'{}');
    const checked=v=>('source:'+v.id) in local?local['source:'+v.id]:selected.includes(v.id);
    const count=t.sources.filter(checked).length;
    const preparing=['sources','transcript'].includes(window.StudioBoard.describe(t).stage);
    const busy=(t.jobs||[]).some(j=>j.status==='running'&&!['proposal','suggest_edit'].includes(j.kind));
    return `<div class="pf-source-library"><div class="pf-section-title"><h4>사용할 영상</h4><span class="pf-count">${t.sources.length}개 보유 · <b data-selected-count>${count}</b>개 선택</span></div>
      ${t.sources.length?`<div class="pf-source-tools"><button type="button" data-pf="select-all-sources">전체 선택</button><button type="button" data-pf="clear-sources">선택 해제</button></div><div class="pf-sources">${t.sources.map((v,i)=>`<div class="pf-source-card"><video controls preload="metadata" src="${esc(v.url)}"></video><label><input type="checkbox" data-field="source:${v.id}" ${checked(v)?'checked':''}> ${esc(v.original_name||'소스 영상 '+(i+1))}</label>${link(v.url,'영상 다운로드')}</div>`).join('')}</div>`:'<div class="pf-empty"><b>아직 사용할 영상이 없어요</b><p>위에 영상을 넣으면 여기에 미리보기와 선택 항목이 나타납니다.</p></div>'}
      ${preparing?`<button class="pf-primary-next" data-pf="use-sources" ${!count||busy?'disabled':''}>선택한 영상으로 제작 이어가기 →</button><p class="pf-help">${busy?'현재 자료 작업이 끝나면 업로드한 영상으로 이어갈 수 있어요.':'선택한 영상을 사용하고, 원본 대본 확인부터 이어서 진행합니다.'}</p>`:`<button data-pf="save-sources" ${!count?'disabled':''}>소스 선택 저장</button><p class="pf-help">저장 후 아래 ‘변경사항 반영해 재제작’을 누르면 선택한 영상으로 편집합니다.</p>`}</div>`;
  }
  function editor(t){
    const f=t.feedback||{},run=t.pipeline.find(r=>r.id===t.run_id),inputs=run?.inputs||{};
    const s=item(t,'scripts',t.script_id),e=item(t,'edits',t.edit_id),voice=item(t,'voices',t.voice_id);
    const currentText=f.script_text??s?.text??'';
    return `<div class="pf-editor">
      <details open data-pf-section="sources"><summary>영상 소스 준비</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">↥</span><div><h3>${t.sources.length?'새 영상을 더 넣거나 사용할 영상을 고르세요':'영상부터 넣고 시작해 볼까요?'}</h3><p>직접 찾은 영상 여러 개를 한 번에 추가하고 제작을 이어가세요.</p></div></div><div data-upload-widget></div>${sourceLibrary(t)}
      <details class="pf-advanced"><summary>직접 찾기 어려우면 · 자동 소스 검색</summary><label>찾을 장면이나 제품<textarea data-field="search" placeholder="예: 캠핑 수납 가방을 사용하는 장면"></textarea></label><button data-pf="search">소스 검색 시작</button><p>${esc(window.StudioBoard.message(t.source_search?.message,''))}</p>${audit(t.source_audit)}</details></details>
      <details open data-pf-section="script"><summary>대본 다듬기</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">✎</span><div><h3>우리 영상의 이야기를 완성하세요</h3><p>직접 고치거나 AI에게 수정할 방향을 알려주세요. 원본과 후보 대본은 아래에서 비교할 수 있어요.</p></div></div>
      <label>제작에 사용할 대본<textarea data-field="script" placeholder="제작할 대본을 입력하세요">${esc(currentText)}</textarea></label><div class="pf-button-row"><button data-pf="save-script">대본 저장</button><button class="pf-secondary" data-pf="check-script">문장 검사</button></div><details class="pf-advanced"><summary>문장 검사 결과</summary><div data-script-review aria-live="polite">${scriptReview((t.script_candidates||[]).find(c=>c.text===currentText))}</div></details>
      <div class="pf-tool-card"><label>AI에게 수정 요청<textarea data-field="script-request" placeholder="예: 시작을 질문으로 바꾸고 설명을 짧게 해줘"></textarea></label><button data-pf="propose-script" ${s?'':'disabled'}>수정안 만들기</button>${!s?'<p class="pf-help">제작 대본이 준비되면 AI 수정안을 만들 수 있어요.</p>':''}
      ${t.proposals.slice().reverse().map(p=>`<details><summary>수정안 · ${esc(p.summary)}</summary><p>${esc(p.text)}</p><button data-pf="proposal" data-id="${p.id}">이 수정안 선택</button></details>`).join('')}</div>
      <details class="pf-advanced"><summary>원본 · 후보 대본 비교</summary><h4>원본 발화</h4><p class="pf-text">${esc(t.original_text||'원본 영상의 대본을 준비하고 있어요.')}</p><p>${esc(t.selection_reason||'')}</p>
      ${(t.script_candidates||[]).map((c,i)=>`<details><summary>후보 ${i+1}${i===t.selected_candidate?' · 추천':''}</summary><p>${esc(c.text)}</p><button data-pf="candidate" data-index="${i}">이 대본 선택</button></details>`).join('')}</details></details>
      <details open data-pf-section="voice"><summary>목소리와 읽는 속도</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">♫</span><div><h3>들어보고 자연스럽게 다듬으세요</h3><p>속도와 발음을 조절하고 저장하면 다음 음성 제작에 적용됩니다.</p></div></div>${voice?`<div class="pf-audio-card"><b>현재 제작 음성</b><audio controls src="${esc(voice.path_url)}"></audio></div>`:'<div class="pf-empty"><b>음성을 아직 만들지 않았어요</b><p>소스와 대본을 준비하면 음성 제작으로 이어집니다.</p><button data-pf-tab="script">대본 확인하기 →</button></div>'}<div class="pf-tool-card"><label>읽는 속도 <input data-field="speed" type="number" min="0.8" max="1.25" step="0.05" value="${f.speed??inputs.speed??1}"> 배</label><details class="pf-advanced"><summary>발음 교정 · 어려운 단어가 있을 때</summary><label>한 줄에 ‘원문=읽을 발음’<textarea data-field="pronunciation" placeholder="USB=유에스비">${esc((f.pronunciations??inputs.pronunciations??[]).map(p=>p.from+'='+p.to).join('\n'))}</textarea></label><p class="pf-help">자막은 그대로 두고 읽는 발음만 바꿉니다.</p></details><button data-pf="save-voice">음성 설정 저장</button><button class="pf-secondary" data-pf="regenerate-voice" ${voice?'':'disabled'}>음성 다시 만들기 예약</button></div></details>
      <details open data-pf-section="edit"><summary>장면과 자막 편집</summary><div class="pf-section-intro"><span class="pf-section-icon" aria-hidden="true">▣</span><div><h3>장면을 고르고 자막을 맞추세요</h3><p>시간 구간별로 장면·자막·강조를 바꾼 뒤 저장하세요.</p></div></div>${e?.plan?`<div class="pf-edit-layout"><aside class="pf-edit-preview">${e.preview_url?`<video data-edit-preview controls playsinline preload="metadata" src="${esc(e.preview_url)}"></video>`:'<p>미리보기 준비 중</p>'}<p>영상을 확인하면서 오른쪽 장면과 자막을 수정하세요.</p><button data-pf="open-capcut" data-edit-id="${e.id}">CapCut에서 직접 편집 ↗</button></aside><div class="pf-edit-timeline"><details class="pf-advanced"><summary>AI에게 구간 수정 요청</summary><label>구간 수정 요청<textarea data-field="edit-request" placeholder="예: 첫 장면을 교체하고 마지막 자막을 강조해줘"></textarea></label><label>시작 초 <input data-field="edit-start" type="number" value="0" min="0" step="0.01"></label><label>끝 초 <input data-field="edit-end" type="number" value="${e.duration}" min="0" step="0.01"></label><button data-pf="request-edit">수정안 준비</button></details>
      ${e.plan.beats.map(b=>{const c=e.plan.cues.find(v=>v.id===b.cue_id),draft=f.changes?.find(v=>v.beat_id===b.id)||{};return `<div class="pf-beat"><button class="pf-secondary pf-time" data-pf-seek="${b.start}">▷ ${b.start.toFixed(2)}–${b.end.toFixed(2)}초</button>${b.needs_review||t.candidate_requests?.includes(b.id)?'<span class="pf-count">장면 확인 필요</span>':''}<details class="pf-advanced"><summary>장면 선택 이유</summary><p>${esc(b.reason)}</p></details><label>장면 <select data-field="shot:${b.id}">${b.options.map((o,i)=>`<option value="${o.shot_id}" ${(draft.shot_id||b.selected_shot_id)===o.shot_id?'selected':''}>${esc('장면 '+(i+1)+' · '+o.reason)}</option>`).join('')}</select></label><details><summary>장면 후보 영상 보기</summary><div class="pf-sources">${b.options.map(o=>{const shot=e.plan.shots.find(s=>s.id===o.shot_id);return `<div><video controls preload="none" src="${esc(shot.video_url)}#t=${shot.start},${shot.end}"></video><small>${esc(shot.observation)}</small></div>`;}).join('')}</div></details>
      <label>자막 <input data-field="caption:${b.id}" value="${esc(draft.text??c.text)}"></label><details class="pf-advanced"><summary>자막 타이밍 · 강조 설정</summary><label>시작 <input type="number" step="0.01" data-field="start:${b.id}" value="${draft.start??c.start}"></label><label>끝 <input type="number" step="0.01" data-field="end:${b.id}" value="${draft.end??c.end}"></label><label>강조 <select data-field="emphasis:${b.id}">${[0,1,2].map(n=>`<option value="${n}" ${(draft.emphasis??b.emphasis)===n?'selected':''}>${['없음','분명하게','강하게'][n]}</option>`).join('')}</select></label></details><button data-pf="save-beat" data-beat="${b.id}">이 구간 피드백 저장</button></div>`;}).join('')}</div></div>`:'<div class="pf-empty"><b>편집할 영상이 아직 없어요</b><p>음성 제작이 끝나면 장면과 자막을 준비합니다.</p><button data-pf-tab="voice">음성 준비 상태 보기 →</button></div>'}</details><div class="pf-actionbar"><p class="pf-impact">${impact(f)}</p><button data-pf="discard-feedback">변경사항 초기화</button><button data-pf="reproduce" ${t.pending_reproduction||!Object.keys(f).length?'disabled':''}>${t.pending_reproduction?'현재 단계 종료 후 재제작 대기':'변경사항 반영해 재제작 →'}</button></div></div>`;
  }
  function impact(f){if(!Object.keys(f).length)return '수정한 항목을 저장하면 새 버전을 만들 수 있어요';if(['script_text','speed','pronunciations','regenerate_voice'].some(k=>k in f))return '재생성 범위: TTS → 편집·프로젝트 → 최종 MP4';if('source_ids' in f||f.changes)return '재생성 범위: 편집·프로젝트 → 최종 MP4';return '피드백 저장됨';}
  function runtime(t){
    const action=t.error?'<button data-pf="retry">중단 단계 재시도</button>':t.automation?.active&&t.status!=='completed'?'<button data-pf="pause-auto">자동 진행 중지</button>':!t.automation?.active&&t.status!=='completed'?'<button data-pf="resume-auto">자동 진행 재개</button>':'';
    return `<div class="pf-runtime">${action}<p>${esc(window.StudioBoard.message(t.error||t.message))}</p></div>`;
  }
  function mount(root,t,options={}){
    root._task=t;root._options=options;
    const bindUploads=()=>window.SourceUpload?.bind(root,t,result=>{options.onUpdate?.(result);mount(root,result,options);},()=>{root._renderedRevision=null;mount(root,root._task,options);});
    if(root._taskId!==t.id){root._taskId=t.id;root._selected=null;root._dirty=false;root._feedbackBaseRevision=null;root._renderedRevision=null;root.innerHTML='';}
    const runningNote=root.querySelector('.pf-runtime');
    if(runningNote){const temp=document.createElement('div');temp.innerHTML=runtime(t);const content=temp.firstElementChild.innerHTML;if(runningNote.innerHTML!==content)runningNote.innerHTML=content;}
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
      const library=root.querySelector('.pf-source-library');
      if(library&&![...library.querySelectorAll('video')].some(v=>!v.paused)){
        const tmp=document.createElement('div');tmp.innerHTML=sourceLibrary(t);
        if(library.innerHTML!==tmp.firstElementChild.innerHTML)library.innerHTML=tmp.firstElementChild.innerHTML;
      }
      bindUploads();
      options.onRender?.();return;
    }
    if(root._renderedRevision===t.revision && root._renderedSelected===root._selected && root.querySelector('.production-flow')){options.onRender?.();return;}
    root._renderedRevision=t.revision;root._renderedSelected=root._selected;
    const mediaPositions=new Map([...root.querySelectorAll('video,audio')].map(m=>[m.getAttribute('src'),m.currentTime]));
    const opens=[...root.querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent);
    root.innerHTML=`<section class="production-flow">${options.editor&&t.automation?.protocol===2?runtime(t):''}${summary(t,root._selected)}${options.editor&&t.automation?.protocol===2?editor(t):''}<p class="pf-message" role="status"></p></section>`;
    root.querySelectorAll('video,audio').forEach(m=>{const position=mediaPositions.get(m.getAttribute('src'));if(position>0){const restore=()=>{m.currentTime=position;};if(m.readyState>=2)restore();else m.addEventListener('loadeddata',restore,{once:true});}});
    if(opens.length)root.querySelectorAll('details').forEach(d=>d.open=opens.includes(d.querySelector('summary')?.textContent));
    const local=JSON.parse(localStorage.getItem(storageKey(t))||'null');
    if(options.editor&&local){for(const field of root.querySelectorAll('[data-field]'))if(field.dataset.field in local){if(field.type==='checkbox')field.checked=local[field.dataset.field];else field.value=local[field.dataset.field];}root._dirty=true;root._feedbackBaseRevision=Number(localStorage.getItem(storageKey(t)+'-revision')??t.feedback_revision??0);}
    if(local&&'script' in local){const review=root.querySelector('[data-script-review]');if(review)review.textContent='불러온 편집 내용을 다시 검사해 주세요.';}
    root.oninput=event=>{const e=event.target;if(!e.dataset.field)return;if(e.dataset.field==='script'){const review=root.querySelector('[data-script-review]');if(review)review.textContent='대본이 바뀌었어요. 다시 검사해 주세요.';}if(!root._dirty){root._feedbackBaseRevision=root._task.feedback_revision||0;localStorage.setItem(storageKey(root._task)+'-revision',String(root._feedbackBaseRevision));}root._dirty=true;const draft=JSON.parse(localStorage.getItem(storageKey(root._task))||'{}');draft[e.dataset.field]=e.type==='checkbox'?e.checked:e.value;localStorage.setItem(storageKey(root._task),JSON.stringify(draft));if(e.dataset.field.startsWith('source:')){const n=root.querySelectorAll('[data-field^="source:"]:checked').length;root.querySelector('[data-selected-count]').textContent=n;for(const button of root.querySelectorAll('[data-pf="use-sources"],[data-pf="save-sources"]'))button.disabled=!n||button.dataset.pf==='use-sources'&&(root._uploading||(root._task.jobs||[]).some(j=>j.status==='running'&&!['proposal','suggest_edit'].includes(j.kind)));}};
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
      const seek=event.target.closest('[data-pf-seek]');if(seek){const video=root.querySelector('[data-edit-preview]');if(video)video.currentTime=Number(seek.dataset.pfSeek);return;}
      const tab=event.target.closest('[data-pf-tab]');if(tab){options.onTab?.(tab.dataset.pfTab);return;}
      const button=event.target.closest('[data-pf]');if(!button)return;
      const action=button.dataset.pf, task=root._task;let kind=action,body={};
      if(action==='select-all-sources'||action==='clear-sources'){for(const field of root.querySelectorAll('[data-field^="source:"]')){field.checked=action==='select-all-sources';field.dispatchEvent(new Event('input',{bubbles:true}));}return;}
      if(action==='use-sources')body={source_ids:[...root.querySelectorAll('[data-field^="source:"]:checked')].map(e=>e.dataset.field.slice(7))};
      if(action==='save-script')body={text:value('script')};
      if(action==='candidate'){kind='select-candidate';body={index:Number(button.dataset.index)};}
      if(action==='proposal'){kind='apply-proposal';body={proposal_id:button.dataset.id};}
      if(action==='save-sources'){kind='save-feedback';body={source_ids:[...root.querySelectorAll('[data-field^="source:"]:checked')].map(e=>e.dataset.field.slice(7))};}
      if(action==='search'){kind='refresh-sources';body={request:value('search')};}
      if(action==='save-voice'||action==='regenerate-voice'){
        kind=action==='save-voice'?'save-feedback':action;
        body={speed:Number(value('speed')),pronunciations:value('pronunciation').split('\n').filter(v=>v.trim()).map(v=>{const pos=v.indexOf('=');return {from:pos<0?'':v.slice(0,pos).trim(),to:pos<0?'':v.slice(pos+1).trim()};})};
      }
      if(action==='propose-script')body={request:value('script-request')};
      if(action==='request-edit')body={edit_id:task.edit_id,request:value('edit-request'),start:Number(value('edit-start')),end:Number(value('edit-end'))};
      if(action==='open-capcut')body={edit_id:button.dataset.editId};
      if(action==='save-beat'){kind='revise-edit';const id=button.dataset.beat;body={edit_id:task.edit_id,changes:[{beat_id:id,shot_id:value('shot:'+id),text:value('caption:'+id),start:Number(value('start:'+id)),end:Number(value('end:'+id)),emphasis:Number(value('emphasis:'+id))}]};}
      if(action==='reproduce'&&root._dirty){message('입력한 항목의 피드백 저장 버튼을 먼저 눌러주세요.');return;}
      button.disabled=true;message('저장·요청 중…');
      try{
        if(action==='check-script'){
          const text=value('script'),result=await api('/'+task.id+'/check-script',{text});
          if(root._task.id===task.id&&value('script')===text){root.querySelector('[data-script-review]').innerHTML=scriptReview(result);message('현재 입력한 대본 검사 완료');}
          else message('검사 중 대본이 바뀌었어요. 다시 검사해 주세요.');
          return;
        }
        const fresh=await api('/'+task.id);
        const feedbackActions=['save-feedback','save-script','restore-script','apply-proposal','regenerate-voice','revise-edit','request-edit','reproduce','discard-feedback','select-candidate'];
        const result=await api('/'+task.id+'/'+kind,{revision:fresh.revision,...(feedbackActions.includes(kind)?{feedback_revision:root._feedbackBaseRevision??task.feedback_revision??0}:{}),...body});
        // Preserve unsaved fields in other sections; clear only fields saved here.
        const local=JSON.parse(localStorage.getItem(storageKey(task))||'{}');
        const prefixes=action==='save-script'?['script']:action==='save-voice'||action==='regenerate-voice'?['speed','pronunciation']:['save-sources','use-sources'].includes(action)?['source:']:action==='save-beat'?['shot:'+button.dataset.beat,'caption:'+button.dataset.beat,'start:'+button.dataset.beat,'end:'+button.dataset.beat,'emphasis:'+button.dataset.beat]:action==='search'?['search']:action==='propose-script'?['script-request']:action==='request-edit'?['edit-request','edit-start','edit-end']:[];
        for(const k of Object.keys(local))if(prefixes.some(p=>k===p||p.endsWith(':')&&k.startsWith(p)))delete local[k];
        if(action==='candidate'||action==='proposal')delete local.script;
        if(action==='discard-feedback')for(const k of Object.keys(local))delete local[k];
        if(Object.keys(local).length){localStorage.setItem(storageKey(task),JSON.stringify(local));localStorage.setItem(storageKey(task)+'-revision',String(result.feedback_revision||0));}else{localStorage.removeItem(storageKey(task));localStorage.removeItem(storageKey(task)+'-revision');}root._feedbackBaseRevision=null;
        root._dirty=false;document.activeElement.blur();options.onUpdate?.(result);mount(root,result,options);
        message(({'use-sources':'선택한 영상으로 제작을 이어갑니다. 현재 단계에서 진행 상황을 확인하세요.',retry:'재시도 요청을 접수했습니다. 위 현재 단계에서 실행 상태를 확인하세요.','start-auto':'자동 제작 요청을 접수했습니다.','resume-auto':'자동 진행 재개를 요청했습니다.','pause-auto':'자동 진행 중지를 요청했습니다. 현재 실행 중인 작업은 마무리될 수 있습니다.',reproduce:'재제작 요청 완료'})[action]||'저장했습니다. 변경사항 반영은 재제작 버튼으로 실행합니다.');
      }catch(e){message(window.StudioBoard.message(e.message));}finally{button.disabled=false;}
    };
    bindUploads();options.onRender?.();
  }
  window.ProductionFlow={mount,api,scriptReview};
})();
