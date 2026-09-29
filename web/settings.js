(async function () {
'use strict';
const $=s=>document.querySelector(s), $$=(s,el)=>Array.from((el||document).querySelectorAll(s));
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('ko-KR');
const R=window.HOTPOST_REPORT||{}, S=R.settings||{posts_per_account:30,maturity_hours:72};
window.HotpostDisplay.theme($('#theme-toggle'));
try {
const response=await fetch('/api/criteria');if(!response.ok)throw new Error('판정 기준을 불러오지 못했습니다.');
const active=await response.json(), DEFAULT=active.defaults;R.criteria=active;
let display=await window.HotpostDisplay.load();
const defaults=window.HotpostDisplay.defaults;
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

  function applyCriteria() { syncPanel(); $('#settings-status').textContent='변경사항을 저장해 주세요.'; }
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
      if (type === 'range') return `<div class="ctl"><label for="criterion-${key}">${label}</label><input id="criterion-${key}" type="range" data-k="${key}" min="${a}" max="${b}" step="${step}"><output data-o="${key}"></output></div>`;
      if (type === 'number') return `<div class="ctl" title="${a || ''}"><label for="criterion-${key}">${label}</label><input id="criterion-${key}" type="number" data-k="${key}" min="0" step="1"><span class="hint">${a ? '설명 보기' : ''}</span></div>`;
      if (type === 'select') return `<div class="ctl"><label for="criterion-${key}">${label}</label><select id="criterion-${key}" data-k="${key}">${a.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select><span></span></div>`;
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
        if (k === 't1') { C.t2 = Math.max(C.t1, C.t2); C.t3 = Math.max(C.t2, C.t3); }
        if (k === 't2') { C.t1 = Math.min(C.t1, C.t2); C.t3 = Math.max(C.t2, C.t3); }
        if (k === 't3') { C.t2 = Math.min(C.t2, C.t3); C.t1 = Math.min(C.t1, C.t2); }
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
  $('#presets').addEventListener('click', e => { const b=e.target.closest('button'); if(b){C={...DEFAULT,...PRESETS[b.dataset.preset]};applyCriteria();} });
  $('#method').innerHTML = `<ul>
    <li><b>기준은 절대 수치가 아니라 "그 계정의 평소 대비 배수"</b>입니다. 팔로워 규모가 달라도 공정하게 비교하기 위해, 계정마다 최근 ${S.posts_per_account}개 게시물(같은 유형 우선)의 <b>중앙값</b>을 평소 성과로 잡습니다.</li>
    <li>게시 후 ${S.maturity_hours}시간까지는 반응이 덜 쌓였으므로, 평소 성과를 35%→100% 로 점진 적용해 <b>신규 게시물이 불리하지 않게</b> 보정합니다(설정 페이지에서 끌 수 있음).</li>
    <li>종합 배수 = 각 지표 배수의 가중 기하평균. 가중치와 등급 기준 배수는 <b>⚙️ 판정 기준 조절</b> 패널에서 바꾸고 저장하면 서버에서 재계산됩니다.</li>
    <li>목록 순서는 배수를 기본으로 하되 절대 규모를 약간 반영해, 아주 작은 계정의 우연한 튐이 맨 위를 차지하지 않게 합니다.</li>
    <li>"댓글 급증"은 댓글이 평소 2.5배 이상일 때 표시합니다. 댓글은 조회수보다 <b>저장·공유·논쟁을 부르는 주제</b>를 잘 드러내므로 별도로 봅니다.</li>
    <li>핫 주제는 기준을 통과한 게시물을 주방·요리, 청소·세탁, 캠핑·여행 등 상위 카테고리로 묶습니다. 캡션과 해시태그의 구체적인 주제어를 사용하며, 분류 근거가 없으면 생활·기타로 표시합니다.</li>
    <li>수집을 반복하면 스냅샷이 쌓여 <b>시간당 증가 속도</b>가 상세 화면에 표시됩니다(📈 상승 중).</li>
  </ul>`;

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


const acc=$('#account');for(const a of R.accounts||[]){const o=new Option('@'+a.username,a.username);acc.add(o);}
if(display.account&&!Array.from(acc.options).some(o=>o.value===display.account))acc.add(new Option('@'+display.account+' (현재 목록에 없음)',display.account));
function syncDisplay(){
 $$('.seg').forEach(seg=>$$('button',seg).forEach(b=>{b.classList.toggle('on',String(display[seg.dataset.key])===b.dataset.v);b.setAttribute('aria-pressed',String(b.classList.contains('on')));b.disabled=seg.id==='period'&&display.detection==='today';}));
 for(const k of ['tier','sort','assessment','account'])$('#'+k).value=display[k];
}
$$('.seg').forEach(seg=>seg.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;display[seg.dataset.key]=seg.dataset.key==='period'?Number(b.dataset.v):b.dataset.v;syncDisplay();applyCriteria();}));
for(const k of ['tier','sort','assessment','account'])$('#'+k).addEventListener('change',e=>{display[k]=k==='tier'?Number(e.target.value):e.target.value;applyCriteria();});
$('#display-reset').onclick=()=>{display={...defaults};syncDisplay();applyCriteria();};
syncDisplay();syncPanel();$('#settings-status').textContent='현재 저장된 설정입니다.';$('#settings-save').disabled=false;
$('#settings-save').onclick=async()=>{
 const button=$('#settings-save');button.disabled=true;
 try{
  const response=await fetch('/api/criteria',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({values:C})});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'판정 기준 저장 실패');
  C={...data.criteria.values};syncPanel();
  await window.HotpostDisplay.save(display);
  $('#settings-status').textContent='저장했습니다. 터진 게시물 페이지에서 변경된 결과를 확인하세요.';
 }catch(e){$('#settings-status').textContent=e.message;}
 finally{button.disabled=false;}
};
}catch(e){$('#settings-status').textContent='설정 확인 실패: '+e.message;}
})();
