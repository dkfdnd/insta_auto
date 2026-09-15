(function () {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value || '').replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
  const fmt = (value) => Number(value || 0).toLocaleString('ko-KR');
  const date = (timestamp) => timestamp ? new Date(timestamp * 1000).toLocaleDateString('ko-KR') : '수집 전';
  let accounts = [];

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
    list.innerHTML = accounts.map((account) => `<article class="account-row" data-username="${esc(account.username)}">
      <div class="account-avatar">${account.profile_pic_url ? `<img src="${esc(account.profile_pic_url)}" alt="">` : esc(account.username.slice(0, 2).toUpperCase())}</div>
      <div class="account-main">
        <div><a href="https://www.instagram.com/${encodeURIComponent(account.username)}/" target="_blank" rel="noopener">@${esc(account.username)} ↗</a>${account.full_name ? `<span>${esc(account.full_name)}</span>` : ''}</div>
        <p>${account.note ? esc(account.note) : '<span class="hint">메모 없음</span>'}</p>
      </div>
      <div class="account-stats"><span>팔로워 <b>${fmt(account.followers)}</b></span><span>수집 게시물 <b>${fmt(account.posts_count)}</b></span><span>최근 게시 <b>${date(account.last_post_at)}</b></span></div>
      <button class="btn account-delete" data-delete="${esc(account.username)}">삭제</button>
    </article>`).join('');
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
        ? `매일 ${String(schedule.hour).padStart(2, '0')}:${String(schedule.minute).padStart(2, '0')}` : '자동 수집 미등록';
      $('#last-collection').textContent = last ? new Date(last.finished_at * 1000).toLocaleString('ko-KR') : '실행 기록 없음';
      $('#last-post-update').textContent = collection.newest_post_update
        ? new Date(collection.newest_post_update * 1000).toLocaleString('ko-KR') : '갱신 기록 없음';
      const tracking = data.hot_tracking || {};
      $('#hot-tracking').textContent = `진행 중 ${tracking.active || 0}개 · 누적 ${tracking.total || 0}개`;
    } catch (error) {
      $('#schedule-state').textContent = error.message;
    }
  }

  $('#account-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type=submit]'); button.disabled = true;
    try {
      const response = await fetch('/api/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: $('#account-input').value, note: $('#account-note').value }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.error || '등록하지 못했습니다.');
      message(data.created ? `@${data.account.username} 계정을 등록했습니다.` : `@${data.account.username} 정보를 수정했습니다.`);
      $('#account-input').value = ''; $('#account-note').value = ''; await loadAccounts();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });

  $('#account-list').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-delete]'); if (!button) return;
    const username = button.dataset.delete;
    if (!confirm(`@${username} 계정을 관리 목록에서 삭제할까요?\n기존 수집 데이터는 삭제되지 않습니다.`)) return;
    button.disabled = true;
    try {
      const response = await fetch('/api/accounts/' + encodeURIComponent(username), { method: 'DELETE' });
      const data = await response.json(); if (!response.ok) throw new Error(data.error || '삭제하지 못했습니다.');
      message(`@${username} 계정을 관리 목록에서 삭제했습니다.`); await loadAccounts();
    } catch (error) { message(error.message, true); button.disabled = false; }
  });
  $('#account-refresh').addEventListener('click', loadAccounts);
  loadAccounts(); loadCollectionStatus();
})();
