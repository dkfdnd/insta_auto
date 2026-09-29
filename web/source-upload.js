/* Local uploads are queued per work panel, never shared across videos. */
(() => {
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={queued:'업로드 대기',uploading:'전송 중',checking:'영상 확인 중',done:'추가 완료',duplicate:'이미 보유한 영상',failed:'다시 확인'};
  function bind(root,task,onUploaded,onIdle){
    const zone=root.querySelector('[data-upload-widget]');if(!zone)return;
    root._uploadQueue ||= [];
    root._uploadCallbacks={onUploaded,onIdle,taskId:task.id};
    function paint(){
      const list=root.querySelector('[data-upload-list]');if(!list)return;
      const markup=root._uploadQueue.map((f,i)=>`<li data-upload-state="${f.state}"><span class="upload-file-icon" aria-hidden="true">${f.state==='done'?'✓':f.state==='failed'?'!':'▷'}</span><div><strong>${esc(f.file.name)}</strong><span>${labels[f.state]}${f.state==='uploading'?` · ${f.percent}%`:''}${f.error?' · '+esc(f.error):''}</span><progress max="100" value="${f.percent}" aria-label="${esc(f.file.name)} 전송 진행"></progress></div>${f.state==='failed'&&f.retryable!==false?`<button type="button" data-upload-retry="${i}">재시도</button>`:''}</li>`).join('');
      if(list._markup!==markup){list.innerHTML=markup;list._markup=markup;}
      const done=root._uploadQueue.filter(f=>['done','duplicate'].includes(f.state)).length;
      const failed=root._uploadQueue.filter(f=>f.state==='failed').length;
      const note=root.querySelector('[data-upload-summary]');
      if(note)note.textContent=root._uploadQueue.length?`${root._uploadQueue.length}개 중 ${done}개 처리${failed?` · ${failed}개 확인 필요`:''}${root._uploading?' · 업로드 중':' · 아래에서 사용할 영상을 선택하세요.'}`:'';
      zone.setAttribute('aria-busy',String(!!root._uploading));
      if(root._uploading)for(const button of root.querySelectorAll('[data-pf="use-sources"],[data-action="use-sources"]'))button.disabled=true;
    }
    async function drain(){
      if(root._uploading)return;
      root._uploading=true;paint();
      try{
        for(const row of root._uploadQueue){
          if(row.state!=='queued')continue;
          row.state='uploading';row.percent=0;paint();
          const known=new Set((root._task?.sources||[]).map(s=>s.id));
          try{
            const result=await new Promise((resolve,reject)=>{
              const xhr=new XMLHttpRequest();xhr.open('POST',`/api/studio/${encodeURIComponent(task.id)}/upload-source?name=${encodeURIComponent(row.file.name)}`);
              xhr.timeout=15*60*1000;
              xhr.upload.onprogress=e=>{if(e.lengthComputable)row.percent=Math.round(e.loaded/e.total*100);if(row.percent===100)row.state='checking';paint();};
              xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status>=200&&xhr.status<300)resolve(data);else reject(Error(data.error||'영상 업로드를 완료하지 못했어요.'));}catch(e){reject(e);}};
              xhr.onerror=()=>reject(Error('연결이 끊겼어요. 연결 상태를 확인하고 이 파일만 재시도하세요.'));
              xhr.ontimeout=()=>reject(Error('업로드 응답이 늦어지고 있어요. 잠시 후 다시 시도하세요.'));
              xhr.send(row.file);
            });
            row.state=result.sources.some(s=>!known.has(s.id))?'done':'duplicate';row.percent=100;
            root._uploadCallbacks.onUploaded(result);
          }catch(e){row.state='failed';row.error=window.StudioBoard.message(e.message,'영상을 업로드하지 못했어요. 파일과 연결 상태를 확인한 뒤 재시도하세요.');}
          paint();
        }
      }finally{root._uploading=false;paint();root._uploadCallbacks.onIdle?.();}
    }
    function add(files){
      for(const file of files){
        if(root._uploadQueue.some(r=>r.file.name===file.name&&r.file.size===file.size&&r.file.lastModified===file.lastModified&&r.state!=='failed'))continue;
        const error=!/\.(mp4|mov|webm)$/i.test(file.name)?'MP4, MOV, WEBM 파일을 선택하세요.':!file.size?'빈 파일은 사용할 수 없어요.':file.size>512*1024*1024?'파일 하나당 512MB 이하로 선택하세요.':'';
        root._uploadQueue.push({file,state:error?'failed':'queued',percent:0,error,retryable:!error});
      }
      paint();drain();
    }
    if(!zone._bound){
      zone._bound=true;
      zone.innerHTML=`<div class="upload-dropzone" data-dropzone><span class="upload-symbol" aria-hidden="true">↥</span><h4>여기에 영상 여러 개를 놓아주세요</h4><p>파일을 끌어 놓거나 버튼을 눌러 한 번에 선택하세요.</p><button type="button" data-upload-open>＋ 영상 여러 개 선택</button><input type="file" data-upload-files multiple accept=".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm" hidden><small>MP4 · MOV · WEBM / 파일당 최대 512MB</small></div><p class="upload-summary" data-upload-summary role="status" aria-live="polite"></p><ul class="upload-list" data-upload-list></ul>`;
      zone.onclick=e=>{if(e.target.closest('[data-upload-open]'))zone.querySelector('[data-upload-files]').click();const retry=e.target.closest('[data-upload-retry]');if(retry){const row=root._uploadQueue[Number(retry.dataset.uploadRetry)];if(row.file.size>0&&row.file.size<=512*1024*1024&&/\.(mp4|mov|webm)$/i.test(row.file.name)){row.state='queued';row.error='';drain();}}};
      zone.onchange=e=>{if(e.target.matches('[data-upload-files]')){add([...e.target.files]);e.target.value='';}};
      let depth=0;
      zone.ondragenter=e=>{e.preventDefault();depth++;zone.classList.add('is-dragging');};
      zone.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';};
      zone.ondragleave=e=>{e.preventDefault();if(--depth<=0){depth=0;zone.classList.remove('is-dragging');}};
      zone.ondrop=e=>{e.preventDefault();depth=0;zone.classList.remove('is-dragging');add([...e.dataTransfer.files]);};
    }
    paint();
  }
  window.SourceUpload={bind};
})();
