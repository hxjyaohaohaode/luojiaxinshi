const fields={details:'办理说明',scope:'谁来办',due_date:'截止日期',due_time:'截止时刻',deadline_text:'期限原文',materials:'材料要求',submission:'提交方式',location:'办理地点',status:'事项状态',progress:'办理结果',dependencies:'前置步骤',conditions:'办理条件或是否参加'};
export const reviewPending=task=>task.change_review?.state==='pending';

export function createActionReviewUI({state,api,esc,showDialog,toast,area,drafts,route}){
  const $=s=>document.querySelector(s);
  function banner(t){
    const issues=t.schedule_issues||[];
    return (reviewPending(t)?`<section class="action-review-banner"><strong>这件事的要求有变动，来看看影响</strong><p>之前的完成记录、凭证和备注都还在。看看已经办的还算不算数，要补的话就重新打开那一步。</p><button type="button" class="button" data-action-review="${t.id}">看看变动影响</button></section>`:'')+
      (issues.length?`<div class="alert"><strong>安排上有点要留意</strong>${issues.map(i=>`<p>${esc(i.message)}</p>`).join('')}</div>`:'');
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
    if(!reviewPending(t)){toast('这项已经确认过了，看看当前记录吧');return;}
    const r=t.change_review,key=`review:${tid}:${t.version}:${r.version}`,cache=await drafts.load(key);
    if(request!==state.dialogRequest||state.session?.user?.id!==owner)return;
    drafts.activate(key);const d=cache.payload||{};
    showDialog('看看变动影响',`<form id="action-review-form" data-workspace-form="action-review" data-task-id="${tid}" data-version="${r.version}" data-task-version="${t.version}" data-cache-key="${key}" class="stack"><h3>${esc(t.data.title)}</h3><p class="muted">要求、前置步骤或结果有变动，原来的记录都还在。这里只是你自己判断之前办的还算不算数。</p><div class="action-review-causes">${r.data.causes.map(c=>`<article><strong>${esc(c.source_id===tid?'这一步的变化':c.title)}</strong><p>${c.source_id===tid?'这一步有变化':'前置步骤有变化'}${c.fields.length?'：'+c.fields.map(k=>esc(fields[k]||k)).join('、'):''}。</p>${c.source_id!==tid&&c.kind!=='deleted'&&!(c.kind==='deleted'||c.source_id.startsWith('missing_'))?`<button type="button" class="button small" data-workflow-task="${esc(c.source_id)}">看看那一步</button>`:''}${(c.kind==='deleted'||c.source_id.startsWith('missing_'))?'<p class="small muted">原来那一步找不到了，对照原文看看吧。</p>':''}</article>`).join('')}</div>${(t.schedule_issues||[]).map(i=>`<p class="alert">${esc(i.message)}</p>`).join('')}<fieldset class="action-review-options"><legend>你打算怎么处理</legend><label class="check"><input type="radio" name="decision" value="keep" ${d.decision==='keep'?'checked':''} required><span>之前办的还算数，保留进度</span></label>${t.status!=='cancelled'?`<label class="check"><input type="radio" name="decision" value="reopen" ${d.decision==='reopen'?'checked':''} required><span>要重新办或补材料，改回待完成</span></label>`:''}</fieldset>${area('你的判断依据和要做的事','note',d.note||'',4,'required minlength="2" maxlength="1500" placeholder="例如：问过负责老师，新加的签字页我也要交，需要补交。"')}<div class="workflow-tools"><button type="button" class="button" data-action="edit-task" data-id="${tid}">先改计划和提醒</button></div><div class="form-footer workflow-save"><button type="submit" class="button primary">保存我的判断</button></div></form>`);
  }
  document.addEventListener('input',e=>{if(e.target.closest('#action-review-form'))persist();});
  document.addEventListener('change',e=>{if(e.target.closest('#action-review-form'))persist();});
  document.addEventListener('submit',async e=>{
    const form=e.target;if(form.id!=='action-review-form')return;e.preventDefault();if(form.inert)return;
    persist();const body=Object.fromEntries(new FormData(form)),key=form.dataset.cacheKey,tid=form.dataset.taskId;
    const payload={...body,version:Number(form.dataset.version),task_version:Number(form.dataset.taskVersion)};
    const request=state.dialogRequest,page=state.renderId,submittedCache=drafts.checkpoint(key);form.inert=true;form.querySelector('.form-error')?.remove();
    try{
      await drafts.flush(key);await api(`/tasks/${tid}/change-review`,{method:'POST',json:payload});let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；不过旧草稿没清理掉，可以检查一下暂存内容';}
      if(request===state.dialogRequest){$('#dialog').close();if(page===state.renderId)await route();}
      toast((body.decision==='reopen'?'已改回待完成，之前的记录还能翻到':'保存好了')+cacheWarning,!!cacheWarning);
    }catch(error){if(form.isConnected){const p=document.createElement('p');p.className='alert error form-error';p.setAttribute('role','alert');p.textContent=error.message;form.prepend(p);p.scrollIntoView({block:'nearest'});}else toast(error.message,true);}
    finally{form.inert=false;}
  });
  document.addEventListener('click',async e=>{const button=e.target.closest('[data-action-review]');if(!button||button.disabled)return;button.disabled=true;try{await open(button.dataset.actionReview);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
  return {banner,persist};
}
