const fields={details:'办理说明',scope:'办理责任',due_date:'正式日期',due_time:'截止时刻',deadline_text:'期限原文',materials:'材料要求',submission:'提交方式',location:'办理地点',status:'事项状态',progress:'办理结果',dependencies:'前置关系',conditions:'办理条件或参加意愿'};
export const reviewPending=task=>task.change_review?.state==='pending';

export function createActionReviewUI({state,api,esc,showDialog,toast,area,drafts,route}){
  const $=s=>document.querySelector(s);
  function banner(t){
    const issues=t.schedule_issues||[];
    return (reviewPending(t)?`<section class="action-review-banner"><strong>办理依据已变化，需要核对影响</strong><p>原完成记录、回执与备注仍保留。请确认已有办理是否仍有效，或重新打开需要补正的步骤。</p><button type="button" class="button" data-action-review="${t.id}">核对办理影响</button></section>`:'')+
      (issues.length?`<div class="alert"><strong>个人安排需要留意</strong>${issues.map(i=>`<p>${esc(i.message)}</p>`).join('')}</div>`:'');
  }
  function persist(){
    const form=$('#action-review-form');if(!form||!form.dataset.cacheKey||drafts.peek(form.dataset.cacheKey).retired)return;
    const value=Object.fromEntries(new FormData(form));
    if(JSON.stringify(value)!==JSON.stringify(drafts.peek(form.dataset.cacheKey).payload))drafts.stage(form.dataset.cacheKey,value);
  }
  async function open(tid){
    const request=++state.dialogRequest,owner=state.session?.user?.id;
    const {task:t}=await api(`/tasks/${tid}/workflow`);
    if(request!==state.dialogRequest||state.session?.user?.id!==owner)return;
    if(!reviewPending(t)){toast('这项办理影响已核对，请查看当前记录');return;}
    const r=t.change_review,key=`review:${tid}:${t.version}:${r.version}`,cache=await drafts.load(key);
    if(request!==state.dialogRequest||state.session?.user?.id!==owner)return;
    drafts.activate(key);const d=cache.payload||{};
    showDialog('核对办理影响',`<form id="action-review-form" data-workspace-form="action-review" data-task-id="${tid}" data-version="${r.version}" data-task-version="${t.version}" data-cache-key="${key}" class="stack"><h3>${esc(t.data.title)}</h3><p class="muted">办理要求、前置关系或结果发生变化，原记录保留。确认的是已有办理是否仍适用，不代表学校重新受理。</p><div class="action-review-causes">${r.data.causes.map(c=>`<article><strong>${esc(c.source_id===tid?'本步骤的变化':c.title)}</strong><p>${c.source_id===tid?'本步骤有变化':'相关前置步骤有变化'}${c.fields.length?'：'+c.fields.map(k=>esc(fields[k]||k)).join('、'):''}。</p>${c.source_id!==tid&&c.kind!=='deleted'&&!(c.kind==='deleted'||c.source_id.startsWith('missing_'))?`<button type="button" class="button small" data-workflow-task="${esc(c.source_id)}">查看来源步骤</button>`:''}${(c.kind==='deleted'||c.source_id.startsWith('missing_'))?'<p class="small muted">原步骤尚未导入或已缺失，请结合原文核实。</p>':''}</article>`).join('')}</div>${(t.schedule_issues||[]).map(i=>`<p class="alert">${esc(i.message)}</p>`).join('')}<fieldset class="action-review-options"><legend>本人核对后的处理</legend><label class="check"><input type="radio" name="decision" value="keep" ${d.decision==='keep'?'checked':''} required><span>原办理仍然有效，保留当前进度</span></label>${t.status!=='cancelled'?`<label class="check"><input type="radio" name="decision" value="reopen" ${d.decision==='reopen'?'checked':''} required><span>需要重新办理或补正，恢复为待完成</span></label>`:''}</fieldset>${area('核对依据与需要处理的内容','note',d.note||'',4,'required minlength="2" maxlength="1500" placeholder="例如：已向负责老师核实，新增签字页适用于本人，需要补交。"')}<div class="workflow-tools"><button type="button" class="button" data-action="edit-task" data-id="${tid}">先调整个人计划与提醒</button></div><div class="form-footer workflow-save"><button type="submit" class="button primary">保存复核结论</button></div></form>`);
  }
  document.addEventListener('input',e=>{if(e.target.closest('#action-review-form'))persist();});
  document.addEventListener('change',e=>{if(e.target.closest('#action-review-form'))persist();});
  document.addEventListener('submit',async e=>{
    const form=e.target;if(form.id!=='action-review-form')return;e.preventDefault();if(form.inert)return;
    persist();const body=Object.fromEntries(new FormData(form)),key=form.dataset.cacheKey,tid=form.dataset.taskId;
    const payload={...body,version:Number(form.dataset.version),task_version:Number(form.dataset.taskVersion)};
    const request=state.dialogRequest,page=state.renderId,submittedCache=drafts.checkpoint(key);form.inert=true;form.querySelector('.form-error')?.remove();
    try{
      await drafts.flush(key);await api(`/tasks/${tid}/change-review`,{method:'POST',json:payload});let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；旧草稿清理未完成，请核对暂存状态';}
      if(request===state.dialogRequest){$('#dialog').close();if(page===state.renderId)await route();}
      toast((body.decision==='reopen'?'已恢复待完成，原办理记录仍可回查':'已保存本人复核结论')+cacheWarning,!!cacheWarning);
    }catch(error){if(form.isConnected){const p=document.createElement('p');p.className='alert error form-error';p.setAttribute('role','alert');p.textContent=error.message;form.prepend(p);p.scrollIntoView({block:'nearest'});}else toast(error.message,true);}
    finally{form.inert=false;}
  });
  document.addEventListener('click',async e=>{const button=e.target.closest('[data-action-review]');if(!button||button.disabled)return;button.disabled=true;try{await open(button.dataset.actionReview);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
  return {banner,persist};
}
