/* No content generation happens here: this is the handoff/selection UI. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current = null;
  let rendered = '';
  let outputRendered = '';
  const labels = {acquired:'자료 준비됨',rewriting:'대본 재가공 중',awaiting_selection:'대본 선택 대기',script_selected:'대본 확정',synthesizing:'음성 생성 중',editing:'편집 중',draft_ready:'CapCut 초안 준비됨',blocked:'확인이 필요합니다'};
  async function api(path, body) {
    const response = await fetch('/api/' + path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '요청 실패');
    return data;
  }
  function notice(message) {$('notice').textContent = message;}
  function draw(job) {
    current = job; $('work').hidden = false;
    $('title').textContent = job.product;
    $('status').textContent = (labels[job.status] || job.status) + ' · 대본 버전 ' + job.revision;
    $('error').textContent = job.error || '';
    $('original').textContent = job.reference_script;
    $('build').disabled = !job.script_path || !!job.running;
    $('rewrite').disabled = !!job.script_path || !!job.running;
    const scripts = job.scripts_result?.scripts || [];
    const key = job.id + ':' + JSON.stringify(scripts) + ':' + job.revision;
    // Polling must not erase the user's unsaved transformation/scene choices.
    if (rendered !== key) {
      rendered = key;
      $('selection').hidden = scripts.length === 0;
      $('scripts').innerHTML = scripts.map((s,i) => `<label class="choice"><input type="radio" name="script" value="${i}" ${i === (job.selected_script ?? 0) ? 'checked' : ''}> <b>${esc(s.title)}</b><p>${esc(s.text)}</p><small>${esc((s.rewrite_review?.reasons || []).join(' ')) || '문구 검사 후 관점·전개를 직접 검토하세요.'}</small></label>`).join('');
      $('angle').value = job.transformation?.new_angle || '';
      $('structure').value = job.transformation?.structure_change || '';
      $('visual').value = job.transformation?.visual_change || '';
      $('edit-style').value = job.edit_style || 'brisk'; $('reviewed').checked = false;
      $('scenes').innerHTML = job.assets.map(asset => {
        const scene = job.scenes?.find(s => s.asset_id === asset.id);
        const quality = asset.source.source_quality || 'unknown';
        return `<div class="choice" data-asset="${esc(asset.id)}"><label><input class="use" type="checkbox" ${scene ? 'checked' : ''} ${quality === 'edited-with-text' ? 'disabled' : ''}> 소스 ${esc(asset.id)} · ${esc(quality)}</label><p>${esc(asset.source.title || asset.source.provider)}</p><video controls preload="none" src="/api/productions/${job.id}/assets/${esc(asset.id)}"></video><label>장면 설명<input class="label" maxlength="80" value="${esc(scene?.label || '')}"></label><div class="range"><label>시작 초<input class="start" type="number" min="0" step="0.1" value="${scene?.range?.[0] ?? ''}"></label><label>종료 초<input class="end" type="number" min="0" step="0.1" value="${scene?.range?.[1] ?? ''}"></label></div>${quality === 'unknown' ? '<label><input class="source-reviewed" type="checkbox"> 미분류 영상의 화면을 직접 확인했습니다.</label>' : ''}</div>`;
      }).join('');
    }
    const outputKey = job.id + ':' + job.revision + ':' + JSON.stringify([job.voice, job.editing]);
    if (outputKey !== outputRendered) {
      outputRendered = outputKey;
      $('output').innerHTML = (job.voice ? `<p>생성 음성</p><audio controls src="/api/productions/${job.id}/audio?v=${job.revision}"></audio>` : '') +
      (job.editing ? `<p>결과: ${esc(job.editing.output_kind || 'CapCut 초안')}</p><pre>${esc(job.editing.draft_path || '')}</pre><p>${esc((job.editing.warnings || []).join('\n'))}</p><p class="muted">초안을 열어 원본과 비교하고 최종 수정·내보내기를 진행하세요.</p>` : '');
    }
  }
  async function reload() {
    const [records, assets] = await Promise.all([api('productions'),api('jobs')]);
    const selected = current?.id;
    $('jobs').innerHTML = '<option value="">제작 기록 선택</option>' + records.items.map(j => `<option value="${j.id}">${esc(j.product)} · ${esc(labels[j.status] || j.status)}</option>`).join('');
    if (selected) $('jobs').value = selected;
    for (const kind of ['source','transcript']) {
      const old = $(kind).value;
      $(kind).innerHTML = assets.jobs.filter(j => j.kind === kind && j.status === 'done').map(j => `<option value="${esc(j.id)}">${esc(j.shortcode)} · ${new Date(j.created_at * 1000).toLocaleString('ko-KR')}</option>`).join('');
      if (old && [...$(kind).options].some(o => o.value === old)) $(kind).value = old;
    }
    if (selected) draw(await api('productions/' + selected));
    notice('기록을 불러왔습니다.');
  }
  function action(id, fn) { $(id).onclick = async () => {$(id).disabled = true; try {await fn();} catch(e) {notice(e.message);} finally {$(id).disabled = false;} }; }
  action('reload', reload);
  action('health', async () => {
    const result = await api('production-health');
    $('health-result').textContent = Object.entries(result.checks).map(([name,item]) => `${name}: ${item.ready ? '준비됨' : '확인 필요'} · ${item.message}`).join('\n');
  });
  action('create', async () => {draw(await api('productions',{source_job_id:$('source').value,transcript_job_id:$('transcript').value,product:$('product').value,product_url:$('product-url').value,notes:$('notes').value}));await reload();notice('제작을 등록했습니다. 대본 재가공을 요청하세요.');});
  $('jobs').onchange = async () => {if ($('jobs').value) {try {draw(await api('productions/' + $('jobs').value));} catch(e) {notice(e.message);}}};
  action('rewrite', async () => {await api('productions/' + current.id + '/rewrite',{});notice('대본 작업을 요청했습니다.');});
  action('select', async () => {
    const scenes = [...document.querySelectorAll('[data-asset]')].filter(el => el.querySelector('.use').checked).map(el => {
      const start = el.querySelector('.start').value, end = el.querySelector('.end').value;
      if ((start === '') !== (end === '')) throw new Error('장면 시작·종료를 함께 입력하세요.');
      return {asset_id:el.dataset.asset,label:el.querySelector('.label').value,range:start === '' ? null : [Number(start),Number(end)],reviewed:!!el.querySelector('.source-reviewed')?.checked};
    });
    draw(await api('productions/' + current.id + '/select',{script_index:Number(document.querySelector('[name=script]:checked')?.value),reviewed:$('reviewed').checked,scenes,edit_style:$('edit-style').value,transformation:{new_angle:$('angle').value,structure_change:$('structure').value,visual_change:$('visual').value}}));
    notice('대본과 변환 계획을 확정했습니다. 음성·초안 제작을 진행할 수 있습니다.');
  });
  action('build', async () => {await api('productions/' + current.id + '/build',{});notice('음성·편집 작업을 요청했습니다. CapCut이 실행 중이면 종료 후 재개하세요.');});
  setInterval(async () => {if (current) {try {draw(await api('productions/' + current.id));} catch(e) {notice(e.message);}}},4000);
  reload().catch(e => notice(e.message));
})();
