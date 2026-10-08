/* Collection receipt: registration and execution status are separate facts. */
(()=>{
 const root=document.querySelector('#collection-intake');if(!root)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const work=id=>`studio.html?work=${encodeURIComponent(id)}`;
 let refreshing=false,busy=false,last='';
 async function refresh(){
  if(refreshing||busy)return;refreshing=true;
  try{
   const r=await fetch('/api/studio/intake',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();
   root.hidden=!d.available;if(!d.available)return;
   const snapshot=JSON.stringify(d);if(snapshot===last)return;last=snapshot;
   const opened=root.querySelector('[data-intake-candidates]')?.open;
   const detailOpen=root.querySelector('[data-intake-detail]')?.open;
   const problemsOpen=root.querySelector('[data-intake-problems]')?.open;
   const updated=d.updated_at?new Date(d.updated_at*1000).toLocaleString('ko-KR',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}):'갱신 중';
   root.innerHTML=`<header><div><h2>최근 수집</h2><p>${esc(updated)}</p></div><a href="index.html">게시물 ↗</a></header>
    <div class="intake-stats">${[['새로 발견한 게시물',d.new_posts],['새 핫 영상',d.new_hot_videos],['자동 신규 등록',d.created],['기존 작업 연결',d.existing]].map(([label,n])=>`<div><strong>${d.ready?n:'—'}</strong><span>${label}</span></div>`).join('')}</div>
    <details data-intake-detail ${detailOpen?'open':''}><summary>수집 연결 내역${d.blocked?` · 확인 필요 ${d.blocked}개`:''}</summary><p class="intake-policy">${!d.ready?'수집 결과를 갱신하고 있어요. 완료 후 신규 영상과 제작실 연결 결과가 표시됩니다.':!d.selection_ready?(d.enabled?'자동 선정 결과를 기다리고 있어요.':'자동 선정이 꺼져 있어요. 아래에서 만들 영상을 직접 고르세요.'):'한국시간 오늘 최초 감지된 핫 영상 중 상위 2개를 자동 선정합니다. 이전 감지일은 소모 처리하며, 기존 작업은 중복 추가하지 않습니다.'}</p>
    ${d.rows.length?`<details data-intake-problems ${problemsOpen?'open':''}><summary class="${d.blocked?'intake-warning':''}">자동 선정 ${d.rows.length}개 · ${d.blocked?`진행 불가 ${d.blocked}개 · 원인과 해결방법 보기`:'연결 결과 보기'}</summary><div class="intake-results">`:''}${d.rows.map(v=>`<article><div class="intake-row-heading"><b>${v.rank}위 · ${{new:'신규 등록',existing:'기존 작업',skipped:'선정 보류',pending:'등록 대기'}[v.registration]}</b><span class="intake-state ${esc(v.state)}">${esc(v.label)}</span></div><h3>${esc(v.title||v.shortcode)}</h3><p>${esc(v.reason)}</p><p class="intake-solution">${esc(v.solution)}</p>${v.task_id?`<a class="button secondary" href="${work(v.task_id)}">${v.state==='blocked'?'문제 확인하고 해결하기':'작업 열기'} →</a>`:''}</article>`).join('')}${d.rows.length?'</div></details>':''}
    ${d.candidates.length?`<details data-intake-candidates ${opened?'open':''}><summary>이번에 발견한 핫 영상 ${d.candidates.length}개 · 직접 골라 제작하기</summary><p>추가하면 소스 확보부터 제작을 시작합니다. 이미 추가한 영상은 기존 작업을 엽니다.</p><div class="intake-candidates">${d.candidates.map(v=>`<article><div><small>@${esc(v.username)}</small><h3>${esc(v.title)}</h3></div>${v.task_id?`<a class="button secondary" href="${work(v.task_id)}">기존 작업 열기</a>`:`<button class="primary" data-intake-add="${esc(v.shortcode)}">이 영상 제작 시작</button>`}</article>`).join('')}</div></details>`:''}</details><p data-intake-error role="status" hidden></p>`;
  }catch{root.hidden=false;let note=root.querySelector('[data-intake-error]');if(!note){root.innerHTML='<p data-intake-error role="status"></p>';note=root.firstElementChild;}note.hidden=false;note.textContent='수집 연결 상태를 불러오지 못했어요. 잠시 후 자동으로 다시 확인합니다.';last='';}
  finally{refreshing=false;}
 }
 root.addEventListener('click',async e=>{
  const button=e.target.closest('[data-intake-add]');if(!button||busy)return;
  busy=true;button.disabled=true;button.textContent='제작실에 추가 중…';
  try{
   const r=await fetch('/api/studio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({shortcodes:[button.dataset.intakeAdd],automatic:true,only_new:true})});const d=await r.json();
   if(!r.ok)throw Error(d.error||'추가하지 못했어요. 다시 시도하세요.');
   location.href=work(d.tasks[0].id);
  }catch(e){const note=root.querySelector('[data-intake-error]');note.hidden=false;note.textContent=e.message;button.disabled=false;button.textContent='이 영상 제작 시작';busy=false;}
 });
 refresh();setInterval(refresh,30000);
})();
