/* Display the six real production milestones, independently from execution state. */
(function (root) {
  'use strict';
  const columns = [
    ['sources', '소스 확보', '제작에 사용할 영상 모으기'],
    ['transcript', '원본 내용', '원본 영상의 음성·화면 내용 확인'],
    ['script', '제작 대본', '후보 비교 · 자동 선정'],
    ['voice', '음성 제작', '음성 생성 · 청취'],
    ['edit', '영상 편집', '장면 · 자막 · 프로젝트'],
    ['export', '내보내기', '최종 영상 출력 · 완료'],
  ];
  const shortNames = ['소스','원문','대본','음성','편집','출력'];
  const assetKeys = ['sources','transcript','script','voice','project','export'];
  const tabs = ['sources','original','script','voice','edit','results'];
  const stageOfKind = {prepare:'sources', collect_sources:'sources', rewrite:'script', voice:'voice', edit:'edit', revision:'edit', revise:'edit', edit_request:'edit', register:'edit', export:'export'};
  const stageOfStatus = {preparing:'sources', source_wait:'sources', rewriting:'script', script_review:'script', voice_generating:'voice', voice_review:'voice', editing:'edit', draft_review:'edit', registering:'edit', exporting:'export', completed:'export'};
  const activityNames = {prepare:'자료 준비', rewrite:'대본 재가공', voice:'음성 생성', edit:'영상 편집', revision:'편집 수정', revise:'편집 수정', edit_request:'편집 수정', register:'프로젝트 등록', export:'MP4 내보내기', collect_sources:'소스 자동 추가 수집', refresh_sources:'소스 추가 수집', proposal:'대본 수정안 생성', suggest_edit:'편집 수정안 생성'};
  const stateNames = {running:'진행 중', queued:'실행 대기', review:'검토 필요', blocked:'제작 준비 필요', waiting:'제작 대기', retry:'재시도 대기', paused:'일시중지', error:'확인 필요', completed:'제작 완료', unknown:'상태 확인 필요'};
  function message(value, fallback='작업 상태를 확인하고 다시 시도해 주세요.') {
    const s=String(value||'');
    if(/Source manifest contains no selected local videos|제작에 사용할 소스 영상이 없습니다/.test(s))return '아직 사용할 영상이 없어요. 다른 검색어와 플랫폼으로 자동 추가 수집합니다.';
    if(/captcha|CAPTCHA|사람 확인/.test(s))return '해당 검색 서비스에서 사람 확인이 필요해요. 다른 플랫폼의 소스 확보를 이어갑니다.';
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
    const owned=task.creation_mode==='self_shot';
    const taskColumns=columns.map((c,i)=>owned&&i===1?['transcript','제작 정보 준비','제품 정보와 대본 입력']:c);
    const jobs=[...(task.jobs||[])].sort((a,b)=>(b.updated||0)-(a.updated||0));
    const relevant=jobs.filter(j=>stageOfKind[j.kind]);
    const unfinished=relevant.find(j=>['running','queued','paused','failed'].includes(j.status));
    let stage=stageOfStatus[task.status]||stageOfKind[task.automation?.stage]||stageOfKind[unfinished?.kind]||(task.edit_id?'edit':task.voice_id?'voice':task.script_id?'script':'sources');
    const runningJobs=jobs.filter(j=>j.status==='running');
    const primaryRunning=runningJobs.some(j=>stageOfKind[j.kind]);
    const executing=runningJobs.find(j=>stageOfKind[j.kind]);
    if(executing&&!task.error)stage=stageOfKind[executing.kind];
    const automatic=task.automation?.protocol===2;
    const review=['script_review','voice_review','draft_review'].includes(task.status)&&!automatic;
    const state=task.error||task.status==='attention'?'error':primaryRunning?'running':task.status==='completed'?'completed':task.production_blockers?.length||task.source_acquisition?.hold?'blocked':task.status==='paused'||task.automation?.paused_by_user?'paused':task.status==='waiting_capcut'?'waiting':task.status==='retry_wait'?'retry':relevant.some(j=>j.status==='queued')?'queued':review?'review':automatic?'waiting':'unknown';
    const run=(task.pipeline||[]).find(r=>r.id===task.run_id);
    const previous=(task.pipeline||[]).find(r=>r.id===task.latest_completed_run_id);
    // Old output must never count towards a new run's progress.
    const evidence=run?.steps?.length ? assetKeys.map(key=>run.steps.find(s=>s.key===key)?.status==='completed')
      : task.automation?.protocol===2 ? Array(6).fill(false)
      : [!!task.sources?.length,!!task.original_text?.trim(),!!task.approved_script_id,!!task.approved_voice_id,!!task.edit_id,task.status==='completed'];
    if(stage==='sources'&&evidence[0]&&!(owned&&!task.self_shot?.started))stage='transcript';
    // Automatic production needs no human script/voice approval. Completed
    // artifacts belong to completed milestones even when an old review status remains.
    if(!executing&&automatic&&['script_review','voice_review','draft_review'].includes(task.status)){
      const pending=evidence.findIndex(v=>!v);
      if(pending>=0)stage=columns[pending][0];
    }
    const currentIndex=columns.findIndex(c=>c[0]===stage);
    const complete=state==='completed';
    const steps=taskColumns.map(([id,label],i)=>{
      const current=!complete&&i===currentIndex;
      const live=!complete&&runningJobs.some(j=>stageOfKind[j.kind]===id||j.kind==='prepare'&&id==='transcript')&&
        (task.source_goal ? run?.steps?.find(s=>s.key===assetKeys[i])?.status==='running' : current&&state==='running');
      return {id,label,short:shortNames[i],number:i+1,tab:tabs[i],current,live,
        state:current?'current':complete||evidence[i]?'done':'pending'};
    });
    const done=steps.filter(s=>s.state==='done').length;
    const phase=complete?'6 / 6 단계 완료':`${currentIndex+1} / 6 단계`;
    const sourceError=['failed','blocked'].includes(task.source_search?.status);
    const sourceResolved=['sources','transcript'].includes(stage)&&task.sources?.length&&/Source manifest contains no selected local videos|제작에 사용할 소스 영상/.test(task.error||'');
    const note=sourceResolved?`직접 추가한 영상 ${task.sources.length}개가 준비됐어요. 사용할 영상을 선택하고 제작을 이어가세요.`:message(task.error||(sourceError?task.source_search.message:task.message),stateNames[state]);
    const nextAction=complete?'완성 영상 보기':state==='blocked'?'필요한 준비 확인하기':review?{script:'대본 검토하기',voice:'음성 들어보기',edit:'초안 검토하기'}[stage]:state==='error'?'문제 확인하기':`${columns[currentIndex][1]} 작업 열기`;
    return {stage,state,label:state==='running'&&task.automation?.paused_by_user?'진행 중 · 중지 예약':stateNames[state],running:runningJobs.length>0,primaryRunning,review,complete,steps,done,
      currentIndex,phase,total:6,stageName:taskColumns[currentIndex][1],attention:state==='error'||state==='blocked'||sourceError,
      versions:run?`${run.number}번째 영상`:`대본 ${task.scripts?.length||0}개`,
      previous:previous&&previous.id!==run?.id?`${previous.number}번째 완성본 보관 중`:'',
      activity:runningJobs.map(j=>activityNames[j.kind]||'추가 작업').join(' · '),message:note,nextAction,
      tab:tabs[currentIndex]};
  }
  function matches(task, filter, query) {
    const d=describe(task),q=(query||'').trim().toLowerCase();
    return (!q||`${task.title} ${task.shortcode}`.toLowerCase().includes(q))&&
      (filter==='all'||filter==='running'&&['running','queued','retry'].includes(d.state)||filter==='review'&&d.review||filter==='attention'&&!d.complete&&(d.attention||d.review||['paused','waiting','unknown'].includes(d.state))||filter==='completed'&&d.complete);
  }
  function listPage(tasks,{filter='running',query='',page=1,pageSize=12}={}){
    const filtered=tasks.filter(t=>matches(t,filter,query)).sort((a,b)=>(b.created||0)-(a.created||0)||a.id.localeCompare(b.id));
    const pages=Math.max(1,Math.ceil(filtered.length/pageSize)),current=Math.min(pages,Math.max(1,page));
    return {items:filtered.slice((current-1)*pageSize,current*pageSize),total:filtered.length,page:current,pages,pageSize};
  }
  function text(node,value){if(node.textContent!==String(value))node.textContent=value;}
  function activityMarkup(live=false){
    return `<span class="studio-working-dots" ${live?'':'hidden'} aria-hidden="true"><i></i><i></i><i></i></span>`;
  }
  function createProgress(){
    const el=document.createElement('div');el.className='milestone-progress';
    el.setAttribute('role','progressbar');el.setAttribute('aria-valuemin','0');el.setAttribute('aria-valuemax','6');
    el.innerHTML='<ol aria-hidden="true">'+columns.map((c,i)=>`<li data-step="${c[0]}"><span class="step-node">${i+1}</span><span class="step-label">${shortNames[i]}</span></li>`).join('')+'</ol>';
    return el;
  }
  function updateProgress(el,d){
    el.setAttribute('aria-valuenow',d.done);el.setAttribute('aria-label','제작 단계 진행');
    el.setAttribute('aria-valuetext',`${d.phase}, ${d.stageName}, ${d.label}, ${d.done}개 단계 완료`);
    el.classList.toggle('is-live',d.steps.some(s=>s.live));
    for(const step of d.steps){const li=el.querySelector(`[data-step="${step.id}"]`);li.dataset.stepState=step.state;li.dataset.live=String(step.live);text(li.querySelector('.step-node'),step.state==='done'?'✓':step.number);}
  }
  const bucket=d=>d.complete?'finished':d.attention||d.review||['paused','waiting','unknown'].includes(d.state)?'attention':'working';
  function boardPage(tasks,{filter='all',query='',pages={},pageSize=4}={}){
    const filtered=listPage(tasks,{filter,query,pageSize:Math.max(1,tasks.length)}).items;
    const lanes=['working','attention','finished'].map(id=>{
      const items=filtered.filter(t=>bucket(describe(t))===id),total=items.length;
      const count=Math.max(1,Math.ceil(total/pageSize)),page=Math.min(count,Math.max(1,pages[id]||1));
      return {id,total,page,pages:count,pageSize,items:items.slice((page-1)*pageSize,page*pageSize)};
    });
    return {lanes,total:filtered.length};
  }
  function mount(container,overview,pager,recent){
    const caches={board:new Map(),grid:new Map()},lanes=new Map(),previousStates=new Map(),justFinished=[];
    let mountedView=null;
    overview.innerHTML='<h2>제작 현황</h2>'+[['working','진행 중','running'],['attention','확인 필요','attention'],['finished','완성','completed']].map(([id,label,filter])=>`<button class="metric" data-metric="${id}" data-filter="${filter}"><span>${label}</span><strong>0<small>편</small></strong></button>`).join('');
    for(const [i,[id,label,hint]] of [['working','제작 중','지금 만드는 영상'],['attention','내가 확인할 영상','자료 준비·검토·문제 해결'],['finished','완성 영상','보고 내려받으세요']].entries()){
      const lane=document.createElement('section');lane.className='kanban-column';lane.dataset.stage=id;lane.setAttribute('aria-labelledby','lane-'+id);
      lane.innerHTML=`<header class="column-head"><span class="column-number">${String(i+1).padStart(2,'0')}</span><div><h2 id="lane-${id}">${label}<span class="column-count">0</span></h2><p>${hint}</p></div></header><div class="column-cards"></div><p class="column-empty">이 상태의 작업이 없습니다</p><nav class="lane-pagination" aria-label="${label} 페이지"></nav>`;
      lanes.set(id,lane);
    }
    const stamp=n=>n?new Date(n*1000).toLocaleDateString('ko-KR',{month:'numeric',day:'numeric',timeZone:'Asia/Seoul'}):'';
    const setMarkup=(node,markup)=>{if(node._markup!==markup){node.innerHTML=markup;node._markup=markup;}};
    function cardFor(task,d,view,selectedId){
      const nodes=caches[view];let card=nodes.get(task.id);
      if(!card){
        card=document.createElement('article');card.className='work-card';card.dataset.workCard=task.id;
        const visual='<div class="card-visual"><img hidden alt="" loading="lazy"><span class="card-placeholder" aria-hidden="true">▷</span></div>';
        card.innerHTML=view==='board'?'<div class="card-identity">'+visual+'<div class="card-heading"><span class="card-mode"></span><h3></h3></div></div><div class="card-body"><div class="progress-heading"><strong class="card-phase"></strong><span class="card-stage"></span></div><details class="card-progress-details"><summary>자세한 제작 단계</summary><div class="progress-mount"></div></details><div class="current-work"><div class="card-top"><span class="board-status"></span></div><p class="card-message"></p><p class="card-activity" hidden></p></div></div><footer class="card-footer"><div class="card-version-line"><span class="card-version"></span><span class="card-previous"></span></div><button type="button" class="card-open"></button></footer>':'<button class="card-cover" type="button">'+visual+'</button><div class="card-heading"><h3></h3><div class="card-top"><span class="board-status"></span></div><p class="card-stage"></p><div class="card-meta"><span class="card-mode"></span><time></time></div></div>';
        card.querySelector('button').dataset.work=task.id;card.querySelector('button').setAttribute('aria-controls','work-drawer');
        card.querySelector('.card-top').insertAdjacentHTML('beforeend',activityMarkup());
        if(view==='board')card.querySelector('.progress-mount').append(createProgress());
        nodes.set(task.id,card);
      }
      card.classList.toggle('current',task.id===selectedId);card.classList.toggle('is-running',d.running);card.dataset.state=d.state;
      const live=d.steps.some(s=>s.live);card.dataset.productionLive=String(live);card.querySelector('.studio-working-dots').hidden=!live;
      const button=card.querySelector('button');button.setAttribute('aria-expanded',String(task.id===selectedId));button.setAttribute('aria-label',`${title(task)} · ${d.nextAction}`);
      const labels={h3:title(task),'.card-mode':task.creation_mode==='self_shot'?'내 촬영':'터진게시물','.board-status':d.label,'.card-stage':view==='board'?d.stageName:d.complete?'완성 영상 보기':d.stageName+' · '+d.phase};
      if(view==='board')Object.assign(labels,{'.card-phase':d.phase,'.card-message':d.message,'.card-version':d.versions,'.card-previous':d.previous,'.card-open':d.nextAction+' →','.card-activity':d.activity});
      else labels.time=stamp(task.created);
      for(const [selector,value] of Object.entries(labels))text(card.querySelector(selector),value);
      if(view==='board'){updateProgress(card.querySelector('.milestone-progress'),d);card.querySelector('.card-activity').hidden=!d.running;card.querySelector('.current-work').setAttribute('aria-busy',String(live));}
      const img=card.querySelector('img'),edit=(task.edits||[]).find(e=>e.id===task.edit_id),owned=task.creation_mode==='self_shot';
      const cover=task.thumbnail_url||(owned?(task.sources||[]).find(s=>s.thumbnail_url)?.thumbnail_url:null)||edit?.cover_url||edit?.plan?.shots?.find(s=>s.thumbnail_url)?.thumbnail_url||(!owned?`thumbs/${encodeURIComponent(task.shortcode)}.jpg`:null);
      if(cover&&img.getAttribute('src')!==cover){img.onerror=()=>{img.hidden=true;card.querySelector('.card-placeholder').hidden=false;};img.onload=()=>{img.hidden=false;card.querySelector('.card-placeholder').hidden=true;};img.src=cover;img.hidden=false;}
      if(!cover)img.hidden=true;card.querySelector('.card-placeholder').hidden=!!cover&&!img.hidden;
      return card;
    }
    function render(tasks,{selectedId,filter='all',query='',page=1,view='board',lanePages={}}={}){
      view=view==='grid'?'grid':'board';
      const focus=document.activeElement,views=new Map(tasks.map(t=>[t.id,describe(t)])),counts={attention:0,working:0,finished:0};
      for(const task of tasks){const d=views.get(task.id);if(matches(task,'running',''))counts.working++;if(matches(task,'attention',''))counts.attention++;if(d.complete)counts.finished++;if(previousStates.has(task.id)&&!previousStates.get(task.id)&&d.complete)justFinished.unshift(task.id);previousStates.set(task.id,d.complete);}
      for(const [id,count] of Object.entries(counts))overview.querySelector(`[data-metric="${id}"] strong`).firstChild.nodeValue=String(count);
      if(mountedView!==view){container.replaceChildren();if(view==='board')for(const lane of lanes.values())container.append(lane);mountedView=view;}
      container.dataset.view=view;
      const grid=listPage(tasks,{filter,query,page}),board=boardPage(tasks,{filter,query,pages:lanePages});
      const shown=view==='board'?board.lanes.flatMap(l=>l.items):grid.items;
      const visibleIds=new Set(shown.map(t=>t.id));
      for(const [id,node] of caches[view])if(!visibleIds.has(id))node.remove();
      const put=(parent,items)=>{let cursor=parent.firstElementChild;for(const task of items){const card=cardFor(task,views.get(task.id),view,selectedId);if(card!==cursor)parent.insertBefore(card,cursor);cursor=card.nextElementSibling;}};
      if(view==='board'){
        for(const data of board.lanes){
          const lane=lanes.get(data.id);text(lane.querySelector('.column-count'),data.total);lane.querySelector('.column-empty').hidden=!!data.items.length;put(lane.querySelector('.column-cards'),data.items);
          const nav=lane.querySelector('.lane-pagination');nav.hidden=data.total<=data.pageSize;
          setMarkup(nav,`<span>${(data.page-1)*data.pageSize+1}–${Math.min(data.page*data.pageSize,data.total)} / ${data.total}</span><div><button type="button" data-lane="${data.id}" data-lane-page="${data.page-1}" ${data.page===1?'disabled':''} aria-label="${lane.querySelector('h2').firstChild.textContent} 이전 페이지">‹</button><button type="button" data-lane="${data.id}" data-lane-page="${data.page+1}" ${data.page===data.pages?'disabled':''} aria-label="${lane.querySelector('h2').firstChild.textContent} 다음 페이지">›</button></div>`);
        }
        container.dataset.lanePages=JSON.stringify(Object.fromEntries(board.lanes.map(l=>[l.id,l.page])));
      }else put(container,grid.items);
      if(focus&&document.contains(focus)&&document.activeElement!==focus)focus.focus({preventScroll:true});
      container.dataset.page=String(view==='grid'?grid.page:page);
      if(pager){pager.hidden=view==='board'||!grid.total;const start=grid.total?(grid.page-1)*grid.pageSize+1:0,end=Math.min(grid.page*grid.pageSize,grid.total);setMarkup(pager,`<span>${start}–${end} / 총 ${grid.total}개</span><div><button type="button" data-board-page="${grid.page-1}" ${grid.page===1?'disabled':''}>이전</button><span>${grid.page} / ${grid.pages}</span><button type="button" data-board-page="${grid.page+1}" ${grid.page===grid.pages?'disabled':''}>다음</button></div>`);}
      if(recent){const ids=[...new Set(justFinished)].filter(id=>views.get(id)?.complete).slice(0,3);recent.hidden=filter!=='running'||!ids.length;const wrapper=document.createElement('div');for(const id of ids){const button=document.createElement('button');button.type='button';button.dataset.work=id;button.textContent='✓ '+title(tasks.find(t=>t.id===id))+' · 완성 영상 보기';wrapper.append(button);}setMarkup(recent,'<h2>방금 완료</h2>'+wrapper.innerHTML);}
      return grid.total;
    }
    return {render};
  }
  function mountJourney(root){
    root.innerHTML='<div class="journey-overview"><div class="journey-caption"><strong></strong><span></span></div></div><ol class="journey-list">'+columns.map(([id,label],i)=>`<li data-journey="${id}"><span class="journey-node">${i+1}</span><button data-detail-tab="${tabs[i]}"><strong>${label}</strong><span class="journey-state"></span></button></li>`).join('')+'</ol>';
    root.querySelector('.journey-overview').append(createProgress());
    return t=>{
      const d=describe(t);text(root.querySelector('.journey-caption strong'),d.phase);text(root.querySelector('.journey-caption span'),`${d.done}개 단계 완료`);
      updateProgress(root.querySelector('.milestone-progress'),d);
      for(const step of d.steps){const li=root.querySelector(`[data-journey="${step.id}"]`);li.dataset.stepState=step.state;li.dataset.live=String(step.live);
        text(li.querySelector('.journey-node'),step.state==='done'?'✓':step.number);
        text(li.querySelector('.journey-state'),step.current?d.label:step.state==='done'?'완료':'예정');
        if(step.current)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');
      }
    };
  }
  const api={columns,describe,matches,listPage,boardPage,mount,mountJourney,createProgress,updateProgress,message,title,activityMarkup};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.StudioBoard=api;
})(typeof window==='undefined'?globalThis:window);
