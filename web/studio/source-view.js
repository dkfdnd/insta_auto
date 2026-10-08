/* Source search status, inventory and next-run selection. No API writes live here. */
(() => {
  'use strict';
  // Load a first frame only for visible cards, including cards revealed by a
  // tab, disclosure or horizontal scroll. Large libraries stay inexpensive.
  function bindPreviews(root){
    root._sourcePreviewObserver?.disconnect();
    const videos=[...root.querySelectorAll('video[data-source-preview]')].filter(v=>v.preload==='none'&&!v.poster);
    const load=video=>{
      if(video.preload!=='none')return;
      video.preload='metadata';
      if(video.readyState===0&&video.paused)video.load();
    };
    if(!videos.length)return;
    if(typeof IntersectionObserver==='undefined'){videos.forEach(load);return;}
    const observer=new IntersectionObserver(entries=>{
      for(const entry of entries)if(entry.isIntersecting){load(entry.target);observer.unobserve(entry.target);}
    });
    root._sourcePreviewObserver=observer;
    videos.forEach(video=>observer.observe(video));
  }
  function create({esc, link, item, storageKey}) {
  function sourceSearchState(t){
    const jobs=t.jobs||[],search=t.source_search||{};
    const busy=jobs.find(j=>['prepare','refresh_sources','collect_sources'].includes(j.kind)&&['queued','running'].includes(j.status));
    const latest=jobs.find(j=>j.kind==='refresh_sources');
    const failed=search.status==='failed'&&latest?.status==='failed'?latest:null;
    // A prepare failure may be transcription or rewriting; only an explicit missing-source error is actionable here.
    const missing=!t.sources?.length&&/Source manifest contains no selected local videos|제작에 사용할 소스 영상이 없습니다/.test(t.error||'');
    const hold=t.source_acquisition?.hold||search.hold;
    return {busy,failed,missing,hold};
  }
  function sourceSearchStatus(t){
    const {busy,failed,missing}=sourceSearchState(t),search=t.source_search||{};
    if(t.creation_mode==='self_shot')return `<p class="pf-help">내 촬영 영상 ${t.sources.length}/20개 · 사용할 영상을 선택하세요.</p>`;
    if(t.source_goal){
      const g=t.source_goal,labels=Object.entries(g.platforms||{}).map(([p,n])=>`${esc(p)} ${n}개`).join(' · ');
      const quota=Object.entries(g.platform_targets||{}).map(([p,c])=>`${esc(p==='tiktok'?'틱톡':p)} ${c.usable}/${c.target}개`).join(' · ');
      const quotaLine=(quota?`<p><strong>필수 확보 기준 · ${quota}</strong></p>`:'')+(search.strategy_message?`<p class="pf-help" data-search-strategy>${esc(search.strategy_message)}</p>`:'');
      const hold=t.source_acquisition?.hold||search.hold;
      if(!busy&&!g.ready&&hold)return `<div class="pf-search-notice is-error" role="status"><strong>소스 자동 수집 중지 · ${g.count}/${g.target}개</strong><p>${esc(search.message||t.message)}</p>${quotaLine}<small>확보한 영상·대본·음성은 보존됩니다. 검색 내역의 인증·로그인 문제를 해결하거나 아래에서 새로운 검색 조건을 입력하세요. 이미 수행한 검색은 자동 반복하지 않습니다.</small></div>`;
      const failedJob=(t.jobs||[]).find(j=>j.kind==='collect_sources'&&j.status==='failed');
      if(!busy&&failedJob)return `<div class="pf-search-notice is-error" role="status"><strong>소스 수집 확인 필요 · ${g.count}/${g.target}개</strong><p>${labels}</p>${quotaLine}<p>${esc(window.StudioBoard.message(search.message))}</p><button data-pf="retry-automatic-sources" data-job-id="${esc(failedJob.id)}">문제 해결 후 소스 수집 재시도</button></div>`;
      const title=g.ready?'소스 준비 완료':t.automation?.paused_by_user||t.automation?.consumed_by_daily_policy?'소스 자동 수집 일시중지':busy?.status==='running'?'소스 자동 추가 수집 중':'소스 자동 추가 수집 대기';
      return `<div class="pf-search-notice" role="status"><strong>${title} · ${g.count}/${g.target}개</strong><p>${labels||'사용 가능한 영상을 찾고 있습니다.'}</p>${quotaLine}${g.ready?'':`<small>다른 검색어와 플랫폼으로 계속 확보합니다.${g.core_ready?'':' 핵심 기능을 보여주는 장면도 확인합니다.'} 대본·음성 제작은 별도로 진행합니다.</small>`}</div>`;
    }
    if(busy)return `<div class="pf-search-notice" role="status"><strong>${busy.kind==='prepare'?'제작 자료 준비 중':busy.status==='queued'?'소스 검색 대기 중':'소스 검색 진행 중'}</strong><p>${esc(window.StudioBoard.message(busy.kind==='prepare'?t.message:search.message,'현재 요청을 처리하고 있습니다.'))}</p><small>현재 작업이 끝나면 추가 검색할 수 있어요.</small></div>`;
    if(failed||missing)return `<div class="pf-search-notice is-error" role="status"><strong>${failed?'소스 검색이 중단됐어요':'사용할 소스를 확보하지 못했어요'}</strong><p>${esc(window.StudioBoard.message(failed?search.message:t.error))}</p><button data-pf="retry-source-search" ${failed?`data-job-id="${esc(failed.id)}"`:''} ${failed&&!t.source_search_retry_supported?'disabled':''}>실패한 소스 검색 다시 시도</button><small>${failed&&!t.source_search_retry_supported?'서버 업데이트 적용이 필요합니다. 로컬 Hotpost 서버를 재시작한 뒤 새로고침하세요. 아래에서 검색 조건을 직접 입력해 추가 검색할 수도 있습니다.':(failed?'이전 검색 조건으로 다시 실행합니다.':'기본 검색을 다시 실행합니다. 확보 후 사용할 영상을 선택해 제작을 이어가세요.')+' 인증·연결 문제가 있었다면 먼저 해결해 주세요.'}</small></div>`;
    const goal=t.source_audit?.platform_targets?.tiktok;
    const goalText=goal?`<div class="pf-search-notice" role="status"><strong>TikTok 사용 가능 ${goal.usable}/${goal.target}개 · ${goal.status==='met'?'목표 달성':'목표 미달 또는 검색 미완료'}</strong><p>${Object.entries(goal.languages||{}).map(([l,ok])=>esc({en:'영어',ko:'한국어',zh:'중국어'}[l]||l)+' '+(ok?'검색 완료':'미완료')).join(' · ')}</p>${goal.status==='met'?'':'<small>아래 소스 검색 내역에서 로그인·차단·검색어 부족 여부를 확인해 주세요. 필요한 검색어·인증을 준비한 뒤 추가 검색할 수 있어요.</small>'}</div>`:'';
    return (search.status==='done'?`<p class="pf-help" role="status">${esc(window.StudioBoard.message(search.message,''))}</p>`:'')+goalText;
  }
  function sourceSearchPanel(t){
    const {busy,failed,missing}=sourceSearchState(t);
    return `<section class="pf-source-search">${!busy&&!failed&&!missing?'<div class="pf-search-record">'+sourceSearchStatus(t)+'</div>':''}<details class="pf-advanced" data-search-options ${!t.sources?.length&&!busy?'open':''}><summary>조건을 바꿔 추가 검색</summary><p class="pf-help">원하는 장면이 부족할 때 제품명·동작·촬영 장면을 구체적으로 입력하세요. 처음 소스 찾기와 같은 검색을 새 조건으로 다시 실행하며, 기존 영상은 유지합니다.</p><label>추가로 필요한 장면<textarea data-field="search" maxlength="1000" placeholder="예: 캠핑 수납 가방을 펼쳐 내부 칸막이를 보여주는 장면" aria-describedby="source-search-help"></textarea></label><p class="pf-help" id="source-search-help">새 영상이 발견되지 않을 수도 있습니다. 기존 결과의 다음 페이지를 가져오는 기능은 아닙니다.</p><button data-pf="search" ${busy?'disabled':''}>입력한 조건으로 추가 검색</button><p data-search-validation role="status"></p>${audit(t.source_audit)}</details></section>`;
  }
  function updateSourceSearch(root,t){
    const box=root.querySelector('[data-search-status]');
    if(box){const html=sourceSearchStatus(t);if(box.innerHTML!==html)box.innerHTML=html;}
    const button=root.querySelector('[data-pf="search"]');
    if(button)button.disabled=!!sourceSearchState(t).busy||!!root._saving;
    const alert=root.querySelector('[data-source-alert]');if(alert){const s=sourceSearchState(t);alert.hidden=!(s.busy||s.failed||s.missing||s.hold);if(!alert.hidden&&!alert.querySelector('[data-search-status]')){const html=sourceSearchStatus(t);if(alert.innerHTML!==html)alert.innerHTML=html;}}
  }
  function audit(a){
    if(!a)return '';
    const reasons={download_failed:'다운로드 실패',invalid_duration:'영상 길이 확인 필요',heavy_text_overlay:'자막이 많은 영상',low_product_or_scene_similarity:'주제·장면 불일치',title_query_mismatch:'검색어 불일치',low_resolution:'해상도 부족',not_probed:'영상 확인 대기',verification_failed:'영상 검증 실패',platform_budget_exhausted:'검색 시간 종료',download_budget_deferred:'남은 시간 부족으로 다음 검사에 이월',platform_cooldown:'검색 서비스 휴식 중'};
    const statuses={timeout:'시간 초과',results:'후보 발견',no_results:'결과 없음',login_required:'로그인 필요',captcha:'사람 확인 필요',verification_required:'이전 인증 차단으로 검색 건너뜀',rate_limited:'요청 제한',cooldown:'재시도 대기',error:'검색 실패',http_error:'응답 오류',started:'검색 시작',no_supported_queries:'지원 언어 검색어 없음',query_exhausted:'이 경로의 미사용 검색어 소진',image_exhausted:'미사용 장면 이미지 소진',strategy_skipped:'이전 실패에 따라 다른 경로로 전환',page_unresolved:'검색 화면에서 결과를 판독하지 못함',readiness_blocked:'페이지 판독 실패로 재검색 중지'};
    const platforms={tiktok:'틱톡',douyin:'더우인',xiaohongshu:'샤오홍슈',instagram:'인스타그램',youtube:'유튜브',bilibili:'빌리빌리',stock:'기타 영상 서비스',other:'기타'};
    const outcomes={not_attempted:'실제 시도 없음',captcha:'인증 화면 확인',auth_required:'로그인 필요',access_denied:'접근 거부',access_restricted:'공개 접근 불가',rate_limited:'요청 제한',download_failed:'다운로드 실패',search_failed:'검색 실패',no_candidates:'후보 없음',review_pending:'사용할 장면 검토 중',quality_rejected:'영상 검증 탈락',metadata_rejected:'검색 결과의 영상 길이 불일치',duplicate:'중복 영상',budget_exhausted:'이번 수집 시간·횟수 한도',cooldown:'재시도 대기'};
    const outcomeRows=Object.entries(a.platform_outcomes||{}).map(([p,n])=>`<p><strong>${esc(platforms[p]||p)}</strong> · 실제 검색 ${n.search_attempts||0}회 · 다운로드 시도 ${n.download_attempts||0}회<br>${Object.entries(n.reasons||{}).map(([r,c])=>`${esc(outcomes[r]||r)} ${c}`).join(' · ')}${n.skipped_searches?`<br>검색 건너뜀 ${n.skipped_searches}회 · ${Object.entries(n.skipped_reasons||{}).map(([r,c])=>`${esc(statuses[r]||outcomes[r]||r)} ${c}`).join(' · ')}`:''}</p>`).join('');
    const strategy=a.strategy;
    const strategyHtml=strategy?`<div data-search-strategy><strong>검색 전략 · ${esc(strategy.label)}</strong><p>${(strategy.reasons||[]).map(esc).join(' · ')}</p>${Object.entries(strategy.skipped_routes||{}).map(([p,r])=>`<p>${esc(p)}: ${esc(r)}</p>`).join('')}<p>${strategy.vendor_search?'제품 시연 판매처도 검색':'확인한 주제에 맞는 영상 경로만 검색'}</p></div>`:'';
    const inspectionHtml=a.inspection?.length?`<details><summary>후보 검사 순서의 근거와 시간 배분</summary><p>제목의 주제·행동 일치로 검사 순서를 정합니다. 영상의 사용 가능 여부는 실제 장면 검사로 판단합니다.</p>${a.inspection.map(c=>`<p><strong>${esc(c.title||'제목 없는 후보')}</strong><br>${(c.reasons||[]).map(esc).join(' · ')}${c.duration!=null?` · 검색 결과의 길이 ${esc(c.duration)}초`:''}${c.download_budget_seconds!=null?` · 다운로드 시간 배분 ${esc(c.download_budget_seconds)}초`:''}${c.rejections?.length?`<br>${c.rejections.map(r=>esc(reasons[r]||r)).join(' · ')}`:''}</p>`).join('')}</details>`:'';
    return `<details><summary>소스 검색 내역</summary>${strategyHtml}<p>채택 ${a.selected||0}개 · 제작 가능 ${a.usable??'확인 중'}개</p>${Object.entries(a.platforms||{}).map(([p,n])=>`<p>${esc(p)}: 후보 ${n.candidates} → 다운로드 ${n.received} → 채택 ${n.selected}</p>`).join('')}<p>${Object.entries(a.rejections||{}).map(([r,n])=>esc(reasons[r]||'추가 검토 필요')+': '+n).join(' · ')}</p>${inspectionHtml}${outcomeRows?`<details><summary>플랫폼별 시도·실패 이유</summary>${outcomeRows}</details>`:''}<details><summary>검색어와 실행 기록</summary>${(a.searches||a.planned_queries||[]).map(q=>`<p>${esc(q.provider||'')} · ${esc({ko:'한국어',en:'영어',zh:'중국어',image:'이미지'}[q.language]||'검색')} · ${esc(q.query)} · ${esc(statuses[q.status]||'확인 중')}${q.reason?` · ${esc(q.reason)}`:''}</p>`).join('')}</details></details>`;
  }
  function sourcePoster(source,t){
    const edit=item(t,'edits',t.edit_id);
    return source.thumbnail_url||(edit?.plan?.shots||[]).find(s=>s.source_id===source.id)?.thumbnail_url||'';
  }
  function sourceLibrary(t){
    const {delivered,usedIds,selected}=selection(t);
    const local=JSON.parse(localStorage.getItem(storageKey(t))||'{}');
    const checked=v=>('source:'+v.id) in local?local['source:'+v.id]:selected.includes(v.id);
    const count=t.sources.filter(checked).length;
    const preparing=t.creation_mode==='self_shot'?!t.self_shot?.started:['sources','transcript'].includes(window.StudioBoard.describe(t).stage);
    const busy=(t.jobs||[]).some(j=>j.status==='running'&&!['proposal','suggest_edit'].includes(j.kind));
    const used=t.sources.filter(v=>usedIds.includes(v.id));
    const added=t.sources.filter(v=>!usedIds.includes(v.id)&&(v.rights==='user_supplied'||v.original_name));
    const other=t.sources.filter(v=>!usedIds.includes(v.id)&&!added.includes(v));
    const cards=items=>`<div class="pf-sources">${items.map(v=>`<div class="pf-source-card"><video data-source-preview controls playsinline preload="none" ${sourcePoster(v,t)?`poster="${esc(sourcePoster(v,t))}"`:""} src="${esc(v.url)}"></video><label class="sd-source-check"><input type="checkbox" aria-label="영상 ${t.sources.indexOf(v)+1} 사용" data-field="source:${v.id}" ${checked(v)?'checked':''}></label><small class="pf-source-usage">${usedIds.includes(v.id)?(t.creation_mode==='self_shot'?'이번 제작 후보로 선택됨':'현재 영상에 사용됨'):'새 제작에 사용 가능'}</small><div class="pf-source-badges">${v.source_role==='context_only'?'<span>상황 설명용 장면</span>':''}${v.blur_required?'<span>문자·워터마크 가림 필요</span>':''}</div><details><summary>영상 정보</summary><p>${esc(v.original_name||v.title||'영상 '+(t.sources.indexOf(v)+1))}</p>${link(v.url,'영상 내려받기')}</details></div>`).join('')}</div>`;
    return `<div class="pf-source-library"><div class="pf-source-selection"><span class="pf-count">${t.sources.length}개 보유 · 다음 제작에 <b data-selected-count>${count}</b>개 선택</span>${t.sources.length?'<div class="pf-source-tools"><button type="button" data-pf="select-all-sources">전체 선택</button><button type="button" data-pf="clear-sources">선택 해제</button></div>':''}</div>
      ${used.length?`<section class="pf-source-group pf-source-used" data-source-group="used"><h4>${t.creation_mode==='self_shot'?(delivered?'완성본 제작에 고른 후보 영상':'이번 제작의 후보 영상'):(delivered?'완성 영상에 사용한 장면':'이번 제작에 선택한 장면')}</h4><p class="pf-help">${t.creation_mode==='self_shot'?'AI가 후보 중 일부 장면을 사용합니다. 체크를 바꾸면 다음 제작에 반영됩니다.':'다음 제작에서 사용할 영상에 체크하세요.'}</p>${cards(used)}</section>`:''}
      ${added.length?`<section class="pf-source-group pf-source-added" data-source-group="added"><h4>직접 추가한 영상 · ${added.length}개</h4>${cards(added)}</section>`:''}
      ${other.length?`<details class="pf-source-other" data-source-group="other" ${!used.length&&!added.length?'open':''}><summary>사용 가능한 영상 · ${other.length}개</summary>${cards(other)}</details>`:''}
      <div class="pf-source-upload"><h4>새 영상 추가</h4><div data-upload-widget></div></div>
      <div class="pf-source-save">${preparing?`<button class="pf-primary-next" data-pf="use-sources" ${!count||busy?'disabled':''}>${t.creation_mode==='self_shot'?'선택한 촬영 영상으로 제작 시작':'선택한 영상으로 제작 이어가기'}</button><p class="pf-help">${busy?'자료 작업이 끝나면 제작을 이어갈 수 있습니다.':!count?'사용할 영상에 먼저 체크해 주세요.':'선택한 영상을 사용해 대본·음성·영상 제작을 이어갑니다.'}</p>`:'<p class="pf-help">선택을 바꾼 뒤 아래 ‘수정 내용으로 영상 만들기’를 누르세요.</p>'}</div></div>`;
  }
  function selection(t){
    const run=t.pipeline?.find(r=>r.id===t.run_id);
    const delivered=t.pipeline?.find(r=>r.id===t.latest_completed_run_id);
    // Saved selections are for a future edit, not evidence of a completed video's sources.
    const baseline=delivered||run;
    const usedIds=baseline?.artifacts?.sources?.map(v=>v.id)??baseline?.inputs?.source_ids??[];
    const selected=t.feedback?.source_ids??run?.inputs?.source_ids??(usedIds.length?usedIds:t.sources.map(v=>v.id));
    return {delivered,usedIds,selected};
  }
  function sourceBaseline(t,id){
    return selection(t).selected.includes(id);
  }
    return {sourceSearchState, sourceSearchStatus, sourceSearchPanel, updateSourceSearch, sourceLibrary, sourceBaseline};
  }
  window.StudioSourceView = {create,bindPreviews};
})();
