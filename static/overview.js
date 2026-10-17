import {brandMotion,contextHint} from './motion.js';
export function createOverview({state,esc,icon,companion,greeting,taskRow,noticeRow,moveSelection}){
  const $=selector=>document.querySelector(selector);
  let section='tasks';
  function render(){
    const pending=state.tasks.filter(t=>t.status==='pending'&&t.data.scope==='personal');
    const ordered=[...pending].sort((a,b)=>Number(b.overdue)-Number(a.overdue)||Number(b.due_soon)-Number(a.due_soon)||(a.data.due_date||'9999').localeCompare(b.data.due_date||'9999'));
    const notices=state.notices.filter(n=>n.status!=='confirmed');
    const urgent=pending.filter(t=>t.overdue||t.due_soon),uncertain=pending.filter(t=>!t.data.due_date||!t.data.deadline_confirmed);
    const caughtUp=!pending.length&&state.tasks.some(t=>t.status==='done');
    if(!$('#overview-board'))$('#content').innerHTML=`<div class="overview-compact"><div class="overview-heading"><div><h1>${greeting()}，${esc(state.session.user.profile.preferred_name||state.session.user.display_name)}。</h1><p>把今天理顺，留一点时间给自己。</p></div><div id="overview-companion"></div></div><div id="overview-brief" class="overview-brief" aria-label="需要留意的事项"></div><section class="panel flush" id="overview-board"><div class="overview-tabs tabs" role="tablist" aria-label="需要处理的事项"><button type="button" class="tab" role="tab" data-overview-section="tasks">待办</button><button type="button" class="tab" role="tab" data-overview-section="notices">待核对通知</button></div><div id="overview-items" role="tabpanel"></div><div class="overview-footer"><a id="overview-all" class="button small plain"></a></div></section><a class="overview-new button" href="#new">${icon('plus')} 处理新通知</a></div>`;
    const pose=caughtUp?'complete':'welcome';if($('#overview-companion').dataset.pose!==pose){$('#overview-companion').innerHTML=companion(pose,'overview-companion');$('#overview-companion').dataset.pose=pose;}
    $('#overview-brief').innerHTML=(urgent.length?`<a class="attention" href="#tasks" data-overview-filter="soon"><b>${urgent.length}</b> 临近或已过期</a>`:'')+(uncertain.length?`<a href="#tasks" data-overview-filter="unverified"><b>${uncertain.length}</b> 期限待核对</a>`:'')+(notices.length?`<a href="#notices"><b>${notices.length}</b> 通知待核对</a>`:'');
    $('#overview-brief').hidden=!urgent.length&&!uncertain.length&&!notices.length;
    const list=section==='tasks'?ordered:notices,limit=matchMedia('(max-width:650px)').matches?2:4;
    for(const tab of document.querySelectorAll('[data-overview-section]')){const active=tab.dataset.overviewSection===section;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;tab.textContent=tab.dataset.overviewSection==='tasks'?`待办 · ${pending.length}`:`待核对 · ${notices.length}`;}
    moveSelection($('.overview-tabs'));
    const started=state.notices.length>0||state.tasks.length>0;
    $('#overview-items').innerHTML=list.length?list.slice(0,limit).map(section==='tasks'?taskRow:noticeRow).join(''):`<div class="overview-empty">${brandMotion(started?'serene':'radar')}<h2>${section==='tasks'?(caughtUp?'已确认的待办都处理好了':started?'暂时没有待完成的事项':'从第一则通知开始'):(started?'通知都已核对':'还没有待核对的通知')}</h2><p>${section==='tasks'?(started?'已确认的待办中，暂时没有待完成事项。也可以去日历看看课程和其他安排。':'带上完整原文，把需要自己办理的步骤留下来。'):'有新的材料时，再放进来就好。'}</p></div>`;
    const all=$('#overview-all');all.href=section==='tasks'?'#tasks':'#notices';all.textContent=`查看全部${section==='tasks'?'待办':'通知'} ${list.length>limit?'('+list.length+') ':''}→`;all.dataset.overviewFilter=section==='tasks'?'pending':'';
  }
  document.addEventListener('click',event=>{const tab=event.target.closest('[data-overview-section]');if(tab){section=tab.dataset.overviewSection;render();}});
  return {render};
}
