(function () {
  const defaults = {detection:'today',period:24,kind:'all',tier:1,sort:'rank',assessment:'all',account:''};
  async function request(options) {
    const response=await fetch('/api/display-settings',{cache:'no-store',...options});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'화면 설정 저장/조회 실패');
    return data.values;
  }
  function describe(s) {
    return [s.detection==='today'?'오늘 발견 · 한국 시간 00시부터':'최근 '+({24:'24시간',72:'3일',168:'7일',336:'14일',720:'30일'}[s.period])+' 내 발견',
      {all:'전체 유형',video:'릴스',image:'사진'}[s.kind],s.tier?'🔥'.repeat(s.tier)+' 이상':'전체 등급',
      {rank:'급상승순',views:'조회수순',comments:'댓글순',likes:'좋아요순',recent:'최근 발견순'}[s.sort],
      {all:'모든 판정',confirmed:'성과 확인',provisional:'잠정 후보'}[s.assessment],s.account?'@'+s.account:'모든 계정'].join(' · ');
  }
  function theme(button) {
    const apply=t=>{if(t)document.documentElement.dataset.theme=t;button.textContent=(document.documentElement.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'))==='dark'?'☀️':'🌙';};
    try{apply(JSON.parse(localStorage.getItem('hp-theme')));}catch(_){apply();}
    button.onclick=()=>{const next=button.textContent==='🌙'?'dark':'light';apply(next);try{localStorage.setItem('hp-theme',JSON.stringify(next));}catch(_){}};
  }
  window.HotpostDisplay={defaults,load:()=>request(),save:values=>request({method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({values})}),describe,theme};
})();
