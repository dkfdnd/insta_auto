/* Read-only post results. Studio owns editing and production actions. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {sources:'소스 영상', script:'대본', voice:'음성', final:'완성 영상'};
  const statusText = {completed:'완료', running:'진행 중', failed:'실패', queued:'대기 중', waiting:'대기 중', blocked:'준비 필요', paused:'일시중지', pending:'대기 중'};
  const kinds = {sources:['collect_sources','refresh_sources'], script:['prepare','rewrite'], voice:['voice'], final:['edit','revision','revise','edit_request','register','export']};
  const href = (t, tab, run) => `studio.html?work=${encodeURIComponent(t.id)}&tab=${tab}${run ? '&run='+encodeURIComponent(run) : ''}`;
  const selected = (t, group, key) => (t[group] || []).find(v => v.id === t[key]);
  const stamp = value => value ? new Date(value*1000).toLocaleString('ko-KR', {timeZone:'Asia/Seoul',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}) : '이전';
  function platform(source) {
    let host = ''; try { host = new URL(source.origin_url).hostname.toLowerCase(); } catch (_) {}
    return [['틱톡',/tiktok/],['더우인',/douyin/],['샤오홍슈',/xiaohongshu|xhslink/],['인스타그램',/instagram/],['유튜브',/youtube|youtu\.be/],['빌리빌리',/bilibili/],['Pexels',/pexels/]].find(([,re])=>re.test(host))?.[0] || (host || '기타');
  }
  function inventory(t) {
    if (t.source_goal) return t.source_goal;
    const seen = new Set(), sources = (t.sources || []).filter(s => {
      const id = s.sha256 || s.origin_url || s.id;
      if (!id || seen.has(id) || s.available === false) return false;
      seen.add(id); return true;
    });
    const platforms = {}; sources.forEach(s => {const p=platform(s); platforms[p]=(platforms[p]||0)+1;});
    const core = sources.some(s => s.source_role!=='context_only' && s.functional_review?.same_core_function===true);
    return {target:10, count:sources.length, platforms, core_ready:core, ready:sources.length>=10&&core};
  }
  function model(t) {
    const runs=t.pipeline||[], active=runs.find(r=>r.id===t.run_id)||runs.at(-1);
    const script=selected(t,'scripts','script_id'), candidate=selected(t,'voices','voice_id');
    const voice=candidate?.script_id===script?.id ? candidate : null;
    const goal=inventory(t), completed=runs.filter(r=>r.video_url).sort((a,b)=>(b.completed||b.created||b.number||0)-(a.completed||a.created||a.number||0));
    const jobs=t.jobs||[], steps={};
    for(const key of Object.keys(labels)) {
      const historyComplete=active?.status==='completed'&&!!active.video_url;
      const done = key==='sources' ? historyComplete||goal.ready : key==='script' ? !!script : key==='voice' ? !!voice : !!active?.video_url;
      const relevant=jobs.filter(j=>kinds[key].includes(j.kind));
      const live=relevant.find(j=>j.status==='running'), queued=relevant.find(j=>j.status==='queued');
      const latest=relevant[0], assets=active?.steps||[];
      const asset=assets.find(s=>s.key==={sources:'sources',script:'script',voice:'voice',final:'export'}[key]);
      let state=done?'completed':live?'running':queued?'queued':latest?.status==='failed'?'failed':'waiting';
      if (!done&&!live&&!queued&&['failed','blocked','paused'].includes(asset?.status)) state=asset.status;
      if (key==='voice'&&!done&&!live&&!queued&&state!=='failed'&&t.production_blockers?.includes('personal_clone_unavailable')) state='blocked';
      if (!done&&!live&&!queued&&t.automation?.paused_by_user)state='paused';
      steps[key]={state, text:statusText[state]||'대기 중'};
    }
    return {active,script,voice,goal,steps,completed,needsClone:!voice&&steps.voice.state!=='running'&&t.production_blockers?.includes('personal_clone_unavailable')};
  }
  function stageMarkup(t,m,selection) {
    return Object.entries(labels).map(([key,label])=>{
      const s=m.steps[key], suffix=key==='sources'?` · ${m.goal.count}${m.active?.video_url?'':'/'+m.goal.target}개 확보`:'';
      return `<button type="button" class="pr-stage is-${s.state}" data-stage="${key}" ${key==='final'?`aria-pressed="${selection===key}" aria-controls="pr-video-results"`:`aria-expanded="${selection===key}" aria-controls="pr-step-result"`} ${selection===key?'data-selected="true"':''} aria-label="${label}, ${s.text}${suffix}, 결과 보기"><span class="pr-symbol ${s.state==='running'?'pr-spinner':''}" aria-hidden="true">${s.state==='running'?'':s.state==='completed'?'✓':s.state==='failed'?'!':'○'}</span><strong>${label}</strong><span>${esc(s.text+suffix)}</span></button>`;
    }).join('');
  }
  function stepResult(t,m,key) {
    if(!key||key==='final')return '';
    const go=(tab,text)=>`<a class="pr-text-link" href="${esc(href(t,tab))}">${text} →</a>`;
    if(key==='sources'){
      const rows={...m.goal.platforms},issues={},names={tiktok:'틱톡',douyin:'더우인',xiaohongshu:'샤오홍슈',instagram:'인스타그램',youtube:'유튜브',bilibili:'빌리빌리','google-lens':'Google 검색','yandex-images':'Yandex 검색'};
      const notes={captcha:'인증 대기',verification_required:'인증 확인 필요',login_required:'로그인 필요',rate_limited:'요청 제한',cooldown:'재시도 대기',timeout:'응답 지연',error:'검색 오류',page_unresolved:'검색 화면 확인 실패',no_supported_queries:'검색어 보완 중'};
      for(const r of t.source_audit?.searches||[]){const name=names[r.provider];if(name){issues[name]=notes[r.status]||'';if(issues[name]&&!(name in rows))rows[name]=0;}}
      const liveNote=t.source_search?.status==='running'?String(t.source_search.message||''):'';
      const livePlatform=Object.keys(names).find(p=>liveNote.toLowerCase().startsWith(p));
      if(livePlatform){const issue=/captcha|인증 대기/i.test(liveNote)?'인증 대기':/로그인/.test(liveNote)?'로그인 필요':/429|요청 제한/.test(liveNote)?'요청 제한':'';if(issue){const name=names[livePlatform];issues[name]=issue;rows[name]??=0;}}
      const quota=Object.entries(m.goal.platform_targets||{}).map(([p,c])=>`${esc(names[p]||p)} ${c.usable}/${c.target}개`).join(' · ');
      return `<h4>확보한 소스 영상 · 총 ${m.goal.count}${m.active?.video_url?'':'/'+m.goal.target}개</h4><dl class="pr-platforms">${Object.entries(rows).map(([p,n])=>`<div><dt>${esc(p)}${issues[p]?`<small> · ${esc(issues[p])}</small>`:''}</dt><dd>${n}개</dd></div>`).join('')||'<div><dt>아직 확보한 영상이 없어요.</dt></div>'}</dl>${quota?`<p><strong>필수 확보 기준 · ${quota}</strong></p>`:''}${m.goal.ready||m.active?.video_url?'<p>제작에 필요한 소스가 준비됐어요.</p>':`<p>${m.steps.sources.state==='running'?'부족한 장면을 다른 검색어와 플랫폼에서 찾고 있어요.':m.steps.sources.state==='failed'?'소스 수집에 오류가 발생했어요. 상세 기록을 확인할 수 있어요.':m.steps.sources.state==='paused'?'자동 수집을 일시중지한 상태예요.':'부족한 장면을 자동으로 추가 수집할 예정이에요.'}</p>`}${go('sources','제작실에서 소스 보기')}`;
    }
    if(key==='script')return `<h4>${m.completed.length&&!m.active?.video_url?'수정 중인 대본':'제작 대본'}</h4>${m.script?`<div class="pr-script">${esc(m.script.text)}</div>`:`<p>${m.steps.script.state==='running'?'원본 레퍼런스를 분석해 대본을 만들고 있어요.':m.steps.script.state==='failed'?'대본 제작에 오류가 발생했어요.':'제작 대본을 준비하고 있어요.'}</p>`}${go('script','제작실에서 대본 수정')}`;
    const v=m.voice;
    return `<h4>제작 음성</h4>${v?`<p>${esc(v.voice_profile_id ? (v.voice_name||'제작실에서 선택한 목소리') : '내 복제 목소리')}${v.duration?' · '+Math.round(v.duration)+'초':''}</p><audio controls preload="none" src="${esc(v.path_url||v.url||'')}"></audio>`:`<p>${m.needsClone?'내 목소리 녹음과 복제 설정을 확인해 주세요. 설정을 마친 뒤 제작실에서 중단 단계를 재시도할 수 있어요.':m.steps.voice.state==='running'?'선택한 대본으로 음성을 만들고 있어요.':m.steps.voice.state==='failed'?'음성 제작에 오류가 발생했어요.':'현재 대본의 음성 제작을 기다리고 있어요.'}</p>`}${go('voice',m.needsClone?'내 목소리 등록·설정':'제작실에서 음성 확인')}`;
  }
  function waiting(t,m) {
    const live=Object.keys(labels).filter(k=>m.steps[k].state==='running');
    const failed=Object.keys(labels).filter(k=>m.steps[k].state==='failed');
    let message=live.length?live.map(k=>labels[k]).join(' · ')+' 작업을 진행하고 있어요.':failed.length?failed.map(k=>labels[k]).join(' · ')+' 제작에 오류가 발생했어요.':'제작 대기 중이에요.';
    if(m.needsClone)message='음성 제작이 멈춰 있어요';
    const description=m.needsClone?'내 목소리 녹음과 복제 설정을 확인해 주세요.':'완성되면 원본과 나란히 재생하고 다운로드할 수 있어요.';
    const separateWork=m.needsClone&&live.length?`<p>${esc(live.map(k=>labels[k]).join(' · '))} 작업은 별도로 진행 중이에요.</p>`:'';
    return `<div class="pr-waiting${m.needsClone?' is-blocked':''}" role="status">${m.needsClone?'<span class="pr-symbol" aria-hidden="true">!</span>':live.length?'<span class="pr-spinner" aria-hidden="true"></span>':''}<strong>${esc(message)}</strong><p>${description}</p>${separateWork}${m.needsClone?`<a class="pr-secondary" href="${esc(href(t,'voice'))}">내 목소리 등록·설정</a>`:''}<a class="pr-text-link" href="${esc(href(t,'script'))}">제작실에서 수정 →</a></div>`;
  }
  const video=(url,name,side)=>`<div class="pr-video"><h4>${name}</h4>${url?`<video controls playsinline preload="none" aria-label="${name}" src="${esc(url)}"></video><div class="pr-player-tools"><button type="button" data-play="${side}">▶ 재생</button><button type="button" data-fullscreen="${side}" aria-label="${name} 전체 화면">전체 화면</button></div>`:'<p class="pr-missing">원본 영상을 불러오지 못했어요.</p>'}</div>`;
  function actions(t,run) {
    const download=run.steps?.find(s=>s.key==='export')?.download_url;
    const historical=run.id!==t.run_id;
    return `${download?`<a class="pr-primary" href="${esc(download)}" download>↓ 영상 다운로드</a>`:''}<a class="pr-secondary" href="${esc(href(t,historical?'results':'edit',run.id))}">${historical?'이 영상의 제작 자료 보기':'제작실에서 수정'}</a>`;
  }
  function compare(t,run) {
    return `<div class="pr-compare">${video(t.reference_url,'원본 레퍼런스','reference')}${video(run.video_url,'우리 완성 영상','result')}</div><div class="pr-actions">${actions(t,run)}</div>`;
  }
  function updateComparison(body,t,run) {
    if(!body.querySelector('.pr-compare'))body.innerHTML=compare(t,run);
    const players=body.querySelectorAll('.pr-video');
    [[t.reference_url,'원본 레퍼런스','reference'],[run.video_url,'우리 완성 영상','result']].forEach(([url,label,side],i)=>{
      const previous=players[i].querySelector('video')?.getAttribute('src')||'';
      if(previous!==(url||''))players[i].outerHTML=video(url,label,side);
    });
    patch(body.querySelector('.pr-actions'),actions(t,run));
  }
  function diagnostics(t) {
    const errors=(t.jobs||[]).filter(j=>j.status==='failed');
    return `${t.error?`<p>${esc(t.error)}</p>`:''}${errors.map(j=>`<p>${esc(j.kind)} · ${esc(j.error||'작업 실패')}</p>`).join('')||'<p>추가 오류 기록이 없어요.</p>'}<a class="pr-text-link" href="${esc(href(t,'results'))}">제작실에서 상세 기록 보기 →</a>`;
  }
  function patch(el,html) { if(el._html!==html){el.innerHTML=html;el._html=html;} }
  function mount(root,t) {
    if(root._postId!==t.id) {
      root.innerHTML='<section class="post-result"><header><h3 data-title></h3></header><nav class="pr-stages" aria-label="제작 단계 · 누르면 결과를 확인할 수 있어요"></nav><p class="pr-stage-hint">단계를 누르면 결과를 볼 수 있어요.</p><section id="pr-step-result" class="pr-step-result" hidden></section><div id="pr-video-results"><div class="pr-current"></div><section class="pr-history" aria-label="제작 영상"></section></div><p class="pr-connection" role="status" hidden></p><details class="pr-diagnostics"><summary>상세 정보 · 오류 기록</summary><div></div></details></section>';
      root._postId=t.id; root._selection=null; root._cards=new Map();
      if(!root._mediaListenersBound){
        root._mediaListenersBound=true;
        root.addEventListener('play',event=>{if(event.target.matches('video,audio'))root.querySelectorAll('video,audio').forEach(v=>{if(v!==event.target)v.pause();});},true);
        root.addEventListener('error',event=>{if(event.target.matches('video')){const box=event.target.closest('.pr-video');if(box&&!box.querySelector('.pr-media-error')){const p=document.createElement('p');p.className='pr-media-error';p.textContent='재생하지 못했어요. 다시 재생하거나 파일을 다운로드해 주세요.';box.append(p);}}},true);
      }
      root.onclick=event=>{
        const button=event.target.closest('button');if(!button)return;
        if(button.dataset.stage){root._selection=root._selection===button.dataset.stage?null:button.dataset.stage;mount(root,root._task);if(button.dataset.stage==='final')root.querySelector('#pr-video-results').scrollIntoView?.({block:'nearest'});}
        if(button.dataset.collapse){const card=root._cards.get(button.dataset.collapse);card._collapsed=!card._collapsed;mount(root,root._task);}
        if(button.dataset.play||button.dataset.fullscreen){const video=button.closest('.pr-video').querySelector('video');if(button.dataset.play){if(video.paused){video.muted=false;video.play().catch(()=>{});}else video.pause();}else if(video.requestFullscreen)video.requestFullscreen().catch(()=>{});else video.webkitEnterFullscreen?.();}
      };
      root.addEventListener('play',e=>{const b=e.target.closest('.pr-video')?.querySelector('[data-play]');if(b)b.textContent='Ⅱ 일시정지';},true);
      root.addEventListener('pause',e=>{const b=e.target.closest('.pr-video')?.querySelector('[data-play]');if(b)b.textContent='▶ 재생';},true);
    }
    root._task=t; const m=model(t); root._model=m;
    const states=Object.values(m.steps).map(s=>s.state), prefix=m.completed.length?'수정본':'영상';
    root.querySelector('[data-title]').textContent=m.active?.video_url?'완성 영상':states.includes('running')?prefix+' 제작 중':states.includes('failed')?prefix+' 제작 실패':states.includes('paused')?prefix+' 제작 일시중지':states.includes('blocked')?prefix+' 제작 준비 필요':prefix+' 제작 대기';
    const focusedStage=root.contains(document.activeElement)?document.activeElement?.dataset?.stage:null;
    patch(root.querySelector('.pr-stages'),stageMarkup(t,m,root._selection));
    if(focusedStage)root.querySelector(`[data-stage="${focusedStage}"]`)?.focus({preventScroll:true});
    const panel=root.querySelector('.pr-step-result'); panel.hidden=!root._selection||root._selection==='final';
    patch(panel,stepResult(t,m,root._selection));
    const current=root.querySelector('.pr-current'), history=root.querySelector('.pr-history');
    const visible=[...(m.active?.video_url?[m.active]:[]),...m.completed.filter(r=>r.id!==m.active?.id)];
    for(const run of visible) {
      let card=root._cards.get(run.id);
      if(!card){card=document.createElement('article');card.className='pr-result-card';card.dataset.runId=run.id;card.innerHTML='<header><h3></h3><button type="button"></button></header><div class="pr-card-body"></div>';root._cards.set(run.id,card);}
      const isCurrent=run.id===m.active?.id, button=card.querySelector('header button');
      card.querySelector('header h3').textContent=(isCurrent?'':'이전 완성 영상 · ')+stamp(run.completed||run.created)+' 완성';
      button.dataset.collapse=run.id;button.textContent=card._collapsed?'펼치기 ∨':'접기 ∧';button.setAttribute('aria-expanded',String(!card._collapsed));button.setAttribute('aria-label',(card._collapsed?'이전 완성 영상 펼치기':'이전 완성 영상 접기'));button.hidden=isCurrent;
      const body=card.querySelector('.pr-card-body');body.id='pr-body-'+run.id;button.setAttribute('aria-controls',body.id);body.hidden=!isCurrent&&!!card._collapsed;
      updateComparison(body,t,run);
      // Keep all completed players in one stable parent. Starting a remake
      // changes only headings; it never detaches a playing previous result.
      if(card.parentElement!==history)history.append(card);
    }
    const old=root.querySelector('.pr-current .pr-waiting-wrap');
    if(!m.active?.video_url){let box=old;if(!box){box=document.createElement('div');box.className='pr-waiting-wrap';current.append(box);}patch(box,waiting(t,m));}else old?.remove();
    const ordered=visible;
    ordered.forEach((run,i)=>{const card=root._cards.get(run.id);if(history.children[i]!==card)history.insertBefore(card,history.children[i]||null);});
    history.classList.toggle('has-current',!!m.active?.video_url);
    patch(root.querySelector('.pr-diagnostics>div'),diagnostics(t));
    root.querySelector('.pr-connection').hidden=true;
  }
  function connectionError(root) {const notice=root.querySelector('.pr-connection');if(notice){notice.hidden=false;notice.textContent='상태를 갱신하지 못했어요. 연결되면 자동으로 다시 확인합니다.';}}
  window.PostResult={mount,model,inventory,stageMarkup,stepResult,compare,connectionError};
})();
