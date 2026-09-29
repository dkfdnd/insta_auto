/* A read-only projection of durable studio jobs; moving a card never changes a job. */
(function (root) {
  'use strict';
  const columns = [
    ['sources', '자료 준비', '소스 영상 · 원본 발화'],
    ['script', '대본', '선정 · 수정 · 검토'],
    ['voice', '음성', 'TTS 생성 · 청취'],
    ['edit', '편집', '장면 · 자막 · 프로젝트'],
    ['export', '내보내기', 'CapCut · 최종 MP4'],
    ['completed', '제작 완료', '완료본 확인 · 다운로드'],
  ];
  const stageOfKind = {prepare:'sources', rewrite:'script', voice:'voice', edit:'edit', revision:'edit', revise:'edit', edit_request:'edit', register:'export', export:'export'};
  const stageOfStatus = {preparing:'sources', rewriting:'script', script_review:'script', voice_generating:'voice', voice_review:'voice', editing:'edit', draft_review:'edit', registering:'export', exporting:'export', completed:'completed'};
  const activityNames = {prepare:'자료 준비', rewrite:'대본 재가공', voice:'음성 생성', edit:'영상 편집', revision:'편집 수정', revise:'편집 수정', edit_request:'편집 수정', register:'프로젝트 등록', export:'MP4 내보내기', refresh_sources:'소스 추가 수집', proposal:'대본 수정안 생성', suggest_edit:'편집 수정안 생성'};
  const stateNames = {running:'처리 중', queued:'실행 대기', review:'검토 필요', waiting:'외부 작업 대기', retry:'재시도 대기', paused:'일시중지', error:'확인 필요', completed:'내보내기 완료', unknown:'상태 확인 필요'};
  function describe(task) {
    const jobs = [...(task.jobs || [])].sort((a,b)=>(b.updated||0)-(a.updated||0));
    const relevant = jobs.filter(j=>stageOfKind[j.kind]);
    const unfinished = relevant.find(j=>['running','queued','paused','failed'].includes(j.status));
    let stage = stageOfStatus[task.status] || stageOfKind[task.automation?.stage]
      || stageOfKind[unfinished?.kind] || (task.edit_id?'edit':task.voice_id?'voice':task.script_id?'script':'sources');
    const runningJobs = jobs.filter(j=>j.status==='running');
    const primaryRunning = runningJobs.some(j=>stageOfKind[j.kind]);
    const review = ['script_review','voice_review','draft_review'].includes(task.status);
    let state = task.error || task.status==='attention' ? 'error'
      : primaryRunning ? 'running'
      : task.status==='paused' ? 'paused'
      : task.status==='waiting_capcut' ? 'waiting'
      : task.status==='retry_wait' ? 'retry'
      : review ? 'review'
      : task.status==='completed' ? 'completed'
      : relevant.some(j=>j.status==='queued') ? 'queued' : 'unknown';
    const sourceError = task.source_search?.status==='failed';
    const run = (task.pipeline||[]).find(r=>r.id===task.run_id);
    const completed = (task.pipeline||[]).find(r=>r.id===task.latest_completed_run_id);
    const versions = run ? `V${run.number}${completed && completed.id!==run.id ? ` 제작 중 · V${completed.number} 완료본 보유` : ''}` : `${task.scripts?.length||0}개 대본 버전`;
    const activity = runningJobs.map(j=>activityNames[j.kind]||'추가 작업').join(' · ');
    return {stage, state, label:stateNames[state], running:runningJobs.length>0, review,
      attention:state==='error'||sourceError, versions, activity,
      message:task.error || (sourceError ? task.source_search.message : task.message) || stateNames[state],
      tab:stage==='completed'||stage==='export'?'results':stage};
  }
  function matches(task, filter, query) {
    const d=describe(task), q=(query||'').trim().toLowerCase();
    return (!q || `${task.title} ${task.shortcode}`.toLowerCase().includes(q)) &&
      (filter==='all'||filter==='running'&&d.running||filter==='review'&&d.review||filter==='attention'&&d.attention||filter==='completed'&&d.stage==='completed');
  }
  function mount(container, overview) {
    const nodes=new Map(), lanes=new Map();
    for (const [id,title,hint] of columns) {
      const lane=document.createElement('section'); lane.className='kanban-column'; lane.dataset.stage=id;
      lane.setAttribute('aria-labelledby','lane-'+id);
      lane.innerHTML=`<header class="column-head"><div><h2 id="lane-${id}">${title} <span class="column-count">0</span></h2><p>${hint}</p></div><span class="column-marker" aria-hidden="true"></span></header><div class="column-cards"></div><p class="column-empty">이 단계의 작업이 없습니다</p>`;
      container.append(lane); lanes.set(id,lane);
    }
    const metrics=[['review','검토할 작업','내 확인을 기다리는 영상'],['running','실제 처리 중','현재 실행 중인 작업'],['attention','확인 필요','오류 · 자료 확인'],['completed','제작 완료','최종 MP4 내보내기 완료']];
    overview.innerHTML=metrics.map(([id,title,hint])=>`<div class="metric" data-metric="${id}"><span>${title}</span><strong>0<small> 편</small></strong><small>${hint}</small></div>`).join('');
    function text(node,value) { if(node.textContent!==String(value))node.textContent=value; }
    function render(tasks, {selectedId,filter='all',query=''}={}) {
      const counts={review:0,running:0,attention:0,completed:0};
      for(const task of tasks){const d=describe(task);for(const k of ['review','running','attention'])if(d[k])counts[k]++;if(d.stage==='completed')counts.completed++;}
      for(const [id] of metrics){const strong=overview.querySelector(`[data-metric="${id}"] strong`);if(strong.firstChild.nodeValue!==String(counts[id]))strong.firstChild.nodeValue=String(counts[id]);}
      const visible=tasks.filter(t=>matches(t,filter,query)).sort((a,b)=>(a.created||0)-(b.created||0)||a.id.localeCompare(b.id));
      const visibleIds=new Set(visible.map(t=>t.id));
      for(const [id,node] of nodes)if(!visibleIds.has(id)){node.remove();nodes.delete(id);}
      const focus=document.activeElement;
      for(const task of visible){
        const d=describe(task); let card=nodes.get(task.id);
        if(!card){
          card=document.createElement('button');card.type='button';card.className='work-card';card.dataset.work=task.id;
          card.innerHTML='<div class="card-visual"><img hidden alt=""><span class="card-placeholder" aria-hidden="true">▶</span><span class="card-mode"></span></div><div class="card-body"><div class="card-top"><span class="board-status"></span><span class="activity-dot" hidden aria-hidden="true"></span></div><h3></h3><p class="card-code"></p><p class="card-message"></p><p class="card-activity" hidden></p><div class="card-bottom"><span class="card-version"></span><span class="card-open">작업 열기 ↗</span></div></div>';
          nodes.set(task.id,card);
        }
        card.classList.toggle('current',task.id===selectedId);card.classList.toggle('is-running',d.running);card.dataset.state=d.state;
        card.setAttribute('aria-expanded',String(task.id===selectedId));card.setAttribute('aria-controls','work-drawer');
        text(card.querySelector('h3'),task.title||task.shortcode);text(card.querySelector('.card-code'),task.shortcode);
        text(card.querySelector('.board-status'),d.label);text(card.querySelector('.card-message'),d.message);
        text(card.querySelector('.card-mode'),task.automation?'자동 제작':'직접 검토');
        text(card.querySelector('.card-version'),d.versions);text(card.querySelector('.card-activity'),d.activity);
        card.querySelector('.card-activity').hidden=!d.running;card.querySelector('.activity-dot').hidden=!d.running;
        const img=card.querySelector('img'),cover=task.thumbnail_url||(task.edits||[]).find(e=>e.id===task.edit_id)?.cover_url||`thumbs/${encodeURIComponent(task.shortcode)}.jpg`;
        if(cover && img.getAttribute('src')!==cover){img.src=cover;img.hidden=false;img.onerror=()=>{img.hidden=true;};}
        if(!cover){img.hidden=true;img.removeAttribute('src');}
        const lane=lanes.get(d.stage).querySelector('.column-cards');
        if(card.parentElement!==lane){const moved=!!card.parentElement;lane.append(card);if(moved){card.classList.remove('stage-arrived');void card.offsetWidth;card.classList.add('stage-arrived');}}
      }
      if(focus && document.contains(focus) && document.activeElement!==focus)focus.focus({preventScroll:true});
      for(const [id,lane] of lanes){const n=visible.filter(t=>describe(t).stage===id).length;text(lane.querySelector('.column-count'),n);lane.querySelector('.column-empty').hidden=n>0;}
      return visible.length;
    }
    return {render};
  }
  const api={columns,describe,matches,mount};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.StudioBoard=api;
})(typeof window==='undefined'?globalThis:window);
