/* 오늘의 터진 게시물 - 서버 판정 결과를 표시하고 기준을 저장한다. */
(async function () {
  'use strict';
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const R = window.HOTPOST_REPORT;
  async function loadCollectionHealth() {
    const el = document.querySelector('#collection-health');
    if (!el) return;
    const stamp = value => value ? new Date(value * 1000).toLocaleString('ko-KR') : '없음';
    try {
      const response = await fetch('/api/collection-status', {cache: 'no-store'});
      if (!response.ok) throw new Error('status unavailable');
      const data = await response.json(), c = data.collection, run = c.last_run;
      const labels = {none:'실행 전', running:'실행 중', success:'갱신 완료', partial_failure:'갱신 완료 · 일부 계정 실패', failure:'실패', blocked:'중단'};
      const result = run ? ` · 성공 ${run.accounts_ok} / 실패 ${run.accounts_failed} / 건너뜀 ${run.accounts_skipped || 0}` : '';
      const views = c.view_observations || {};
      el.textContent = `수집 ${labels[c.state] || c.state} · 데이터 갱신 ${stamp(c.newest_post_update)}`;
      const details=document.createElement('a');details.href='accounts.html';details.textContent=' 계정별 수집 상태 →';el.append(details);
      if (c.state !== 'running' && (!c.newest_post_update || Date.now()/1000 - c.newest_post_update > 26*3600)) el.textContent += ' · 최신 수집 데이터가 아닙니다';
      if (c.last_success_at > (R?.generated_at || 0)) {
        el.append(document.createTextNode(' · 현재 목록보다 새로운 수집 데이터가 있습니다. '));
        const refresh = document.createElement('button');
        refresh.type = 'button';
        refresh.textContent = '최신 게시물 보기';
        refresh.addEventListener('click', () => window.location.reload());
        el.append(refresh);
      }
    } catch (_) {
      el.textContent = '현재 수집 상태를 확인할 수 없습니다. 표시된 게시물의 데이터 기준 시각을 확인하세요.';
    }
  }
  loadCollectionHealth();
  setInterval(loadCollectionHealth, 60000);

  // ---------- 유틸 ----------
  const fmt = (n) => {
    if (n === null || n === undefined) return '–';
    if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, '') + '억';
    if (n >= 1e4) return (n / 1e4).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, '') + '만';
    return Math.round(n).toLocaleString('ko-KR');
  };
  const ago = (h) => (h < 1 ? '방금' : h < 24 ? Math.round(h) + '시간 전' : h < 24 * 14 ? Math.round(h / 24) + '일 전' : Math.round(h / 24 / 7) + '주 전');
  const dateStr = (ts) => new Date(ts * 1000).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const ratioCls = (r) => (r == null ? 'flat' : r >= 2.5 ? 'up' : r >= 1.5 ? 'mid' : r >= 0.8 ? 'flat' : 'down');
  const ratioTxt = (r) => (r == null ? '' : '×' + (r >= 10 ? Math.round(r) : r.toFixed(1)));
  const tierTxt = (t) => ({ 0: '', 1: '🔥', 2: '🔥🔥', 3: '🔥🔥🔥' })[t];
  const kindTxt = (k) => ({ reel: '릴스', video: '동영상', image: '사진', carousel: '캐러셀' })[k] || k;
  const confTxt = { high: '높음', medium: '보통', low: '낮음' };
  const flagTxt = { comments_spike: '💬 댓글 급증', views_spike: '👀 조회수 급증', likes_spike: '❤️ 좋아요 급증', fresh: '🆕 48시간 내', rising: '📈 상승 중',
    ad_candidate: '광고 후보', sponsored_candidate: '협찬 후보', group_buy_candidate: '공동구매 후보', event_candidate: '이벤트 후보' };
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const initials = (u) => (u || '?').replace(/[^a-z0-9가-힣]/gi, '').slice(0, 2).toUpperCase();
  const isVideo = (p) => p.kind === 'reel' || p.kind === 'video';
  const store = {
    get: (k, d) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };

  // ---------- 테마 ----------
  const themeBtn = $('#theme-toggle');
  const applyTheme = (t) => {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    themeBtn.textContent = cur === 'dark' ? '☀️' : '🌙';
  };
  applyTheme(store.get('hp-theme', ''));
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark'; applyTheme(next); store.set('hp-theme', next);
  });

  if (!R) {
    $('#meta').textContent = '아직 리포트가 없습니다.';
    $('#app').innerHTML = '<div class="empty" style="margin-top:24px">데이터가 없습니다. 터미널에서 <code>python -m hotpost run</code> 을 실행한 뒤 새로고침하세요.</div>';
    return;
  }

  // ---------- 판정 기준 ----------
  const S = R.settings;
  const acctMap = Object.fromEntries((R.accounts || []).map((account) => [account.username, account]));
  let POSTS=[];
  function recompute(){POSTS=R.posts.slice();}
  // ---------- 헤더 / 배너 ----------
  $('#meta').textContent = `${R.generated_at_kst} 기준 · 판정 v${R.criteria.version} · ${R.summary.accounts}개 계정 · 최근 ${S.recent_days}일 게시물 ${R.posts.length}개 분석`;
  const sb = $('#source-badge');
  if (R.is_sample) { sb.textContent = '샘플 데이터'; sb.classList.add('sample'); }
  else { sb.textContent = { instaloader: '실데이터 · 세션 수집', web: '실데이터 · 웹 수집', dump: '실데이터 · 브라우저 덤프' }[R.source] || '실데이터'; sb.classList.add('live'); }
  if (R.is_sample) { const b = $('#banner'); b.hidden = false; b.innerHTML = '⚠️ 지금 보고 있는 것은 <b>생성된 샘플 데이터</b>입니다. 실제 데이터를 보려면 <code>python -m hotpost login --user 아이디 --browser chrome</code> 로 세션을 만든 뒤 <code>python -m hotpost run</code> 을 실행하세요.'; }
  else if (R.notes && R.notes.length) {
    // Report notes are historical. A removed monitoring account must not keep
    // raising an active warning just because no new collection has run yet.
    const b = $('#banner');
    try {
      const response = await fetch('/api/accounts', {cache:'no-store'});
      if (!response.ok) throw new Error('account list unavailable');
      const data = await response.json();
      const managed = new Set(data.accounts.map(a => a.username.toLowerCase()));
      const notes = R.notes.filter(note => {
        const match = /^@([a-z0-9_.]+):/i.exec(note);
        return !match || managed.has(match[1].toLowerCase());
      });
      if (notes.length) {
        b.hidden = false;
        b.innerHTML = `⚠️ ${esc(R.generated_at_kst)} 수집 기록 · 일부 계정 수집 실패: ` + notes.map(esc).join(' / ');
      }
    } catch (_) {
      b.hidden = false;
      b.textContent = '현재 계정 목록을 확인하지 못했습니다. 과거 수집 실패 기록은 레퍼런스 계정에서 확인하세요.';
    }
  }
  if (!R.is_sample && R.last_data_update_at && Date.now() / 1000 - R.last_data_update_at > 30 * 3600) {
    const b = $('#banner'); b.hidden = false;
    b.innerHTML += `<div>마지막 데이터 갱신: ${esc(dateStr(R.last_data_update_at))}. 재분석 시각과 실제 관측 시각은 다를 수 있습니다.</div>`;
  }

  // ---------- 상태 ----------
  let saved;
  try {saved=await window.HotpostDisplay.load();} catch(e){saved={...window.HotpostDisplay.defaults};$('#banner').hidden=false;$('#banner').textContent='저장된 화면 설정을 불러오지 못해 기본 조건을 표시합니다.';}
  const state={...saved,q:'',topic:null};
  const linkedAccount=new URLSearchParams(location.search).get('account');if(linkedAccount)state.account=linkedAccount;
  function currentSettings(){
    const c=R.criteria.values;
    $('#current-settings').textContent=window.HotpostDisplay.describe(state)+` · 등급 기준 ${c.t1}/${c.t2}/${c.t3}배`;
  }
  currentSettings();
  function showSearch(open){$('#search-box').hidden=!open;$('#search-toggle').setAttribute('aria-expanded',String(open));$('#search-toggle').setAttribute('aria-label',open?'검색창 닫기':'검색창 열기');if(open)$('#q').focus();}
  $('#search-toggle').onclick=()=>{const open=$('#search-box').hidden;showSearch(open);if(!open){$('#q').value='';state.q='';renderAll();}};
  $('#q').addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();showSearch(false);$('#q').value='';state.q='';renderAll();$('#search-toggle').focus();}});
  let qt;$('#q').addEventListener('input',e=>{clearTimeout(qt);qt=setTimeout(()=>{state.q=e.target.value.trim().toLowerCase();renderAll();},150);});
  window.addEventListener('focus',async()=>{try{const active=await (await fetch('/api/criteria',{cache:'no-store'})).json();if(active.version!==R.criteria.version){location.reload();return;}const fresh=await window.HotpostDisplay.load();Object.assign(state,fresh);if(linkedAccount)state.account=linkedAccount;currentSettings();renderAll();}catch(_){}});
  // ---------- 필터 ----------
  function baseFiltered() {   // 기간·유형·계정·검색 (등급/주제 제외) → 주제 계산용
    const q = state.q;
    return POSTS.filter((p) => {
      if (state.detection === 'today') {
        if (!window.HotpostDetection.isToday(p)) return false;
      } else if (p.age_hours > state.period) return false;
      if (state.kind === 'video' && !isVideo(p)) return false;
      if (state.kind === 'image' && isVideo(p)) return false;
      if (state.account && p.username !== state.account) return false;
      if (q && !(p.caption.toLowerCase().includes(q) || p.username.includes(q) || p.hashtags.some((h) => h.includes(q.replace(/^#/, ''))))) return false;
      return true;
    });
  }
  function filtered(base) {
    const list = base.filter((p) => {
      if (p.tier < state.tier) return false;
      if (state.assessment !== 'all' && p.assessment?.status !== state.assessment) return false;
      if (state.topic) {
        const t = state.topic;
        const hit = (p.categories || ['생활·기타']).includes(t);
        if (!hit) return false;
      }
      return true;
    });
    const key = { rank: (p) => p.rank_score, views: (p) => p.views || 0, comments: (p) => p.comments, likes: (p) => p.likes, recent: (p) => p.taken_at }[state.sort];
    list.sort((a, b) => key(b) - key(a) || b.taken_at - a.taken_at);
    return list;
  }

  // ---------- 주제 (클라이언트 재계산) ----------
  function topics(base) {
    const groups=new Map();
    base.filter(p=>p.tier>=Math.max(1,state.tier)&&(state.assessment==='all'||p.assessment?.status===state.assessment)).forEach(p=>{
      for(const label of p.categories||['생활·기타']){if(!groups.has(label))groups.set(label,{label,posts:0,score:0,accounts:new Set()});const g=groups.get(label);g.posts++;g.score+=p.tier;g.accounts.add(p.username);}
    });
    return [...groups.values()].sort((a,b)=>(a.label==='생활·기타')-(b.label==='생활·기타')||b.score-a.score).map(g=>({...g,accounts:g.accounts.size}));
  }
  const topicsEl = $('#topics');
  function renderTopics(base) {
    const list = topics(base);
    topicsEl.innerHTML = list.length ? '' : '<span class="hint">이 조건에서는 주제를 뽑을 만큼 핫 게시물이 없습니다.</span>';
    list.forEach((t) => {
      const el = document.createElement('button');
      el.className = 'chip' + (t.kind === 'keyword' ? ' kw' : '') + (state.topic === t.label ? ' on' : '');
      el.innerHTML = `${esc(t.label)} <span class="n">${t.posts}</span>`;
      el.title = `${t.accounts}개 계정 · ${t.posts}개 게시물`;
      el.addEventListener('click', () => { state.topic = state.topic === t.label ? null : t.label; renderAll(); });
      topicsEl.appendChild(el);
    });
  }

  // ---------- 통계 ----------
  function renderStats() {
    const hot = POSTS.filter((p) => p.tier >= 1);
    $('#stats').innerHTML = [
      ['hot', '🔥 기준 통과', hot.length, `/ ${POSTS.length}개`],
      ['hot', '성과 확인', hot.filter((p) => p.assessment?.status === 'confirmed').length, '개'],
      ['hot', '잠정 후보', hot.filter((p) => p.assessment?.status !== 'confirmed').length, '개'],
      ['', '분석 계정', R.summary.accounts, '개'],
      ['', '릴스 비중', Math.round((POSTS.filter(isVideo).length / Math.max(1, POSTS.length)) * 100), '%'],
    ].map(([c, k, v, u]) => `<div class="stat ${c}"><div class="k">${k}</div><div class="v">${v}<small>${u}</small></div></div>`).join('');
  }

  // ---------- 카드 ----------
  const productionByCode = new Map();
  const studioByCode = new Map();
  const studioSelected = new Set();
  document.addEventListener('click', async e => {
    const choice = e.target.closest('.studio-choice');
    if (choice) {
      e.stopPropagation();
      if (e.target.type === 'checkbox') {
        const code = e.target.dataset.studioCode;
        if (e.target.checked) studioSelected.add(code); else studioSelected.delete(code);
        $('#studio-selection').hidden = studioSelected.size === 0;
        $('#studio-selected-count').textContent = `${studioSelected.size}개 선택`;
      }
      return;
    }
    if (e.target.id !== 'studio-add-selected') return;
    e.stopPropagation(); e.target.disabled = true;
    try {
      const response = await fetch('/api/studio', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({shortcodes:[...studioSelected]})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '제작실 추가 실패');
      location.href = 'studio.html?work=' + encodeURIComponent(result.tasks[0].id);
    } catch (error) { e.target.textContent = error.message; e.target.disabled = false; }
  }, true);
  function productionMarkup(code) {
    const work = studioByCode.get(code);
    if (work) return `<a class="production-link" href="studio.html?work=${encodeURIComponent(work.id)}" onclick="event.stopPropagation()">${work.automation?'자동 제작 '+work.automation.rank+'위':'제작실 작업'} · 진행/영상 리뷰 →</a><br><small class="${work.error?'production-error':''}">${esc(work.error||work.message)}</small>`;
    const job = productionByCode.get(code);
    if (!job) return '<span class="hint">제작 선택으로 추가 · 수집 후 상위 2개는 자동 제작</span>';
    const source = job.source || {}, transcript = job.transcript || {};
    const link = (url, label) => url ? `<a class="production-link" href="${esc(url)}" onclick="event.stopPropagation()">${label}</a>` : `<span>${label}</span>`;
    const states = {queued:'대기',voice:'음성 생성 중',building:'프로젝트 생성 중',draft_ready:'프로젝트 완료',exporting:'내보내기 중',done:'완료',error:'실패 · 재시도 필요',missing:'결과 파일 없음'};
    const stageLabel = (status, runningLabel) => job.status === 'queued' && !['done','draft_ready','missing'].includes(status)
      ? '대기' : status === 'running' ? runningLabel : states[status] || '대기';
    return `<div>${link(source.download_url, source.download_url ? `소스 영상 다운로드 완료 · ${source.count}개 ↓` : '소스 영상 · ' + stageLabel(source.status, '찾는 중'))}</div>
      <div>${link(transcript.download_url, transcript.download_url ? '대본 다운로드 완료 ↓' : '대본 · ' + stageLabel(transcript.status, '추출 중'))}</div>
      ${(job.variants || []).map(v => `<div>${link(v.download_url, `쇼츠 V${v.version} · ${v.download_url ? '다운로드 ↓' : stageLabel(v.status, '제작 중')}`)} ${v.script_url ? link(v.script_url, '재작성 대본 ↓') : ''}</div>`).join('')}
      <small class="${job.status === 'error' ? 'production-error' : ''}">${esc(job.status === 'queued' ? '자동 제작 대기' : job.error || job.message)}</small>
      ${job.status === 'error' ? `<button class="btn ghost production-retry" data-code="${esc(code)}">중단 단계부터 다시 시도</button>` : ''}`;
  }
  async function refreshProductions() {
    const responses = await Promise.allSettled([
      fetch('/api/studio', {cache:'no-store'}).then(r=>r.ok?r.json():null),
      fetch('/api/legacy-productions', {cache:'no-store'}).then(r=>r.ok?r.json():null)
    ]);
    if (responses[0].status==='fulfilled' && responses[0].value?.tasks) {
      studioByCode.clear();
      for (const item of responses[0].value.tasks) studioByCode.set(item.shortcode,item);
    }
    try {
      const data = responses[1].status==='fulfilled'?responses[1].value:null;
      for (const item of data?.productions||[]) productionByCode.set(item.shortcode, item);
      $$('.production-status').forEach(el => { el.innerHTML = productionMarkup(el.dataset.code); });
    } catch (_) { /* Keep verified last state while the server reconnects. */ }
  }
  document.addEventListener('click', async e => {
    const button = e.target.closest('.production-retry');
    if (!button) return;
    e.stopPropagation(); button.disabled = true;
    try {
      const response = await fetch(`/api/legacy-productions/${encodeURIComponent(button.dataset.code)}/retry`, {method:'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '재시도 실패');
      if(data.id?.startsWith('work-')) { location.href='studio.html?work='+encodeURIComponent(data.id); return; } productionByCode.set(data.shortcode, data); await refreshProductions();
    } catch (error) { button.textContent = error.message; button.disabled = false; }
  }, true);
  refreshProductions();
  setInterval(refreshProductions, 4000);
  function metric(label, val, ratio, na) {
    return `<div class="m ${na ? 'na' : ''}"><div class="k">${label}</div><div class="v">${na ? '–' : fmt(val)}</div><div class="r ${ratioCls(ratio)}">${na ? '' : ratioTxt(ratio) + (ratio != null ? ' 평소 대비' : '')}</div></div>`;
  }
  function card(p, i) {
    const flags = p.flags.filter((f) => flagTxt[f]).map((f) => `<span class="flag ${f === 'fresh' ? 'neutral' : ''}">${flagTxt[f]}</span>`).join('');
    const thumb = p.thumb ? `<img loading="lazy" src="${esc(p.thumb)}" alt="">` : `<div class="ph">${isVideo(p) ? '🎬' : '🖼'}</div>`;
    return `<article class="card" data-code="${esc(p.shortcode)}">
      <div class="thumb">${thumb}
        ${isVideo(p) ? `<label class="studio-choice" style="position:absolute;bottom:10px;right:10px;z-index:4;background:#fffef2;color:#285b46;border-radius:6px;padding:7px 10px;font-size:12px;cursor:pointer"><input type="checkbox" data-studio-code="${esc(p.shortcode)}" ${studioSelected.has(p.shortcode)?'checked':''}> 제작 선택</label>` : ''}
        <div class="tl">${p.tier ? `<span class="pill t${p.tier}">${tierTxt(p.tier)} ×${p.multiplier.toFixed(1)}</span>` : `<span class="pill">×${p.multiplier.toFixed(1)}</span>`}</div>
        <div class="tr"><span class="pill kind">${kindTxt(p.kind)}${p.video_duration ? ' · ' + Math.round(p.video_duration) + 's' : ''}</span></div>
        <div class="rank">#${i + 1}</div>
      </div>
      <div class="body">
        ${p.tier ? `<div class="flags"><span class="flag neutral" title="${esc((p.assessment?.reasons || []).join(' · '))}">${esc(p.assessment?.label || '잠정 후보')}</span></div>` : ''}
        <div class="who"><span class="avatar">${initials(p.username)}</span><span class="name">@${esc(p.username)}</span><span class="time" title="${dateStr(p.taken_at)}">${ago(p.age_hours)}</span></div>
        <div class="hint">핫 최초 감지일 · ${window.HotpostDetection.dateKey(p.hot_detected_at) || (p.tier ? '기록 없음' : '미감지')} (한국시간)</div>
        <div class="metrics">
          ${metric('조회수', p.views, p.ratios.views, !isVideo(p) || p.views == null)}
          ${metric('좋아요', p.likes, p.ratios.likes, false)}
          ${metric('댓글', p.comments, p.ratios.comments, false)}
        </div>
        <div class="cap">${esc(p.caption.replace(/#\S+/g, '').trim()) || '<span class="hint">(캡션 없음)</span>'}</div>
        ${flags ? `<div class="flags">${flags}</div>` : ''}
        ${isVideo(p) ? `<div class="production-status" data-code="${esc(p.shortcode)}">${productionMarkup(p.shortcode)}</div>` : ''}
        <div class="foot"><span class="conf">신뢰도 ${confTxt[p.confidence]} · 비교 ${p.baseline.peers}개</span><a href="${esc(p.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Instagram ↗</a></div>
      </div>
    </article>`;
  }
  let current = [];
  function render() {
    const base = baseFiltered();
    current = filtered(base);
    $('#cards').innerHTML = current.map(card).join('');
    const emp = $('#empty'); emp.hidden = current.length > 0;
    if (!current.length) emp.textContent = state.detection === 'today' ? '현재 필터에 맞는 오늘 최초 감지 핫 게시물이 없습니다. 데이터 기준 시각과 다른 필터도 확인하세요.' : state.tier > 0 ? '조건에 맞는 터진 게시물이 없습니다. 기간을 늘리거나 판정 기준을 낮춰 보세요.' : '조건에 맞는 게시물이 없습니다.';
    const desc = [state.detection === 'today' ? '오늘 최초 감지 (한국시간)' : state.period <= 24 ? '24시간' : state.period / 24 + '일', state.kind === 'all' ? '' : state.kind === 'video' ? '릴스' : '사진', state.tier ? tierTxt(state.tier) + ' 이상' : '전체', state.account ? '@' + state.account : '', state.topic ? '주제 "' + state.topic + '"' : ''].filter(Boolean).join(' · ');
    $('#result-count').textContent = `${current.length}개 · ${desc}`;
    const hotBase = base.filter((p) => p.tier >= 1).length;
    return base;
  }
  function renderAll() { recompute(); renderStats(); const base = render(); renderTopics(base); }

  // ---------- 플랫폼 로그인 관리 ----------
  // ---------- 상세 모달 ----------
  const modal = $('#modal');
  $('#cards').addEventListener('click', (e) => { const c = e.target.closest('.card'); if (c) openDetail(POSTS.find((p) => p.shortcode === c.dataset.code)); });
  modal.addEventListener('click', (e) => { if (e.target.dataset.close !== undefined) closeDetail(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDetail(); });
  let flowTimer, flowCode;
  function closeDetail() { clearTimeout(flowTimer); flowCode=null; modal.hidden = true; document.body.style.overflow = ''; }
  async function refreshProduction(code) {
    clearTimeout(flowTimer);
    if(flowCode!==code||modal.hidden)return;
    const root=$('#production-flow',modal);if(!root)return;
    try {
      const data=await window.ProductionFlow.api('');
      if(flowCode!==code)return;
      const task=data.tasks.find(t=>t.shortcode===code);
      if(task)window.ProductionFlow.mount(root,task);
      else {
        root.innerHTML='<section class="production-flow"><h3>자동 제작</h3><p>소스 확보 → 대본 → TTS → CapCut 프로젝트 → 최종 MP4</p><button id="begin-auto">자동 제작 시작</button></section>';
        $('#begin-auto',root).onclick=async e=>{e.target.disabled=true;try{await window.ProductionFlow.api('',{shortcodes:[code],automatic:true});refreshProduction(code);}catch(err){e.target.disabled=false;root.append(document.createTextNode(err.message));}};
      }
    }catch(e){root.textContent='제작 상태를 불러오지 못했습니다: '+e.message;}
    if(flowCode===code)flowTimer=setTimeout(()=>refreshProduction(code),3000);
  }
  function bar(label, val, base, ratio) {
    if (val == null) return '';
    const max = Math.max(val, base || 0, 1);
    return `<div class="row"><span>${label}</span><div class="track"><div class="fill" style="width:${(val / max) * 100}%"></div>${base ? `<div class="base" style="left:${(base / max) * 100}%"></div>` : ''}</div><div class="num">${fmt(val)} <small>/ 평소 ${fmt(base)}</small><br><span class="r ${ratioCls(ratio)}">${ratioTxt(ratio)}</span></div></div>`;
  }
  function openDetail(p) {
    if (!p) return;
    clearTimeout(flowTimer); flowCode=p.shortcode;
    const a = acctMap[p.username] || {}, v = p.velocity;
    $('#modal-body').innerHTML = `<div class="detail">
      <div class="thumb">${p.thumb ? `<img src="${esc(p.thumb)}" alt="">` : `<div class="ph">${isVideo(p) ? '🎬' : '🖼'}</div>`}</div>
      <div class="detail-body">
        <div class="who"><span class="avatar">${initials(p.username)}</span><span class="name">@${esc(p.username)}</span>${a.full_name ? `<span class="fn">${esc(a.full_name)}</span>` : ''}<span class="time">${dateStr(p.taken_at)} (${ago(p.age_hours)})</span></div>
        <h3>${tierTxt(p.tier) || '—'} 평소 대비 ×${p.multiplier.toFixed(1)} <small class="hint">${kindTxt(p.kind)}</small></h3>
        ${isVideo(p) ? '<div id="production-flow"></div>' : ''}
        <div class="cmp">
          ${isVideo(p) ? bar('조회수', p.views, p.baseline.views, p.ratios.views) : ''}
          ${bar('좋아요', p.likes, p.baseline.likes, p.ratios.likes)}
          ${bar('댓글', p.comments, p.baseline.comments, p.ratios.comments)}
        </div>
        <div class="kv">
          <div>핫 최초 감지일 (한국시간)<b>${window.HotpostDetection.dateKey(p.hot_detected_at) || (p.tier ? '기록 없음' : '미감지')}</b></div>
          <div>팔로워<b>${fmt(a.followers)}</b></div>
          <div>비교 게시물<b>${p.baseline.peers}개</b></div>
          <div>반응 성숙도<b>${Math.round((R.criteria.values.maturity ? p.maturity : 1) * 100)}%</b></div>
          <div>신뢰도<b>${confTxt[p.confidence]}</b></div>
          <div>판정 상태<b>${esc(p.assessment?.label || '재분석 필요')}</b></div>
          <div>보정 전 배수<b>${p.assessment ? '×' + p.assessment.unadjusted_multiplier.toFixed(2) : '—'}</b></div>
          ${p.assessment?.reasons?.length ? `<div>추가 확인 사항<b>${esc(p.assessment.reasons.join(' · '))}</b></div>` : ''}
          ${v ? `<div>증가 속도 (${v.hours}h)<b>${v.views_per_hour != null ? fmt(v.views_per_hour) + ' 뷰/h · ' : ''}${v.comments_per_hour} 댓글/h</b></div>` : ''}
          ${p.growth ? `<div>최근 조회 상태<b>${esc(p.growth.state)}</b></div><div>최근 조회 속도<b>${p.growth.views_per_hour == null ? '성공 관측 부족' : fmt(p.growth.views_per_hour) + ' 뷰/h'}</b></div>
            <div>가속도<b>${p.growth.acceleration == null ? '비교 구간 부족' : fmt(p.growth.acceleration) + ' 뷰/h²'}</b></div>
            <div>조회 성공 관측<b>${p.growth.successful_observations}개</b></div>
            <div>성장 비교<b>${p.growth.comparison.mode === 'age_matched' ? '같은 게시 연령 ' + p.growth.comparison.peers + '개' : '평소 중앙값 대체 · 신뢰도 낮음'}</b></div>` : ''}
          ${p.tracking ? `<div>14일 추적<b>D+${p.tracking.day} · 성공 ${p.tracking.successful_observations}회${p.tracking.finalized_at ? ' · 종료' : ''}</b></div>` : ''}
        </div>
        ${p.flags.filter((f) => flagTxt[f]).length ? `<div class="flags">${p.flags.filter((f) => flagTxt[f]).map((f) => `<span class="flag">${flagTxt[f]}</span>`).join('')}</div>` : ''}
        <div class="fullcap">${esc(p.caption) || '(캡션 없음)'}</div>
        ${p.hashtags.length ? `<div class="tags">${p.hashtags.map((h) => `<span data-tag="${esc(h)}">#${esc(h)}</span>`).join('')}</div>` : ''}
        <div class="detail-actions">
          <a class="linkbtn secondary" href="${esc(p.url)}" target="_blank" rel="noopener">Instagram에서 보기 ↗</a>
          ${isVideo(p) ? `<button class="linkbtn source-download" id="source-download" data-code="${esc(p.shortcode)}">소스 영상 찾기·다운로드</button><button class="linkbtn secondary" id="transcript-extract">대본 추출</button>` : ''}
        </div>
        ${isVideo(p) ? '<div class="source-status" id="source-status" hidden></div><div class="source-status transcript-status" id="transcript-status" hidden></div>' : ''}
      </div></div>`;
    $$('.tags span', modal).forEach((s) => s.addEventListener('click', () => { closeDetail(); state.q = '#' + s.dataset.tag; $('#q').value = state.q; showSearch(true); renderAll(); }));
    const sourceBtn = $('#source-download', modal);
    if (sourceBtn) sourceBtn.addEventListener('click', () => startSourceJob(p.shortcode, sourceBtn));
    const transcriptBtn = $('#transcript-extract', modal);
    if (transcriptBtn) transcriptBtn.addEventListener('click', () => startTranscriptJob(p.shortcode, transcriptBtn));
    modal.hidden = false; document.body.style.overflow = 'hidden';
    if(isVideo(p))refreshProduction(p.shortcode);
  }

  async function startSourceJob(shortcode, button) {
    const status = $('#source-status', modal);
    button.disabled = true; status.hidden = false; status.classList.remove('error');
    status.innerHTML = '<b>준비 중…</b><div class="source-progress"><i style="width:2%"></i></div><small>최대 20개의 소스 영상을 찾습니다. 후보 수에 따라 시간이 오래 걸릴 수 있습니다.</small>';
    try {
      const response = await fetch('/api/source-jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shortcode }) });
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || '작업을 시작하지 못했습니다.');
      pollSourceJob(job.id, button, status);
    } catch (e) {
      status.classList.add('error'); status.textContent = '실패: ' + e.message; button.disabled = false;
    }
  }

  async function pollSourceJob(id, button, status) {
    try {
      const response = await fetch('/api/source-jobs/' + encodeURIComponent(id));
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || '상태를 확인하지 못했습니다.');
      if (job.status === 'error') throw new Error(job.error || '탐색 작업이 실패했습니다.');
      const notes = job.notes && job.notes.length ? `<small class="source-note">${job.notes.map(esc).join('<br>')}</small>` : '';
      const qc = job.quality_counts || {};
      const resultText = `${job.probe_attempts || job.probed_downloads || 0}개 시도 · ${job.probed_downloads || 0}개 수신 · 유효 후보 ${job.downloaded}개 · 클린 소스 ${qc['clean-source'] || 0} · 검토 필요 ${qc['light-overlay'] || 0} · OCR 미검증 ${qc.unknown || 0}`;
      status.innerHTML = `<b>${esc(job.message)}</b><div class="source-progress"><i style="width:${job.progress || 0}%"></i></div><small>${job.status === 'done' ? `${resultText}. ZIP에서 유형별 폴더로 구분했습니다.` : '모달을 닫아도 서버에서 계속 진행됩니다.'}</small>${notes}`;
      if (job.status === 'done') {
        button.disabled = false; button.textContent = '다시 탐색';
        const link = document.createElement('a'); link.className = 'linkbtn source-ready'; link.href = job.download_url;
        link.textContent = `ZIP 다운로드 (${job.downloaded}개)`; status.appendChild(link); return;
      }
      setTimeout(() => pollSourceJob(id, button, status), 1500);
    } catch (e) {
      status.classList.add('error'); status.textContent = '실패: ' + e.message; button.disabled = false;
    }
  }

  async function startTranscriptJob(shortcode, button) {
    const status = $('#transcript-status', modal);
    button.disabled = true; status.hidden = false; status.classList.remove('error');
    status.innerHTML = '<b>대본 추출 준비 중…</b><div class="source-progress"><i style="width:2%"></i></div><small>영상의 실제 음성과 화면 글자를 별도로 분석합니다.</small>';
    try {
      const response = await fetch('/api/transcript-jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shortcode }) });
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || '작업을 시작하지 못했습니다.');
      pollTranscriptJob(job.id, button, status);
    } catch (e) {
      status.classList.add('error'); status.textContent = '실패: ' + e.message; button.disabled = false;
    }
  }

  async function pollTranscriptJob(id, button, status) {
    try {
      const response = await fetch('/api/transcript-jobs/' + encodeURIComponent(id));
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || '상태를 확인하지 못했습니다.');
      if (job.status === 'error') throw new Error(job.error || '대본 추출에 실패했습니다.');
      if (job.status === 'done') {
        const lines = job.result.lines || [];
        const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
        status.innerHTML = `<b>대본 추출 완료 · 음성 ${job.result.speech.length}구간 · 화면 글자 ${job.result.screen_text.length}구간</b>
          <small>자동 인식 결과입니다. 화면 글자는 음성 대사로 간주하지 않습니다.</small>
          <div class="transcript-lines">${lines.length ? lines.map((line) => `<div class="transcript-line"><time>${clock(line.start)}</time><span class="transcript-tag">${line.source === 'speech' ? '음성' : '화면 글자'}</span><span>${esc(line.text)}</span></div>`).join('') : '<small>추출 가능한 대사나 화면 글자가 없습니다.</small>'}</div>
          <div class="detail-actions"><a class="linkbtn source-ready" href="${job.download_txt_url}">TXT 다운로드</a><a class="linkbtn secondary source-ready" href="${job.download_json_url}">JSON 다운로드</a></div>
          ${job.result.notes.map((note) => `<small class="source-note">${esc(note)}</small>`).join('')}`;
        button.disabled = false; button.textContent = '다시 추출'; return;
      }
      status.innerHTML = `<b>${esc(job.message || '분석 중…')}</b><div class="source-progress"><i style="width:${job.progress || 0}%"></i></div><small>모달을 닫아도 서버에서 계속 진행됩니다.</small>`;
      setTimeout(() => pollTranscriptJob(id, button, status), 1500);
    } catch (e) {
      status.classList.add('error'); status.textContent = '실패: ' + e.message; button.disabled = false;
    }
  }

  renderAll();
  const linkedPost = new URLSearchParams(location.search).get('post');
  if (linkedPost) openDetail(POSTS.find(p=>p.shortcode===linkedPost));
  let detectionDay = window.HotpostDetection.dateKey(Date.now() / 1000);
  setInterval(() => {
    const day = window.HotpostDetection.dateKey(Date.now() / 1000);
    if (day !== detectionDay) { detectionDay = day; renderAll(); }
  }, 60000);
})();
