import {taskTimeLabel} from './notice-timing.js';

// Show only destinations actually present in this requirement. Never guess a portal.
export function submissionLinks(text=''){
  const urls=String(text).match(/https?:\/\/[^\s<>"'，。；、）】]+/gi)||[];
  return [...new Set(urls.map(value=>value.replace(/[).,;]+$/,'')))].filter(value=>{
    try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password;}catch{return false;}
  });
}

export function draftRouteSummary(draft,index,tasks,{esc}){
  const d=draft.data||draft,p=draft._plan||{},dependencies=(p.depends_on||[]).map(id=>tasks.find(t=>t._plan_id===id)?.title).filter(Boolean);
  const kind=d.scope==='other'?'单位 / 他人环节':d.scope==='uncertain'?'责任待核实':{required:'需要办理',optional:'自愿选择',verification:'先核对信息',unclassified:'个人步骤'}[p.action_kind||'unclassified'];
  const links=submissionLinks(d.submission);
  return `<div class="handling-route-summary"><div class="route-heading"><h3>${esc(d.title||'待补充步骤')}</h3><span class="pill ${p.action_kind==='optional'?'orange':''}">${kind}</span></div>${d.details?`<p class="route-description">${esc(d.details)}</p>`:''}<dl class="route-facts"><div><dt>时间</dt><dd>${esc(taskTimeLabel(d))}</dd></div>${d.materials?.length?`<div><dt>准备材料</dt><dd>${esc(d.materials.join('、'))}</dd></div>`:''}${d.submission?`<div><dt>办理渠道</dt><dd>${esc(d.submission)}</dd></div>`:''}${d.location?`<div><dt>地点</dt><dd>${esc(d.location)}</dd></div>`:''}${d.contact?`<div><dt>联系</dt><dd>${esc(d.contact)}</dd></div>`:''}</dl>${dependencies.length?`<p class="route-prerequisite"><strong>${p.dependency_mode==='any'?'先完成其中一步':'先完成'}</strong> ${esc(dependencies.join('、'))}</p>`:''}${p.conditions?.length?`<p class="route-prerequisite"><strong>${p.condition_mode==='any'?'确认其中一个条件':'办理前确认'}</strong> ${esc(p.conditions.join('；'))}</p>`:''}${d.uncertainties?.length?`<p class="small route-unknown">待核实：${esc(d.uncertainties.join('；'))}。不依赖这些信息的准备可以先进行。</p>`:''}${links.length?`<div class="row wrap">${links.map(url=>`<a class="button small" href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开原文中的办理入口 ↗</a>`).join('')}</div>`:''}</div>`;
}

export function currentHandlingStep(task){
  if(task.handling_state&&['closed','changes','choice','prerequisites','blocked','followup','receipt','materials','start'].includes(task.handling_state.kind))return task.handling_state;
  const d=task.workflow?.data||{},materials=task.data.materials||[];
  if(task.status==='cancelled')return {kind:'closed',label:'已取消',detail:'保留此前的材料和办理记录。'};
  if(task.status==='done')return {kind:'closed',label:'已完成个人办理',detail:'可继续查看提交记录和实际反馈。'};
  if(task.pending_changes?.length||task.change_review?.state==='pending')return {kind:'changes',label:'核对变动影响',detail:'已有准备和记录保留，先查看哪些要求发生变化。'};
  if(d.action_kind==='optional'&&d.participation!=='joined')return d.participation==='declined'?{kind:'choice',label:'已选择不参加',detail:'保留原通知，可按实际情况重新选择是否参加。'}:{kind:'choice',label:'先决定是否参加',detail:'选择后再推进报名或提交，准备资料可以先做。'};
  if(task.workflow?.blocked||task.execution_issues?.length)return {kind:'prerequisites',label:'处理这一步的前提',detail:task.execution_issues?.map(x=>x.label).join('；')||'查看未完成的前置步骤；可先准备不依赖它们的材料。'};
  if(d.stage==='blocked')return {kind:'blocked',label:'核对阻碍是否已经解除',detail:d.outcome||'查看实际原因，按当前情况更新办理进度。'};
  if(task.followup_due&&d.next_step)return {kind:'followup',label:'到时间跟进了',detail:d.next_step};
  if(['submitted','accepted','waiting'].includes(d.stage))return {kind:'receipt',label:'跟进实际反馈',detail:d.next_step||'保留提交凭证，等待或查询受理结果。'};
  if(d.stage==='rejected')return {kind:'receipt',label:'先核对未通过的反馈',detail:d.outcome||'查看实际原因，再决定是否补充、重新办理或结束个人事项。'};
  if(d.stage==='supplement')return {kind:'materials',label:'按反馈补充材料',detail:d.outcome||'补充实际要求的文件，再记录这次提交。'};
  const missing=materials.filter(value=>!d.prepared_materials?.includes(value));
  if(missing.length)return {kind:'materials',label:'先准备材料',detail:missing.join('、')};
  return {kind:'start',label:d.execution_mode==='submission'?'进入原渠道办理':'开始这一步',detail:task.data.submission||task.data.details||task.data.title};
}

