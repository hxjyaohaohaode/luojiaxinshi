import {beginFormFeedback} from './ui-request.js';
import {createActionReviewUI,reviewPending} from './action-review.js';
import {conditionsEditor,readConditions,installConditionEditing,taskIsPending} from './action-plans.js';
export const stageNames={preparing:'准备中',submitted:'已提交，待结果',supplement:'待补件',accepted:'已核实受理',rejected:'未通过',blocked:'办理受阻'};
export const changeNames={correction:'要求更正',postponement:'提前 / 延期',cancellation:'正式取消',restoration:'正式恢复',supplement:'补充要求',unverified:'待核实线索'};
const fieldNames={title:'事项',details:'办理说明',due_date:'截止日期',due_time:'截止时刻',deadline_text:'期限原文',materials:'材料清单',submission:'提交方式',location:'办理地点',contact:'联系方式',status:'事项状态'};
const statusNames={pending:'待完成',done:'已完成',cancelled:'已取消'};

export function taskMatchesFilter(task,filter){
  const w=task.workflow;
  if(filter==='pending')return taskIsPending(task);
  if(filter==='followup')return taskIsPending(task)&&(task.followup_due||['submitted','supplement','blocked'].includes(w?.data.stage));
  if(filter==='changes')return !!task.pending_changes?.length||reviewPending(task);
  if(filter==='sync')return task.needs_calendar_sync||task.calendar_check_required;
  if(filter==='blocked')return taskIsPending(task)&&(w?.blocked||w?.data.stage==='blocked'||task.execution_issues?.length);
  return null;
}

