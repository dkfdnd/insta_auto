/* Shared workspace view models. No production state is changed by navigation. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const route=value=>value==='original'?'script':value==='export'?'results':value;
  function tabState(steps,tab){
    const matching=steps.filter(s=>route(s.tab)===tab);
    return matching.some(s=>s.current)?'current':matching.length&&matching.every(s=>s.state==='done')?'done':'pending';
  }
  function range(start,end,duration){
    if(!Number.isFinite(duration)||duration<=0||!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return null;
    const left=Math.max(0,Math.min(duration,start)),right=Math.max(0,Math.min(duration,end));
    return right>left?{start:left,end:right,left:left/duration*100,width:(right-left)/duration*100}:null;
  }
  function track(items,duration,kind,selected){
    return items.map((item,i)=>{
      const span=range(item.start,item.end,duration);if(!span)return '';
      const label=`${i+1}. ${item.text||'장면'} · ${span.start.toFixed(2)}–${span.end.toFixed(2)}초`;
      return `<button type="button" class="ce-track-segment" data-timeline-${kind}="${i}" aria-label="${esc(label)}" title="${esc(label)}" aria-pressed="${i===selected}" style="left:${span.left}%;width:${span.width}%">${esc(item.text||'장면 '+(i+1))}</button>`;
    }).join('');
  }
  function seek(video,at,duration){
    if(video.readyState<1||!Number.isFinite(at)||!Number.isFinite(duration)||duration<=0)return false;
    video.pause();
    video.currentTime=Math.max(0,Math.min(duration,Number.isFinite(video.duration)?video.duration:duration,at));
    return true;
  }
  function guidance(t){
    if(t.source_acquisition?.hold||t.source_search?.hold)return {kind:'blocked',title:'소스 자동 수집을 중지했습니다',body:t.source_search?.message||t.message,items:[],resumeLabel:'문제 해결 후 자동 제작 재개',footer:'검색 내역을 확인하고 인증·로그인 문제를 해결하거나 새로운 검색 조건을 입력하세요. 기존 영상·대본·음성은 보존됩니다.'};
    const garlic=t.shortcode==='DeEau5JxJfy'||/마늘/.test(t.title||'');
    const blockers=(t.production_blockers||[]).map(key=>({
      personal_clone_unavailable:'본인 복제 목소리가 아직 준비되지 않았습니다. VoiceBench에서 본인 참조 음성·전사문과 복제 모델을 준비해야 합니다. 기본 여성 목소리로 자동 대체하지 않습니다.',
      core_footage_gap:garlic?'다진마늘을 준비·보관하고 한 스푼씩 사용하는 핵심 동작 영상이 부족합니다. 닭고기·샐러드 영상은 요리 맥락에 사용할 수 있지만 이 동작을 대신하지는 못합니다.':'대본이 강조하는 핵심 기능·동작 영상이 부족합니다. 소재 탭에서 해당 동작이 보이는 소스 영상을 추가하세요.'
    }[key]||'추가 제작 자료가 필요합니다. 현재 단계의 안내를 확인하세요.'));
    const automatic=t.automation?.protocol===2;
    if(blockers.length)return {kind:'blocked',title:t.script_id?'대본은 준비됐고, 제작 준비가 남았습니다':'필요한 제작 자료가 아직 부족합니다',body:'대본 승인 때문에 멈춘 것이 아닙니다. 아래 준비를 마친 뒤 자동 제작을 재개하세요.',items:blockers,resumeLabel:'준비 후 자동 제작 재개',footer:'재개하면 중단 단계부터 다시 확인합니다. 준비가 부족하면 같은 사유로 멈출 수 있습니다.'};
    if(automatic&&!t.automation.active&&t.status!=='completed'){
      const edited=['save-script','restore-script','apply-proposal'].includes(t.automation.pause_reason)||t.automation.stage==='manual_review'||(t.scripts||[]).some(s=>s.id===t.script_id&&s.origin==='agent_editorial_correction');
      return {kind:'paused',title:edited?'대본 수정 내용을 보관해 제작이 멈춰 있습니다':'자동 제작이 멈춰 있습니다',body:edited?'앞선 수정 내용을 보관하는 과정에서 자동 진행이 멈췄습니다. 선택된 대본으로 이어가려면 ‘자동 제작 재개’를 누르세요.':'계속 만들려면 ‘자동 제작 재개’를 누르세요. 대본을 다운로드하거나 승인할 필요는 없습니다.',items:[],resumeLabel:'자동 제작 재개',footer:'Top Pick은 자동 선정 후 본인 복제 음성 → 편집 → 최종 영상까지 이어집니다. 대본 검토는 선택 사항입니다.'};
    }
    if(automatic)return {kind:'automatic',title:'Top Pick으로 자동 제작합니다',body:'대본 승인 없이 본인 복제 음성 → 편집 → 최종 영상까지 이어집니다. 대본은 아래에서 확인할 수 있고, 다운로드는 선택 사항입니다.',items:[],footer:''};
    return {kind:'manual',title:'직접 제작하는 작업입니다',body:'제작실에서 대본과 목소리를 선택해 진행하세요.',items:[],footer:''};
  }
  function versionPicker(t,display){
    const runs=t.pipeline||[],names={running:'실제 제작 중',queued:'실행 대기',completed:'제작 완료',failed:'문제 확인 필요',error:'문제 확인 필요',review:'직접 검토 대기',blocked:'제작 준비 필요',paused:'일시중지',waiting:'제작 대기',superseded:'수정본으로 전환',legacy:'기존 제작'};
    const label=r=>{
      // Also works against older servers whose run checkpoint says 'running'
      // even though the actual queue is idle. Preserve terminal older versions.
      const live=r.id===t.run_id&&!['completed','superseded','legacy'].includes(r.status)&&window.StudioBoard;
      const status=live?window.StudioBoard.describe(t).state:r.status;
      const parent=runs.find(p=>p.id===r.parent_id)||runs.find(p=>p.number===r.number-1);
      const inputs=r.inputs||{},previous=parent?.inputs||{},changes=[];
      if(parent){
        if(r.artifacts?.script_id&&parent.artifacts?.script_id&&r.artifacts.script_id!==parent.artifacts.script_id)changes.push('대본 변경');
        if(['voice_profile_id','speed','pronunciations'].some(key=>JSON.stringify(inputs[key]??null)!==JSON.stringify(previous[key]??null)))changes.push('목소리 설정 변경');
        if(JSON.stringify(inputs.source_ids??[])!==JSON.stringify(previous.source_ids??[]))changes.push('사용 영상 변경');
        if(inputs.changes?.length)changes.push('장면·자막 변경');
      }
      const date=Number(r.created)>0?new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(Number(r.created)*1000)):'';
      return `제작 버전 v${r.number} · ${names[status]||'상태 확인 필요'}${r.id===t.latest_completed_run_id?' · 최신 완료':''}${parent?' · '+(changes.join(', ')||'다시 제작'):''}${date?' · '+date:''}`;
    };
    const picker=runs.length>1?`<select data-pf-version aria-label="같은 소재의 제작 버전 선택">${runs.slice().reverse().map(r=>`<option value="${esc(r.id)}" ${r.id===display.id?'selected':''}>${esc(label(r))}</option>`).join('')}</select>`:`<strong class="pf-version-label">${esc(label(display))}</strong>`;
    return `<div class="pf-heading"><h4>지금 보고 있는 버전</h4>${picker}</div><details class="pf-version-help"><summary>제작 버전이란?</summary><p>${runs.length===1?'아직 버전이 한 개뿐입니다. ':''}같은 소재로 다시 만든 영상의 이력입니다. 다시 만들면 새 버전이 추가되며, 완성된 버전만 재생할 수 있습니다.</p></details>`;
  }
  function comparison(t,run){
    const result=run.video_url||run.preview_url;
    const player=(url,marker,empty)=>url?`<video ${marker} controls playsinline preload="metadata" tabindex="0" src="${esc(url)}"></video>`:`<div class="pf-comparison-empty"><strong>${empty}</strong><p>파일이 준비되면 여기에서 재생할 수 있어요.</p></div>`;
    if(t.creation_mode==='self_shot')return `<section class="pf-comparison" data-owned-output aria-label="내 촬영 영상 제작본"><header><div><h4>내 촬영 영상으로 만든 쇼츠</h4><p>재생 버튼을 눌러 확인하세요.</p></div></header><div class="pf-comparison-grid"><article><h5>우리 영상 · v${esc(run.number)}${!run.video_url&&run.preview_url?' · 편집 미리보기':''}</h5>${player(result,'data-result-preview','이 버전의 영상은 아직 없습니다')}</article></div></section>`;
    return `<section class="pf-comparison" aria-label="원본과 제작본 비교"><header><div><h4>원본과 우리 영상 비교</h4><p>재생 버튼을 눌러 각각 확인하세요.</p></div></header><div class="pf-comparison-grid"><article><h5>참고한 원본 영상</h5>${player(t.reference_url,'data-comparison-reference','원본 영상이 없습니다')}</article><article><h5>우리 영상 · v${esc(run.number)}${!run.video_url&&run.preview_url?' · 편집 미리보기':''}</h5>${player(result,'data-result-preview','이 버전의 영상은 아직 없습니다')}</article></div></section>`;
  }
  window.StudioWorkspace={route,tabState,range,track,seek,comparison,guidance,versionPicker};
})();
