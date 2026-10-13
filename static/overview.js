export function createOverview({state,esc,icon,companion,greeting,taskRow,noticeRow,moveSelection}){
  const $=selector=>document.querySelector(selector);
  let section='tasks';
  function render(){
    const pending=state.tasks.filter(t=>t.status==='pending'&&t.data.scope==='personal');
    const ordered=[...pending].sort((a,b)=>Number(b.overdue)-Number(a.overdue)||Number(b.due_soon)-Number(a.due_soon)||(a.data.due_date||'9999').localeCompare(b.data.due_date||'9999'));
    const notices=state.notices.filter(n=>n.status!=='confirmed');
    if(!$('#overview-board'))$('#content').innerHTML=`<div class="overview-compact"><div class="overview-heading"><div><h1>${greeting()}，${esc(state.session.user.display_name)}。</h1><p>把今天理顺，留一点时间给自己。</p></div>${companion('welcome','overview-companion')}</div><section class="panel flush" id="overview-board"><div class="overview-tabs tabs" role="tablist" aria-label="需要处理的事项"><button type="button" class="tab" role="tab" data-overview-section="tasks">待办</button><button type="button" class="tab" role="tab" data-overview-section="notices">待核对通知</button></div><div id="overview-items" role="tabpanel"></div><div class="overview-footer"><a id="overview-all" class="button small plain"></a></div></section><a class="overview-new button" href="#new">${icon('plus')} 处理新通知</a></div>`;
    const list=section==='tasks'?ordered:notices,limit=matchMedia('(max-width:650px)').matches?2:4;
    for(const tab of document.querySelectorAll('[data-overview-section]')){const active=tab.dataset.overviewSection===section;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.textContent=tab.dataset.overviewSection==='tasks'?`待办 · ${pending.length}`:`待核对 · ${notices.length}`;}
    moveSelection($('.overview-tabs'));
    $('#overview-items').innerHTML=list.length?list.slice(0,limit).map(section==='tasks'?taskRow:noticeRow).join(''):`<div class="overview-empty">${icon('check')}<h2>${section==='tasks'?'暂时没有待办':'通知都已核对'}</h2><p>${section==='tasks'?'可以去日历看看课程和其他安排。':'有新的材料时，再放进来就好。'}</p></div>`;
    const all=$('#overview-all');all.href=section==='tasks'?'#tasks':'#notices';all.textContent=`查看全部${section==='tasks'?'待办':'通知'} ${list.length>limit?'('+list.length+') ':''}→`;all.dataset.overviewFilter=section==='tasks'?'pending':'';
  }
  document.addEventListener('click',event=>{const tab=event.target.closest('[data-overview-section]');if(tab){section=tab.dataset.overviewSection;render();}});
  return {render};
}
