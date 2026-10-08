(function(root){
  'use strict';
  const memory=new Map();
  function remedy(reason){
    const text=String(reason||'').toLowerCase();
    if(/429|rate.limit|요청 제한|too many/.test(text))return {text:'해당 서비스 요청을 멈추고 제한이 해제된 뒤 다시 수집하세요. 즉시 반복 실행하지 마세요.',href:'accounts.html#help-rate-limit',label:'요청 제한 해결 방법'};
    if(/captcha|캡차|verification|challenge|checkpoint|인증|본인 확인/.test(text))return {text:'전용 Chrome에 표시된 인증을 직접 완료한 뒤 수집을 다시 실행하세요.',href:'accounts.html#help-login',label:'인증 해결 방법'};
    if(/login|session|로그인|세션/.test(text))return {text:'수집 서버 PC의 전용 Instagram Chrome에서 로그인 상태를 확인한 뒤 다시 수집하세요.',href:'accounts.html#help-login',label:'로그인 복구 방법'};
    if(/사용할 수 없|찾을 수 없|존재하지|not.found|404|비공개/.test(text))return {text:'계정 프로필을 열어 아이디 변경·삭제·비공개 여부를 확인하세요. 더 이상 수집하지 않을 계정은 관리 목록에서 제외하세요.',href:'accounts.html#account-list',label:'계정 확인·관리'};
    return {text:'마지막 수집 기록과 계정별 상태를 확인하고, 원인을 해결한 뒤 수집을 다시 실행하세요.',href:'accounts.html#collection-help',label:'수집 복구 방법'};
  }
  function collection(data, accounts, report, now=Date.now()/1000){
    const c=data.collection||{},run=c.last_run, schedule=data.schedule||{};
    const managed=new Set(accounts.map(a=>a.username.toLowerCase()));
    const notes=String(run ? (run.notes||'') : (report.notes||[]).join('\n')).split('\n').filter(Boolean);
    const relevant=notes.filter(note=>{const m=/^@([a-z0-9_.]+):/i.exec(note);return !m||managed.has(m[1].toLowerCase());});
    const removed=notes.length-relevant.length;
    const retiredOnly=removed>0&&!relevant.length&&!run?.stop_reason&&!run?.accounts_skipped&&(!run||run.accounts_failed<=removed);
    const stamp=c.newest_post_update?new Date(c.newest_post_update*1000).toLocaleString('ko-KR'):'아직 없음';
    const failed=!retiredOnly&&(['failure','blocked','partial_failure'].includes(c.state)||relevant.length>0);
    const identity=[run?.id,run?.started_at,run?.finished_at,c.newest_post_update,c.state,run?.stop_reason,relevant,retiredOnly];
    let model={title:'데이터 갱신 '+stamp,detail:'수집 기록과 계정별 상태는 레퍼런스 계정에서 확인할 수 있습니다.',tone:'info',identity,
      actions:[{label:'수집 기록 보기',href:'accounts.html#collection-health'}]};
    if(c.state==='running')return {...model,title:'수집 진행 중',detail:'완료되면 갱신 결과가 표시됩니다. 중복 실행하지 않아도 됩니다.'};
    if(failed){
      const reason=[run?.stop_reason,...relevant].filter(Boolean).join(' · '), help=remedy(reason);
      model={...model,title:'지난 수집 기록 · 확인이 필요한 항목',detail:reason||'이전 수집에서 일부 계정을 완료하지 못했습니다.',solution:help.text,tone:'warning',actions:[help]};
    } else if(!c.newest_post_update||now-c.newest_post_update>26*3600||schedule.missed_today){
      model={...model,title:!c.newest_post_update?'아직 수집 데이터가 없습니다.':'최근 수집 데이터 확인이 필요합니다.',
        detail:'데이터 갱신 '+stamp+(schedule.missed_today?' · 오늘 예약 수집이 확인되지 않았습니다.':''),tone:'warning',
        solution:'서버 PC에서 자동 수집 일정을 확인하거나 수동 수집을 실행하세요. 새로고침만으로 Instagram 데이터를 다시 수집하지는 않습니다.',
        actions:[{label:'수집 실행·일정 확인 방법',href:'accounts.html#help-collect'}]};
    }
    if(c.last_success_at>(report.generated_at||0)){
      model={...model,detail:model.detail+' · 현재 목록보다 새로운 수집 결과가 있습니다.',actions:[...model.actions,{label:'최신 목록 새로고침',reload:true}]};
    }
    return model;
  }
  function show(el,model,{dismissible=true}={}){
    if(!el)return;
    const signature=JSON.stringify(model),key='hp-dismissed-notice:'+el.id;
    let dismissed=memory.get(key);try{dismissed=localStorage.getItem(key)||dismissed;}catch(_){}
    el.replaceChildren();el.className='banner notice '+(model.tone||'info');el.setAttribute('role','status');
    const body=document.createElement('div');body.className='notice-body';
    const title=document.createElement('strong');title.textContent=model.title;body.append(title);
    if(model.detail){const p=document.createElement('p');p.textContent=model.detail;body.append(p);}
    if(model.solution){const p=document.createElement('p');p.className='notice-solution';p.textContent='해결 방법: '+model.solution;body.append(p);}
    const actions=document.createElement('div');actions.className='notice-actions';
    for(const action of model.actions||[]){
      const button=document.createElement(action.href?'a':'button');button.className='btn ghost';button.textContent=action.label;
      if(action.href)button.href=action.href;else {button.type='button';button.onclick=action.run||(()=>location.reload());}
      actions.append(button);
    }
    body.append(actions);el.append(body);
    if(!dismissible){el.hidden=false;return;}
    const close=document.createElement('button');close.type='button';close.className='icon-button notice-close';close.textContent='×';close.setAttribute('aria-label','안내 닫기');
    close.onclick=()=>{memory.set(key,signature);try{localStorage.setItem(key,signature);}catch(_){}el.hidden=true;};
    el.append(close);el.hidden=dismissed===signature;
  }
  const api={show,collection,remedy};root.HotpostNotices=api;
  if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof window==='object'?window:globalThis);
