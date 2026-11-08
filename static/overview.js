import {taskIsPending} from './action-plans.js';
import {taskMatchesFilter} from './workflow.js';
import {calendarEntries,dayKey,addDays} from './calendar-model.js';
import {isNoticeOpen} from './notice-intake.js';
import {taskTimeLabel,needsTimingReview,taskOnDay} from './notice-timing.js';

// Summaries describe saved records, never an AI recommendation or a submission.
export function overviewData(tasks, notices) {
  const personal = tasks.filter(task => task.data.scope === 'personal');
  const pending = personal.filter(taskIsPending);
  const ordered = [...pending].sort((a, b) =>
    Number(!!b.followup_due) - Number(!!a.followup_due) ||
    Number(!!b.overdue) - Number(!!a.overdue) ||
    Number(!!b.due_soon) - Number(!!a.due_soon) ||
    (a.data.due_date || a.data.scheduled?.start_date || '9999').localeCompare(b.data.due_date || b.data.scheduled?.start_date || '9999'));
  return {
    pending, ordered,
    notices: notices.filter(notice => notice.status !== 'confirmed'&&isNoticeOpen(notice)&&notice.recommended!==false&&!['closed','irrelevant','tracking'].includes(notice.intent)),
    tracking: notices.filter(notice => isNoticeOpen(notice)&&notice.intent==='tracking'),
    urgent: pending.filter(task => task.overdue || task.due_soon),
    uncertain: pending.filter(needsTimingReview),
    followup: tasks.filter(task => taskMatchesFilter(task, 'followup')),
    changed: tasks.filter(task => taskMatchesFilter(task, 'changes')),
    sync: tasks.filter(task => taskMatchesFilter(task, 'sync')),
    completed: personal.filter(task => task.status === 'done').length,
    total: personal.filter(task => task.status === 'done' || taskIsPending(task)).length,
  };
}

export function overviewWeek(tasks, today = dayKey()) {
  return Array.from({length:7}, (_, index) => {
    const day = addDays(today, index);
    return {day, tasks: tasks.filter(task => task.data.scope === 'personal' && taskIsPending(task) && taskOnDay(task.data,day))};
  });
}

export function createOverview({state,esc,icon,taskRow,noticeRow}) {
  const $=selector=>document.querySelector(selector);
  let owner=null,section='tasks';
  const role=()=>state.session?.user?.profile?.campus_role||'';
  function todayAgenda(){
    const today=dayKey(),items=calendarEntries(state.arrangements||[],state.tasks,today,today);
    const name=role()==='student'?'今天的课程与安排':role()==='teacher'?'今天的教学与安排':'今天的工作安排';
    return `<section class="home-section home-agenda"><div class="home-section-heading"><h2>${name}</h2><a href="#calendar">全部日程 ${icon('arrow')}</a></div>${items.length?items.slice(0,4).map(e=>`<a class="home-agenda-row" href="#${e.source==='arrangement'?'calendar':'tasks'}/${esc(e.id)}"><time>${e.allDay?'全天':esc(e.start||'待核对')}</time><span><strong>${esc(e.title)}</strong>${e.location?`<small>${esc(e.location)}</small>`:''}</span>${icon('arrow')}</a>`).join('')+(items.length>4?`<a class="home-more" href="#calendar">还有 ${items.length-4} 项安排 →</a>`:''):`<p class="home-empty-line">今天暂无已保存安排 <a href="#calendar">${role()==='student'?'导入课表或添加安排':'添加安排'} →</a></p>`}</section>`;
  }
  function render(){
    const data=overviewData(state.tasks,state.notices);
    if(owner!==state.session.user.id){
      owner=state.session.user.id;
      section=role()==='staff'&&data.followup.length?'followup':data.pending.length?'tasks':data.notices.length?'notices':'tasks';
    }
    const title=role()==='student'?'我的事务':role()==='teacher'?'教学与个人事务':role()==='staff'?'工作与个人事务':'我的事务';
    $('#content').innerHTML=`<section class="personal-home" data-home-context="personal"><header class="home-heading"><div><h1>${title}</h1><p>${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date())}</p></div><a class="button primary small" href="#new">${icon('plus')} 收通知</a></header>
      <div class="home-counts" aria-label="个人事务概览"><a href="#tasks" data-overview-filter="pending">待办 <b>${data.pending.length}</b></a><a href="#notices">通知 <b>${data.notices.length}</b></a><a href="#tasks" data-overview-filter="followup">待跟进 <b>${data.followup.length}</b></a></div>
      ${data.tracking.length?`<p class="home-empty-line" role="status">系统正在整理 ${data.tracking.length} 则信息，无须逐条处理。<a href="#notices">查看进度 →</a></p>`:''}
      ${data.urgent.length||data.changed.length||data.uncertain.length?`<div class="home-attention">${data.urgent.length?`<a href="#tasks" data-overview-filter="soon">${data.urgent.length} 项临近或已过期</a>`:''}${data.changed.length?`<a href="#tasks" data-overview-filter="changes">${data.changed.length} 项变更待核实</a>`:''}${data.uncertain.length?`<a href="#tasks" data-overview-filter="unverified">${data.uncertain.length} 项时间待核对</a>`:''}</div>`:''}
      <div class="home-columns ${role()==='teacher'?'agenda-first':''}"><section class="home-section home-inbox" id="overview-board"><div class="home-section-heading"><h2>${role()==='staff'?'办理与跟进':'需要处理'}</h2><a href="#chat/new">问小信使 ${icon('spark')}</a></div><div class="home-tabs" role="tablist" aria-label="需要处理的事项">${[['tasks','待办'],['notices','通知'],['followup','跟进']].map(([key,label])=>`<button type="button" role="tab" id="overview-tab-${key}" aria-controls="overview-items" data-overview-section="${key}">${label}</button>`).join('')}</div><div id="overview-items" role="tabpanel"></div><a id="overview-all" class="home-more"></a></section>${todayAgenda()}</div></section>`;
    renderItems(data);
  }
  function renderItems(data){
    const list=section==='notices'?data.notices:section==='followup'?data.followup:data.ordered;
    for(const tab of document.querySelectorAll('[data-overview-section]')){
      const active=tab.dataset.overviewSection===section;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
    }
    const items=$('#overview-items');items.setAttribute('aria-labelledby','overview-tab-'+section);
    items.innerHTML=list.length?list.slice(0,6).map(item=>section==='notices'?noticeRow(item):taskRow(item)).join(''):`<p class="home-empty-line">${section==='notices'?'暂无待核对通知':section==='followup'?'暂无待跟进事项':'暂无待完成事项'}</p>`;
    const all=$('#overview-all');all.href=section==='notices'?'#notices':'#tasks';all.textContent=`查看全部${section==='notices'?'通知':'事项'}${list.length?'（'+list.length+'）':''} →`;all.dataset.overviewFilter=section==='tasks'?'pending':section==='followup'?'followup':'';
  }
  document.addEventListener('click',event=>{const tab=event.target.closest('[data-overview-section]');if(tab){section=tab.dataset.overviewSection;renderItems(overviewData(state.tasks,state.notices));}});
  document.addEventListener('keydown',event=>{
    const tab=event.target.closest('[data-overview-section]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const keys=['tasks','notices','followup'],index=keys.indexOf(section);section=keys[event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowLeft'?2:1))%3];renderItems(overviewData(state.tasks,state.notices));$('#overview-tab-'+section).focus();
  });
  return {render};
}
