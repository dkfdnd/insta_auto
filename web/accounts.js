(function () {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value || '').replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
  const fmt = (value) => Number(value || 0).toLocaleString('ko-KR');
  const date = (timestamp) => timestamp ? new Date(timestamp * 1000).toLocaleDateString('ko-KR') : '수집 전';
  let accounts = [];
  const report=window.HOTPOST_REPORT||{};
  const summaries=new Map((report.accounts||[]).map(a=>[a.username,a]));

  const theme = $('#accounts-theme');
  function applyTheme(value) {
    if (value) document.documentElement.dataset.theme = value;
    const current = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    theme.textContent = current === 'dark' ? '☀️' : '🌙';
  }
  let savedTheme = '';
  try { savedTheme = localStorage.getItem('hp-theme') ? JSON.parse(localStorage.getItem('hp-theme')) : ''; } catch (error) {}
  applyTheme(savedTheme);
  theme.addEventListener('click', () => {
    const current = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next; localStorage.setItem('hp-theme', JSON.stringify(next)); applyTheme(next);
  });

  function message(text, error) {
    const el = $('#account-message'); el.hidden = false; el.textContent = text; el.classList.toggle('error', Boolean(error));
  }

  function render() {
    $('#account-count').textContent = accounts.length;
    const list = $('#account-list');
    if (!accounts.length) {
      list.innerHTML = '<div class="empty">아직 관리 중인 계정이 없습니다. 위에서 첫 계정을 등록하세요.</div>'; return;
    }
    list.innerHTML = accounts.map((account) => {const summary=summaries.get(account.username);const candidates=(report.acquisition_candidates||[]).filter(p=>p.username===account.username);return `<article class="account-row" data-username="${esc(account.username)}">
      <div class="account-avatar">${account.profile_pic_url ? `<img src="${esc(account.profile_pic_url)}" alt="">` : esc(account.username.slice(0, 2).toUpperCase())}</div>
      <div class="account-main">
        <div><a href="https://www.instagram.com/${encodeURIComponent(account.username)}/" target="_blank" rel="noopener">@${esc(account.username)} ↗</a>${account.full_name ? `<span>${esc(account.full_name)}</span>` : ''}</div>
        <p>${account.note ? esc(account.note) : '<span class="hint">메모 없음</span>'}</p>
      </div>
      <div class="account-stats"><span>팔로워 <b>${fmt(account.followers)}</b></span><span>수집 게시물 <b>${fmt(account.posts_count)}</b></span><span>최근 게시 <b>${date(account.last_post_at)}</b></span>
        <span>조회 누락 <b>${Math.round((account.views_missing_rate || 0) * 100)}%</b></span>
        <span>최근 조회 성공 <b>${account.recent_success_rate == null ? '데이터 없음' : Math.round(account.recent_success_rate * 100) + '%'}</b></span>
        <span>마지막 성공 조회 <b>${date(account.last_success_observed_at)}</b></span>
        <span>연속 수집 실패 <b>${account.consecutive_failures || 0}회</b></span></div>
      <div class="account-performance">${summary?`<span>평소 조회수 <b>${fmt(summary.median_views)}</b></span><span>평소 좋아요 <b>${fmt(summary.median_likes)}</b></span><span>평소 댓글 <b>${fmt(summary.median_comments)}</b></span><span>릴스 비중 <b>${Math.round(summary.reel_share*100)}%</b></span><span>7일 핫 <b>${summary.hot_7d}개</b></span><span>최근 ${report.settings?.recent_days||30}일 핫 <b>${summary.hot_recent} / ${summary.posts_recent}개</b></span>`:'<span class="hint">분석 결과 없음 · 수집 후 성과가 표시됩니다.</span>'}<a href="/?account=${encodeURIComponent(account.username)}">이 계정 게시물 보기 →</a></div>
      ${candidates.length?`<details class="account-candidates"><summary>팔로워 대비 조회수 · 제작 후보 ${candidates.length}개</summary><p class="hint">참고 후보입니다. 자동 제작 선정과는 별개입니다.</p><div class="chips">${candidates.map(p=>`<a class="chip" href="/?post=${encodeURIComponent(p.shortcode)}">${esc(p.shortcode)} · 팔로워 대비 ${Number(p.views_per_follower).toFixed(2)}배 · 조회 ${fmt(p.views)}</a>`).join('')}</div></details>`:''}
      <button class="btn account-delete" data-delete="${esc(account.username)}">삭제</button>
    </article>`;}).join('');
  }

  async function loadAccounts() {
    const list = $('#account-list');
    try {
      const response = await fetch('/api/accounts'); const data = await response.json();
      if (!response.ok) throw new Error(data.error || '계정 목록을 가져오지 못했습니다.');
      accounts = data.accounts || []; render();
    } catch (error) { list.innerHTML = `<div class="empty error">${esc(error.message)}</div>`; }
  }

  async function loadCollectionStatus() {
    try {
      const response = await fetch('/api/collection-status'); const data = await response.json();
      if (!response.ok) throw new Error(data.error || '수집 상태 확인 실패');
      const schedule = data.schedule || {}, collection = data.collection || {}, last = collection.last_run;
      $('#schedule-state').textContent = schedule.installed && schedule.loaded
        ? `매일 ${String(schedule.hour).padStart(2, '0')}:${String(schedule.minute).padStart(2, '0')}` :
        schedule.installed ? '자동 수집 로드 실패' : '자동 수집 미등록';
      $('#last-collection').textContent = collection.state === 'running' ? '수집 실행 중' : last ?
        `${new Date(last.finished_at * 1000).toLocaleString('ko-KR')} · ${collection.state === 'blocked' ? '중단: ' + last.stop_reason : collection.state === 'success' ? '성공' : collection.state === 'partial_failure' ? '부분 실패' : '전체 실패'} · 성공 ${last.accounts_ok} / 실패 ${last.accounts_failed} / 건너뜀 ${last.accounts_skipped || 0}` : '실행 기록 없음';
      $('#last-collection-success').textContent = collection.last_success_at
        ? new Date(collection.last_success_at * 1000).toLocaleString('ko-KR') : '성공 기록 없음';
      $('#next-collection').textContent = schedule.missed_today ? '오늘 7시 수집 누락' : schedule.next_run_at
        ? new Date(schedule.next_run_at * 1000).toLocaleString('ko-KR') : '예정 없음';
      $('#last-post-update').textContent = collection.newest_post_update
        ? new Date(collection.newest_post_update * 1000).toLocaleString('ko-KR') : '갱신 기록 없음';
      const tracking = data.hot_tracking || {};
      $('#hot-tracking').textContent = `진행 중 ${tracking.active || 0}개 · 누적 ${tracking.total || 0}개`;
    } catch (error) {
      $('#schedule-state').textContent = error.message;
    }
  }

  const bytes = (value) => value >= 1024 ** 3 ? (value / 1024 ** 3).toFixed(2) + 'GB' :
    (value / 1024 ** 2).toFixed(1) + 'MB';
  function toggleNotifications(open){
    $('#notification-panel').hidden=!open;$('#notification-toggle').setAttribute('aria-expanded',String(open));
    if(open){loadNotifications();$('#notification-close').focus();}
  }
  $('#notification-toggle').onclick=()=>toggleNotifications($('#notification-panel').hidden);
  $('#notification-close').onclick=()=>{toggleNotifications(false);$('#notification-toggle').focus();};
  document.addEventListener('click',e=>{if(!e.target.closest('.notification-anchor'))toggleNotifications(false);});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#notification-panel').hidden){toggleNotifications(false);$('#notification-toggle').focus();}});
  async function loadNotifications() {
    try {
      const response=await fetch('/api/notifications',{cache:'no-store'});const data=await response.json();
      if(!response.ok)throw new Error(data.error||'알림 조회 실패');
      const badge=$('#notification-count');badge.textContent=data.unseen>99?'99+':data.unseen;badge.hidden=!data.unseen;
      $('#notification-toggle').setAttribute('aria-label',`알림함 · 읽지 않은 알림 ${data.unseen}개`);
      $('#notification-list').innerHTML=data.notifications.length?data.notifications.map(item=>
        `<article class="notification-item ${item.seen_at?'read':'unread'}"><div class="notification-item-head"><strong>${item.seen_at?'읽은 알림':'새 알림'}</strong><time>${date(item.created_at)}</time></div><p>${esc(item.message)}</p>${item.seen_at?'':`<button class="btn ghost" data-seen="${item.id}">읽음으로 표시</button>`}</article>`).join(''):'<p class="notification-empty">알림이 없습니다.</p>';
    }catch(e){$('#notification-status').textContent=e.message;}
  }
  $('#notification-list').onclick=async e=>{
    const button=e.target.closest('[data-seen]');if(!button)return;button.disabled=true;
    try{const r=await fetch(`/api/notifications/${button.dataset.seen}/seen`,{method:'POST'});if(!r.ok)throw new Error('읽음 처리 실패');await loadNotifications();}catch(e){$('#notification-status').textContent=e.message;button.disabled=false;}
  };
  $('#notification-clear').onclick=async()=>{
    const button=$('#notification-clear');button.disabled=true;
    try{const r=await fetch('/api/notifications/seen',{method:'DELETE'});const data=await r.json();if(!r.ok)throw new Error(data.error||'알림 삭제 실패');$('#notification-status').textContent=`읽은 알림 ${data.deleted}개를 삭제했습니다.`;await loadNotifications();}
    catch(e){$('#notification-status').textContent=e.message;}finally{button.disabled=false;}
  };
  setInterval(loadNotifications,30000);

  async function loadJobs() {
    try {
      const data = await (await fetch('/api/jobs')).json();
      $('#jobs-list').innerHTML = data.jobs.length ? data.jobs.map((job) => {
        const base = job.kind === 'source' ? `/api/source-jobs/${encodeURIComponent(job.id)}` :
          `/api/transcript-jobs/${encodeURIComponent(job.id)}`;
        const links = job.status === 'done' ? job.kind === 'source' ?
          `<a href="${base}/download">ZIP 다운로드</a>` :
          `<a href="${base}/download?format=txt">TXT</a> · <a href="${base}/download?format=json">JSON</a>` : '';
        return `<div class="operational-item"><span>${job.kind === 'source' ? '소스' : '대본'} · ${esc(job.shortcode)} · ${esc(job.status)} ${job.progress}%</span>
          <small>${links} ${job.status === 'done' ? `<button class="btn ghost" data-archive="${esc(job.id)}" data-current="${job.archived ? 1 : 0}">${job.archived ? '보관 해제' : '보관'}</button>` : ''}</small></div>`;
      }).join('') : '<div class="hint">저장된 작업이 없습니다.</div>';
    } catch (error) { $('#jobs-list').textContent = error.message; }
  }
  $('#jobs-refresh').addEventListener('click', loadJobs);
  $('#jobs-list').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-archive]'); if (!button) return;
    await fetch(`/api/jobs/${encodeURIComponent(button.dataset.archive)}/archive`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archived: button.dataset.current !== '1' }),
    });
    loadJobs();
  });

  async function loadDisk() {
    try {
      const data = await (await fetch('/api/storage')).json();
      $('#disk-usage').textContent = `전체 ${bytes(data.total_bytes)} · 소스 ${bytes(data.source_jobs_bytes)} · 대본 ${bytes(data.transcripts_bytes)} · 모델 ${bytes(data.models_bytes)} · 설정 최대 ${bytes(data.max_bytes)}`;
    } catch (error) { $('#disk-usage').textContent = error.message; }
  }
  $('#storage-preview').addEventListener('click', async () => {
    try {
      const data = await (await fetch('/api/storage/dry-run')).json();
      const plan = $('#storage-plan'); plan.hidden = false;
      plan.innerHTML = `<b>임시 파일 ${data.items.length}건 · 예상 확보 ${bytes(data.expected_freed_bytes)}</b>` +
        data.items.map((item) => `<div class="operational-item"><span>${esc(item.path)}</span><small>${bytes(item.bytes)}</small></div>`).join('');
      $('#storage-cleanup').hidden = !data.items.length;
    } catch (error) { $('#storage-plan').hidden = false; $('#storage-plan').textContent = error.message; }
  });
  $('#storage-cleanup').addEventListener('click', async () => {
    const preview = await (await fetch('/api/storage/dry-run')).json();
    if (!preview.items.length) return;
    if (!confirm(`표시된 미보관 임시 파일 ${preview.items.length}건을 정리할까요? 예상 확보 ${bytes(preview.expected_freed_bytes)}`)) return;
    const result = await (await fetch('/api/storage/cleanup', { method: 'POST' })).json();
    $('#storage-plan').textContent = `임시 파일 ${result.deleted.length}건 정리 · 확보 ${bytes(result.freed_bytes)}`;
    $('#storage-cleanup').hidden = true; loadDisk();
  });

  $('#account-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type=submit]'); button.disabled = true;
    try {
      const response = await fetch('/api/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: $('#account-input').value, note: $('#account-note').value }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.error || '등록하지 못했습니다.');
      message(data.created ? `@${data.account.username} 계정을 등록하고 Git 공유 목록에 저장했습니다. 커밋·push하면 다른 PC와 공유됩니다.` : `@${data.account.username}의 이 PC 메모를 수정했습니다.`);
      $('#account-input').value = ''; $('#account-note').value = ''; await loadAccounts();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });

  $('#account-list').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-delete]'); if (!button) return;
    const username = button.dataset.delete;
    if (!confirm(`@${username} 계정을 관리 목록과 Git 공유 파일에서 삭제할까요?\n기존 수집 데이터는 삭제되지 않습니다.`)) return;
    button.disabled = true;
    try {
      const response = await fetch('/api/accounts/' + encodeURIComponent(username), { method: 'DELETE' });
      const data = await response.json(); if (!response.ok) throw new Error(data.error || '삭제하지 못했습니다.');
      message(`@${username} 계정을 관리 목록과 Git 공유 파일에서 삭제했습니다. 기존 수집 데이터는 보존됩니다.`); await loadAccounts();
    } catch (error) { message(error.message, true); button.disabled = false; }
  });
  $('#account-refresh').addEventListener('click', loadAccounts);
  loadAccounts(); loadCollectionStatus(); loadNotifications(); loadJobs(); loadDisk();
})();
