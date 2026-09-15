/* 오늘의 터진 게시물 - 서버 판정 결과를 표시하고 기준을 저장한다. */
(function () {
  'use strict';
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const R = window.HOTPOST_REPORT;

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
  const W = R.weights || { video: { views: .5, comments: .3, likes: .2 }, image: { likes: .6, comments: .4 } };
  const DEFAULT = R.criteria_defaults || {
    t1: S.hot_multiplier, t2: S.tier2_multiplier, t3: S.tier3_multiplier,
    wvViews: W.video.views * 100, wvComments: W.video.comments * 100, wvLikes: W.video.likes * 100,
    wiLikes: W.image.likes * 100, wiComments: W.image.comments * 100,
    minRatioViews: 0, minRatioComments: 0, minRatioLikes: 0,
    minViews: 0, minComments: 0, minLikes: 0, minEng: S.min_engagement || 20,
    followersMin: 0, followersMax: 0, confidence: 'all', maturity: true,
  };
  if (!R.criteria) R.criteria = { version: 0, values: DEFAULT };
  const PRESETS = {
    default: {},
    comments: { wvViews: 25, wvComments: 55, wvLikes: 20, wiLikes: 40, wiComments: 60, minRatioComments: 1.5 },
    views: { wvViews: 70, wvComments: 15, wvLikes: 15, minRatioViews: 1.5 },
    strict: { t1: 2.5, t2: 4, t3: 7, minEng: 100, confidence: 'medium' },
    loose: { t1: 1.4, t2: 2.2, t3: 3.5, minEng: 10 },
  };
  let C = Object.assign({}, R.criteria.values);
  const norm3 = (a, b, c) => { const s = a + b + c || 1; return [a / s, b / s, c / s]; };
  const norm2 = (a, b) => { const s = a + b || 1; return [a / s, b / s]; };

  let POSTS = [];
  function recompute() { POSTS = R.posts.slice(); }
  async function saveCriteria(values) {
    const response = await fetch('/api/criteria', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ values }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '판정 기준 저장 실패');
    Object.assign(R, data.report);
    C = Object.assign({}, data.criteria.values);
    syncPanel(); renderAll();
    $('#meta').textContent = `${R.generated_at_kst} 기준 · 판정 v${data.criteria.version} · ${R.summary.accounts}개 계정 · 최근 ${S.recent_days}일 게시물 ${R.posts.length}개 분석`;
  }
  let criteriaQueue = Promise.resolve();
  function applyCriteria() {
    syncPanel();
    const values = Object.assign({}, C);
    criteriaQueue = criteriaQueue.catch(() => {}).then(() => saveCriteria(values));
    criteriaQueue.catch((error) => { $('#crit-count').textContent = error.message; });
  }

  // ---------- 기준 패널 UI ----------
  const critBody = $('#crit-body');
  const CONTROLS = [
    ['등급 기준 배수', '평소 대비 종합 배수가 이 값 이상이면 해당 등급', [
      ['t1', '🔥 이상', 'range', 1.1, 6, 0.1], ['t2', '🔥🔥 이상', 'range', 1.5, 10, 0.1], ['t3', '🔥🔥🔥 이상', 'range', 2, 20, 0.5]]],
    ['릴스 가중치', '조회수·댓글·좋아요 배수를 어떤 비율로 합칠지', [
      ['wvViews', '조회수', 'range', 0, 100, 5], ['wvComments', '댓글', 'range', 0, 100, 5], ['wvLikes', '좋아요', 'range', 0, 100, 5], ['__wbar_v']]],
    ['사진·캐러셀 가중치', '', [
      ['wiLikes', '좋아요', 'range', 0, 100, 5], ['wiComments', '댓글', 'range', 0, 100, 5], ['__wbar_i']]],
    ['개별 지표 최소 배수', '0 이면 미적용. 예: 댓글이 평소 2배 이상인 것만', [
      ['minRatioViews', '조회수 ≥', 'range', 0, 10, 0.5], ['minRatioComments', '댓글 ≥', 'range', 0, 10, 0.5], ['minRatioLikes', '좋아요 ≥', 'range', 0, 10, 0.5]]],
    ['절대 최소값', '평소 대비가 아니라 실제 수치 기준. 0 이면 미적용', [
      ['minViews', '최소 조회수', 'number'], ['minComments', '최소 댓글', 'number'], ['minLikes', '최소 좋아요', 'number'],
      ['minEng', '노이즈 컷', 'number', '좋아요 + 댓글×5 + 조회수/50 이 이 값 미만이면 등급을 주지 않음']]],
    ['계정·신뢰도', '', [
      ['followersMin', '팔로워 ≥', 'number'], ['followersMax', '팔로워 ≤', 'number'],
      ['confidence', '신뢰도', 'select', [['all', '전체'], ['medium', '보통 이상'], ['high', '높음만']]],
      ['maturity', '신규 게시물 보정', 'check', '게시 72시간 미만은 기준선을 낮춰 비교']]],
  ];
  function buildPanel() {
    critBody.innerHTML = CONTROLS.map(([title, desc, ctls]) => `<div class="cg"><h4>${title}${desc ? `<small>${desc}</small>` : ''}</h4>` + ctls.map((c) => {
      const [key, label, type, a, b, step] = c;
      if (key === '__wbar_v') return `<div class="wbar" id="wbar-v"></div><div class="wlegend"><span><i style="background:var(--accent)"></i>조회수</span><span><i style="background:var(--mid)"></i>댓글</span><span><i style="background:var(--flat)"></i>좋아요</span></div>`;
      if (key === '__wbar_i') return `<div class="wbar" id="wbar-i"></div><div class="wlegend"><span><i style="background:var(--accent)"></i>좋아요</span><span><i style="background:var(--mid)"></i>댓글</span></div>`;
      if (type === 'range') return `<div class="ctl"><label>${label}</label><input type="range" data-k="${key}" min="${a}" max="${b}" step="${step}"><output data-o="${key}"></output></div>`;
      if (type === 'number') return `<div class="ctl" title="${a || ''}"><label>${label}</label><input type="number" data-k="${key}" min="0" step="1"><span class="hint">${a ? '설명 보기' : ''}</span></div>`;
      if (type === 'select') return `<div class="ctl"><label>${label}</label><select data-k="${key}">${a.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select><span></span></div>`;
      if (type === 'check') return `<label class="toggle" title="${a}"><input type="checkbox" data-k="${key}"> ${label}</label>`;
      return '';
    }).join('') + '</div>').join('') +
      `<div class="crit-foot"><span id="crit-count"></span><button class="btn ghost" id="crit-reset">기본값으로 되돌리기</button></div>`;
    $$('[data-k]', critBody).forEach((el) => {
      const k = el.dataset.k;
      const handler = () => {
        if (el.type === 'checkbox') C[k] = el.checked;
        else if (el.tagName === 'SELECT') C[k] = el.value;
        else C[k] = +el.value || 0;
        if (k === 't1' && C.t2 < C.t1) C.t2 = C.t1;
        if (k === 't2' && C.t3 < C.t2) C.t3 = C.t2;
        applyCriteria();
      };
      el.addEventListener('change', handler);
    });
    $('#crit-reset').addEventListener('click', () => { C = Object.assign({}, DEFAULT); applyCriteria(); });
  }
  function syncPanel() {
    $$('[data-k]', critBody).forEach((el) => { const k = el.dataset.k; if (el.type === 'checkbox') el.checked = !!C[k]; else el.value = C[k]; });
    $$('output[data-o]', critBody).forEach((o) => { const k = o.dataset.o; o.textContent = k.startsWith('w') ? Math.round(C[k]) + '%' : C[k].toFixed(1) + '배'; });
    const [a, b, c] = norm3(C.wvViews, C.wvComments, C.wvLikes);
    $('#wbar-v').innerHTML = `<span class="w1" style="width:${a * 100}%"></span><span class="w2" style="width:${b * 100}%"></span><span class="w3" style="width:${c * 100}%"></span>`;
    const [d, e] = norm2(C.wiLikes, C.wiComments);
    $('#wbar-i').innerHTML = `<span class="w1" style="width:${d * 100}%"></span><span class="w2" style="width:${e * 100}%"></span>`;
    const [v1, v2, v3] = [a, b, c].map((x) => Math.round(x * 100));
    const extras = [];
    if (C.minRatioViews) extras.push(`조회수 ≥×${C.minRatioViews}`);
    if (C.minRatioComments) extras.push(`댓글 ≥×${C.minRatioComments}`);
    if (C.minRatioLikes) extras.push(`좋아요 ≥×${C.minRatioLikes}`);
    if (C.minViews) extras.push(`조회 ${fmt(C.minViews)}+`);
    if (C.minComments) extras.push(`댓글 ${fmt(C.minComments)}+`);
    if (C.minLikes) extras.push(`좋아요 ${fmt(C.minLikes)}+`);
    if (C.followersMin || C.followersMax) extras.push(`팔로워 ${C.followersMin ? fmt(C.followersMin) : '0'}~${C.followersMax ? fmt(C.followersMax) : '∞'}`);
    if (C.confidence !== 'all') extras.push(`신뢰도 ${C.confidence === 'high' ? '높음' : '보통+'}`);
    if (!C.maturity) extras.push('신규 보정 끔');
    $('#crit-summary').innerHTML = `<b>🔥 ×${C.t1.toFixed(1)}</b> · 🔥🔥 ×${C.t2.toFixed(1)} · 🔥🔥🔥 ×${C.t3.toFixed(1)} · 릴스 조회${v1}/댓글${v2}/좋아요${v3}${extras.length ? ' · ' + extras.join(' · ') : ''}`;
    const activePreset = Object.keys(PRESETS).find((k) => { const P = Object.assign({}, DEFAULT, PRESETS[k]); return Object.keys(DEFAULT).every((x) => P[x] === C[x]); });
    $$('#presets button').forEach((btn) => btn.classList.toggle('on', btn.dataset.preset === activePreset));
  }
  buildPanel();
  $('#crit-toggle').addEventListener('click', () => {
    const open = critBody.hidden; critBody.hidden = !open;
    $('#crit-toggle').setAttribute('aria-expanded', String(open));
    $('#crit-toggle').textContent = open ? '⚙️ 판정 기준 닫기' : '⚙️ 판정 기준 조절';
  });
  $('#presets').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; C = Object.assign({}, DEFAULT, PRESETS[b.dataset.preset]); applyCriteria(); });

  // ---------- 헤더 / 배너 ----------
  $('#meta').textContent = `${R.generated_at_kst} 기준 · 판정 v${R.criteria.version} · ${R.summary.accounts}개 계정 · 최근 ${S.recent_days}일 게시물 ${R.posts.length}개 분석`;
  const sb = $('#source-badge');
  if (R.is_sample) { sb.textContent = '샘플 데이터'; sb.classList.add('sample'); }
  else { sb.textContent = { instaloader: '실데이터 · 세션 수집', web: '실데이터 · 웹 수집', dump: '실데이터 · 브라우저 덤프' }[R.source] || '실데이터'; sb.classList.add('live'); }
  if (R.is_sample) { const b = $('#banner'); b.hidden = false; b.innerHTML = '⚠️ 지금 보고 있는 것은 <b>생성된 샘플 데이터</b>입니다. 실제 데이터를 보려면 <code>python -m hotpost login --user 아이디 --browser chrome</code> 로 세션을 만든 뒤 <code>python -m hotpost run</code> 을 실행하세요.'; }
  else if (R.notes && R.notes.length) { const b = $('#banner'); b.hidden = false; b.innerHTML = '⚠️ 일부 계정 수집 실패: ' + R.notes.map(esc).join(' / '); }

  // ---------- 상태 ----------
  const state = { period: 336, kind: 'all', tier: 1, sort: 'rank', account: '', q: '', topic: null };

  // ---------- 툴바 ----------
  $$('.seg').forEach((seg) => seg.addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    $$('button', seg).forEach((x) => x.classList.toggle('on', x === b));
    state[seg.dataset.key] = seg.dataset.key === 'period' ? +b.dataset.v : b.dataset.v; renderAll();
  }));
  $('#tier').addEventListener('change', (e) => { state.tier = +e.target.value; render(); });
  $('#sort').addEventListener('change', (e) => { state.sort = e.target.value; render(); });
  const accSel = $('#account');
  R.accounts.slice().sort((a, b) => a.username.localeCompare(b.username)).forEach((a) => { const o = document.createElement('option'); o.value = a.username; o.textContent = '@' + a.username; accSel.appendChild(o); });
  accSel.addEventListener('change', (e) => { state.account = e.target.value; renderAll(); });
  let qt; $('#q').addEventListener('input', (e) => { clearTimeout(qt); qt = setTimeout(() => { state.q = e.target.value.trim().toLowerCase(); renderAll(); }, 150); });
  $('#reset').addEventListener('click', () => {
    Object.assign(state, { period: 336, kind: 'all', tier: 1, sort: 'rank', account: '', q: '', topic: null });
    $$('#period button').forEach((b) => b.classList.toggle('on', b.dataset.v === '336'));
    $$('#kind button').forEach((b) => b.classList.toggle('on', b.dataset.v === 'all'));
    $('#tier').value = '1'; $('#sort').value = 'rank'; accSel.value = ''; $('#q').value = ''; renderAll();
  });

  // ---------- 필터 ----------
  function baseFiltered() {   // 기간·유형·계정·검색 (등급/주제 제외) → 주제 계산용
    const q = state.q;
    return POSTS.filter((p) => {
      if (p.age_hours > state.period) return false;
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
      if (state.topic) {
        const t = state.topic;
        const hit = t.startsWith('#') ? p.hashtags.includes(t.slice(1).toLowerCase()) : ((p.terms || []).includes(t) || p.caption.toLowerCase().includes(t));
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
    const TW = { 0: 0.15, 1: 1, 2: 2, 3: 3 };
    const weight = new Map(), accounts = new Map(), posts = new Map(), kind = new Map(), seenAcc = new Set();
    const bump = (key, w, p, k) => {
      weight.set(key, (weight.get(key) || 0) + w);
      if (!accounts.has(key)) accounts.set(key, new Set());
      accounts.get(key).add(p.username);
      posts.set(key, (posts.get(key) || 0) + 1);
      if (!kind.has(key)) kind.set(key, k);
    };
    base.slice().sort((a, b) => b.multiplier - a.multiplier).forEach((p) => {
      const w = TW[p.tier];
      new Set(p.hashtags).forEach((h) => { if (h !== p.username.toLowerCase()) bump('#' + h, w, p, 'hashtag'); });
      (p.terms || []).forEach((t) => {
        const k = p.username + ' ' + t;
        if (seenAcc.has(k)) bump(t, w * 0.1, p, 'keyword');
        else { seenAcc.add(k); bump(t, w * (t.includes(' ') ? 1.1 : 0.8), p, 'keyword'); }
      });
    });
    return Array.from(weight.entries()).sort((a, b) => b[1] - a[1])
      .filter(([k, w]) => { const n = accounts.get(k).size; return !(kind.get(k) === 'keyword' && n < 2) && !(w < 1 && n < 2); })
      .slice(0, 24).map(([k, w]) => ({ label: k, kind: kind.get(k), score: w, posts: posts.get(k), accounts: accounts.get(k).size }));
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
      el.addEventListener('click', () => { state.topic = state.topic === t.label ? null : t.label; if (state.topic) { state.tier = 0; $('#tier').value = '0'; } renderAll(); });
      topicsEl.appendChild(el);
    });
  }

  // ---------- 통계 ----------
  function renderStats() {
    const hot = POSTS.filter((p) => p.tier >= 1);
    $('#stats').innerHTML = [
      ['hot', '🔥 터진 게시물', hot.length, `/ ${POSTS.length}개`],
      ['hot', '최근 24시간', hot.filter((p) => p.age_hours <= 24).length, '개'],
      ['hot', '최근 7일', hot.filter((p) => p.age_hours <= 168).length, '개'],
      ['', '분석 계정', R.summary.accounts, '개'],
      ['', '릴스 비중', Math.round((POSTS.filter(isVideo).length / Math.max(1, POSTS.length)) * 100), '%'],
    ].map(([c, k, v, u]) => `<div class="stat ${c}"><div class="k">${k}</div><div class="v">${v}<small>${u}</small></div></div>`).join('');
  }

  // ---------- 카드 ----------
  function metric(label, val, ratio, na) {
    return `<div class="m ${na ? 'na' : ''}"><div class="k">${label}</div><div class="v">${na ? '–' : fmt(val)}</div><div class="r ${ratioCls(ratio)}">${na ? '' : ratioTxt(ratio) + (ratio != null ? ' 평소 대비' : '')}</div></div>`;
  }
  function card(p, i) {
    const flags = p.flags.filter((f) => flagTxt[f]).map((f) => `<span class="flag ${f === 'fresh' ? 'neutral' : ''}">${flagTxt[f]}</span>`).join('');
    const thumb = p.thumb ? `<img loading="lazy" src="${esc(p.thumb)}" alt="">` : `<div class="ph">${isVideo(p) ? '🎬' : '🖼'}</div>`;
    return `<article class="card" data-code="${esc(p.shortcode)}">
      <div class="thumb">${thumb}
        <div class="tl">${p.tier ? `<span class="pill t${p.tier}">${tierTxt(p.tier)} ×${p.multiplier.toFixed(1)}</span>` : `<span class="pill">×${p.multiplier.toFixed(1)}</span>`}</div>
        <div class="tr"><span class="pill kind">${kindTxt(p.kind)}${p.video_duration ? ' · ' + Math.round(p.video_duration) + 's' : ''}</span></div>
        <div class="rank">#${i + 1}</div>
      </div>
      <div class="body">
        <div class="who"><span class="avatar">${initials(p.username)}</span><span class="name">@${esc(p.username)}</span><span class="time" title="${dateStr(p.taken_at)}">${ago(p.age_hours)}</span></div>
        <div class="metrics">
          ${metric('조회수', p.views, p.ratios.views, !isVideo(p) || p.views == null)}
          ${metric('좋아요', p.likes, p.ratios.likes, false)}
          ${metric('댓글', p.comments, p.ratios.comments, false)}
        </div>
        <div class="cap">${esc(p.caption.replace(/#\S+/g, '').trim()) || '<span class="hint">(캡션 없음)</span>'}</div>
        ${flags ? `<div class="flags">${flags}</div>` : ''}
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
    if (!current.length) emp.textContent = state.tier > 0 ? '조건에 맞는 터진 게시물이 없습니다. 기간을 늘리거나 판정 기준을 낮춰 보세요.' : '조건에 맞는 게시물이 없습니다.';
    const desc = [state.period <= 24 ? '24시간' : state.period / 24 + '일', state.kind === 'all' ? '' : state.kind === 'video' ? '릴스' : '사진', state.tier ? tierTxt(state.tier) + ' 이상' : '전체', state.account ? '@' + state.account : '', state.topic ? '주제 "' + state.topic + '"' : ''].filter(Boolean).join(' · ');
    $('#result-count').textContent = `${current.length}개 · ${desc}`;
    const hotBase = base.filter((p) => p.tier >= 1).length;
    $('#crit-count').innerHTML = `현재 기준으로 선택 기간에 <b>🔥 ${hotBase}개</b> / ${base.length}개 · 전체 기간 🔥 ${POSTS.filter((p) => p.tier >= 1).length}개 / ${POSTS.length}개`;
    return base;
  }
  function renderAll() { recompute(); renderStats(); const base = render(); renderTopics(base); renderTable(); }

  // ---------- 플랫폼 로그인 관리 ----------
  const sessionModal = $('#session-modal');
  const sessionStart = $('#session-start');
  const sessionFinish = $('#session-finish');
  let sessionPoll = null;
  function closeSessionModal() { sessionModal.hidden = true; if (sessionPoll) clearTimeout(sessionPoll); sessionPoll = null; }
  $$('[data-session-close]', sessionModal).forEach((el) => el.addEventListener('click', closeSessionModal));
  $('#platform-login').addEventListener('click', () => { sessionModal.hidden = false; refreshPlatformSession(); });
  function renderPlatformSession(data) {
    $('#session-platforms').innerHTML = (data.platforms || []).map((p) =>
      `<div class="session-platform">${esc(p.label)}<span class="${p.connected ? 'connected' : ''}">${p.connected ? '● 인증 확인' : p.cookie_present ? '◐ 쿠키 있음 · ' + esc(p.auth_status || '미검증') : '○ 로그인 필요'}</span></div>`).join('');
    const status = $('#session-status');
    status.classList.toggle('error', Boolean(data.error));
    status.innerHTML = `<b>${esc(data.error || data.message || '상태 확인 완료')}</b><small>${data.cookie_file_ready ? '다운로드용 쿠키 파일 준비됨' : '로그인 창에서 인증하면 다운로드용 쿠키가 생성됩니다.'}</small>`;
    sessionStart.hidden = Boolean(data.active);
    sessionFinish.hidden = !data.active;
  }
  async function refreshPlatformSession() {
    try {
      const response = await fetch('/api/platform-session'); const data = await response.json();
      if (!response.ok) throw new Error(data.error || '로그인 상태 확인 실패');
      renderPlatformSession(data);
      if (data.active && !sessionModal.hidden) sessionPoll = setTimeout(refreshPlatformSession, 1800);
    } catch (e) { $('#session-status').classList.add('error'); $('#session-status').textContent = e.message; }
  }
  sessionStart.addEventListener('click', async () => {
    sessionStart.disabled = true;
    try {
      const response = await fetch('/api/platform-session', { method: 'POST' }); const data = await response.json();
      if (!response.ok) throw new Error(data.error || '로그인 창 실행 실패');
      renderPlatformSession(data); sessionPoll = setTimeout(refreshPlatformSession, 1200);
    } catch (e) { $('#session-status').classList.add('error'); $('#session-status').textContent = e.message; }
    finally { sessionStart.disabled = false; }
  });
  sessionFinish.addEventListener('click', async () => {
    sessionFinish.disabled = true;
    try { await fetch('/api/platform-session/finish', { method: 'POST' }); setTimeout(refreshPlatformSession, 800); }
    finally { sessionFinish.disabled = false; }
  });

  // ---------- 상세 모달 ----------
  const modal = $('#modal');
  $('#cards').addEventListener('click', (e) => { const c = e.target.closest('.card'); if (c) openDetail(POSTS.find((p) => p.shortcode === c.dataset.code)); });
  modal.addEventListener('click', (e) => { if (e.target.dataset.close !== undefined) closeDetail(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDetail(); });
  function closeDetail() { modal.hidden = true; document.body.style.overflow = ''; }
  function bar(label, val, base, ratio) {
    if (val == null) return '';
    const max = Math.max(val, base || 0, 1);
    return `<div class="row"><span>${label}</span><div class="track"><div class="fill" style="width:${(val / max) * 100}%"></div>${base ? `<div class="base" style="left:${(base / max) * 100}%"></div>` : ''}</div><div class="num">${fmt(val)} <small>/ 평소 ${fmt(base)}</small><br><span class="r ${ratioCls(ratio)}">${ratioTxt(ratio)}</span></div></div>`;
  }
  function openDetail(p) {
    if (!p) return;
    const a = acctMap[p.username] || {}, v = p.velocity;
    $('#modal-body').innerHTML = `<div class="detail">
      <div class="thumb">${p.thumb ? `<img src="${esc(p.thumb)}" alt="">` : `<div class="ph">${isVideo(p) ? '🎬' : '🖼'}</div>`}</div>
      <div class="detail-body">
        <div class="who"><span class="avatar">${initials(p.username)}</span><span class="name">@${esc(p.username)}</span>${a.full_name ? `<span class="fn">${esc(a.full_name)}</span>` : ''}<span class="time">${dateStr(p.taken_at)} (${ago(p.age_hours)})</span></div>
        <h3>${tierTxt(p.tier) || '—'} 평소 대비 ×${p.multiplier.toFixed(1)} <small class="hint">${kindTxt(p.kind)}</small></h3>
        <div class="cmp">
          ${isVideo(p) ? bar('조회수', p.views, p.baseline.views, p.ratios.views) : ''}
          ${bar('좋아요', p.likes, p.baseline.likes, p.ratios.likes)}
          ${bar('댓글', p.comments, p.baseline.comments, p.ratios.comments)}
        </div>
        <div class="kv">
          <div>팔로워<b>${fmt(a.followers)}</b></div>
          <div>비교 게시물<b>${p.baseline.peers}개</b></div>
          <div>반응 성숙도<b>${Math.round((C.maturity ? p.maturity : 1) * 100)}%</b></div>
          <div>신뢰도<b>${confTxt[p.confidence]}</b></div>
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
    $$('.tags span', modal).forEach((s) => s.addEventListener('click', () => { closeDetail(); state.q = '#' + s.dataset.tag; $('#q').value = state.q; state.tier = 0; $('#tier').value = '0'; renderAll(); }));
    const sourceBtn = $('#source-download', modal);
    if (sourceBtn) sourceBtn.addEventListener('click', () => startSourceJob(p.shortcode, sourceBtn));
    const transcriptBtn = $('#transcript-extract', modal);
    if (transcriptBtn) transcriptBtn.addEventListener('click', () => startTranscriptJob(p.shortcode, transcriptBtn));
    modal.hidden = false; document.body.style.overflow = 'hidden';
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
      const resultText = `${job.probed_downloads || 0}개를 검사해 유효 후보 ${job.downloaded}개 · 클린 소스 ${qc['clean-source'] || 0} · 검토 필요 ${qc['light-overlay'] || 0} · 자막 포함 ${qc['edited-with-text'] || 0}`;
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

  // ---------- 계정 표 ----------
  const accountSummaryBody = $('#accounts-summary-body');
  const accountSummaryToggle = $('#accounts-summary-toggle');
  let accountSummaryCollapsed = store.get('hp-accounts-summary-collapsed', false);
  function syncAccountSummary() {
    accountSummaryBody.hidden = accountSummaryCollapsed;
    accountSummaryToggle.setAttribute('aria-expanded', String(!accountSummaryCollapsed));
    accountSummaryToggle.textContent = accountSummaryCollapsed ? '펼치기 ▾' : '접기 ▴';
  }
  accountSummaryToggle.addEventListener('click', () => {
    accountSummaryCollapsed = !accountSummaryCollapsed;
    store.set('hp-accounts-summary-collapsed', accountSummaryCollapsed); syncAccountSummary();
  });
  syncAccountSummary();

  const cols = [
    ['username', '계정', (a) => `<div class="who"><span class="avatar">${initials(a.username)}</span><span class="name">@${esc(a.username)}</span>${a.full_name ? `<span class="fn">${esc(a.full_name)}</span>` : ''}</div>`],
    ['followers', '팔로워', (a) => fmt(a.followers)],
    ['median_views', '평소 조회수', (a) => (a.median_views ? fmt(a.median_views) : '–')],
    ['median_likes', '평소 좋아요', (a) => fmt(a.median_likes)],
    ['median_comments', '평소 댓글', (a) => fmt(a.median_comments)],
    ['reel_share', '릴스 비중', (a) => Math.round(a.reel_share * 100) + '%'],
    ['hot_7d', '🔥 7일', (a) => `<span class="hotn">${a.hot_7d}</span>`],
    ['hot_recent', `🔥 ${S.recent_days}일`, (a) => `<span class="bar" style="width:${Math.min(60, a.hot_recent * 8)}px"></span>${a.hot_recent} / ${a.posts_recent}`],
    ['last_post_at', '최근 게시', (a) => ago((R.generated_at - a.last_post_at) / 3600)],
  ];
  let sortCol = 'hot_recent', sortDir = -1;
  function renderTable() {
    const rows = R.accounts.map((a) => {
      const mine = POSTS.filter((p) => p.username === a.username);
      return Object.assign({}, a, { posts_recent: mine.length, hot_recent: mine.filter((p) => p.tier >= 1).length, hot_7d: mine.filter((p) => p.tier >= 1 && p.age_hours <= 168).length });
    }).sort((a, b) => { const x = a[sortCol], y = b[sortCol]; return (typeof x === 'string' ? x.localeCompare(y) : (x || 0) - (y || 0)) * sortDir; });
    $('#accounts').innerHTML = `<thead><tr>${cols.map(([k, l]) => `<th data-k="${k}" class="${k === sortCol ? 'on' : ''}">${l}${k === sortCol ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('')}</tr></thead>` +
      `<tbody>${rows.map((a) => `<tr class="acc ${state.account === a.username ? 'on' : ''}" data-u="${esc(a.username)}">${cols.map(([, , f]) => `<td>${f(a)}</td>`).join('')}</tr>`).join('')}</tbody>`;
  }
  $('#accounts').addEventListener('click', (e) => {
    const th = e.target.closest('th'); if (th) { if (sortCol === th.dataset.k) sortDir *= -1; else { sortCol = th.dataset.k; sortDir = -1; } renderTable(); return; }
    const tr = e.target.closest('tr.acc'); if (tr) { state.account = state.account === tr.dataset.u ? '' : tr.dataset.u; accSel.value = state.account; state.tier = 0; $('#tier').value = '0'; renderAll(); $('#cards').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });

  // ---------- 방법론 ----------
  $('#method').innerHTML = `<ul>
    <li><b>기준은 절대 수치가 아니라 "그 계정의 평소 대비 배수"</b>입니다. 팔로워 규모가 달라도 공정하게 비교하기 위해, 계정마다 최근 ${S.posts_per_account}개 게시물(같은 유형 우선)의 <b>중앙값</b>을 평소 성과로 잡습니다.</li>
    <li>게시 후 ${S.maturity_hours}시간까지는 반응이 덜 쌓였으므로, 평소 성과를 35%→100% 로 점진 적용해 <b>신규 게시물이 불리하지 않게</b> 보정합니다(판정 기준 패널에서 끌 수 있음).</li>
    <li>종합 배수 = 각 지표 배수의 가중 기하평균. 가중치와 등급 기준 배수는 <b>⚙️ 판정 기준 조절</b> 패널에서 바꾸면 즉시 재계산되고 브라우저에 저장됩니다.</li>
    <li>목록 순서는 배수를 기본으로 하되 절대 규모를 약간 반영해, 아주 작은 계정의 우연한 튐이 맨 위를 차지하지 않게 합니다.</li>
    <li>"댓글 급증"은 댓글이 평소 2.5배 이상일 때 표시합니다. 댓글은 조회수보다 <b>저장·공유·논쟁을 부르는 주제</b>를 잘 드러내므로 별도로 봅니다.</li>
    <li>"오늘의 핫 주제"는 선택한 기간·유형·계정 안의 게시물에서 해시태그와 캡션 명사(형태소 분석, 상용구 제거)를 등급 가중치(🔥1 · 🔥🔥2 · 🔥🔥🔥3)로 합산한 것입니다. 점선 칩은 캡션 키워드, 실선 칩은 해시태그입니다.</li>
    <li>수집을 반복하면 스냅샷이 쌓여 <b>시간당 증가 속도</b>가 상세 화면에 표시됩니다(📈 상승 중).</li>
  </ul>`;

  syncPanel();
  renderAll();
  fetch('/api/criteria').then((response) => response.json()).then((active) => {
    if (!active.values) return;
    if (active.version !== R.criteria.version) {
      C = Object.assign({}, active.values);
      applyCriteria();
    } else {
      C = Object.assign({}, active.values);
      syncPanel();
    }
  }).catch((error) => { $('#crit-count').textContent = `판정 기준 조회 실패: ${error.message}`; });
})();
