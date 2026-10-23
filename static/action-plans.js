// Draft identities survive reorder and selection; server IDs exist only after confirmation.
export const actionKinds={unclassified:'还没分类',required:'必须办',optional:'可自选',verification:'核对信息'};
export const taskIsPending=task=>task.status==='pending'&&!task.action_excluded;
const freshId=()=>crypto.randomUUID();
const defaultPlan=()=>({action_kind:'unclassified',depends_on:[],conditions:[],participation:'undecided'});
export function initializeDraftPlans(tasks,plans={}){
  const ids=tasks.map(t=>t._plan_id||freshId());
  return tasks.map((t,i)=>{
    if(t._plan)return{...t,_plan_id:ids[i],_source_index:t._source_index??(t.origin==='ai'?i:null)};
    const proposal=plans[i]||{};
    return{...t,_plan_id:ids[i],_plan_update:false,_source_index:t._source_index??(t.origin==='ai'?i:null),
      include:proposal.action_kind==='optional'?false:t.include,
      _plan:{...defaultPlan(),...proposal,depends_on:(proposal.depends_on||[]).map(index=>ids[index]||'missing:'+index)}};
  });
}
export function plainTask(draft){return Object.fromEntries(Object.entries(draft).filter(([key])=>!key.startsWith('_')&&!['include','replacement'].includes(key)));}
export function prepareConfirmation(drafts,notice){
  const selected=drafts.filter(d=>d.include!==false),ids=new Map(selected.map((d,i)=>[d._plan_id,i]));
  if(!selected.length)throw new Error('至少选一个要做的步骤吧');
  if(ids.size!==selected.length)throw new Error('草稿里的步骤对不上了，刷新后再看看');
  const result={tasks:selected.map(plainTask),plans:{},replacements:{},target_versions:{}};
  for(const[draftIndex,draft]of selected.entries()){
    let existing;
    if(draft.replacement){
      existing=notice.tasks.find(t=>t.id===draft.replacement);if(!existing)throw new Error('原来的待办在别的页面改过了，重新打开通知看看最新的');
      result.replacements[draftIndex]=existing.id;result.target_versions[existing.id]=existing.version;
    }
    const p=draft._plan||defaultPlan();
    if(existing&&!draft._plan_update)continue;
    if(p.action_kind==='unclassified'&&!p.conditions.length&&!p.depends_on.length)continue;
    const dependencies=p.depends_on.map(id=>{
      if(!ids.has(id))throw new Error('前置步骤“'+(drafts.find(t=>t._plan_id===id)?.title||'已移除步骤')+'”还没选中。把它选上，或者调整一下前置步骤。');
      return ids.get(id);
    });
    result.plans[draftIndex]={...p,depends_on:dependencies,workflow_version:existing?.workflow?.version??0};
  }
  return result;
}
export function draftPlanEditor(draft,index,tasks,esc){
  const p=draft._plan||defaultPlan(),active=!!draft._plan_update,replace=!!draft.replacement;
  const candidates=tasks.filter(t=>t._plan_id!==draft._plan_id);
  return `<details class="details draft-plan" ${p.action_kind==='optional'||p.conditions.length||p.depends_on.length?'open':''}><summary>事项类型和前置步骤 · ${esc(actionKinds[p.action_kind])}</summary>
    <div data-plan-replacement ${replace?'':'hidden'}><label class="check"><input type="checkbox" name="plan_update" ${active?'checked':''}><span>同时更新原待办的类型、前置步骤和条件</span></label><p class="small muted">默认保留原来的安排。勾上后按这里更新；没变的条件保留之前的确认，新加的条件要重新确认。</p></div>
    <fieldset class="draft-plan-controls" ${replace&&!active?'disabled':''}><label class="field">事项类型<select name="plan_kind">${Object.entries(actionKinds).map(([k,v])=>`<option value="${k}" ${p.action_kind===k?'selected':''}>${v}</option>`).join('')}</select></label>
    <div data-plan-optional ${p.action_kind==='optional'?'':'hidden'}><label class="field">你想参加吗<select name="plan_participation">${Object.entries({undecided:'还没想好，先记着',joined:'要参加',declined:'不参加，留个记录'}).map(([k,v])=>`<option value="${k}" ${p.participation===k?'selected':''}>${v}</option>`).join('')}</select></label></div>
    <label class="field">要先确认的条件（每行一条）<textarea name="plan_conditions" rows="2" maxlength="3208" placeholder="例如：已收到正式立项通知">${esc(p.conditions.join('\n'))}</textarea></label><p class="small muted">条件会先记成“待确认”，之后在“办理与跟进”里更新；满不满足由你来确认，AI 不会替你打勾。</p>
    ${candidates.length?`<details class="plan-dependencies" ${p.depends_on.length?'open':''}><summary>必须先做的步骤${p.depends_on.length?' · '+p.depends_on.length+' 项':''}</summary><div class="dependency-list">${candidates.map(t=>`<label class="check"><input type="checkbox" name="plan_dependency" value="${esc(t._plan_id)}" ${p.depends_on.includes(t._plan_id)?'checked':''}><span>${esc(t.title||'未命名步骤')}</span></label>`).join('')}</div><p class="small muted">只选原文要求必须先做的；一般的建议顺序不用选。选中的前置步骤要一起保存。</p></details>`:''}</fieldset></details>`;
}
export function readDraftPlan(el,base){
  const get=name=>el.querySelector(`[name="${name}"]`),kind=get('plan_kind')?.value||'unclassified';
  return{_plan_id:base._plan_id||freshId(),_source_index:base._source_index??null,_plan_update:!!get('plan_update')?.checked,
    _plan:{action_kind:kind,participation:kind==='optional'?get('plan_participation').value:'undecided',
      conditions:(get('plan_conditions')?.value||'').split('\n').map(t=>t.trim()).filter(Boolean),
      depends_on:[...el.querySelectorAll('[name="plan_dependency"]:checked')].map(e=>e.value)}};
}
export function syncDraftPlanControls(target){
  const editor=target.closest('.task-editor');if(!editor)return;
  const replacement=editor.querySelector('[name="replacement"]')?.value,box=editor.querySelector('[name="plan_update"]');
  if(!box)return;
  if(target.name==='replacement')box.checked=false;
  editor.querySelector('[data-plan-replacement]').hidden=!replacement;
  editor.querySelector('.draft-plan-controls').disabled=!!replacement&&!box.checked;
  editor.querySelector('[data-plan-optional]').hidden=editor.querySelector('[name="plan_kind"]').value!=='optional';
}

