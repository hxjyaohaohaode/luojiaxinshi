import {observationReceipt} from './review-observation.js';
const actions={changed:'已修改关联内容',acknowledged:'作为办理注意事项',disagreed:'意见不适用',excluded:'相关步骤本次不保存'};
const contextual=issue=>issue.task_index===null&&['condition','obligation','applicability'].includes(issue.code);
const excluded=(issue,tasks)=>issue.task_index!==null&&!tasks.some(t=>t._source_index===issue.task_index&&t.include!==false);
const options=(tasks,esc)=>'<option value="">选择修改或补充的步骤</option>'+tasks.filter(t=>t.include!==false).map(t=>`<option value="${esc(t._plan_id)}">${esc(t.title||'未命名步骤')}</option>`).join('');

export function issueControls(issue,index,tasks,value,esc){
  const auto=excluded(issue,tasks),decision=value?.action||'';
  return `<div class="quality-decision" data-quality-decision="${index}"><p class="small muted" data-quality-excluded ${auto?'':'hidden'}>相关步骤未选中，本次不保存；重新选中后仍需处理此意见。</p>
    <fieldset ${auto?'disabled hidden':''}><legend class="sr-only">意见 ${index+1} 的处理</legend>
    <label class="field">这条意见如何处理<select name="quality_action" required><option value="">请选择处理方式</option>${['changed',...(contextual(issue)?['acknowledged']:[]),'disagreed'].map(action=>`<option value="${action}" ${decision===action?'selected':''}>${actions[action]}</option>`).join('')}</select></label>
    <label class="field" data-quality-target ${issue.task_index===null&&decision==='changed'?'':'hidden'}>关联实际改动<select name="quality_task_key" ${issue.task_index===null&&decision==='changed'?'required':'disabled'}>${options(tasks,esc)}</select></label>
    <label class="field" data-quality-note ${decision?'':'hidden'}><span data-quality-note-label>${decision==='changed'?'处理说明（可选）':'本人核实依据（至少 8 个字）'}</span><textarea name="quality_note" rows="2" maxlength="700" ${decision&&decision!=='changed'?'required minlength="8"':''}>${esc(value?.note||'')}</textarea></label>
    </fieldset></div>`;
}

export function readIssueDecisions(root){
  if(!root)return {};
  return Object.fromEntries([...root.querySelectorAll('[data-quality-decision]')].map(row=>[row.dataset.qualityDecision,{
    action:row.querySelector('[name=quality_action]').value,note:row.querySelector('[name=quality_note]').value,
    task_key:row.querySelector('[name=quality_task_key]').value}]));
}

export function syncIssueControls(root,quality,tasks,decisions,esc){
  if(!root)return;
  let count=0;
  for(const row of root.querySelectorAll('[data-quality-decision]')){
    const i=Number(row.dataset.qualityDecision),issue=quality.issues[i],value=decisions[i]||{},auto=excluded(issue,tasks),action=value.action||'';
    row.querySelector('[data-quality-excluded]').hidden=!auto;
    const fieldset=row.querySelector('fieldset');fieldset.disabled=auto;fieldset.hidden=auto;
    const target=row.querySelector('[name=quality_task_key]'),markup=options(tasks,esc);
    if(target.innerHTML!==markup)target.innerHTML=markup;
    target.value=value.task_key||'';
    const needsTarget=issue.task_index===null&&action==='changed';target.disabled=!needsTarget;target.required=needsTarget;
    row.querySelector('[data-quality-target]').hidden=!needsTarget;
    const note=row.querySelector('[name=quality_note]');note.required=!!action&&action!=='changed';note.minLength=note.required?8:0;
    row.querySelector('[data-quality-note]').hidden=!action;
    row.querySelector('[data-quality-note-label]').textContent=note.required?'本人核实依据（至少 8 个字）':'处理说明（可选）';
    if(auto||(action&&(!note.required||note.value.trim().length>=8)&&(!needsTarget||target.value)))count++;
  }
  const status=root.querySelector('[data-quality-count]');if(status)status.textContent=`已有处理选择 ${count} / ${(quality.issues||[]).length}；保存时会检查实际改动和关联。`;
  resizeQualityNotes(root);
}

export function resizeQualityNotes(root){
  if(!root)return;
  for(const note of root.querySelectorAll('[name=quality_note]'))if(note.getBoundingClientRect().width){
    note.style.height='auto';note.style.height=Math.min(220,Math.max(74,note.scrollHeight+2))+'px';
  }
}

export function prepareQualityConfirmation(drafts,notice,decisions,manualReviewed=false){
  if(notice.quality_resolution_contract!==1)return {};
  const selected=drafts.filter(t=>t.include!==false),quality=notice.draft?.quality||{},issue_resolutions=[];
  if(quality.status==='needs_review')for(const [i,issue]of quality.issues.entries()){
    if(excluded(issue,drafts)){issue_resolutions.push({issue_index:i,action:'excluded',note:'',task_indices:[]});continue;}
    const value=decisions[i]||{};
    if(!['changed','acknowledged','disagreed'].includes(value.action))throw new Error(`请处理意见 ${i+1} 后再保存。`);
    let task_indices=[];
    if(value.action==='changed'){
      const target=issue.task_index===null?selected.findIndex(t=>t._plan_id===value.task_key):selected.findIndex(t=>t._source_index===issue.task_index);
      if(target<0)throw new Error(`意见 ${i+1} 的关联步骤未选中，请重新选择。`);
      task_indices=[target];
    }else if((value.note||'').trim().length<8)throw new Error(`意见 ${i+1} 需要至少 8 个字的核实依据。`);
    issue_resolutions.push({issue_index:i,action:value.action,note:value.note||'',task_indices});
  }
  return {source_indices:selected.map(t=>t._source_index??null),issue_resolutions,manual_quality_reviewed:manualReviewed};
}

export function qualityReceipt(receipt,esc){
  if(!receipt)return '';
  const issues=receipt.issues||[];
  if(!issues.length&&!receipt.manual_reviewed)return observationReceipt(receipt.observation,receipt.imported);
  return `<details class="quality-receipt"><summary>${receipt.imported?'导入的历史核对记录':'本次核对与处理记录'}${issues.length?' · '+issues.length+' 条':''}</summary><p class="small muted">${receipt.imported?'这是导入的历史记录，未对当前材料重新核实。':''}这是本人确认时的处理记录，不表示模型或学校已经核准。原意见保留，后续更正另有记录。</p>
    ${observationReceipt(receipt.observation,receipt.imported)}
    ${receipt.manual_reviewed?`<p>独立复核未完成，本人已记录逐份人工核对。</p><p>${esc(receipt.note||'')}</p>`:''}
    ${issues.map((item,i)=>`<details class="quality-receipt-item"><summary>意见 ${i+1} · ${esc(actions[item.action]||'本人处理')}</summary><p>${esc(item.finding.message)}</p>${item.task_titles?.length?`<p>关联当时保存的步骤：${item.task_titles.map(esc).join('、')}</p>`:''}${item.note?`<p class="quality-human-note">本人依据：${esc(item.note)}</p>`:''}${(item.finding.evidence||[]).map(e=>`<div class="evidence">${e.source_id?`<button type="button" data-action="evidence" data-source="${esc(e.source_id)}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button>`:`<span class="small muted">${esc(e.locator)} · 原件未导入</span>`}<p>${esc(e.quote)}</p></div>`).join('')}</details>`).join('')}
  </details>`;
}
