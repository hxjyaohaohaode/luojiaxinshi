import {taskTimeLabel} from './notice-timing.js';
import {beginFormFeedback} from './ui-request.js';
import {workflowStage,stageOptions,handlingEditor,readMilestones,installHandlingEditor,syncHandlingFields} from './workflow-kinds.js';
import {animateLocalPanel,setDetailsExpanded,finishReferenceMotion} from './reference-interactions.js';
import {createActionReviewUI,reviewPending} from './action-review.js';
import {conditionsEditor,readConditions,installConditionEditing,taskIsPending} from './action-plans.js';
import {mountTaskMaterials} from './task-materials.js';
export const stageNames={preparing:'准备中',submitted:'已提交，等结果',supplement:'待补件',accepted:'已受理',rejected:'未通过',blocked:'卡住了'};
export const changeNames={correction:'要求更正',postponement:'提前 / 延期',cancellation:'通知取消',restoration:'恢复办理',supplement:'补充要求',unverified:'待确认的消息'};
const fieldNames={title:'事项',details:'办理说明',due_date:'截止日期',due_time:'截止时刻',deadline_text:'期限原文',materials:'材料清单',submission:'提交方式',location:'办理地点',contact:'联系方式',status:'事项状态'};
const statusNames={pending:'待完成',done:'已完成',cancelled:'已取消'};

export function taskMatchesFilter(task,filter){
  const w=task.workflow;
  if(filter==='pending')return taskIsPending(task);
  if(filter==='followup')return taskIsPending(task)&&(w?.data.board_lane==='followup'||task.followup_due||['submitted','supplement','blocked','waiting'].includes(w?.data.stage));
  if(filter==='changes')return !!task.pending_changes?.length||reviewPending(task);
  if(filter==='sync')return task.needs_calendar_sync||task.calendar_check_required;
  if(filter==='blocked')return taskIsPending(task)&&(w?.blocked||w?.data.stage==='blocked'||task.execution_issues?.length);
  return null;
}