export function conditionRow(condition,esc){
  return `<div class="action-condition" data-condition-id="${esc(condition.id)}" data-original-condition="${esc(condition.text)}">
    <label class="field">办理前提<textarea name="condition_text" rows="2" required minlength="2" maxlength="400">${esc(condition.text)}</textarea></label>
    <label class="field">确认结果<select name="condition_state">${Object.entries({unknown:'待确认',met:'已满足',not_met:'还没满足'}).map(([k,v])=>`<option value="${k}" ${condition.state===k?'selected':''}>${v}</option>`).join('')}</select></label>
    <label class="field">依据 / 之前的记录<textarea name="condition_note" rows="2" minlength="2" maxlength="1500" ${condition.state!=='unknown'?'required':''} placeholder="比如看了哪条通知、名单，或问了谁">${esc(condition.note||'')}</textarea></label>
    <button type="button" class="button small plain" data-remove-condition>删掉这条前提</button></div>`;
}
export function conditionsEditor(conditions,esc){return `<fieldset class="workflow-section condition-section"><legend>办理前提与外部条件</legend><p class="small muted">先确认资格、立项这些前提，再记提交或完成。改了条件内容，之前的确认结果会清空。</p><div data-condition-list>${conditions.map(c=>conditionRow(c,esc)).join('')}</div><button type="button" class="button small" data-add-condition ${conditions.length>=8?'disabled':''}>加一条前提</button><p class="small muted">最多 8 条，每条都要满足；“任选其一”的写在同一条里。</p></fieldset>`;}
export function readConditions(form){return[...form.querySelectorAll('[data-condition-id]')].map(e=>({id:e.dataset.conditionId,text:e.querySelector('[name="condition_text"]').value.trim(),state:e.querySelector('[name="condition_state"]').value,note:e.querySelector('[name="condition_note"]').value.trim()}));}
export function installConditionEditing(esc,persist){
  document.addEventListener('click',event=>{
    const form=event.target.closest('#workflow-form');if(!form)return;
    if(event.target.closest('[data-add-condition]')){
      if(form.querySelectorAll('[data-condition-id]').length>=8)return;
      form.querySelector('[data-condition-list]').insertAdjacentHTML('beforeend',conditionRow({id:freshId(),text:'',state:'unknown',note:''},esc));
      form.querySelector('[data-condition-id]:last-child [name="condition_text"]')?.focus();persist();
    }else if(event.target.closest('[data-remove-condition]')){event.target.closest('[data-condition-id]').remove();persist();}
    form.querySelector('[data-add-condition]').disabled=form.querySelectorAll('[data-condition-id]').length>=8;
  });
  document.addEventListener('change',event=>{
    if(event.target.name==='condition_state'&&event.target.closest('#workflow-form'))event.target.closest('[data-condition-id]').querySelector('[name="condition_note"]').required=event.target.value!=='unknown';
  },true);
  document.addEventListener('input',event=>{
    if(event.target.name!=='condition_text'||!event.target.closest('#workflow-form'))return;
    const row=event.target.closest('[data-condition-id]');
    if(event.target.value.trim()!==row.dataset.originalCondition){row.querySelector('[name="condition_state"]').value='unknown';const note=row.querySelector('[name="condition_note"]');note.value='';note.required=false;}
  },true);
}
