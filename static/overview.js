import {taskIsPending} from './action-plans.js';
import {brandMotion} from './motion.js';
import {taskMatchesFilter} from './workflow.js';
import {animateSurface,numberMarkup,ringMarkup} from './experience-system.js';
import {dayKey,addDays} from './calendar-model.js';

// Summaries describe saved records, never an AI recommendation or a submission.
export function overviewData(tasks, notices) {
  const personal = tasks.filter(task => task.data.scope === 'personal');
  const pending = personal.filter(taskIsPending);
  const ordered = [...pending].sort((a, b) =>
    Number(!!b.followup_due) - Number(!!a.followup_due) ||
    Number(!!b.overdue) - Number(!!a.overdue) ||
    Number(!!b.due_soon) - Number(!!a.due_soon) ||
    (a.data.due_date || '9999').localeCompare(b.data.due_date || '9999'));
  return {
    pending, ordered,
    notices: notices.filter(notice => notice.status !== 'confirmed'),
    urgent: pending.filter(task => task.overdue || task.due_soon),
    uncertain: pending.filter(task => !task.data.due_date || !task.data.deadline_confirmed),
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
    return {day, tasks: tasks.filter(task => task.data.scope === 'personal' && taskIsPending(task) && task.data.due_date === day)};
  });
}

