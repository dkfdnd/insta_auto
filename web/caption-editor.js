/* Live captions share the exported timeline. The underlying picture and audio never shift. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const current=t=>(t.edits||[]).find(e=>e.id===t.edit_id);
  const fields=root=>[...root.querySelectorAll('[data-caption-card]')];
  const input=(card,k)=>card.querySelector(`[data-field="${k}:${card.dataset.captionCard}"]`);
  function collect(root){return fields(root).map(c=>({beat_id:c.dataset.captionCard,text:input(c,'caption').value.trim(),start:Number(input(c,'start').value),end:Number(input(c,'end').value)}));}
  function validate(root,t){
    const edit=current(t);let end=0;
    for(const c of collect(root)){
      if(!c.text||c.text.length>100||c.text.includes('\n'))return '자막은 1~100자의 한 줄로 입력하세요.';
      if(!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.start<end||c.end<=c.start||c.end>edit.duration+.001)return '자막 시간이 겹치거나 영상 범위를 벗어났어요. 표시된 시작·끝 시간을 조정하세요.';
      end=c.end;
    }
    return '';
  }
  function shiftControls(id,index){
    return `<div class="ce-shift-controls"><div class="ce-shift-options" role="group" aria-label="${index+1}번 자막 이동 간격"><span class="ce-shift-label">이동 간격</span>${[.1,.5,1].map(n=>`<button type="button" data-caption-step="${n}" aria-pressed="${n===.1}">${n}초</button>`).join('')}<label class="ce-shift-custom"><span>직접 입력</span><input type="number" data-caption-shift min="0.01" step="0.01" value="0.1" inputmode="decimal" aria-label="${index+1}번 자막 이동 간격(초)"><span>초</span></label></div><div class="ce-shift"><button data-sync="earlier" data-beat="${esc(id)}" aria-label="${index+1}번 자막 0.1초 앞당기기">← 0.1초 앞당기기</button><button data-sync="later" data-beat="${esc(id)}" aria-label="${index+1}번 자막 0.1초 늦추기">0.1초 늦추기 →</button></div><p class="ce-shift-help">이 자막의 시작·끝을 함께 이동합니다.</p></div>`;
  }
  function markup(t,e){
    if(!e?.plan)return '<section data-pf-section="edit"><div class="pf-empty"><b>미리보기를 준비하고 있어요</b><p>대본과 음성이 준비되면 이곳에서 영상을 확인하고 내보낼 수 있습니다.</p></div></section>';
    const f=t.feedback||{},conflict=f.changes?.length&&(f.base_edit_id!==e.id||f.changes.some(c=>Object.keys(c).some(k=>!['beat_id','text','start','end'].includes(k))));
    return `<section data-pf-section="edit" class="ce-editor" data-caption-edit="${esc(e.id)}"><div class="pf-section-intro"><div><span class="pf-count">현재 편집본 · 변경은 새 출력으로 저장</span><h3>보고, 맞추고, 내보내세요</h3><p>자막 시간과 문구는 미리보기에 바로 반영됩니다. 실제 대사를 바꾸려면 대본·목소리로 돌아가세요.</p></div></div>
      <p data-caption-state role="status"></p><div data-caption-stale hidden><p>이전 자막 입력은 이 기기에 보관되어 있습니다.</p><button data-pf="discard-local-edit">이전 자막 입력을 비우고 새 영상 보기</button></div>${conflict?`<details class="ce-saved-conflict" open><summary>이전 버전 또는 장면 수정이 보관돼 있어요</summary><p>아래 내용을 확인·복사한 뒤 비우고 새 영상에서 편집하세요.</p><p>${f.changes.map(c=>esc(c.text||'장면·강조 수정')+' '+esc(c.start??'')+'–'+esc(c.end??'')).join('<br>')}</p><button data-pf="discard-edit-feedback">보관한 구간 수정만 비우기</button></details>`:''}<div class="ce-toolbar"><button data-pf="save-captions">편집 저장</button><button data-caption-undo disabled>실행 취소</button><button data-pf="export-edit" class="ce-export">MP4 내보내기</button></div>
      <div class="ce-layout"><aside class="ce-monitor"><div class="ce-frame"><video data-edit-preview controls controlslist="nofullscreen nodownload" disablepictureinpicture playsinline preload="metadata" src="${esc(e.clean_preview_url||e.preview_url)}"></video><canvas data-caption-canvas width="1080" height="1920" aria-hidden="true"></canvas></div>

      <button data-pf="prepare-caption-preview" class="pf-secondary" ${e.clean_preview_url?'hidden':''}>편집 미리보기 준비</button>
      <button class="pf-capcut-launch" data-pf="open-capcut" data-edit-id="${esc(e.id)}">↗ CapCut에서 정밀 편집</button><p class="pf-capcut-help">장면 교체·효과·정밀 편집은 CapCut에서 진행하세요. 웹의 미저장 자막은 먼저 내보내세요. CapCut에서 수정한 내용은 웹에 자동으로 돌아오지 않습니다.</p>
      <span data-sync-caption hidden></span><output data-sync-range class="ce-time-readout"></output></aside>
      <div class="ce-captions"><div class="ce-list-heading"><h4>자막 편집</h4><span>${e.plan.cues.length}개 구간 · 간격 선택 또는 직접 입력</span></div>${e.plan.beats.map((b,i)=>{const cue=e.plan.cues.find(c=>c.id===b.cue_id),d=(!conflict&&f.changes?.find(c=>c.beat_id===b.id))||{};return `<article class="pf-beat ce-cue" data-sync-beat="${esc(b.id)}" data-caption-card="${esc(b.id)}"><div class="ce-cue-heading"><button data-sync="loop" data-beat="${esc(b.id)}" aria-pressed="false">▷ ${i+1}. 앞뒤 함께 듣기</button><output data-sync-times></output></div><label>화면에 보일 자막<input maxlength="100" data-field="caption:${esc(b.id)}" value="${esc(d.text??cue.text)}"></label>${shiftControls(b.id,i)}<details><summary>시작·끝 시간 직접 맞추기</summary><div class="ce-times"><label>시작(초)<input type="number" step="0.01" min="0" data-field="start:${esc(b.id)}" value="${d.start??cue.start}"></label><label>끝(초)<input type="number" step="0.01" min="0" data-field="end:${esc(b.id)}" value="${d.end??cue.end}"></label></div><button data-sync="start" data-beat="${esc(b.id)}">현재 위치를 시작으로</button><button data-sync="end" data-beat="${esc(b.id)}">현재 위치를 끝으로</button></details><p class="pf-sync-feedback" role="status"></p></article>`;}).join('')}</div></div></section>`;
  }
  function remember(root){
    const box=root.querySelector('[data-caption-edit]');if(!box)return;
    const snapshot=JSON.stringify(collect(root));box._history??=[];
    if(box._history.at(-1)!==snapshot)box._history.push(snapshot);
    if(box._history.length>40)box._history.shift();
  }
  function ready(root,t){
    const e=current(t),box=root.querySelector('[data-caption-edit]');
    return !!(t.caption_editor_supported&&e?.clean_preview_url&&box?.dataset.captionEdit===e.id);
  }
  function refresh(root,t){
    const box=root.querySelector('[data-caption-edit]');if(!box)return;
    const e=current(t),ok=ready(root,t),busy=(t.jobs||[]).some(j=>['queued','running'].includes(j.status)&&!['refresh_sources','proposal','suggest_edit'].includes(j.kind));
    const f=t.feedback||{},savedConflict=f.changes?.length&&(f.base_edit_id!==e?.id||f.changes.some(c=>Object.keys(c).some(k=>!['beat_id','text','start','end'].includes(k))));
    const issue=root._captionError||(savedConflict?'보관한 구간 수정을 확인한 뒤 비우고 새 영상을 편집하세요.':ok?validate(root,t):'');
    const local=JSON.parse(localStorage.getItem('production-feedback-'+t.id)||'{}');
    const dirty=Object.keys(local).some(k=>/^(caption|start|end):/.test(k));
    const other=Object.keys(local).some(k=>/^(script$|speed$|pronunciation$|source:)/.test(k))||Object.keys(t.feedback||{}).some(k=>!['changes','base_edit_id','caption_only'].includes(k));
    const note=box.querySelector('[data-caption-state]');
    note.textContent=!t.caption_editor_supported?'서버 업데이트 적용 후 편집할 수 있습니다. 기존 영상은 아래에서 확인하세요.':box.dataset.captionEdit!==e?.id?'새 영상이 준비됐어요. 이전 입력을 보관한 뒤 새 영상을 확인하세요.':!ok?'자막을 분리한 편집 미리보기를 준비해 주세요.':issue|| (other?'소스·대본·음성 변경을 먼저 저장·반영하거나 초기화하세요.':busy?'현재 버전 내보내기·제작 중 · 이후 수정은 다음 내보내기에 반영됩니다.':dirty?'미리보기 반영됨 · 내보내면 함께 저장됩니다.':t.feedback?.changes?.length?'편집 저장됨 · MP4에 반영하려면 내보내세요.':'편집 준비 완료 · 자막을 바꾸면 화면에서 바로 확인할 수 있어요.');
    note.dataset.error=String(!!issue);box.querySelector('[data-caption-stale]').hidden=box.dataset.captionEdit===e?.id;
    for(const button of box.querySelectorAll('[data-pf="save-captions"],[data-pf="export-edit"]'))button.disabled=!ok||!!issue||other||busy||!!root._saving;
    for(const control of box.querySelectorAll('[data-sync],[data-caption-step],input'))control.disabled=!ok;
    box.querySelector('[data-caption-undo]').disabled=!ok||!box._history?.length;
    box.querySelector('[data-pf="prepare-caption-preview"]').hidden=ok;
    box.querySelector('[data-pf="prepare-caption-preview"]').disabled=!t.caption_editor_supported||!!root._saving;
    box.querySelector('[data-pf="open-capcut"]').disabled=dirty||!!t.feedback?.changes?.length||busy||!!root._saving;
    box.querySelector('[data-pf="export-edit"]').textContent=busy?'내보내기·제작 진행 중':!dirty&&!t.feedback?.changes?.length&&e?.export_url?'현재 MP4 다운로드':'수정본 MP4 내보내기';
    const video=box.querySelector('video');
    if(ok&&video.getAttribute('src')!==e.clean_preview_url){const position=video.currentTime;video.src=e.clean_preview_url;video.addEventListener('loadedmetadata',()=>{video.currentTime=position;},{once:true});}
    box._paint?.();
  }
  function bind(root,t){
    const box=root.querySelector('[data-caption-edit]');if(!box)return;
    if(box._bound){refresh(root,t);return;}box._bound=true;
    const video=box.querySelector('video'),canvas=box.querySelector('canvas'),ctx=canvas.getContext('2d');
    // Keep the external editor discoverable without covering mobile caption controls.
    box.querySelector('.ce-toolbar').append(box.querySelector('[data-pf="open-capcut"]'));
    const help=box.querySelector('.pf-capcut-help');box.querySelector('.ce-layout').before(help);
    const chooser=document.createElement('nav');chooser.className='ce-cue-picker';chooser.setAttribute('aria-label','수정할 자막 선택');
    const cards=fields(root);let selected=0;
    chooser.innerHTML='<button type="button" data-cue-prev aria-label="이전 자막">← 이전</button><select aria-label="수정할 자막">'+cards.map((c,i)=>`<option value="${i}">${i+1}. ${esc(input(c,'caption').value)}</option>`).join('')+'</select><button type="button" data-cue-next aria-label="다음 자막">다음 →</button>';
    const choose=(n,seek=false)=>{selected=Math.max(0,Math.min(cards.length-1,n));cards.forEach((c,i)=>c.classList.toggle('ce-selected',i===selected));chooser.querySelector('select').value=selected;chooser.querySelector('[data-cue-prev]').disabled=selected===0;chooser.querySelector('[data-cue-next]').disabled=selected===cards.length-1;if(seek&&cards[selected]&&video.readyState>=1){video.pause();root._syncLoop=null;video.currentTime=Number(input(cards[selected],'start').value);}};
    chooser.querySelector('select').onchange=e=>choose(Number(e.target.value),true);
    chooser.querySelector('[data-cue-prev]').onclick=()=>choose(selected-1,true);chooser.querySelector('[data-cue-next]').onclick=()=>choose(selected+1,true);
    box.querySelector('.ce-captions').prepend(chooser);choose(0);
    const paint=time=>{
      ctx.clearRect(0,0,1080,1920);
      if(!ready(root,root._task))return;
      const at=Math.floor((typeof time==='number'?time:video.currentTime)*30+1e-6)/30,rows=collect(root),cue=rows.find(c=>at>=Math.max(1/30,c.start)&&at<c.end);
      fields(root).forEach(c=>c.classList.toggle('ce-active',c.dataset.captionCard===cue?.beat_id));
      canvas.dataset.activeCue=cue?.beat_id||'';
      if(!cue)return;
      const e=current(root._task),beat=e.plan.beats.find(b=>b.id===cue.beat_id),level=beat.emphasis||0;
      let size=[56,68,80][level];ctx.font=`bold ${size}px "Malgun Gothic",sans-serif`;
      size=Math.max(20,Math.min(size,Math.floor(size*936/Math.max(1,ctx.measureText(cue.text).width))));
      ctx.font=`bold ${size}px "Malgun Gothic",sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.lineJoin='round';ctx.lineWidth=6;ctx.strokeStyle='#000';ctx.fillStyle=level?'#ffdf00':'#fff';
      ctx.shadowColor='#0009';ctx.shadowBlur=2;ctx.shadowOffsetX=2;ctx.shadowOffsetY=2;
      ctx.strokeText(cue.text,540,1180);ctx.fillText(cue.text,540,1180);
    };box._paint=paint;
    let frame=null;
    const tick=(_now,metadata)=>{frame=null;if(!box.isConnected)return;paint(metadata?.mediaTime);if(!video.paused&&!video.ended)frame=video.requestVideoFrameCallback?video.requestVideoFrameCallback(tick):requestAnimationFrame(tick);};
    const start=()=>{if(frame===null)tick();};
    for(const event of ['loadeddata','seeked','timeupdate','pause'])video.addEventListener(event,paint);
    video.addEventListener('play',start);
    box.addEventListener('focusin',e=>{if(e.target.matches('[data-field]'))remember(root);});
    const updateShift=card=>{
      const field=card.querySelector('[data-caption-shift]'),amount=Number(field.value);
      const valid=field.value!==''&&Number.isFinite(amount)&&amount>0&&field.validity.valid;
      field.setAttribute('aria-invalid',String(!valid));
      card.querySelectorAll('[data-caption-step]').forEach(b=>b.setAttribute('aria-pressed',String(valid&&Number(b.dataset.captionStep)===amount)));
      const index=fields(root).indexOf(card)+1;
      for(const action of ['earlier','later']){
        const b=card.querySelector(`[data-sync="${action}"]`),label=action==='earlier'?'앞당기기':'늦추기';
        b.textContent=action==='earlier'?`← ${valid?amount+'초 ':''}${label}`:`${valid?amount+'초 ':''}${label} →`;
        b.setAttribute('aria-label',`${index}번 자막 ${valid?amount+'초 ':''}${label}`);
      }
      card.querySelector('.pf-sync-feedback').textContent=valid?'':'이동 간격은 0.01초 이상의 숫자를 소수점 두 자리까지 입력하세요.';
    };
    box.addEventListener('click',event=>{
      const button=event.target.closest('[data-caption-step]');if(!button)return;
      const card=button.closest('[data-caption-card]');card.querySelector('[data-caption-shift]').value=button.dataset.captionStep;updateShift(card);
    });
    box.addEventListener('input',event=>{if(event.target.matches('[data-caption-shift]'))updateShift(event.target.closest('[data-caption-card]'));});
    box.addEventListener('input',()=>{root._captionError='';refresh(root,root._task);});
    box.querySelector('[data-caption-undo]').onclick=()=>{
      const saved=box._history?.pop();if(!saved)return;
      for(const c of JSON.parse(saved)){const card=fields(root).find(v=>v.dataset.captionCard===c.beat_id);for(const [k,v] of Object.entries({caption:c.text,start:c.start,end:c.end})){const f=input(card,k);f.value=v;f.dispatchEvent(new Event('input',{bubbles:true}));}}
      refresh(root,root._task);
    };
    refresh(root,t);
  }
  window.CaptionEditor={markup,bind,refresh,collect,validate,remember,ready};
})();
