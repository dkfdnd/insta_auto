/* Pick a server-owned voice identity; never send engine parameters or reference paths. */
(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={'qwen-sohee':'소희 · 여성','qwen-aiden':'에이든 · 남성','qwen-ryan':'라이언 · 남성','qwen-serena':'세레나 · 여성','qwen-vivian':'비비안 · 여성','qwen-uncle_fu':'푸 · 남성','qwen-dylan':'딜런 · 남성','qwen-eric':'에릭 · 남성','qwen-ono_anna':'안나 · 여성','zonos-americanmale':'아메리칸 · 남성','zonos-americanfemale':'아메리칸 · 여성','zonos-britishfemale':'브리티시 · 여성'};
 const label=id=>id?(labels[id]||'선택한 목소리'):'내 목소리 · 기존 기본값';
 function bind(root){
  const box=root.querySelector('[data-voice-picker]');if(!box)return;
  const field=box.querySelector('[data-field="voice-profile"]'),current=box.querySelector('[data-current-voice]');current.textContent=label(field.value);
  if(box._bound)return;box._bound=true;
  field.addEventListener('input',()=>current.textContent=label(field.value));
  box.querySelector('[data-choose-voice]').onclick=async()=>{
   const dialog=document.createElement('dialog');dialog.className='voice-dialog';dialog.setAttribute('aria-label','읽어줄 목소리 선택');
   dialog.innerHTML='<header><div><h2>어떤 목소리로 읽을까요?</h2><p>미리 듣고 고르세요. 선택은 다음 영상 제작에 반영됩니다.</p></div><button type="button" data-voice-close aria-label="목소리 선택 닫기">×</button></header><div class="voice-filters"><div role="group" aria-label="성별"><button data-gender="all" aria-pressed="true">전체</button><button data-gender="female" aria-pressed="false">여성</button><button data-gender="male" aria-pressed="false">남성</button></div><label>모델 <select data-model><option value="">모든 모델</option><option value="Qwen">Qwen</option><option value="ZONOS2">ZONOS2</option></select></label></div><p data-voice-status role="status">목소리를 불러오는 중…</p><button data-voice-reload hidden>다시 불러오기</button><div class="voice-grid"></div><audio data-voice-audio controls hidden></audio>';
   document.body.append(dialog);dialog.showModal();
   let rows=[],gender='all',model='';const audio=dialog.querySelector('audio'),note=dialog.querySelector('[data-voice-status]');
   const close=()=>{audio.pause();dialog.remove();box.querySelector('[data-choose-voice]')?.focus();};
   dialog.querySelector('[data-voice-close]').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
   const render=()=>{
    const filtered=rows.filter(v=>(gender==='all'||v.gender===gender)&&(!model||v.model===model));
    note.textContent=audio.dataset.voiceName&&!audio.paused?audio.dataset.voiceName+' · 미리듣기':filtered.length?'샘플의 대사는 예시입니다. 실제로는 입력한 대본을 읽습니다.':'이 조건에 맞는 목소리가 없습니다.';
    dialog.querySelector('.voice-grid').innerHTML=filtered.map(v=>`<article class="voice-choice ${v.id===field.value?'selected':''}"><span class="voice-model">${esc(v.model||'기존 기본값')} · ${esc({male:'남성',female:'여성',personal:'내 목소리'}[v.gender]||'')}</span><h3>${esc(v.name)}</h3><p>${esc(v.description||'기존에 사용하던 목소리입니다.')}</p><small>${v.native_language?'음색 기준: '+esc(v.native_language):''} ${v.preview_kind==='reference'?'· 공식 참조 녹음':v.preview_kind==='generated'?'· 한국어 샘플':''}</small><div><button type="button" data-listen="${esc(v.id)}" ${v.preview_url?'':'disabled'}>${v.preview_url?'▷ 미리 듣기':'미리듣기 없음'}</button><button type="button" data-select-voice="${esc(v.id)}" ${v.available?'':'disabled'}>${!v.available?'설치 필요':v.id===field.value?'✓ 선택됨':'이 목소리 사용'}</button></div></article>`).join('');
   };
   const load=async()=>{note.textContent='목소리를 불러오는 중…';dialog.querySelector('[data-voice-reload]').hidden=true;try{
    const response=await fetch('/api/studio/voices',{cache:'no-store'});if(response.status===404)throw Error('새 목소리 선택 기능을 적용하려면 터진게시물 서버를 재시작해 주세요.');const data=await response.json();if(!response.ok)throw Error(data.error||'목소리를 불러오지 못했어요.');if(!dialog.isConnected)return;
    rows=[{id:'',name:'내 목소리 · 기존 기본값',gender:'personal',available:true,description:'VoiceBench에 설정된 기존 목소리를 그대로 사용합니다.'},...data.voices];for(const v of rows)if(v.id)labels[v.id]=v.name;render();
   }catch(e){note.textContent=e.message;dialog.querySelector('[data-voice-reload]').hidden=false;}};
   dialog.querySelector('[data-voice-reload]').onclick=load;
   dialog.querySelector('[data-model]').onchange=e=>{model=e.target.value;render();};
   dialog.onclick=async e=>{
    const filter=e.target.closest('[data-gender]');if(filter){gender=filter.dataset.gender;dialog.querySelectorAll('[data-gender]').forEach(b=>b.setAttribute('aria-pressed',String(b===filter)));render();return;}
    const select=e.target.closest('[data-select-voice]');if(select){field.value=select.dataset.selectVoice;field.dispatchEvent(new Event('input',{bubbles:true}));close();return;}
    const play=e.target.closest('[data-listen]');if(play){const v=rows.find(v=>v.id===play.dataset.listen);audio.pause();audio.src=v.preview_url;audio.dataset.voiceName=v.name;audio.setAttribute('aria-label',v.name+' 미리듣기');audio.hidden=false;note.textContent=v.name+' · 미리듣기';try{await audio.play();}catch{note.textContent='재생하지 못했어요. 다시 누르거나 다른 목소리를 들어보세요.';}}
   };
   audio.onerror=()=>note.textContent='샘플을 불러오지 못했어요. 잠시 후 다시 눌러주세요.';
   await load();
  };
 }
 window.VoicePicker={bind,label};
})();