export function createOverview({state,esc,icon,companion,greeting,taskRow,noticeRow,moveSelection}) {
  const $ = selector => document.querySelector(selector);
  let section = 'tasks', owner = null, focusIndex = 0, selectedDay = dayKey();
  function render() {
    if (owner !== state.session.user.id) { owner = state.session.user.id; section = 'tasks'; focusIndex = 0; selectedDay = dayKey(); }
    const {pending,ordered,notices,urgent,uncertain,followup,changed,sync,completed,total} = overviewData(state.tasks,state.notices);
    const caughtUp = !pending.length && completed > 0;
    if (!$('#overview-board')) {
      $('#content').innerHTML = `<div class="overview-compact">
        <h1 class="sr-only">我的工作台</h1>
        <div class="overview-launch">
          <section class="focus-deck" aria-label="重点事项卡片" data-reveal><div class="deck-underlay" aria-hidden="true"></div><div class="deck-underlay second" aria-hidden="true"></div><section id="overview-focus" class="overview-focus" aria-label="优先查看"></section></section>
        </div>
        <div id="action-metrics" class="action-metrics" aria-label="办理概览"></div>
        <section id="overview-week" class="overview-week" aria-label="未来七天的通知期限" data-reveal></section>
        <div class="overview-workspace">
          <section class="panel flush" id="overview-board">
            <div class="overview-board-heading"><div><h2>我的行动清单</h2></div>${icon('tasks')}</div>
            <div class="overview-tabs tabs" role="tablist" aria-label="需要处理的事项">
              ${[['tasks','个人行动'],['followup','办理跟进'],['notices','通知核对']].map(([key,label])=>`<button type="button" class="tab" id="overview-tab-${key}" role="tab" aria-controls="overview-items" data-overview-section="${key}">${label}</button>`).join('')}
            </div>
            <div id="overview-items" role="tabpanel" tabindex="0"></div>
            <div class="overview-footer"><a id="overview-all" class="button small plain"></a></div>
          </section>
          <aside class="overview-aside">
            <section class="overview-reminders" aria-labelledby="overview-reminders-title"><div class="aside-heading">${icon('clock')}<h2 id="overview-reminders-title">值得留意</h2></div><div id="overview-brief" class="overview-brief"></div></section>
            <section id="overview-progress" class="overview-progress" aria-label="个人行动完成情况"></section>
          </aside>
        </div>
      </div>`;
    }

    renderFocus(ordered,notices,caughtUp);
    $('#action-metrics').innerHTML = [
      ['待完成',pending.length,'pending','tasks','个人行动'],
      ['待跟进',followup.length,'followup','history','提交、补件与结果'],
      ['待核实事项',changed.length,'changes','shield','变化与办理影响'],
      ['日历待同步',sync.length,'sync','calendar','核对设备中的安排'],
    ].map(([label,count,filter,symbol,note])=>`<a class="action-metric ${count&&filter!=='pending'?'attention':''}" href="#tasks" data-overview-filter="${filter}"><span class="metric-symbol">${icon(symbol)}</span><span class="metric-label">${label}</span><strong>${numberMarkup(count)}</strong><small>${note}</small>${icon('arrow')}</a>`).join('');
    renderWeek();
    $('#overview-brief').innerHTML = [
      [urgent.length,'临近或已过期','soon','attention'],
      [uncertain.length,'期限待核对','unverified',''],
    ].map(([count,label,filter,cls])=>`<a class="${count?cls:''}" href="#tasks" data-overview-filter="${filter}"><span>${label}</span><b>${count}</b>${icon('arrow')}</a>`).join('')+`<a href="#notices"><span>通知待核对</span><b>${notices.length}</b>${icon('arrow')}</a>`;
    $('#overview-progress').innerHTML = `<div class="between"><h2>完成记录</h2>${icon('check')}</div><div class="completion-summary">${ringMarkup(completed,total,'个人行动完成情况')}<div><strong>${completed}<small> / ${total} 项</small></strong><p>${total?`还有 ${total-completed} 项待完成`:'暂时没有个人行动'}</p></div></div><a href="#tasks" data-overview-filter="done">回看已完成的事 ${icon('arrow')}</a>`;
    renderItems({pending,ordered,notices,followup},caughtUp);
  }
  function renderFocus(ordered,notices,caughtUp) {
    focusIndex = Math.min(focusIndex, Math.max(0, ordered.length - 1));
    const focus = ordered[focusIndex];
    const focusLabel = focus?.followup_due ? '到了跟进时间' : focus?.overdue ? '期限已过，核对进展' : focus?.due_soon ? '近期需要留意' : '接着推进这件事';
    $('#overview-focus').innerHTML = focus
      ? `<div class="focus-label"><span class="focus-dot"></span>${focusLabel}</div><div class="focus-card-content"><h2>${esc(focus.data.title)}</h2><p>${focus.data.due_date?`${icon('calendar')} ${esc(focus.data.due_date)}${focus.data.due_time?' '+esc(focus.data.due_time):''}${focus.data.deadline_confirmed?'':' · 期限待确认'}`:'期限待核对，可先查看原文'}</p><div class="focus-source">${esc(focus.notice_title||'已保存的个人行动')}</div></div><button type="button" class="button" data-workflow-task="${esc(focus.id)}">查看办理详情 ${icon('arrow')}</button>${ordered.length>1?`<div class="deck-controls"><span aria-live="polite">${focusIndex+1} / ${ordered.length} 项待完成</span><div><button type="button" class="icon-button" data-focus-step="-1" aria-label="上一项重点事项" ${focusIndex===0?'disabled':''}>${icon('back')}</button><button type="button" class="icon-button" data-focus-step="1" aria-label="下一项重点事项" ${focusIndex===ordered.length-1?'disabled':''}>${icon('arrow')}</button></div></div>`:''}`
      : `<div class="focus-label"><span class="focus-dot"></span>${caughtUp?'已完成':'待处理'}</div><h2>${notices.length?'还有通知等你核对':caughtUp?'暂无待完成事项':'暂无通知'}</h2>${notices.length?`<p>${notices.length} 则通知待核对</p>`:''}<a class="button" href="${notices.length?'#notices':'#new'}">${notices.length?'去核对通知':'添加通知'} ${icon('arrow')}</a>`;
  }
  function renderItems({pending,ordered,notices,followup},caughtUp) {
    const list = section === 'tasks' ? ordered : section === 'followup' ? followup : notices;
    const labels = {tasks:`个人行动 · ${pending.length}`,followup:`办理跟进 · ${followup.length}`,notices:`通知核对 · ${notices.length}`};
    for (const tab of document.querySelectorAll('[data-overview-section]')) {
      const active = tab.dataset.overviewSection === section;
      tab.classList.toggle('active',active); tab.setAttribute('aria-selected',String(active));
      tab.tabIndex = active ? 0 : -1; tab.textContent = labels[tab.dataset.overviewSection];
    }
    moveSelection($('.overview-tabs'));
    const started = state.notices.length > 0 || state.tasks.length > 0;
    const items = $('#overview-items');
    items.setAttribute('aria-labelledby','overview-tab-'+section);
    items.innerHTML = list.length ? list.slice(0,5).map(section==='notices'?noticeRow:taskRow).join('') : `<div class="overview-empty">${brandMotion(started?'serene':'radar')}<h2>${section==='followup'?'暂时没有待跟进事项':section==='tasks'?(caughtUp?'个人行动已经处理完毕':started?'暂时没有待完成事项':'从第一则通知开始'):'暂时没有待核对通知'}</h2><p>${section==='followup'?'提交后可记录回执、补件要求与下次跟进时间。':section==='tasks'?'收好正文与附件，核对后留下属于自己的步骤。':'新材料、更正和取消都可以关联原通知继续处理。'}</p><a class="button small" href="${section==='followup'?'#tasks':caughtUp?'#calendar':'#new'}">${section==='followup'?'查看个人行动':caughtUp?'看看日历':'处理一则通知'} ${icon('arrow')}</a></div>`;
    const all = $('#overview-all');
    all.href = section === 'notices' ? '#notices' : '#tasks';
    all.textContent = `查看全部${section==='notices'?'通知':'事项'}${list.length>5?'（'+list.length+'）':''} →`;
    all.dataset.overviewFilter = section === 'tasks' ? 'pending' : section === 'followup' ? 'followup' : '';
  }
  function renderWeek() {
    const days = overviewWeek(state.tasks), chosen = days.find(day => day.day === selectedDay) || days[0];
    selectedDay = chosen.day;
    $('#overview-week').innerHTML = `<div class="week-heading"><div><h2>未来七天</h2></div><a href="#calendar" aria-label="在日历查看完整安排">${icon('arrow')}</a></div>
      <div class="week-days" role="group" aria-label="按截止日期查看待办">${days.map((entry,index)=>`<button type="button" data-overview-day="${entry.day}" aria-pressed="${entry.day===selectedDay}" aria-label="${entry.day}，${entry.tasks.length} 项待办"><span>${index===0?'今天':new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'UTC'}).format(new Date(entry.day+'T00:00:00Z'))}</span><strong>${Number(entry.day.slice(-2))}</strong><i class="${entry.tasks.length?'has-items':''}" aria-hidden="true"></i></button>`).join('')}</div>
      <div class="week-agenda" aria-live="polite"><span class="week-agenda-label">${selectedDay.slice(5).replace('-',' / ')} · 通知期限</span>${chosen.tasks.length?`<button type="button" data-workflow-task="${esc(chosen.tasks[0].id)}"><span>${esc(chosen.tasks[0].data.title)}</span>${icon('arrow')}</button><small>${chosen.tasks.length} 项待完成${chosen.tasks.some(t=>!t.data.deadline_confirmed)?' · 有期限待核对':''}</small>`:'<p>这一天，暂时没有待办到期。</p><a href="#calendar">安排自己的时间 '+icon('arrow')+'</a>'}</div>`;
  }
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-overview-section]');
    if(tab){section=tab.dataset.overviewSection;const data=overviewData(state.tasks,state.notices);renderItems(data,!data.pending.length&&data.completed>0);}
    const day = event.target.closest('[data-overview-day]');
    if(day){selectedDay=day.dataset.overviewDay;renderWeek();$(`[data-overview-day="${selectedDay}"]`).focus({preventScroll:true});animateSurface($('.week-agenda'),0);}
    const next = event.target.closest('[data-focus-step]');
    if(next&&!next.disabled){
      const direction=Number(next.dataset.focusStep);focusIndex+=direction;const data=overviewData(state.tasks,state.notices);renderFocus(data.ordered,data.notices,!data.pending.length&&data.completed>0);
      const replacement=$(`[data-focus-step="${direction}"]:not(:disabled)`)||$('[data-focus-step]:not(:disabled)');
      replacement?.focus({preventScroll:true});animateSurface($('.focus-card-content'),direction);
    }
  });
  return {render};
}
