/* Display the six real production milestones, independently from execution state. */
(function (root) {
  'use strict';
  const columns = [
    ['sources', '소스 확보', '제작에 사용할 영상 모으기'],
    ['transcript', '원본 발화', '원본 영상의 말과 내용 확인'],
    ['script', '제작 대본', '새 대본 작성 · 검토'],
    ['voice', '음성 제작', '음성 생성 · 청취'],
    ['edit', '영상 편집', '장면 · 자막 · 프로젝트'],
    ['export', '내보내기', '최종 영상 출력 · 완료'],
  ];
  const shortNames = ['소스','원문','대본','음성','편집','출력'];
  const assetKeys = ['sources','transcript','script','voice','project','export'];
  const tabs = ['sources','original','script','voice','edit','results'];
  const stageOfKind = {prepare:'sources', rewrite:'script', voice:'voice', edit:'edit', revision:'edit', revise:'edit', edit_request:'edit', register:'edit', export:'export'};
  const stageOfStatus = {preparing:'sources', rewriting:'script', script_review:'script', voice_generating:'voice', voice_review:'voice', editing:'edit', draft_review:'edit', registering:'edit', exporting:'export', completed:'export'};
  const activityNames = {prepare:'자료 준비', rewrite:'대본 재가공', voice:'음성 생성', edit:'영상 편집', revision:'편집 수정', revise:'편집 수정', edit_request:'편집 수정', register:'프로젝트 등록', export:'MP4 내보내기', refresh_sources:'소스 추가 수집', proposal:'대본 수정안 생성', suggest_edit:'편집 수정안 생성'};
  const stateNames = {running:'진행 중', queued:'실행 대기', review:'검토 필요', waiting:'외부 작업 대기', retry:'재시도 대기', paused:'일시중지', error:'확인 필요', completed:'제작 완료', unknown:'상태 확인 필요'};
  function message(value, fallback='작업 상태를 확인하고 다시 시도해 주세요.') {
    const s=String(value||'');
    if(/Source manifest contains no selected local videos|제작에 사용할 소스 영상이 없습니다/.test(s))return '아직 사용할 영상이 없어요. 직접 영상을 넣거나 소스 검색을 다시 시도하세요.';
    if(/captcha|CAPTCHA|사람 확인/.test(s))return '검색 서비스에서 사람 확인이 필요해요. 인증을 마친 뒤 다시 시도하거나 직접 영상을 넣어주세요.';
    if(/Failed to fetch|NetworkError|ECONNREFUSED|Connection refused|fetch failed/i.test(s))return '제작 서비스에 연결되지 않았어요. 서비스 실행 상태를 확인하고 다시 시도하세요.';
    if(/timeout|timed out/i.test(s))return '작업 응답이 늦어지고 있어요. 잠시 후 상태를 확인하고 다시 시도하세요.';
    if(/no space|disk full/i.test(s))return '저장 공간이 부족해요. 디스크 공간을 확보한 뒤 다시 시도하세요.';
    if(!s)return fallback;
    if(!/[가-힣]/.test(s)||/Traceback|[A-Z]:\\|\/Users\/|\/home\//.test(s))return fallback;
    return s;
  }
  function title(task){
    let text=String(task.title||'').replaceAll(task.shortcode||'\u0000','').replace(/https?:\/\/\S+|#\S+/g,'').trim();
    return text&&text!==task.id?text.slice(0,110):'새 쇼츠 제작';
  }
  function describe(task) {
    const jobs=[...(task.jobs||[])].sort((a,b)=>(b.updated||0)-(a.updated||0));
    const relevant=jobs.filter(j=>stageOfKind[j.kind]);
    const unfinished=relevant.find(j=>['running','queued','paused','failed'].includes(j.status));
    let stage=stageOfStatus[task.status]||stageOfKind[task.automation?.stage]||stageOfKind[unfinished?.kind]||(task.edit_id?'edit':task.voice_id?'voice':task.script_id?'script':'sources');
    const runningJobs=jobs.filter(j=>j.status==='running');
    const primaryRunning=runningJobs.some(j=>stageOfKind[j.kind]);
    const review=['script_review','voice_review','draft_review'].includes(task.status);
    const state=task.error||task.status==='attention'?'error':primaryRunning?'running':task.status==='paused'||task.automation?.paused_by_user?'paused':task.status==='waiting_capcut'?'waiting':task.status==='retry_wait'?'retry':review?'review':task.status==='completed'?'completed':relevant.some(j=>j.status==='queued')?'queued':'unknown';
    const run=(task.pipeline||[]).find(r=>r.id===task.run_id);
    const previous=(task.pipeline||[]).find(r=>r.id===task.latest_completed_run_id);
    // Old output must never count towards a new run's progress.
    const evidence=run?.steps?.length ? assetKeys.map(key=>run.steps.find(s=>s.key===key)?.status==='completed')
      : task.automation?.protocol===2 ? Array(6).fill(false)
      : [!!task.sources?.length,!!task.original_text?.trim(),!!task.approved_script_id,!!task.approved_voice_id,!!task.edit_id,task.status==='completed'];
    if(stage==='sources'&&evidence[0])stage='transcript';
    const currentIndex=columns.findIndex(c=>c[0]===stage);
    const complete=state==='completed';
    const steps=columns.map(([id,label],i)=>{
      const current=!complete&&i===currentIndex;
      return {id,label,short:shortNames[i],number:i+1,tab:tabs[i],current,
        state:current?'current':complete||evidence[i]?'done':'pending'};
    });
    const done=steps.filter(s=>s.state==='done').length;
    const phase=complete?'6 / 6 단계 완료':`${currentIndex+1} / 6 단계`;
    const sourceError=task.source_search?.status==='failed';
    const sourceResolved=['sources','transcript'].includes(stage)&&task.sources?.length&&/Source manifest contains no selected local videos|제작에 사용할 소스 영상/.test(task.error||'');
    const note=sourceResolved?`직접 추가한 영상 ${task.sources.length}개가 준비됐어요. 사용할 영상을 선택하고 제작을 이어가세요.`:message(task.error||(sourceError?task.source_search.message:task.message),stateNames[state]);
    const nextAction=complete?'완성 영상 보기':review?{script:'대본 검토하기',voice:'음성 들어보기',edit:'초안 검토하기'}[stage]:state==='error'?'문제 확인하기':`${columns[currentIndex][1]} 작업 열기`;
    return {stage,state,label:state==='running'&&task.automation?.paused_by_user?'진행 중 · 중지 예약':stateNames[state],running:runningJobs.length>0,primaryRunning,review,complete,steps,done,
      currentIndex,phase,total:6,stageName:columns[currentIndex][1],attention:state==='error'||sourceError,
      versions:run?`제작 V${run.number}`:`대본 ${task.scripts?.length||0}개`,
      previous:previous&&previous.id!==run?.id?`V${previous.number} 완료본 보유`:'',
      activity:runningJobs.map(j=>activityNames[j.kind]||'추가 작업').join(' · '),message:note,nextAction,
      tab:tabs[currentIndex]};
  }
  function matches(task, filter, query) {
    const d=describe(task),q=(query||'').trim().toLowerCase();
    return (!q||`${task.title} ${task.shortcode}`.toLowerCase().includes(q))&&
      (filter==='all'||filter==='running'&&d.running||filter==='review'&&d.review||filter==='attention'&&d.attention||filter==='completed'&&d.complete);
  }
  function text(node,value){if(node.textContent!==String(value))node.textContent=value;}
  function createProgress(){
    const el=document.createElement('div');el.className='milestone-progress';
    el.setAttribute('role','progressbar');el.setAttribute('aria-valuemin','0');el.setAttribute('aria-valuemax','6');
    el.innerHTML='<ol aria-hidden="true">'+columns.map((c,i)=>`<li data-step="${c[0]}"><span class="step-node">${i+1}</span><span class="step-label">${shortNames[i]}</span></li>`).join('')+'</ol>';
    return el;
  }
  function updateProgress(el,d){
    el.setAttribute('aria-valuenow',d.done);el.setAttribute('aria-label','제작 단계 진행');
    el.setAttribute('aria-valuetext',`${d.phase}, ${d.stageName}, ${d.label}, ${d.done}개 단계 완료`);
    el.classList.toggle('is-live',d.primaryRunning);
    for(const step of d.steps){const li=el.querySelector(`[data-step="${step.id}"]`);li.dataset.stepState=step.state;text(li.querySelector('.step-node'),step.state==='done'?'✓':step.number);}
  }
  function mount(container,overview){
    const nodes=new Map(),lanes=new Map();
    for(const [i,[id,title,hint]] of columns.entries()){
      const lane=document.createElement('section');lane.className='kanban-column';lane.dataset.stage=id;
      lane.setAttribute('aria-labelledby','lane-'+id);
      lane.innerHTML=`<header class="column-head"><span class="column-number">${String(i+1).padStart(2,'0')}</span><div><h2 id="lane-${id}">${title}<span class="column-count">0</span></h2><p>${hint}</p></div></header><div class="column-cards"></div><p class="column-empty">아직 이 단계의 영상이 없어요</p>`;
      container.append(lane);lanes.set(id,lane);
    }
    const metrics=[['review','검토할 영상'],['running','제작 중'],['attention','확인 필요'],['completed','제작 완료']];
    overview.innerHTML=metrics.map(([id,title])=>`<div class="metric" data-metric="${id}"><span>${title}</span><strong>0<small>편</small></strong></div>`).join('');
    function render(tasks,{selectedId,filter='all',query=''}={}){
      const views=new Map(tasks.map(t=>[t.id,describe(t)]));
      const counts={review:0,running:0,attention:0,completed:0};
      for(const d of views.values()){for(const k of ['review','running','attention'])if(d[k])counts[k]++;if(d.complete)counts.completed++;}
      for(const [id] of metrics)overview.querySelector(`[data-metric="${id}"] strong`).firstChild.nodeValue=String(counts[id]);
      const visible=tasks.filter(t=>matches(t,filter,query)).sort((a,b)=>(a.created||0)-(b.created||0)||a.id.localeCompare(b.id));
      const visibleIds=new Set(visible.map(t=>t.id));
      for(const [id,node] of nodes)if(!visibleIds.has(id)){node.remove();nodes.delete(id);}
      const focus=document.activeElement;
      for(const task of visible){
        const d=views.get(task.id);let card=nodes.get(task.id);
        if(!card){
          card=document.createElement('article');card.className='work-card';card.dataset.workCard=task.id;
          card.innerHTML='<div class="card-identity"><div class="card-visual"><img hidden alt=""><span class="card-placeholder" aria-hidden="true">▷</span></div><div class="card-heading"><span class="card-mode"></span><h3></h3></div></div><div class="card-body"><div class="progress-heading"><strong class="card-phase"></strong><span class="card-stage"></span></div><div class="progress-mount"></div><div class="current-work"><div class="card-top"><span class="board-status"></span><span class="activity-dot" hidden aria-hidden="true"></span></div><p class="card-message"></p><p class="card-activity" hidden></p></div></div><footer class="card-footer"><div class="card-version-line"><span class="card-version"></span><span class="card-previous"></span></div><button class="card-open"></button></footer>';
          const button=card.querySelector('.card-open');button.dataset.work=task.id;button.type='button';button.setAttribute('aria-controls','work-drawer');
          card.querySelector('.progress-mount').append(createProgress());nodes.set(task.id,card);
        }
        card.classList.toggle('current',task.id===selectedId);card.classList.toggle('is-running',d.running);card.dataset.state=d.state;
        const button=card.querySelector('.card-open');button.setAttribute('aria-expanded',String(task.id===selectedId));
        const next=d.stage==='sources'&&!task.sources?.length?'영상 넣고 시작하기':d.nextAction;
        text(button,next+' →');button.setAttribute('aria-label',`${title(task)} · ${next}`);
        for(const [selector,value] of Object.entries({h3:title(task),'.card-mode':task.automation?'자동 제작':'직접 검토','.card-phase':d.phase,'.card-stage':d.stageName,'.board-status':d.label,'.card-message':d.message,'.card-version':d.versions,'.card-previous':d.previous,'.card-activity':d.activity}))text(card.querySelector(selector),value);
        updateProgress(card.querySelector('.milestone-progress'),d);
        card.querySelector('.card-activity').hidden=!d.running;card.querySelector('.activity-dot').hidden=!d.running;
        const img=card.querySelector('img'),cover=task.thumbnail_url||(task.edits||[]).find(e=>e.id===task.edit_id)?.cover_url||`thumbs/${encodeURIComponent(task.shortcode)}.jpg`;
        if(img.getAttribute('src')!==cover){img.onerror=()=>{img.hidden=true;};img.src=cover;img.hidden=false;}
        const lane=lanes.get(d.stage).querySelector('.column-cards');
        if(card.parentElement!==lane){const moved=!!card.parentElement;lane.append(card);if(moved){card.classList.remove('stage-arrived');void card.offsetWidth;card.classList.add('stage-arrived');}}
      }
      if(focus&&document.contains(focus)&&document.activeElement!==focus)focus.focus({preventScroll:true});
      for(const [id,lane] of lanes){const n=visible.filter(t=>views.get(t.id).stage===id).length;text(lane.querySelector('.column-count'),n);lane.querySelector('.column-empty').hidden=n>0;}
      return visible.length;
    }
    return {render};
  }
  function mountJourney(root){
    root.innerHTML='<div class="journey-overview"><div class="journey-caption"><strong></strong><span></span></div></div><ol class="journey-list">'+columns.map(([id,label],i)=>`<li data-journey="${id}"><span class="journey-node">${i+1}</span><button data-detail-tab="${tabs[i]}"><strong>${label}</strong><span class="journey-state"></span></button></li>`).join('')+'</ol>';
    root.querySelector('.journey-overview').append(createProgress());
    return t=>{
      const d=describe(t);text(root.querySelector('.journey-caption strong'),d.phase);text(root.querySelector('.journey-caption span'),`${d.done}개 단계 완료`);
      updateProgress(root.querySelector('.milestone-progress'),d);
      for(const step of d.steps){const li=root.querySelector(`[data-journey="${step.id}"]`);li.dataset.stepState=step.state;
        text(li.querySelector('.journey-node'),step.state==='done'?'✓':step.number);
        text(li.querySelector('.journey-state'),step.current?d.label:step.state==='done'?'완료':'예정');
        if(step.current)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');
      }
    };
  }
  const api={columns,describe,matches,mount,mountJourney,createProgress,updateProgress,message,title};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.StudioBoard=api;
})(typeof window==='undefined'?globalThis:window);