export function handlingGuide(task,{esc,candidates=[]}){
  const step=currentHandlingStep(task),links=submissionLinks(task.data.submission),d=task.data,progress=task.workflow?.data||{};
  const change=task.pending_changes?.[0],changeId=typeof change==='string'?change:change?.id,actions=[];
  const focus=(name,label)=>`<button type="button" class="button small" data-workflow-focus="${name}">${label}</button>`;
  if(step.kind==='changes'&&changeId)actions.push(`<button type="button" class="button small primary" data-change-open="${esc(changeId)}" data-notice-id="${esc(task.notice_id)}">核对这条变动</button>`);
  else if(step.kind==='changes')actions.push(focus('review','核对当前办理要求'));
  if(step.kind==='prerequisites'){
    const selected=(progress.dependencies||[]).map(id=>candidates.find(item=>item.id===id)).filter(Boolean),ready=item=>item.status==='done'&&!item.review_required&&!item.conditions_blocked;
    const dependencies=progress.dependency_mode==='any'&&selected.some(ready)?[]:selected.filter(item=>!ready(item));
    actions.push(...dependencies.map(item=>`<button type="button" class="button small primary" data-workflow-task="${esc(item.id)}">先处理：${esc(item.title||item.data?.title||'前置事项')}</button>`),focus('prerequisites','查看办理前提'));
    if(d.materials?.length)actions.push(focus('materials','先准备不依赖前提的材料'));
  }
  if(step.kind==='materials')actions.push(focus('materials','开始准备材料'));
  if(step.kind==='choice')actions.push(focus('choice','选择是否参加'));
  if(step.kind==='receipt')actions.push(focus('receipt','查看提交与实际反馈'));
  if(step.kind==='blocked')actions.push(focus('receipt','更新阻碍与办理进度'));
  if(step.kind==='followup')actions.push(focus('followup','查看本次跟进安排'));
  return `<section class="handling-guide" aria-label="当前办理路径"><div class="route-eyebrow">现在可以做</div><h3>${esc(step.label)}</h3><p>${esc(step.detail)}</p>${step.kind!=='blocked'&&progress.stage==='blocked'&&progress.outcome?`<p class="small route-unknown">已记录的阻碍：${esc(progress.outcome)}</p>`:''}${actions.length?'<div class="row wrap">'+actions.join('')+'</div>':''}${d.submission?`<p class="small"><strong>办理渠道</strong> ${esc(d.submission)}</p>`:''}${d.location?`<p class="small"><strong>地点</strong> ${esc(d.location)}</p>`:''}${d.contact?`<p class="small"><strong>联系</strong> ${esc(d.contact)}</p>`:''}${links.length?`<div class="row wrap">${links.map(url=>`<a class="button small ${step.kind==='start'?'primary':''}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${step.kind==='start'?'前往办理入口':'查看原通知中的渠道'} ↗</a>`).join('')}</div>`:''}${progress.execution_mode==='submission'&&!d.submission?'<p class="small route-unknown">原文未明确提交渠道，可先准备材料，再向发布方确认入口。</p>':''}</section>`;
}
