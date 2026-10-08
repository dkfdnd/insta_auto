/* Optional source ZIP / original transcript extraction in the reference disclosure. */
(() => {
  'use strict';
  function create({modal, esc}) {
    const $ = (selector, root) => root.querySelector(selector);
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

    return {startSourceJob, startTranscriptJob};
  }
  window.ReferenceJobs = {create};
})();
