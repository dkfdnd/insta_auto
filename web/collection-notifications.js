/* Collection notices remain available after reading; only the new badge clears. */
(() => {
  const anchor=document.getElementById('collection-notifications');
  if(!anchor)return;
  const toggle=document.getElementById('collection-notification-toggle');
  const panel=document.getElementById('collection-notification-panel');
  const close=document.getElementById('collection-notification-close');
  const badge=document.getElementById('collection-notification-count');
  const content=document.getElementById('collection-health');
  const key='hp-read-collection-notice';
  let signature='',seen='',model=null;
  try{seen=localStorage.getItem(key)||'';}catch(_){}
  function markRead(){
    if(!signature)return;
    seen=signature;try{localStorage.setItem(key,seen);}catch(_){}
  }
  function refreshBadge(){
    const unread=model?.tone==='warning'&&signature!==seen;
    badge.hidden=!unread;
    toggle.setAttribute('aria-label',unread?'수집 알림 · 새 알림 1개':'수집 알림');
    toggle.title=unread?'확인하지 않은 수집 알림이 있어요':'수집 알림';
  }
  function position(){
    const bottom=document.querySelector('header.top')?.getBoundingClientRect().bottom||130;
    panel.style.setProperty('--collection-panel-top',Math.round(bottom+8)+'px');
    const alignLeft=toggle.getBoundingClientRect().right<Math.min(420,window.innerWidth-24)+12;
    panel.style.setProperty('--collection-panel-left',alignLeft?'0px':'auto');
    panel.style.setProperty('--collection-panel-right',alignLeft?'auto':'0px');
  }
  function setOpen(open,restoreFocus=false){
    panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));
    if(open){position();markRead();refreshBadge();close.focus();}
    else if(restoreFocus)toggle.focus();
  }
  toggle.addEventListener('click',()=>setOpen(panel.hidden,true));
  close.addEventListener('click',()=>setOpen(false,true));
  document.addEventListener('click',event=>{if(!panel.hidden&&!anchor.contains(event.target))setOpen(false);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){event.preventDefault();setOpen(false,true);}});
  window.addEventListener('resize',()=>{if(!panel.hidden)position();});
  window.CollectionNotifications={update(next){
    model=next;
    const nextSignature=JSON.stringify(next);
    if(nextSignature!==signature){
      window.HotpostNotices.show(content,next,{dismissible:false});
      signature=nextSignature;
    }
    document.getElementById('collection-notification-loading').hidden=true;
    if(!panel.hidden)markRead();
    refreshBadge();
  }};
})();