export function createWorkflowUI({state,api,esc,icon,showDialog,toast,field,area,timeInput,toTime,drafts,route,displayTaskUpdate,exportTasks}){
  const $=s=>document.querySelector(s);
  let editing=null,changeNotice=null;
  const reviewUI=createActionReviewUI({state,api,esc,showDialog,toast,area,drafts,route});
  installConditionEditing(esc,persist);
  const select=(label,name,options,value)=>`<label class="field">${label}<select name="${name}">${Object.entries(options).map(([v,l])=>`<option value="${v}" ${v===value?'selected':''}>${l}</option>`).join('')}</select></label>`;
  const btn=(text,attrs,primary=false)=>`<button type="button" class="button ${primary?'primary':''}" ${attrs}>${text}</button>`;
  const stamp=n=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short',hour12:false}).format(new Date(n*1000));
  const format=v=>Array.isArray(v)?v.join('、'):statusNames[v]||v||'未明确';

  function badges(t){
    const w=t.workflow;if(!w)return '';
    return `${reviewPending(t)?'<span class="pill orange">办理影响待复核</span>':''}<span class="workflow-stage">${esc(stageNames[w.data.stage])}</span>${w.data.action_kind==='optional'?'<span class="pill workflow-kind">本人可选</span>':''}${w.blocked?'<span class="pill orange">前置待完成 / 复核</span>':''}${t.execution_issues?.length?'<span class="pill orange">'+esc(t.execution_issues.find(i=>i.code==='participation')?.label||'办理条件待核实')+'</span>':''}${t.followup_due?'<span class="pill orange">到时跟进</span>':''}${t.calendar_check_required&&!t.needs_calendar_sync?'<span class="pill orange">日历导入待核实</span>':''}${t.pending_changes?.length?`<span class="pill orange">${t.pending_changes.length} 条变更待核实</span>`:''}`;
  }

  function noticePanel(n){
    if(!n.tasks.length&&!n.changes?.length)return '';
    const completed=n.tasks.filter(t=>t.status==='done').length,pending=(n.changes||[]).filter(c=>c.state==='pending');
    return `<section class="case-workflow" aria-label="办理与变更"><div class="case-heading"><div><h2>办理与跟进</h2><p>${completed} / ${n.tasks.length} 项个人行动已完成${pending.length?` · ${pending.length} 条变更待处理`:''}</p></div>${btn(icon('history')+' 记录通知变更',`data-change-new="${n.id}"`)}</div>${(n.changes||[]).length?`<details class="change-list" ${pending.length?'open':''}><summary>更正、取消与核实记录 · ${n.changes.length}</summary>${n.changes.map(c=>`<button class="change-list-item" type="button" data-change-open="${c.id}" data-notice-id="${n.id}"><span><strong>${esc(changeNames[c.data.kind])}</strong><small>${esc(c.data.source_label)} · ${stamp(c.original_created_at||c.created_at)}${c.imported?' · 导入历史':''}</small></span><span class="pill ${c.state==='pending'?'orange':''}">${{pending:'待核实确认',applied:'已应用',dismissed:'已排除'}[c.state]}</span>${icon('arrow')}</button>`).join('')}</details>`:''}</section>`;
  }

  function historyHTML(items){
    const names={action_plan_confirmed:'确认办理分类与前置条件',workflow_update:'更新办理记录',change_applied:'确认通知变更',confirm_revision:'补件后更新要求',confirm_task:'确认个人事项',update_task:'调整事项',calendar_export:'导出日历快照',calendar_check:'记录设备验证',workflow_imported:'导入历史办理记录',change_review_required:'办理影响待复核',change_reviewed:'保存办理复核结论',change_review_imported:'导入办理复核记录',import_dependencies_resolved:'补齐分批导入的前置事项'};
    return items.length?`<ol class="workflow-timeline">${items.map(item=>{const after=JSON.parse(item.after_json||'{}'),before=JSON.parse(item.before_json||'{}');let text=after.reason||after.verification_note||after.note||after.outcome||after.next_step||'';if(item.action==='import_dependencies_resolved')text='已按同一账号的原始标识补齐前置关系，请核对当前办理安排。';if(item.action==='change_review_required')text='相关步骤：'+(after.cause?.title||'办理要求')+'；原进度保留，需核对是否仍适用。';if(item.action==='change_reviewed')text=(after.decision==='reopen'?'重新办理':'保留原进度')+' · '+after.note;if(item.action==='workflow_update')text=[stageNames[after.stage],after.outcome,after.next_step].filter(Boolean).join(' · ');if(item.action==='update_task'&&before.status!==after.status)text=`${statusNames[before.status]} → ${statusNames[after.status]}；${after.reason}`;return `<li><div><strong>${esc(names[item.action]||'办理记录')}</strong><time>${stamp(item.created_at)}</time></div><p>${esc(text)}</p></li>`;}).join('')}</ol>`:'<p class="small muted">保存后的办理变化会记录在这里。</p>';
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
    showDialog('办理这件事',`<form id="workflow-form" data-workspace-form="workflow" data-cache-key="${key}" class="workflow-form stack"><div class="workflow-task-head"><span class="workflow-eyebrow">个人行动 · ${esc(statusNames[t.status])}</span><h3>${esc(t.data.title)}</h3><p>${t.data.due_date?'正式期限 '+esc(t.data.due_date+' '+(t.data.due_time||'（未明确时刻）')):'正式期限待核实'}${t.data.submission?' · '+esc(t.data.submission):''}</p><a class="small" href="#notice/${t.notice_id}">回查原通知与变更 ↗</a></div>${t.pending_changes.length?'<div class="alert">收到尚未确认的变更。当前仍保留原安排，请回查通知并核实。</div>':''}${t.status==='cancelled'?'<div class="alert">事项已取消，历史记录仍可回查；收到正式恢复后再更新。</div>':''}<div class="form-grid">${select('办理进度','stage',stageNames,d.stage)}${select('事项性质（以原文为准）','action_kind',{unclassified:'尚未分类',required:'本人必办',optional:'本人可选',verification:'核实信息'},d.action_kind)}</div><div data-optional-choice ${d.action_kind==='optional'?'':'hidden'}>${select('本人参加意愿','participation',{undecided:'尚未决定',joined:'决定参加',declined:'决定不参加'},d.participation)}</div><fieldset class="workflow-section"><legend>准备材料</legend>${t.data.materials.length?`<div class="material-checklist">${t.data.materials.map((m,i)=>`<label class="check"><input type="checkbox" name="material" value="${i}" ${d.prepared_materials.includes(m)?'checked':''}><span>${esc(m)}</span></label>`).join('')}</div>`:'<p class="small muted">当前事项未列明所需材料，可在正式要求中补充。</p>'}</fieldset><details class="workflow-section" ${w.blocked?'open':''}><summary>前置步骤 <span class="small muted">${d.dependencies.length} 项</span></summary><p class="small muted">前置事项完成后，才能将本项标记完成或记录为已提交。取消和删除不会被视为完成。</p><label class="field">查找前置事项<input type="search" data-dependency-search placeholder="输入事项标题"></label><div class="dependency-list">${result.candidates.map(c=>`<label class="check" data-dependency-label="${esc(c.title.toLowerCase())}"><input type="checkbox" name="dependency" value="${c.id}" ${d.dependencies.includes(c.id)?'checked':''}><span>${esc(c.title)}<small>${esc(statusNames[c.status])}${c.notice_id===t.notice_id?' · 本通知':''}</small></span></label>`).join('')||'<p class="small muted">还没有其他个人事项。</p>'}</div>${w.dependencies.filter(x=>x.status==='missing').map(x=>`<label class="check"><input type="checkbox" name="dependency" value="${x.id}" checked><span>前置事项缺失或尚未导入；可保留等待补齐，或取消勾选后重新核对</span></label>`).join('')}</details><fieldset class="workflow-section"><legend>提交与结果</legend>${area('实际提交记录 / 回执编号','receipt',d.receipt,2,'maxlength="2000" placeholder="例如：已在学院系统提交，回执编号……"')}${field('回执链接（可选）','receipt_url',d.receipt_url,'url','maxlength="2000" placeholder="https://…"')}${area('受理结果、补件要求或受阻原因','outcome',d.outcome,2,'maxlength="2000" placeholder="按实际反馈填写，标记完成不等于学校受理"')}</fieldset><fieldset class="workflow-section"><legend>下一次跟进</legend>${field('下一步做什么','next_step',d.next_step,'text','maxlength="1000" placeholder="例如：查询受理结果 / 补交签字页"')}${field('站内跟进时间（北京时间）','followup_at',timeInput(d.followup_at),'datetime-local')}<p class="small muted">到时在工作台显示待跟进；关闭页面后的提醒请使用已验证的日历。</p></fieldset><details class="workflow-section"><summary>办理时间线 · ${result.history.length}</summary>${historyHTML(result.history)}</details><div class="workflow-tools">${btn('编辑要求与个人计划',`data-action="edit-task" data-id="${tid}"`)}${btn('日历与提醒验证',`data-calendar-check="${tid}"`)}</div><div class="form-footer workflow-save"><span class="small muted">只记录本人实际办理情况</span><button type="submit" class="button primary">保存办理记录</button></div></form>`);
    editing={task:t,key};
    $('#workflow-form .workflow-task-head').insertAdjacentHTML('afterend',conditionsEditor(d.conditions||[],esc));
    $('#workflow-form .workflow-task-head').insertAdjacentHTML('afterend',reviewUI.banner(t)+(t.execution_issues?.length?`<div class="alert"><strong>办理前需要处理</strong><ul>${t.execution_issues.map(i=>`<li>${esc(i.label)}</li>`).join('')}</ul></div>`:''));
    for(const c of result.candidates.filter(c=>c.review_required||c.conditions_blocked)){
      const small=$(`#workflow-form [name=dependency][value="${c.id}"]`)?.closest('label')?.querySelector('small');
      if(small)small.textContent+=(c.review_required?' · 办理影响待复核':'')+(c.conditions_blocked?' · 办理条件未满足':'');
    }
    arrangeWorkflow(t,d);
  }

  function arrangeWorkflow(task,data){
    const form=$('#workflow-form');
    const nodes=[...form.children],head=form.querySelector('.workflow-task-head'),save=form.querySelector('.workflow-save');
    const tabs=document.createElement('div');tabs.className='workflow-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','办理内容');
    const panels={};
    for(const [id,label] of [['record','办理记录'],['requirements','要求与前置'],['history','历史记录']]){
      const tab=document.createElement('button');tab.type='button';tab.id='workflow-tab-'+id;tab.dataset.workflowTab=id;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','workflow-panel-'+id);tab.textContent=label;tabs.append(tab);
      const panel=document.createElement('section');panel.className='workflow-page';panel.id='workflow-panel-'+id;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);panels[id]=panel;
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
        section.innerHTML='<summary>提交与结果 <span class="small muted">回执、补件或受阻原因</span></summary>';
        for(const child of [...node.children])if(child.tagName!=='LEGEND')section.append(child);
        panels.record.append(section);continue;
      }
      if(node.querySelector('[name=next_step]')){
        const section=document.createElement('details');section.className='workflow-section workflow-followup';section.open=!!data.next_step||!!data.followup_at;
        section.innerHTML='<summary>下一次跟进 <span class="small muted">事项与提醒时间</span></summary>';
        for(const child of [...node.children])if(child.tagName!=='LEGEND')section.append(child);
        panels.record.append(section);continue;
      }
      panels.record.append(node);
    }
    const hint=document.createElement('p');hint.className='workflow-scope-note';hint.textContent='先更新进度，需要时再补充回执和跟进。';
    const cancel=document.createElement('button');cancel.type='button';cancel.className='button';cancel.dataset.action='close-dialog';cancel.textContent='返回';
    save.querySelector('span').textContent='修改会暂存，保存后更新办理记录';save.insertBefore(cancel,save.querySelector('[type=submit]'));
    form.replaceChildren(head,tabs,hint,...Object.values(panels),save);
    const choose=(id,focus=false)=>{
      for(const button of tabs.children){const active=button.dataset.workflowTab===id;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;if(active&&focus)button.focus();}
      for(const [key,panel] of Object.entries(panels))panel.hidden=key!==id;
      hint.hidden=id!=='record';
    };
    tabs.addEventListener('click',event=>{const tab=event.target.closest('[data-workflow-tab]');if(tab)choose(tab.dataset.workflowTab);});
    tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...tabs.children],index=buttons.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;choose(buttons[next].dataset.workflowTab,true);});
    form.addEventListener('change',event=>{if(event.target.name==='stage'&&event.target.value!=='preparing')form.querySelector('.workflow-receipt').open=true;});
    form.addEventListener('invalid',event=>{const panel=event.target.closest('.workflow-page');if(panel)choose(Object.keys(panels).find(key=>panels[key]===panel));for(let node=event.target.parentElement;node&&node!==form;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;},true);
    choose('record');
  }

  function readWorkflow(form){
    const d={...editing.task.workflow.data},fd=new FormData(form);
    for(const name of ['stage','action_kind','participation','receipt','receipt_url','outcome','next_step'])d[name]=String(fd.get(name)||'').trim();
    if(d.action_kind!=='optional')d.participation='undecided';
    d.prepared_materials=fd.getAll('material').map(i=>editing.task.data.materials[Number(i)]);
    d.dependencies=fd.getAll('dependency');d.followup_at=toTime(fd.get('followup_at'));d.conditions=readConditions(form);
    return d;
  }

  async function newChange(nid){
    persist();const request=++state.dialogRequest,n=await api('/notices/'+nid);
    const key=`change:${nid}:${n.version}`,cached=await drafts.load(key);
    if(request!==state.dialogRequest)return;
    changeNotice=n;drafts.activate(key);const d=cached.payload||{kind:'correction',text:'',source_label:n.source_label||'',source_url:'',published_at:'',targets:{}};
    showDialog('记录通知变更',`<form id="change-form" data-workspace-form="change" data-cache-key="${key}" class="stack"><p class="small muted">${esc(n.title)}。先保存变更依据并预览影响，经本人核实后才修改所选事项。</p><div class="form-grid">${select('变更类型','kind',changeNames,d.kind)}${field('发布方 / 核实来源','source_label',d.source_label,'text','required maxlength="100"')}</div>${area('变更原文或待核实线索','text',d.text,4,'required minlength="2" maxlength="6000" placeholder="保留变更的具体内容、适用对象与时间；转述或撤回消息不能视为正式取消"')}<div class="form-grid">${field('原文链接（可选）','source_url',d.source_url,'url','maxlength="2000"')}${field('原发布时间（北京时间）','published_at',d.published_at,'datetime-local')}</div><div id="change-targets" class="stack"></div><div class="alert info">个人备注、计划时段和提醒时间保留。应用前会检查最新版本；已导出日历的事项需手动同步。</div><div class="form-footer"><button type="submit" class="button primary">保存并预览影响</button></div></form>`);
    renderTargets(d.kind,d.targets);
  }

  function renderTargets(kind,values={}){
    const root=$('#change-targets');if(!root)return;
    if(kind==='unverified'){root.innerHTML='<p class="small muted">这条线索将关联本通知，原期限与待办保持不变。核实后再建立正式更正。</p>';return;}
    root.innerHTML='<h3>明确选择受影响的事项</h3>'+changeNotice.tasks.map(t=>{
      const saved=values[t.id]||{},eligible=kind==='cancellation'?t.status==='pending':kind==='restoration'?t.status==='cancelled':true;
      return `<fieldset class="change-target" data-target="${t.id}"><label class="check"><input type="checkbox" name="target" value="${t.id}" ${saved.selected&&eligible?'checked':''} ${eligible?'':'disabled'}><span><strong>${esc(t.data.title)}</strong><small>${statusNames[t.status]} · 原期限 ${esc(t.data.due_date||'未明确')}${eligible?'':' · 不适用本次操作'}</small></span></label>${!['cancellation','restoration'].includes(kind)?`<div class="target-fields" ${saved.selected?'':'hidden'}><p class="small muted">只勾选要修改的字段；未勾选的要求保持原值。</p>${['due_date','due_time','deadline_text','materials','submission','location','contact','details'].map(k=>`<div class="change-field"><label class="check"><input type="checkbox" name="patch-${k}" ${saved.fields?.[k]?'checked':''}><span>修改${fieldNames[k]}</span></label>${k==='materials'||k==='details'?area(fieldNames[k],k,saved.values?.[k]??(Array.isArray(t.data[k])?t.data[k].join('\n'):t.data[k]||''),2,k==='materials'?'maxlength="10000"':'maxlength="3000"'):field(fieldNames[k],k,saved.values?.[k]??t.data[k]??'',k==='due_date'?'date':k==='due_time'?'time':'text',`maxlength="${k==='submission'?1000:500}"`)}</div>`).join('')}</div>`:''}</fieldset>`;
    }).join('');
    if(!changeNotice.tasks.length)root.insertAdjacentHTML('beforeend','<p class="small muted">还没有正式待办。可先记录待核实线索，或回到通知建立个人步骤。</p>');
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
      const value=form.id==='workflow-form'?{data:readWorkflow(form)}:readChange();
      if(JSON.stringify(value)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,value);
    }
  }

  async function openChange(nid,cid){
    const request=++state.dialogRequest,c=await api(`/notices/${nid}/changes/${cid}`);
    if(request!==state.dialogRequest)return;
    const pending=c.state==='pending',canApply=pending&&!c.stale&&c.data.kind!=='unverified';
    showDialog('核对变更影响',`<form id="change-decision-form" data-workspace-form="decision" data-notice-id="${nid}" data-change-id="${cid}" data-version="${c.version}" class="stack"><div class="workflow-task-head"><span class="workflow-eyebrow">${esc(changeNames[c.data.kind])} · ${{pending:'待核实确认',applied:'已确认应用',dismissed:'已排除'}[c.state]}</span><h3>${esc(c.data.source_label)}</h3>${c.data.published_at?`<p>原发布时间 ${esc(timeInput(c.data.published_at).replace('T',' '))}</p>`:''}</div><blockquote class="change-original">${esc(c.data.text)}</blockquote>${c.data.source_url?`<a href="${esc(c.data.source_url)}" target="_blank" rel="noopener noreferrer">核对原文链接 ↗</a>`:''}${c.stale&&pending?'<div class="alert">通知或事项已更新，此预览已过期。请排除旧提案，再根据最新内容重新记录。</div>':''}${c.data.kind==='unverified'?'<div class="alert">线索未核实，保留最后已确认的期限。核实后请建立正式变更；排除线索不会改动待办。</div>':''}${c.impact.map(i=>`<section class="impact-item"><h3>${esc(i.title)}</h3><dl class="impact-diff">${Object.entries(i.diff).map(([k,v])=>`<div><dt>${esc(fieldNames[k])}</dt><dd><span class="diff-before">${esc(format(v.before))}</span><span class="diff-arrow" aria-label="变更为">→</span><strong>${esc(format(v.after))}</strong></dd></div>`).join('')}</dl>${i.warnings.map(w=>`<p class="small muted">${esc(w)}</p>`).join('')}</section>`).join('')}${c.imported?'<div class="alert info">这是导入的历史记录，原有核实结论不代表当前批次已重新验证。请结合本次原文核对；待核实线索不能直接更新事项。</div>':''}${!pending?`<p class="small muted">${c.decision_note?'原核实结论：'+esc(c.decision_note):'应用时的前后值保存在通知修改记录和各事项时间线中。'}</p>`:`${area('核实依据 / 排除原因','note','',3,'required minlength="2" maxlength="1500" placeholder="写明向谁、通过什么原文核实了对象与要求"')}${canApply?'<label class="check"><input type="checkbox" name="verified"><span>已核实发布方、适用范围与原文，确认应用上方变化</span></label>':''}<div class="form-footer">${btn('排除本条变更','data-dismiss-change')}${canApply?'<button type="submit" class="button primary">确认应用变更</button>':''}</div>`}</form>`);
    for(const [index,item] of c.impact.entries()){
      if(!item.affected_steps?.length)continue;
      document.querySelectorAll('.impact-item')[index]?.insertAdjacentHTML('beforeend',`<div class="action-review-downstream"><strong>还需核对 ${item.affected_steps.length} 个后续步骤</strong><p class="small muted">应用后保留其原进度，标记办理影响待复核。</p>${item.affected_steps.map(step=>`<p class="small">${esc(step.title)} · ${esc(statusNames[step.status])}</p>`).join('')}</div>`);
    }
  }

  async function calendarCheck(tid){
    persist();const request=++state.dialogRequest,{task:t}=await api(`/tasks/${tid}/workflow`);
    if(request!==state.dialogRequest)return;
    const c=t.calendar_check;
    showDialog('日历与提醒验证',`<form id="calendar-check-form" data-workspace-form="calendar-check" data-task-id="${tid}" data-version="${t.version}" class="stack"><h3>${esc(t.data.title)}</h3><div class="calendar-check-status"><span>${t.exported_version?'已导出版本 '+t.exported_version:'尚未导出'}</span><span>当前版本 ${t.version}</span>${c?`<span>${c.current?'本版本':'旧版本'}本人记录：${esc({imported:'已导入',reminder_verified:'锁屏提醒已验证',failed:'验证未通过',removed:'已移除旧事件'}[c.result])}</span>`:''}</div><p class="small muted">导出不代表导入或送达。请在目标设备完成操作，再按实际结果记录。</p>${btn('导出当前日历文件',`data-workflow-export="${tid}"`)}${field('手机 / 电脑与日历应用','device',c?.device||'','text','required minlength="2" maxlength="160" placeholder="例如：iPhone · Apple 日历"')}${select('本人实际验证结果','result',{imported:'已导入，尚未验证提醒',reminder_verified:'关闭页面、锁屏后已实际收到提醒',failed:'未成功导入或未收到提醒',...(t.status==='cancelled'?{removed:'已在目标日历删除旧事件'}:{})},c?.result||'imported')}${area('验证说明','note',c?.note||'',3,'maxlength="1000" placeholder="记录权限设置、提醒时间或失败原因"')}<div class="form-footer"><button type="submit" class="button primary">保存本人验证记录</button></div></form>`);
  }

  async function submit(form,decision='apply'){
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
        const t=taskSnapshot,result=await api(`/tasks/${t.id}/workflow`,{method:'PUT',json:{version:t.workflow.version,task_version:t.version,data:workflowSnapshot}});
        let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；旧草稿清理未完成，请核对暂存状态';}if(request===state.dialogRequest){$('#dialog').close();displayTaskUpdate(result);}toast('办理记录已保存，后续可继续跟进'+cacheWarning,!!cacheWarning);
      }else if(form.id==='change-form'){
        const d=changeSnapshot,targets=[];
        for(const [tid,s] of Object.entries(d.targets)){if(!s.selected)continue;const patch={};for(const [k,on] of Object.entries(s.fields||{}))if(on)patch[k]=k==='materials'?s.values[k].split('\n').map(x=>x.trim()).filter(Boolean):['due_date','due_time'].includes(k)?s.values[k]||null:s.values[k].trim();targets.push({task_id:tid,version:noticeSnapshot.tasks.find(t=>t.id===tid).version,action:d.kind==='cancellation'?'cancel':d.kind==='restoration'?'restore':'revise',patch});}
        const n=noticeSnapshot,c=await api(`/notices/${n.id}/changes`,{method:'POST',json:{...d,published_at:toTime(d.published_at),targets,notice_version:n.version}});
        let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；旧草稿清理未完成，请核对暂存状态';}if(request===state.dialogRequest){form.remove();if(routeId===state.renderId)await route();await openChange(n.id,c.id);}toast('变更已保存，尚未修改正式待办'+cacheWarning,!!cacheWarning);
      }else if(form.id==='change-decision-form'){
        const fd=new FormData(form),nid=form.dataset.noticeId;
        await api(`/notices/${nid}/changes/${form.dataset.changeId}/decision`,{method:'POST',json:{version:Number(form.dataset.version),decision,verified:fd.has('verified'),note:fd.get('note')}});
        if(request===state.dialogRequest)$('#dialog').close();if(routeId===state.renderId)await route();toast(decision==='apply'?'变更已应用，请核对个人计划和外部日历':'已记录核实结论，原安排保留');
      }else if(form.id==='calendar-check-form'){
        const fd=new FormData(form),t=await api(`/tasks/${form.dataset.taskId}/calendar-check`,{method:'POST',json:{task_version:Number(form.dataset.version),...Object.fromEntries(fd)}});
        if(request===state.dialogRequest){$('#dialog').close();displayTaskUpdate(t);}toast('已保存本人验证记录');
      }
    }catch(error){const p=document.createElement('div');p.className='alert error form-error';p.setAttribute('role','alert');p.textContent=error.message;form.prepend(p);p.scrollIntoView({block:'nearest'});}
    finally{form.inert=false;finishFeedback();}
  }

  document.addEventListener('submit',e=>{if(['workflow','change','decision','calendar-check'].includes(e.target.dataset.workspaceForm)){e.preventDefault();submit(e.target);}});
  document.addEventListener('input',e=>{if(e.target.matches('[data-dependency-search]'))for(const label of document.querySelectorAll('[data-dependency-label]'))label.hidden=!label.dataset.dependencyLabel.includes(e.target.value.toLowerCase());if(e.target.closest('#workflow-form,#change-form'))persist();});
  document.addEventListener('change',e=>{const form=e.target.closest('#workflow-form,#change-form');if(!form)return;if(e.target.name==='action_kind')$('[data-optional-choice]').hidden=e.target.value!=='optional';if(form.id==='change-form'&&e.target.name==='kind')renderTargets(e.target.value);if(e.target.name==='target'){const fields=e.target.closest('[data-target]').querySelector('.target-fields');if(fields)fields.hidden=!e.target.checked;}persist();});
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-workflow-task],[data-change-new],[data-change-open],[data-calendar-check],[data-workflow-export],[data-dismiss-change]');if(!b||b.disabled)return;b.disabled=true;
    try{if(b.dataset.workflowTask)await openTask(b.dataset.workflowTask);else if(b.dataset.changeNew)await newChange(b.dataset.changeNew);else if(b.dataset.changeOpen)await openChange(b.dataset.noticeId,b.dataset.changeOpen);else if(b.dataset.calendarCheck)await calendarCheck(b.dataset.calendarCheck);else if(b.dataset.workflowExport){const {task}=await api(`/tasks/${b.dataset.workflowExport}/workflow`);await exportTasks([task]);}else if(b.hasAttribute('data-dismiss-change')){const f=b.closest('form');if(f.reportValidity())await submit(f,'dismiss');}}
    catch(error){toast(error.message,true);}finally{b.disabled=false;}
  });
  return {badges,noticePanel,persist,openTask};
}
