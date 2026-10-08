(() => {
  const buttons = [...document.querySelectorAll('[data-platform-login]')];
  const finish = document.getElementById('platform-session-finish');
  const message = document.getElementById('platform-session-message');
  if (!finish || !message) return;
  const modal = document.getElementById('session-modal');
  const opener = document.getElementById('platform-login');
  let timer, busy = false;
  const states = {authenticated:'인증 확인', login_required:'로그인 필요',
    verification_required:'추가 인증 필요', rate_limited:'요청 제한'};
  async function api(path = '', body) {
    const response = await fetch('/api/platform-session' + path, body === undefined ? {} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '로그인 상태를 확인하지 못했습니다.');
    return data;
  }
  function render(data) {
    message.textContent = data.error || data.message;
    message.classList.toggle('error', Boolean(data.error));
    finish.hidden = !data.active;
    finish.textContent = '세션 저장 완료';
    for (const button of buttons) {
      const id = button.dataset.platformLogin;
      button.disabled = busy || Boolean(data.active && (data.active_platform !== id || data.phase !== 'open'));
      const row = (data.platforms || []).find(p => p.id === id);
      const status = document.querySelector(`[data-platform-status="${id}"]`);
      status.textContent = data.active_platform === id ? ({opening:'로그인 창 여는 중',saving:'세션 저장 중'}[data.phase] || '로그인 창 열림 · 다시 누르면 앞으로') : row?.connected ? '인증 확인' :
        row?.auth_status !== 'unverified' && states[row?.auth_status] ? states[row.auth_status] :
        row?.cookie_present ? '세션 저장됨 · 인증 미확인' :
        row?.cookie_readable === false ? '세션 확인 대기' : id === 'google' ? '검색 인증 미확인' : '로그인 필요';
      status.classList.toggle('connected', Boolean(row?.connected));
    }
    clearTimeout(timer);
    if (!modal?.hidden) timer = setTimeout(refresh, data.active ? 2000 : 20000);
  }
  async function refresh() {
    if (modal?.hidden) return;
    try { render(await api()); }
    catch (error) { message.textContent = error.message; if (!modal?.hidden) timer = setTimeout(refresh, 20000); }
  }
  for (const button of buttons) button.addEventListener('click', async () => {
    busy = true; buttons.forEach(b => b.disabled = true);
    try { const data = await api('', {platform:button.dataset.platformLogin}); busy = false; render(data); }
    catch (error) { busy = false; buttons.forEach(b => b.disabled = false); message.textContent = error.message; }
  });
  finish.addEventListener('click', async () => {
    finish.disabled = true;
    try { render(await api('/finish', {})); }
    catch (error) { message.textContent = error.message; }
    finally { finish.disabled = false; }
  });
  function open() { modal.hidden = false; refresh(); buttons[0]?.focus(); }
  function close() { modal.hidden = true; clearTimeout(timer); opener?.focus(); }
  if (modal && opener) {
    opener.addEventListener('click', open);
    modal.querySelectorAll('[data-session-close]').forEach(el => el.addEventListener('click', close));
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.hidden) close(); });
    if (location.hash === '#platform-login') open();
  } else refresh();
})();
