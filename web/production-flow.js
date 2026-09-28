/* Both surfaces consume the same task and immutable run artifacts. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={pending:'대기',running:'진행 중',completed:'완료',failed:'확인 필요',waiting:'대기 중',superseded:'수정본으로 전환',legacy:'기존 작업'};
  const link=(url,label)=>url?`<a href="${esc(url)}" download>${esc(label)} ↓</a>`:'';
  const item=(t,c,id)=>t[c].find(v=>v.id===id);
  const storageKey=t=>'production-feedback-'+t.id;
  async function api(path,body){const r=await fetch('/api/studio'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'요청 실패');return d;}
  function summary(t,selected){
    const runs=t.pipeline||[], active=runs.find(r=>r.id===t.run_id)||runs.at(-1);
    const display=runs.find(r=>r.id===selected)||runs.find(r=>r.id===t.latest_completed_run_id)||active;
    if(!display)return '';
    return `<div class="pf-summary"><div class="pf-heading"><h3>자동 제작 진행</h3><span>${esc(t.message)}</span></div>
      ${t.error?`<p class="pf-error">${esc(t.error)} <button data-pf="retry">중단 단계 재시도</button></p>`:''}
      <ol class="pf-steps">${(active?.steps||[]).map(s=>`<li class="${s.status}"><b>${esc(s.label)}</b><span>${names[s.status]}</span>${link(s.download_url,'다운로드')}</li>`).join('')}</ol>
      <div class="pf-heading"><h4>결과물 · 최신 완료본 우선</h4><select data-pf-version aria-label="제작 결과 버전">${runs.slice().reverse().map(r=>`<option value="${r.id}" ${r.id===display.id?'selected':''}>V${r.number} · ${names[r.status]||r.status}${r.id===t.latest_completed_run_id?' · 최신 완료':''}</option>`).join('')}</select></div>
      ${display.video_url?`<video controls playsinline preload="metadata" src="${esc(display.video_url)}"></video>`:display.preview_url?`<p>리뷰 미리보기 · CapCut 최종 내보내기 전</p><video controls playsinline preload="metadata" src="${esc(display.preview_url)}"></video>`:'<p>완료되는 단계부터 결과물을 다운로드할 수 있습니다.</p>'}
      <div class="pf-links">${display.steps.map(s=>link(s.download_url,s.label)).join('')}${display.steps.some(s=>s.key==='project'&&s.download_url)?`<button data-pf="open-capcut" data-edit-id="${display.artifacts.edit_id}">CapCut에서 직접 열기</button>`:''}</div>
      <div class="pf-heading"><a href="studio.html?work=${encodeURIComponent(t.id)}">제작실에서 피드백·재제작 →</a>${t.automation?.protocol!==2?'<button data-pf="start-auto">자동 제작 이어서 시작</button>':t.automation?.active&&t.status!=='completed'?'<button data-pf="pause-auto">자동 진행 중지</button>':t.automation?.active?'':'<button data-pf="resume-auto">자동 진행 재개</button>'}</div></div>`;
  }
  function audit(a){if(!a)return '';return `<details><summary>소스 검색 언어·플랫폼·선택 내역</summary><p>채택 ${a.selected||0}개 · 제작 가능 ${a.usable??'확인 중'}개</p>${Object.entries(a.platforms||{}).map(([p,n])=>`<p>${esc(p)}: 후보 ${n.candidates} → 다운로드 ${n.received} → 채택 ${n.selected}</p>`).join('')}<p>${Object.entries(a.rejections||{}).map(([r,n])=>esc(r)+': '+n).join(' · ')}</p><details><summary>검색어와 실행 기록</summary>${(a.searches||a.planned_queries||[]).map(q=>`<p>${esc(q.provider||'')} · ${esc(q.language||'')} · ${esc(q.query)} · ${esc(q.status||'계획')}</p>`).join('')}</details></details>`;}
  function editor(t){
    const f=t.feedback||{},run=t.pipeline.find(r=>r.id===t.run_id),inputs=run?.inputs||{};
    const s=item(t,'scripts',t.script_id),e=item(t,'edits',t.edit_id),voice=item(t,'voices',t.voice_id);
    const selected=f.source_ids||inputs.source_ids||t.sources.map(v=>v.id);
    const currentText=f.script_text??s?.text??'';
    return `<div class="pf-editor"><div class="pf-heading"><h3>피드백 초안</h3><button data-pf="reproduce" ${t.pending_reproduction?'disabled':''}>${t.pending_reproduction?'현재 단계 종료 후 재제작 대기':'변경사항 반영해 재제작'}</button></div>
      <p>각 항목의 ‘피드백 저장’ 후 재제작을 누르세요. 기존 제작은 계속 진행되며 이전 결과는 보존됩니다.</p>
      <p class="pf-impact">${impact(f)} ${t.feedback_message?esc(t.feedback_message):''}</p><button data-pf="discard-feedback">저장한 피드백 초기화</button>
      <details open><summary>1. 소스 선택·추가 확보 (${t.sources.length}개)</summary><div class="pf-sources">${t.sources.map((v,i)=>`<div><video controls preload="none" src="${esc(v.url)}"></video><label><input type="checkbox" data-field="source:${v.id}" ${selected.includes(v.id)?'checked':''}> 소스 ${i+1} 사용</label>${link(v.url,'개별 영상')}<small>${esc(v.original_name||v.origin_url||'출처 기록 확인')}</small></div>`).join('')}</div><button data-pf="save-sources">소스 선택 피드백 저장</button>
      <label>추가 검색어 (한 줄에 하나 · 한국어/영어/중국어)<textarea data-field="search" placeholder="제품명 + 사용 장면"></textarea></label><button data-pf="search">다국어 추가 수집</button><p>${esc(t.source_search?.message||'')}</p><label>직접 영상 업로드 <input type="file" data-upload accept="video/mp4,video/quicktime,video/webm"></label>${audit(t.source_audit)}</details>
      <details open><summary>2. 원본 대본과 Top Pick</summary><details><summary>원본 발화</summary><p class="pf-text">${esc(t.original_text||'추출 대기')}</p></details>
      <p>${esc(t.selection_reason||'후보 평가 대기')}</p>${t.top_pick?`<small>${esc(t.top_pick.rubric)} · 흥행 예측 점수가 아닌 제작 적합성 평가</small>`:''}
      ${(t.script_candidates||[]).map((c,i)=>{const score=t.top_pick?.evaluations?.find(v=>v.index===i);return `<details><summary>후보 ${i+1}${i===t.selected_candidate?' · Top Pick':''}${score?' · '+score.total.toFixed(2)+'/5':''}</summary><p>${esc(c.text)}</p><p>${esc(score?.reason||'')}</p><button data-pf="candidate" data-index="${i}">이 대본을 피드백으로 선택</button></details>`;}).join('')}
      <label>제작 대본<textarea data-field="script">${esc(currentText)}</textarea></label><button data-pf="save-script">대본 피드백 저장</button>
      <label>AI 수정 요청<textarea data-field="script-request" placeholder="예: 첫 문장을 질문으로 바꾸고 설명을 짧게 해줘"></textarea></label><button data-pf="propose-script" ${s?'':'disabled'}>수정안 만들기</button>
      ${t.proposals.slice().reverse().map(p=>`<details><summary>AI 수정안 · ${esc(p.summary)}</summary><p>${esc(p.text)}</p><button data-pf="proposal" data-id="${p.id}">피드백으로 적용</button></details>`).join('')}</details>
      <details open><summary>3. TTS 발음·속도</summary>${voice?`<audio controls src="${esc(voice.path_url)}"></audio>`:''}<label>속도 <input data-field="speed" type="number" min="0.8" max="1.25" step="0.05" value="${f.speed??inputs.speed??1}"></label><label>발음 교정 (한 줄에 원문=읽을 발음)<textarea data-field="pronunciation" placeholder="USB=유에스비">${esc((f.pronunciations??inputs.pronunciations??[]).map(p=>p.from+'='+p.to).join('\n'))}</textarea></label><p>자막 원문은 유지하고 TTS에 적용합니다. 기존 VoiceBench 목소리·엔진 설정을 사용합니다.</p><button data-pf="save-voice">음성 피드백 저장</button><button data-pf="regenerate-voice">같은 설정으로 음성 재생성 예약</button></details>
      <details open><summary>4. 장면·자막·강조</summary>${e?.plan?`<p>대본·음성·소스 변경은 먼저 재제작하고, 새 타임라인에서 구간을 수정하세요.</p><label>구간 수정 요청<textarea data-field="edit-request" placeholder="예: 첫 장면을 교체하고 마지막 자막을 강조해줘"></textarea></label><label>시작 초 <input data-field="edit-start" type="number" value="0" min="0" step="0.01"></label><label>끝 초 <input data-field="edit-end" type="number" value="${e.duration}" min="0" step="0.01"></label><button data-pf="request-edit">수정안 준비</button>
      ${e.plan.beats.map(b=>{const c=e.plan.cues.find(v=>v.id===b.cue_id),draft=f.changes?.find(v=>v.beat_id===b.id)||{};return `<div class="pf-beat"><b>${b.start.toFixed(2)}–${b.end.toFixed(2)}초 ${b.needs_review||t.candidate_requests?.includes(b.id)?'· 장면 확인 필요':''}</b><p>${esc(b.reason)}</p><label>장면 <select data-field="shot:${b.id}">${b.options.map(o=>`<option value="${o.shot_id}" ${(draft.shot_id||b.selected_shot_id)===o.shot_id?'selected':''}>${esc(o.shot_id+' · '+o.reason)}</option>`).join('')}</select></label><details><summary>장면 후보 영상 보기</summary><div class="pf-sources">${b.options.map(o=>{const shot=e.plan.shots.find(s=>s.id===o.shot_id);return `<div><video controls preload="none" src="${esc(shot.video_url)}#t=${shot.start},${shot.end}"></video><small>${esc(shot.id+' · '+shot.observation)}</small></div>`;}).join('')}</div></details>
      <label>자막 <input data-field="caption:${b.id}" value="${esc(draft.text??c.text)}"></label><label>시작 <input type="number" step="0.01" data-field="start:${b.id}" value="${draft.start??c.start}"></label><label>끝 <input type="number" step="0.01" data-field="end:${b.id}" value="${draft.end??c.end}"></label><label>강조 <select data-field="emphasis:${b.id}">${[0,1,2].map(n=>`<option value="${n}" ${(draft.emphasis??b.emphasis)===n?'selected':''}>${['없음','분명하게','강하게'][n]}</option>`).join('')}</select></label><button data-pf="save-beat" data-beat="${b.id}">이 구간 피드백 저장</button></div>`;}).join('')}`:'<p>프로젝트가 생성되면 장면별 수정 항목이 표시됩니다.</p>'}</details></div>`;
  }
  function impact(f){if(!Object.keys(f).length)return '저장한 변경사항 없음';if(['script_text','speed','pronunciations','regenerate_voice'].some(k=>k in f))return '재생성 범위: TTS → 편집·프로젝트 → 최종 MP4';if('source_ids' in f||f.changes)return '재생성 범위: 편집·프로젝트 → 최종 MP4';return '피드백 저장됨';}
  function mount(root,t,options={}){
    root._task=t;root._options=options;
    if(root._taskId!==t.id){root._taskId=t.id;root._selected=null;root._dirty=false;root._feedbackBaseRevision=null;root.innerHTML='';}
    const playing=[...root.querySelectorAll('video,audio')].some(v=>!v.paused);
    if(playing||root._dirty||root.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select')){
      const temp=document.createElement('div');temp.innerHTML=summary(t,root._selected);
      const steps=root.querySelector('.pf-steps'),fresh=temp.querySelector('.pf-steps');if(steps&&fresh)steps.innerHTML=fresh.innerHTML;
      const note=root.querySelector('.pf-heading span');if(note)note.textContent=t.message;
      return;
    }
    const opens=[...root.querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent);
    root.innerHTML=`<section class="production-flow">${summary(t,root._selected)}${options.editor&&t.automation?.protocol===2?editor(t):''}<p class="pf-message" role="status"></p></section>`;
    if(opens.length)root.querySelectorAll('details').forEach(d=>d.open=opens.includes(d.querySelector('summary')?.textContent));
    const local=JSON.parse(localStorage.getItem(storageKey(t))||'null');
    if(options.editor&&local){for(const field of root.querySelectorAll('[data-field]'))if(field.dataset.field in local){if(field.type==='checkbox')field.checked=local[field.dataset.field];else field.value=local[field.dataset.field];}root._dirty=true;root._feedbackBaseRevision=Number(localStorage.getItem(storageKey(t)+'-revision')??t.feedback_revision??0);}
    root.oninput=event=>{const e=event.target;if(!e.dataset.field)return;if(!root._dirty){root._feedbackBaseRevision=root._task.feedback_revision||0;localStorage.setItem(storageKey(root._task)+'-revision',String(root._feedbackBaseRevision));}root._dirty=true;const draft=JSON.parse(localStorage.getItem(storageKey(root._task))||'{}');draft[e.dataset.field]=e.type==='checkbox'?e.checked:e.value;localStorage.setItem(storageKey(root._task),JSON.stringify(draft));};
    root.onchange=async event=>{
      if(event.target.matches('[data-pf-version]')){
        root._selected=event.target.value;root._dirty=false;
        // An explicit version switch must bypass the focus/playback refresh guard.
        event.target.blur();root.querySelectorAll('video,audio').forEach(v=>v.pause());
        mount(root,root._task,options);
      }
      if(event.target.matches('[data-upload]')&&event.target.files[0]){
        const file=event.target.files[0];message('영상 업로드·검증 중…');
        try{const r=await fetch(`/api/studio/${t.id}/upload-source?name=${encodeURIComponent(file.name)}`,{method:'POST',body:file});const result=await r.json();if(!r.ok)throw Error(result.error);options.onUpdate?.(result);root._dirty=false;mount(root,result,options);message('영상 업로드 완료 · 사용할 소스 선택 후 재제작하세요.');}catch(e){message(e.message);}
      }
    };
    const message=text=>{const m=root.querySelector('.pf-message');if(m)m.textContent=text;};
    const field=name=>[...root.querySelectorAll('[data-field]')].find(e=>e.dataset.field===name);
    const value=name=>field(name)?.value||'';
    root.onclick=async event=>{
      const button=event.target.closest('[data-pf]');if(!button)return;
      const action=button.dataset.pf, task=root._task;let kind=action,body={};
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
        const fresh=await api('/'+task.id);
        const feedbackActions=['save-feedback','save-script','restore-script','apply-proposal','regenerate-voice','revise-edit','request-edit','reproduce','discard-feedback','select-candidate'];
        const result=await api('/'+task.id+'/'+kind,{revision:fresh.revision,...(feedbackActions.includes(kind)?{feedback_revision:root._feedbackBaseRevision??task.feedback_revision??0}:{}),...body});
        // Preserve unsaved fields in other sections; clear only fields saved here.
        const local=JSON.parse(localStorage.getItem(storageKey(task))||'{}');
        const prefixes=action==='save-script'?['script']:action==='save-voice'||action==='regenerate-voice'?['speed','pronunciation']:action==='save-sources'?['source:']:action==='save-beat'?['shot:'+button.dataset.beat,'caption:'+button.dataset.beat,'start:'+button.dataset.beat,'end:'+button.dataset.beat,'emphasis:'+button.dataset.beat]:action==='search'?['search']:action==='propose-script'?['script-request']:action==='request-edit'?['edit-request','edit-start','edit-end']:[];
        for(const k of Object.keys(local))if(prefixes.some(p=>k===p||p.endsWith(':')&&k.startsWith(p)))delete local[k];
        if(action==='candidate'||action==='proposal')delete local.script;
        if(action==='discard-feedback')for(const k of Object.keys(local))delete local[k];
        if(Object.keys(local).length){localStorage.setItem(storageKey(task),JSON.stringify(local));localStorage.setItem(storageKey(task)+'-revision',String(result.feedback_revision||0));}else{localStorage.removeItem(storageKey(task));localStorage.removeItem(storageKey(task)+'-revision');}root._feedbackBaseRevision=null;
        root._dirty=false;document.activeElement.blur();options.onUpdate?.(result);mount(root,result,options);message(action==='reproduce'?'재제작 요청 완료':'저장했습니다. 변경사항 반영은 재제작 버튼으로 실행합니다.');
      }catch(e){message(e.message);}finally{button.disabled=false;}
    };
  }
  window.ProductionFlow={mount,api};
})();
