/* Independent entry point. Files join the same task-scoped upload queue. */
(() => {
  'use strict';
  const key='studio-self-shot-brief-v1';
  const dialog=document.createElement('dialog');dialog.className='self-shot-dialog';
  dialog.setAttribute('aria-labelledby','self-shot-title');
  dialog.innerHTML=`<form class="self-shot-form"><div class="dialog-head"><div><div class="eyebrow">내 촬영 영상으로</div><h2 id="self-shot-title">새 쇼츠 만들기</h2></div><button type="button" data-own-close class="icon" aria-label="새 제작 닫기">×</button></div>
    <p>촬영 영상 최대 20개로, 기존 제작실의 스타일에 맞춰 제품 쇼츠를 만듭니다.</p>
    <fieldset class="self-shot-modes"><legend>대본 준비 방법</legend><label><input type="radio" name="script_mode" value="automatic" checked> AI가 대본 쓰기</label><label><input type="radio" name="script_mode" value="manual"> 내 대본 그대로 사용</label></fieldset>
    <label>작업 이름 <span class="self-shot-optional">선택</span><input name="title" maxlength="120" placeholder="비워두면 제품명 또는 대본으로 정합니다"></label>
    <div data-own-auto><label>주제 또는 제품명<input name="product" maxlength="300" required placeholder="예: 접이식 실리콘 도시락통"></label>
      <label>제품 링크 <span class="self-shot-optional">선택</span><input name="product_url" type="url" maxlength="2000" placeholder="https://"></label>
      <details class="self-shot-extra"><summary>제품 특징·사용 경험·댓글 키워드 추가 <span class="self-shot-optional">선택</span></summary><div>
      <label>핵심 특징·제작 의도 <span class="self-shot-optional">선택</span><textarea name="details" maxlength="3000" rows="3" placeholder="예: 다 먹은 뒤 접어서 가방에 넣는 편리함을 강조해 주세요"></textarea></label>
      <label>실제 사용 경험 <span class="self-shot-optional">선택</span><textarea name="experience" maxlength="1500" rows="2" placeholder="직접 경험한 내용이 있다면 적어주세요"></textarea></label>
      <label>댓글 키워드 <span class="self-shot-optional">선택</span><input name="comment_keyword" maxlength="40" placeholder="비워두면 ‘나도’"></label></div></details></div>
    <div data-own-manual hidden><label>영상에서 읽을 대본<textarea name="text" maxlength="3000" rows="8" placeholder="입력한 대본 그대로 내 복제 목소리가 읽습니다"></textarea></label><p>문장 수정이나 댓글 문구 추가 없이 그대로 음성과 자막에 사용합니다.</p></div>
    <p class="self-shot-help">기본 음성은 내 목소리 복제입니다. 사용할 장면은 AI가 고르며, 분량이 부족하면 내 촬영 장면을 재사용하고 결과에 표시합니다.</p>
    <p data-own-error role="alert" hidden></p><div class="self-shot-footer"><button type="button" class="secondary" data-own-close>나중에</button><button type="submit" class="primary" data-own-submit>다음 · 촬영 영상 추가</button></div></form>`;
  document.body.append(dialog);
  const form=dialog.querySelector('form'), field=name=>form.elements.namedItem(name);
  let task=null, creationKey=null, sending=false;
  const newKey=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
  const names=['script_mode','title','product','product_url','details','experience','comment_keyword','text'];
  const values=()=>Object.fromEntries(names.map(name=>[name,field(name).value]));
  function mode(){
    const manual=field('script_mode').value==='manual';
    dialog.querySelector('[data-own-auto]').hidden=manual;dialog.querySelector('[data-own-manual]').hidden=!manual;
    field('product').required=!manual;field('text').required=manual;
    for(const name of ['product','product_url','details','experience','comment_keyword'])field(name).disabled=manual;
    field('text').disabled=!manual;
  }
  function error(text=''){const box=dialog.querySelector('[data-own-error]');box.textContent=text;box.hidden=!text;}
  function open(existing=null){
    if(sending)return;
    task=existing;
    let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}');}catch{}
    const brief=existing?.self_shot||saved;
    form.reset();
    for(const name of names)if(brief[name]!==undefined){
      if(name==='script_mode')form.querySelector('input[value="'+(brief[name]==='manual'?'manual':'automatic')+'"]').checked=true;
      else field(name).value=brief[name];
    }
    creationKey=existing?null:saved.creation_key||newKey();
    dialog.querySelector('.self-shot-extra').open=Boolean(brief.details||brief.experience||brief.comment_keyword);
    dialog.querySelector('#self-shot-title').textContent=existing?'제작 정보 수정':'새 쇼츠 만들기';
    dialog.querySelector('[data-own-submit]').textContent=existing?'제작 정보 저장':'다음 · 촬영 영상 추가';
    mode();error();dialog.showModal();
    field(field('script_mode').value==='manual'?'text':'product').focus();
  }
  form.addEventListener('input',()=>{mode();if(!task)localStorage.setItem(key,JSON.stringify({...values(),creation_key:creationKey}));});
  form.addEventListener('click',event=>{if(event.target.closest('[data-own-close]')&&!sending)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(sending)event.preventDefault();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(sending)return;
    sending=true;error();const button=dialog.querySelector('[data-own-submit]'),label=button.textContent;
    button.disabled=true;button.textContent=task?'저장 중…':'작업 만드는 중…';button.setAttribute('aria-busy','true');
    try{
      const payload={...values(),...(task?{revision:task.revision}:{creation_key:creationKey})};
      if(payload.script_mode==='manual')payload.product_url='';
      const result=await window.ProductionFlow.api(task?'/'+task.id+'/save-self-shot-brief':'/self-shot',payload);
      if(!task)localStorage.removeItem(key);
      dialog.close();document.dispatchEvent(new CustomEvent('studio-self-shot-created',{detail:result}));
    }catch(exc){error(window.StudioBoard.message(exc.message));}
    finally{sending=false;button.disabled=false;button.textContent=label;button.removeAttribute('aria-busy');}
  });
  document.querySelector('#new-self-shot').addEventListener('click',()=>open());
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-self-shot-edit]');if(button){const root=button.closest('[aria-label="작업 상세"]');if(root?._task)open(root._task);}
  });
  window.SelfShot={open};
})();
