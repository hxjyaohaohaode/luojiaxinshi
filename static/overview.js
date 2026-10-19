import {taskIsPending} from './action-plans.js';
import {brandMotion} from './motion.js';
import {taskMatchesFilter} from './workflow.js';

export function createOverview({state,esc,icon,companion,greeting,taskRow,noticeRow,moveSelection}){
  const $=selector=>document.querySelector(selector);
  let section='tasks';
  function render(){
    const pending=state.tasks.filter(t=>taskIsPending(t)&&t.data.scope==='personal');
    const ordered=[...pending].sort((a,b)=>Number(b.followup_due)-Number(a.followup_due)||Number(b.overdue)-Number(a.overdue)||Number(b.due_soon)-Number(a.due_soon)||(a.data.due_date||'9999').localeCompare(b.data.due_date||'9999'));
    const notices=state.notices.filter(n=>n.status!=='confirmed');
    const urgent=pending.filter(t=>t.overdue||t.due_soon),uncertain=pending.filter(t=>!t.data.due_date||!t.data.deadline_confirmed);
    const followup=state.tasks.filter(t=>taskMatchesFilter(t,'followup'));
    const changed=state.tasks.filter(t=>taskMatchesFilter(t,'changes'));
    const sync=state.tasks.filter(t=>taskMatchesFilter(t,'sync'));
    const caughtUp=!pending.length&&state.tasks.some(t=>t.status==='done');
    if(!$('#overview-board'))$('#content').innerHTML=`<div class="overview-compact"><div class="overview-heading"><div class="overview-heading-copy"><div class="overview-kicker">${esc(new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'}).format(new Date()))} · 你的校园行动</div><h1>${greeting()}，${esc(state.session.user.profile.preferred_name||state.session.user.display_name)}。</h1><p>从一则通知，到办好每一件事。</p></div><div id="overview-companion"></div></div><div class="overview-flow" aria-label="通知办理流程"><span><b>1</b> 收好通知</span>${icon('arrow')}<span><b>2</b> 核对行动</span>${icon('arrow')}<span><b>3</b> 办理跟进</span>${icon('arrow')}<span><b>4</b> 留存结果</span></div><div id="action-metrics" class="action-metrics" aria-label="办理概览"></div><div id="overview-brief" class="overview-brief" aria-label="需要留意的事项"></div><section class="panel flush" id="overview-board"><div class="overview-tabs tabs" role="tablist" aria-label="需要处理的事项"><button type="button" class="tab" role="tab" data-overview-section="tasks">个人行动</button><button type="button" class="tab" role="tab" data-overview-section="followup">办理跟进</button><button type="button" class="tab" role="tab" data-overview-section="notices">通知核对</button></div><div id="overview-items" role="tabpanel"></div><div class="overview-footer"><a id="overview-all" class="button small plain"></a></div></section><div class="overview-bottom-actions"><a class="overview-new button primary" href="#new">${icon('plus')} 处理新通知</a><a class="overview-new button plain" href="#chat">${icon('spark')} 带着材料问小信使</a></div></div>`;
    const pose=caughtUp?'complete':'welcome';if($('#overview-companion').dataset.pose!==pose){$('#overview-companion').innerHTML=companion(pose,'overview-companion');$('#overview-companion').dataset.pose=pose;}
    $('#action-metrics').innerHTML=[['待完成',pending.length,'pending','tasks'],['待跟进',followup.length,'followup','history'],['待核实事项',changed.length,'changes','shield'],['日历待同步',sync.length,'sync','calendar']].map(([label,count,filter,symbol])=>`<a class="action-metric ${count&&filter!=='pending'?'attention':''}" href="#tasks" data-overview-filter="${filter}"><span>${label}</span>${icon(symbol)}<strong>${count}</strong></a>`).join('');
    $('#overview-brief').innerHTML=(urgent.length?`<a class="attention" href="#tasks" data-overview-filter="soon"><b>${urgent.length}</b> 临近或已过期</a>`:'')+(uncertain.length?`<a href="#tasks" data-overview-filter="unverified"><b>${uncertain.length}</b> 期限待核对</a>`:'')+`<a href="#tasks" data-overview-filter="done"><b>${state.tasks.filter(t=>t.status==='done').length}</b> 已完成</a>`+(notices.length?`<a href="#notices"><b>${notices.length}</b> 通知待核对</a>`:'');
    $('#overview-brief').hidden=false;
    const list=section==='tasks'?ordered:section==='followup'?followup:notices,limit=5;
    const labels={tasks:`个人行动 · ${pending.length}`,followup:`办理跟进 · ${followup.length}`,notices:`通知核对 · ${notices.length}`};
    for(const tab of document.querySelectorAll('[data-overview-section]')){const active=tab.dataset.overviewSection===section;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;tab.textContent=labels[tab.dataset.overviewSection];}
    moveSelection($('.overview-tabs'));
    const started=state.notices.length>0||state.tasks.length>0;
    $('#overview-items').innerHTML=list.length?list.slice(0,limit).map(section==='notices'?noticeRow:taskRow).join(''):`<div class="overview-empty">${brandMotion(started?'serene':'radar')}<h2>${section==='followup'?'暂时没有待跟进事项':section==='tasks'?(caughtUp?'个人行动已经处理完毕':started?'暂时没有待完成事项':'从第一则通知开始'):'暂时没有待核对通知'}</h2><p>${section==='followup'?'提交后可记录回执、补件要求与下次跟进时间。':section==='tasks'?'收好正文与附件，核对后留下属于自己的步骤。':'新材料、更正和取消都可以关联原通知继续处理。'}</p></div>`;
    const all=$('#overview-all');all.href=section==='notices'?'#notices':'#tasks';all.textContent=`查看全部${section==='notices'?'通知':'事项'}${list.length>limit?'（'+list.length+'）':''} →`;all.dataset.overviewFilter=section==='tasks'?'pending':section==='followup'?'followup':'';
  }
  document.addEventListener('click',event=>{const tab=event.target.closest('[data-overview-section]');if(tab){section=tab.dataset.overviewSection;render();}});
  return {render};
}