export function createWorkflowUI({state,api,esc,icon,showDialog,toast,field,area,timeInput,toTime,drafts,route,displayTaskUpdate,exportTasks}){
  const $=s=>document.querySelector(s);
  let editing=null,changeNotice=null;
  const reviewUI=createActionReviewUI({state,api,esc,showDialog,toast,area,drafts,route});
  installConditionEditing(esc,persist);installHandlingEditor(esc,persist);
  const select=(label,name,options,value)=>`<label class="field">${label}<select name="${name}">${Object.entries(options).map(([v,l])=>`<option value="${v}" ${v===value?'selected':''}>${l}</option>`).join('')}</select></label>`;
  const btn=(text,attrs,primary=false)=>`<button type="button" class="button ${primary?'primary':''}" ${attrs}>${text}</button>`;
  const stamp=n=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short',hour12:false}).format(new Date(n*1000));
  const format=v=>Array.isArray(v)?v.join('、'):statusNames[v]||v||'没写明';

  function badges(t){
    const w=t.workflow;if(!w)return '';
    return `${reviewPending(t)?'<span class="pill orange">受变动影响，待确认</span>':''}<span class="workflow-stage">${esc(t.status==='done'?'已完成':workflowStage(w.data))}</span>${w.data.action_kind==='optional'?'<span class="pill workflow-kind">可自选</span>':''}${w.blocked?'<span class="pill orange">先完成前置步骤</span>':''}${t.execution_issues?.length?'<span class="pill orange">'+esc(t.execution_issues.find(i=>i.code==='participation')?.label||'办理条件待确认')+'</span>':''}${t.followup_due?'<span class="pill orange">该跟进了</span>':''}${t.calendar_check_required&&!t.needs_calendar_sync?'<span class="pill orange">日历还没确认导入</span>':''}${t.pending_changes?.length?`<span class="pill orange">${t.pending_changes.length} 条变动待确认</span>`:''}`;
  }

  function noticePanel(n){
    if(!n.tasks.length&&!n.changes?.length)return '';
    const completed=n.tasks.filter(t=>t.status==='done').length,pending=(n.changes||[]).filter(c=>c.state==='pending');
    return `<section class="case-workflow" aria-label="办理与变更"><div class="case-heading"><div><h2>办理与跟进</h2><p>${completed} / ${n.tasks.length} 件事已完成${pending.length?` · ${pending.length} 条变动待处理`:''}</p></div>${btn(icon('history')+' 记录通知变动',`data-change-new="${n.id}"`)}</div>${(n.changes||[]).length?`<details class="change-list" ${pending.length?'open':''}><summary>变动记录 · ${n.changes.length}</summary>${n.changes.map(c=>`<button class="change-list-item" type="button" data-change-open="${c.id}" data-notice-id="${n.id}"><span><strong>${esc(changeNames[c.data.kind])}</strong><small>${esc(c.data.source_label)} · ${stamp(c.original_created_at||c.created_at)}${c.imported?' · 导入的旧记录':''}</small></span><span class="pill ${c.state==='pending'?'orange':''}">${{pending:'待确认',applied:'已更新',dismissed:'已忽略'}[c.state]}</span>${icon('arrow')}</button>`).join('')}</details>`:''}</section>`;
  }

  function historyHTML(items){
    const names={action_plan_confirmed:'确认了事项类型和前置步骤',workflow_update:'更新了进度',change_applied:'确认了通知变动',confirm_revision:'补件后更新了要求',confirm_task:'确认了这件事',update_task:'调整了事项',calendar_export:'导出了日历',calendar_check:'记录了日历提醒情况',workflow_imported:'导入了之前的进度',change_review_required:'受变动影响，待确认',change_reviewed:'确认了变动后的安排',change_review_imported:'导入了之前的确认记录',import_dependencies_resolved:'补上了前置步骤'};
    return items.length?`<ol class="workflow-timeline">${items.map(item=>{const after=JSON.parse(item.after_json||'{}'),before=JSON.parse(item.before_json||'{}');let text=after.reason||after.verification_note||after.note||after.outcome||after.next_step||'';if(item.action==='import_dependencies_resolved')text='前置步骤已经补上了，看看现在的安排对不对。';if(item.action==='change_review_required')text='受影响的步骤：'+(after.cause?.title||'办理要求')+'；进度先保留着，看看还适不适用。';if(item.action==='change_reviewed')text=(after.decision==='reopen'?'重新办理':'保留原进度')+' · '+after.note;if(item.action==='workflow_update')text=[workflowStage(after),after.outcome,after.next_step].filter(Boolean).join(' · ');if(item.action==='update_task'&&before.status!==after.status)text=`${statusNames[before.status]} → ${statusNames[after.status]}；${after.reason}`;return `<li><div><strong>${esc(names[item.action]||'办理记录')}</strong><time>${stamp(item.created_at)}</time></div><p>${esc(text)}</p></li>`;}).join('')}</ol>`:'<p class="small muted">保存之后，每一步进展都会记在这里。</p>';
  }

  async function openTask(tid){
    persist();
    const request=++state.dialogRequest,owner=state.session.user.id;
    const result=await api(`/tasks/${tid}/workflow`);
    if(request!==state.dialogRequest||owner!==state.session?.user.id)return;
    const t=result.task,w=t.workflow,key=`workflow:${tid}:${t.version}:${w.version}`;
    const cached=await drafts.load(key);
    if(request!==state.dialogRequest)return;
    const d=cached.payload?.data||w.data;
    drafts.activate(key);
    showDialog('办理这件事',`<form id="workflow-form" data-workspace-form="workflow" data-cache-key="${key}" class="workflow-form stack"><div class="workflow-task-head"><span class="workflow-eyebrow">我的事项 · ${esc(statusNames[t.status])}</span><h3>${esc(t.data.title)}</h3><p>${esc(taskTimeLabel(t.data))}${t.data.submission?' · '+esc(t.data.submission):''}</p><a class="small" href="#notice/${t.notice_id}">回看原通知 ↗</a></div>${t.pending_changes.length?'<div class="alert">原通知有待核实的变动，请先核对相关要求，再继续办理。</div>':''}${t.status==='cancelled'?'<div class="alert">这件事已经取消了，之前的记录都还在；如果恢复办理，再来更新就好。</div>':''}<div class="form-grid">${select('办理进度','stage',stageOptions(d.execution_mode,d.stage),d.stage)}${select('事项类型','action_kind',{unclassified:'还没分类',required:'必须办',optional:'可自选',verification:'核对信息'},d.action_kind)}</div><div data-optional-choice ${d.action_kind==='optional'?'':'hidden'}>${select('你想参加吗','participation',{undecided:'还没想好',joined:'要参加',declined:'不参加'},d.participation)}</div><fieldset class="workflow-section" data-prepared-materials><legend>准备材料</legend>${t.data.materials.length?`<div class="material-checklist">${t.data.materials.map((m,i)=>`<label class="check"><input type="checkbox" name="material" value="${i}" ${d.prepared_materials.includes(m)?'checked':''}><span>${esc(m)}</span></label>`).join('')}</div>`:'<p class="small muted">通知里没提到要准备什么材料，之后有要求再补上就行。</p>'}</fieldset><details class="workflow-section" ${w.blocked?'open':''}><summary>前置步骤 <span class="small muted">${d.dependencies.length} 项</span></summary><p class="small muted">按选定的前置规则核对。取消、删除或待复核的步骤不算完成。</p><label class="field">找找前置步骤<input type="search" data-dependency-search placeholder="输入事项标题"></label><div class="dependency-list">${result.candidates.map(c=>`<label class="check" data-dependency-label="${esc(c.title.toLowerCase())}"><input type="checkbox" name="dependency" value="${c.id}" ${d.dependencies.includes(c.id)?'checked':''}><span>${esc(c.title)}<small>${esc(statusNames[c.status])}${c.notice_id===t.notice_id?' · 同一条通知':''}</small></span></label>`).join('')||'<p class="small muted">还没有别的事项。</p>'}</div>${w.dependencies.filter(x=>x.status==='missing').map(x=>`<label class="check"><input type="checkbox" name="dependency" value="${x.id}" checked><span>这个前置步骤找不到了，可能还没导入；可以先留着等它补上，或取消勾选再重新选</span></label>`).join('')}</details><fieldset class="workflow-section"><legend>提交与结果</legend>${area('提交情况 / 凭证编号','receipt',d.receipt,2,'maxlength="2000" placeholder="例如：已在学院系统提交，凭证编号……"')}${field('凭证链接（可选）','receipt_url',d.receipt_url,'url','maxlength="2000" placeholder="https://…"')}${area('结果、补件要求或卡住的原因','outcome',d.outcome,2,'maxlength="2000" placeholder="照学校的实际反馈写就好；这里标完成，只是你自己的记录"')}</fieldset><fieldset class="workflow-section"><legend>下一次跟进</legend>${field('下一步做什么','next_step',d.next_step,'text','maxlength="1000" placeholder="例如：查询受理结果 / 补交签字页"')}${field('跟进时间（北京时间）','followup_at',timeInput(d.followup_at),'datetime-local')}<p class="small muted">到时间会在提醒中心显示；可另行开启本机的关闭页面提醒，或使用已导入的日历。</p></fieldset><details class="workflow-section"><summary>办理时间线 · ${result.history.length}</summary>${historyHTML(result.history)}</details><div class="workflow-tools">${btn('修改要求和计划',`data-action="edit-task" data-id="${tid}"`)}${btn('检查日历提醒',`data-calendar-check="${tid}"`)}</div><div class="form-footer workflow-save"><span class="small muted">记下你的实际进展就好</span><button type="submit" class="button primary">保存进度</button></div></form>`);
    editing={task:t,key};
    $('#workflow-form .workflow-task-head').insertAdjacentHTML('afterend',conditionsEditor(d.conditions||[],esc));
    $('#workflow-form .workflow-task-head').insertAdjacentHTML('afterend',reviewUI.banner(t)+(t.execution_issues?.length?`<div class="alert"><strong>办理前先处理这些</strong><ul>${t.execution_issues.map(i=>`<li>${esc(i.label)}</li>`).join('')}</ul></div>`:''));
    for(const c of result.candidates.filter(c=>c.review_required||c.conditions_blocked)){
      const small=$(`#workflow-form [name=dependency][value="${c.id}"]`)?.closest('label')?.querySelector('small');
      if(small)small.textContent+=(c.review_required?' · 受变动影响，待确认':'')+(c.conditions_blocked?' · 条件还没满足':'');
    }
    $('#workflow-form .workflow-task-head').insertAdjacentHTML('afterend',handlingEditor(d,esc));
    const form=$('#workflow-form');
    form.querySelector('[data-condition-list]').insertAdjacentHTML('beforebegin',select('条件满足方式','condition_mode',{all:'全部满足',any:'满足其中一项'},d.condition_mode||'all'));
    form.querySelector('[data-dependency-search]').closest('label').insertAdjacentHTML('beforebegin',select('前置完成方式','dependency_mode',{all:'全部完成',any:'完成其中一项'},d.dependency_mode||'all'));
    if(t.status==='pending')form.querySelector('.workflow-save').insertAdjacentHTML('beforeend','<button type="submit" name="complete" value="true" class="button">保存并完成</button>');
    arrangeWorkflow(t,d);syncHandlingFields(form);
    const materialSection=document.createElement('section');materialSection.className='personal-materials';materialSection.setAttribute('aria-label','本人办理材料');
    form.querySelector('[data-prepared-materials]').after(materialSection);
    editing.materials=mountTaskMaterials(materialSection,{task:t,api,state,esc,timeInput,toTime,savedDraft:cached.payload?.materialDraft,onChange:persist,onSubmission:submission=>submit(form,'submission',submission)});
  }

  function arrangeWorkflow(task,data){
    const form=$('#workflow-form');
    const nodes=[...form.children],head=form.querySelector('.workflow-task-head'),save=form.querySelector('.workflow-save');
    const tabs=document.createElement('div');tabs.className='workflow-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','办理内容');
    const panels={};
    for(const [id,label] of [['record','办理记录'],['requirements','要求和前置'],['history','历史记录']]){
      const tab=document.createElement('button');tab.type='button';tab.id='workflow-tab-'+id;tab.dataset.workflowTab=id;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','workflow-panel-'+id);tab.textContent=label;tabs.append(tab);
      const panel=document.createElement('section');panel.className='workflow-page';panel.id='workflow-panel-'+id;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);panel.tabIndex=0;panels[id]=panel;
    }
    const grid=form.querySelector('.form-grid');
    // Preserve every original field and draft binding while grouping by intent.
    const stage=grid.querySelector('[name=stage]').closest('label'),kind=grid.querySelector('[name=action_kind]').closest('label');
    panels.record.append(stage);panels.requirements.append(kind);
    for(const node of nodes){
      if([head,save,grid].includes(node))continue;
      if(node.matches('.workflow-tools')){panels.history.append(node);continue;}
      if(node.matches('[data-optional-choice]')||node.querySelector('[data-condition-list]')||node.querySelector('[name=dependency]')||node.textContent.includes('办理前提与外部条件')){panels.requirements.append(node);continue;}
      if(node.matches('details')&&node.textContent.includes('办理时间线')){node.open=true;panels.history.prepend(node);continue;}
      if(node.querySelector('[name=receipt]')){
        const section=document.createElement('details');section.className='workflow-section workflow-receipt';
        section.open=data.stage!=='preparing'||!!data.receipt||!!data.outcome;
        section.innerHTML='<summary>提交与结果 <span class="small muted">凭证、补件或卡住的原因</span></summary>';
        for(const child of [...node.children])if(child.tagName!=='LEGEND')section.append(child);
        panels.record.append(section);continue;
      }
      if(node.querySelector('[name=next_step]')){
        const section=document.createElement('details');section.className='workflow-section workflow-followup';section.open=!!data.next_step||!!data.followup_at;
        section.innerHTML='<summary>下一次跟进 <span class="small muted">下一步和提醒时间</span></summary>';
        for(const child of [...node.children])if(child.tagName!=='LEGEND')section.append(child);
        panels.record.append(section);continue;
      }
      panels.record.append(node);
    }
    const cancel=document.createElement('button');cancel.type='button';cancel.className='button';cancel.dataset.action='close-dialog';cancel.textContent='返回';
    save.querySelector('span').remove();save.insertBefore(cancel,save.querySelector('[type=submit]'));
    const content=document.createElement('div');content.className='workflow-editing';content.append(head,tabs,...Object.values(panels));
    form.replaceChildren(content,save);
    let active=null,invalidTarget=null;const positions=new Map();
    const scroller=id=>getComputedStyle(content).overflowY==='auto'?content:panels[id];
    const choose=(id,focus=false,motion=true)=>{
      if(active===id){if(focus)tabs.querySelector(`[data-workflow-tab="${id}"]`).focus();return;}
      if(active)positions.set(active,scroller(active).scrollTop);const direction=Object.keys(panels).indexOf(id)-Object.keys(panels).indexOf(active);
      for(const button of tabs.children){const active=button.dataset.workflowTab===id;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;if(active&&focus)button.focus();}
      for(const [key,panel] of Object.entries(panels))panel.hidden=key!==id;
      scroller(id).scrollTop=positions.get(id)||0;if(active&&motion)animateLocalPanel(panels[id],Math.sign(direction));active=id;
    };
    tabs.addEventListener('click',event=>{const tab=event.target.closest('[data-workflow-tab]');if(tab)choose(tab.dataset.workflowTab);});
    tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...tabs.children],index=buttons.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;choose(buttons[next].dataset.workflowTab,true);});
    form.addEventListener('change',event=>{if(event.target.name==='stage'&&event.target.value!=='preparing')setDetailsExpanded(form.querySelector('.workflow-receipt'),true);});
    form.addEventListener('invalid',event=>{
      // Native validation emits invalid for every bad field. Keep the first
      // field visible instead of switching to the last failing hidden tab.
      if(invalidTarget)return;invalidTarget=event.target;finishReferenceMotion();const panel=event.target.closest('.workflow-page');if(panel)choose(Object.keys(panels).find(key=>panels[key]===panel),false,false);
      for(let node=event.target.parentElement;node&&node!==form;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
      queueMicrotask(()=>{if(invalidTarget?.isConnected)invalidTarget.focus();});
      setTimeout(()=>{invalidTarget=null;},0);
    },true);
    choose('record');
  }

  function readWorkflow(form){
    const d={...editing.task.workflow.data},fd=new FormData(form);
    for(const name of ['stage','action_kind','participation','receipt','receipt_url','outcome','next_step','execution_mode','phase_label','dependency_mode','condition_mode'])d[name]=String(fd.get(name)||'').trim();
    if(d.action_kind!=='optional')d.participation='undecided';
    d.prepared_materials=fd.getAll('material').map(i=>editing.task.data.materials[Number(i)]);
    d.dependencies=fd.getAll('dependency');d.followup_at=toTime(fd.get('followup_at'));d.conditions=readConditions(form);d.milestones=readMilestones(form);
    return d;
  }

  async function newChange(nid){
    persist();const request=++state.dialogRequest,n=await api('/notices/'+nid);
    const key=`change:${nid}:${n.version}`,cached=await drafts.load(key);
    if(request!==state.dialogRequest)return;
    changeNotice=n;drafts.activate(key);const d=cached.payload||{kind:'correction',text:'',source_label:n.source_label||'',source_url:'',published_at:'',targets:{}};
    showDialog('记录通知变动',`<form id="change-form" data-workspace-form="change" data-cache-key="${key}" class="stack"><p class="small muted">${esc(n.title)}。先把变动记下来，看看会影响哪些事，你确认后才会改。</p><div class="form-grid">${select('变动类型','kind',changeNames,d.kind)}${field('谁发的 / 在哪看到的','source_label',d.source_label,'text','required maxlength="100"')}</div>${area('变动原文或听到的消息','text',d.text,4,'required minlength="2" maxlength="6000" placeholder="写清楚改了什么、对谁、什么时间；别人转述或撤回的消息不算正式取消"')}<div class="form-grid">${field('原文链接（可选）','source_url',d.source_url,'url','maxlength="2000"')}${field('发布时间（北京时间）','published_at',d.published_at,'datetime-local')}</div><div id="change-targets" class="stack"></div><div class="alert info">你的备注、计划时间和提醒都会保留。已经导进手机日历的事项，记得在那边手动改一下。</div><div class="form-footer"><button type="submit" class="button primary">保存并看看影响</button></div></form>`);
    renderTargets(d.kind,d.targets);
  }

  function renderTargets(kind,values={}){
    const root=$('#change-targets');if(!root)return;
    if(kind==='unverified'){root.innerHTML='<p class="small muted">这条消息会先记在这则通知下，原来的期限和待办都不变。确认是真的，再记一条正式变动。</p>';return;}
    root.innerHTML='<h3>选出受影响的事项</h3>'+changeNotice.tasks.map(t=>{
      const saved=values[t.id]||{},eligible=kind==='cancellation'?t.status==='pending':kind==='restoration'?t.status==='cancelled':true;
      return `<fieldset class="change-target" data-target="${t.id}"><label class="check"><input type="checkbox" name="target" value="${t.id}" ${saved.selected&&eligible?'checked':''} ${eligible?'':'disabled'}><span><strong>${esc(t.data.title)}</strong><small>${statusNames[t.status]} · 原截止 ${esc(t.data.due_date||'没写明')}${eligible?'':' · 这次不适用'}</small></span></label>${!['cancellation','restoration'].includes(kind)?`<div class="target-fields" ${saved.selected?'':'hidden'}><p class="small muted">只勾要改的项，没勾的保持不变。</p>${['due_date','due_time','deadline_text','materials','submission','location','contact','details'].map(k=>`<div class="change-field"><label class="check"><input type="checkbox" name="patch-${k}" ${saved.fields?.[k]?'checked':''}><span>修改${fieldNames[k]}</span></label>${k==='materials'||k==='details'?area(fieldNames[k],k,saved.values?.[k]??(Array.isArray(t.data[k])?t.data[k].join('\n'):t.data[k]||''),2,k==='materials'?'maxlength="10000"':'maxlength="3000"'):field(fieldNames[k],k,saved.values?.[k]??t.data[k]??'',k==='due_date'?'date':k==='due_time'?'time':'text',`maxlength="${k==='submission'?1000:500}"`)}</div>`).join('')}</div>`:''}</fieldset>`;
    }).join('');
    if(!changeNotice.tasks.length)root.insertAdjacentHTML('beforeend','<p class="small muted">这则通知还没有待办。可以先记下这条消息，或者回到通知里加个步骤。</p>');
  }

  function readChange(){
    const f=$('#change-form');if(!f)return null;const fd=new FormData(f),targets={};
    for(const el of f.querySelectorAll('[data-target]')){const fields={},values={};for(const i of el.querySelectorAll('[name^="patch-"]')){const k=i.name.slice(6);fields[k]=i.checked;values[k]=el.querySelector(`[name="${k}"]`).value;}targets[el.dataset.target]={selected:el.querySelector('[name=target]').checked,fields,values};}
    return {kind:fd.get('kind'),text:fd.get('text'),source_label:fd.get('source_label'),source_url:fd.get('source_url'),published_at:fd.get('published_at'),targets};
  }

  function persist(){
    reviewUI.persist();
    for(const form of document.querySelectorAll('#workflow-form,#change-form')){
      const key=form.dataset.cacheKey;if(!key||drafts.peek(key).retired)continue;
      const value=form.id==='workflow-form'?{data:readWorkflow(form),materialDraft:editing?.materials?.snapshot()||drafts.peek(key).payload?.materialDraft||null}:readChange();
      if(JSON.stringify(value)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,value);
    }
  }

  async function openChange(nid,cid){
    const request=++state.dialogRequest,c=await api(`/notices/${nid}/changes/${cid}`);
    if(request!==state.dialogRequest)return;
    const pending=c.state==='pending',canApply=pending&&!c.stale&&c.data.kind!=='unverified';
    showDialog('看看变动的影响',`<form id="change-decision-form" data-workspace-form="decision" data-notice-id="${nid}" data-change-id="${cid}" data-version="${c.version}" class="stack"><div class="workflow-task-head"><span class="workflow-eyebrow">${esc(changeNames[c.data.kind])} · ${{pending:'待确认',applied:'已更新',dismissed:'已忽略'}[c.state]}</span><h3>${esc(c.data.source_label)}</h3>${c.data.published_at?`<p>发布于 ${esc(timeInput(c.data.published_at).replace('T',' '))}</p>`:''}</div><blockquote class="change-original">${esc(c.data.text)}</blockquote>${c.data.source_url?`<a href="${esc(c.data.source_url)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a>`:''}${c.stale&&pending?'<div class="alert">这条内容在别的页面改过了，这份预览已经过时。先忽略这条，再按最新内容重新记一次。</div>':''}${c.data.kind==='unverified'?'<div class="alert">这条消息尚未确认。先核对发布方和原文，再决定是否更新事项；忽略不会修改已有要求。</div>':''}${c.impact.map(i=>`<section class="impact-item"><h3>${esc(i.title)}</h3><dl class="impact-diff">${Object.entries(i.diff).map(([k,v])=>`<div><dt>${esc(fieldNames[k])}</dt><dd><span class="diff-before">${esc(format(v.before))}</span><span class="diff-arrow" aria-label="改为">→</span><strong>${esc(format(v.after))}</strong></dd></div>`).join('')}</dl>${i.warnings.map(w=>`<p class="small muted">${esc(w)}</p>`).join('')}</section>`).join('')}${c.imported?'<div class="alert info">这是导入的旧记录，当时的确认结果不一定适用于现在，对着原文再看一眼吧；还没确认的消息不能直接改事项。</div>':''}${!pending?`<p class="small muted">${c.decision_note?'当时的确认说明：'+esc(c.decision_note):'改动前后的内容都记在通知的修改记录和各事项的时间线里。'}</p>`:`${area('确认依据 / 忽略原因','note','',3,'required minlength="2" maxlength="1500" placeholder="比如问了谁、看了哪条原文"')}${canApply?'<label class="check"><input type="checkbox" name="verified"><span>我确认过发布方、适用范围和原文，按上面的改</span></label>':''}<div class="form-footer">${btn('忽略这条变动','data-dismiss-change')}${canApply?'<button type="submit" class="button primary">确认更新</button>':''}</div>`}</form>`);
    for(const [index,item] of c.impact.entries()){
      if(!item.affected_steps?.length)continue;
      document.querySelectorAll('.impact-item')[index]?.insertAdjacentHTML('beforeend',`<div class="action-review-downstream"><strong>还有 ${item.affected_steps.length} 个后续步骤要看看</strong><p class="small muted">更新后它们的进度不变，会标上“受变动影响，待确认”。</p>${item.affected_steps.map(step=>`<p class="small">${esc(step.title)} · ${esc(statusNames[step.status])}</p>`).join('')}</div>`);
    }
  }

  async function calendarCheck(tid){
    persist();const request=++state.dialogRequest,{task:t}=await api(`/tasks/${tid}/workflow`);
    if(request!==state.dialogRequest)return;
    const c=t.calendar_check;
    showDialog('检查日历提醒',`<form id="calendar-check-form" data-workspace-form="calendar-check" data-task-id="${tid}" data-version="${t.version}" class="stack"><h3>${esc(t.data.title)}</h3><div class="calendar-check-status"><span>${t.exported_version?'已导出版本 '+t.exported_version:'还没导出'}</span><span>当前版本 ${t.version}</span>${c?`<span>${c.current?'这一版':'上一版'}你记的是：${esc({imported:'已导入',reminder_verified:'锁屏也能收到提醒',failed:'没成功',removed:'已删掉旧日程'}[c.result])}</span>`:''}</div><p class="small muted">导出的日历文件要自己导入手机或电脑日历才会提醒。导入后，按实际情况记一下。</p>${btn('导出日历文件',`data-workflow-export="${tid}"`)}${field('用的哪台设备、哪个日历','device',c?.device||'','text','required minlength="2" maxlength="160" placeholder="例如：iPhone · Apple 日历"')}${select('实际情况','result',{imported:'导入了，还没确认提醒',reminder_verified:'关掉网页、锁屏也收到了提醒',failed:'没导进去，或没收到提醒',...(t.status==='cancelled'?{removed:'已在日历里删掉旧日程'}:{})},c?.result||'imported')}${area('备注','note',c?.note||'',3,'maxlength="1000" placeholder="比如权限设置、提醒时间或没成功的原因"')}<div class="form-footer"><button type="submit" class="button primary">保存记录</button></div></form>`);
  }

  async function submit(form,decision='apply',submission=null){
    persist();const submit=form.querySelector('[type=submit]');if(form.inert)return;
    // Capture this form before any autosave wait; another dialog can open meanwhile.
    const taskSnapshot=form.id==='workflow-form'?editing.task:null;
    const workflowSnapshot=taskSnapshot?readWorkflow(form):null;
    const noticeSnapshot=form.id==='change-form'?changeNotice:null;
    const changeSnapshot=noticeSnapshot?readChange():null;
    const finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;form.querySelector('.form-error')?.remove();form.inert=true;
    const request=state.dialogRequest,routeId=state.renderId,submittedCache=form.dataset.cacheKey?drafts.checkpoint(form.dataset.cacheKey):null;
    try{
      const key=form.dataset.cacheKey;if(key)await drafts.flush(key);
      if(form.id==='workflow-form'){
        const t=taskSnapshot,result=await api(`/tasks/${t.id}/workflow`,{method:'PUT',json:{version:t.workflow.version,task_version:t.version,data:workflowSnapshot,complete:decision==='complete',...(submission?{submission}:{})}});
        let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；不过旧草稿没清理掉，可以检查一下暂存内容';}if(request===state.dialogRequest){$('#dialog').close();displayTaskUpdate(result);}toast('进度保存好了'+cacheWarning,!!cacheWarning);
      }else if(form.id==='change-form'){
        const d=changeSnapshot,targets=[];
        for(const [tid,s] of Object.entries(d.targets)){if(!s.selected)continue;const patch={};for(const [k,on] of Object.entries(s.fields||{}))if(on)patch[k]=k==='materials'?s.values[k].split('\n').map(x=>x.trim()).filter(Boolean):['due_date','due_time'].includes(k)?s.values[k]||null:s.values[k].trim();targets.push({task_id:tid,version:noticeSnapshot.tasks.find(t=>t.id===tid).version,action:d.kind==='cancellation'?'cancel':d.kind==='restoration'?'restore':'revise',patch});}
        const n=noticeSnapshot,c=await api(`/notices/${n.id}/changes`,{method:'POST',json:{...d,published_at:toTime(d.published_at),targets,notice_version:n.version}});
        let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；不过旧草稿没清理掉，可以检查一下暂存内容';}if(request===state.dialogRequest){form.remove();if(routeId===state.renderId)await route();await openChange(n.id,c.id);}toast('变动记下了，待办还没改'+cacheWarning,!!cacheWarning);
      }else if(form.id==='change-decision-form'){
        const fd=new FormData(form),nid=form.dataset.noticeId;
        await api(`/notices/${nid}/changes/${form.dataset.changeId}/decision`,{method:'POST',json:{version:Number(form.dataset.version),decision,verified:fd.has('verified'),note:fd.get('note')}});
        if(request===state.dialogRequest)$('#dialog').close();if(routeId===state.renderId)await route();toast(decision==='apply'?'已按变动更新，记得看看计划和手机日历':'记下了，原来的安排不变');
      }else if(form.id==='calendar-check-form'){
        const fd=new FormData(form),t=await api(`/tasks/${form.dataset.taskId}/calendar-check`,{method:'POST',json:{task_version:Number(form.dataset.version),...Object.fromEntries(fd)}});
        if(request===state.dialogRequest){$('#dialog').close();displayTaskUpdate(t);}toast('记录保存好了');
      }
    }catch(error){const p=document.createElement('div');p.className='alert error form-error';p.setAttribute('role','alert');p.textContent=error.message;form.prepend(p);p.scrollIntoView({block:'nearest'});}
    finally{form.inert=false;finishFeedback();}
  }

  document.addEventListener('submit',e=>{if(['workflow','change','decision','calendar-check'].includes(e.target.dataset.workspaceForm)){e.preventDefault();submit(e.target,e.submitter?.name==='complete'?'complete':'apply');}});
  document.addEventListener('input',e=>{if(e.target.matches('[data-dependency-search]'))for(const label of document.querySelectorAll('[data-dependency-label]'))label.hidden=!label.dataset.dependencyLabel.includes(e.target.value.toLowerCase());if(e.target.closest('#workflow-form,#change-form'))persist();});
  document.addEventListener('change',e=>{const form=e.target.closest('#workflow-form,#change-form');if(!form)return;if(e.target.name==='action_kind')$('[data-optional-choice]').hidden=e.target.value!=='optional';if(form.id==='change-form'&&e.target.name==='kind')renderTargets(e.target.value);if(e.target.name==='target'){const fields=e.target.closest('[data-target]').querySelector('.target-fields');if(fields)fields.hidden=!e.target.checked;}persist();});
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-workflow-task],[data-change-new],[data-change-open],[data-calendar-check],[data-workflow-export],[data-dismiss-change]');if(!b||b.disabled)return;
    const selection=window.getSelection();if(e.detail&&b.matches('.task-primary')&&selection&&!selection.isCollapsed&&b.contains(selection.anchorNode))return;
    b.disabled=true;
    try{if(b.dataset.workflowTask)await openTask(b.dataset.workflowTask);else if(b.dataset.changeNew)await newChange(b.dataset.changeNew);else if(b.dataset.changeOpen)await openChange(b.dataset.noticeId,b.dataset.changeOpen);else if(b.dataset.calendarCheck)await calendarCheck(b.dataset.calendarCheck);else if(b.dataset.workflowExport){const {task}=await api(`/tasks/${b.dataset.workflowExport}/workflow`);await exportTasks([task]);}else if(b.hasAttribute('data-dismiss-change')){const f=b.closest('form');if(f.reportValidity())await submit(f,'dismiss');}}
    catch(error){toast(error.message,true);}finally{b.disabled=false;}
  });
  return {badges,noticePanel,persist,openTask};
}
