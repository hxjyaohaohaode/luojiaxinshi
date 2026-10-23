export const executionModes={task:'一般行动',submission:'材料申报',attendance:'参加活动',reading:'阅读知悉',decision:'作出选择',collection:'领取',payment:'缴费核对',waiting:'等待结果',custom:'自定义办理'};
export const legacyStages={preparing:'准备中',submitted:'已提交，等结果',supplement:'待补件',accepted:'已受理',rejected:'未通过',blocked:'受阻'};
const labels={task:['待开始','进行中','已记录结果'],attendance:['待参加','参与中','已参加'],reading:['待阅读','阅读中','已阅读'],decision:['待决定','比较与核实中','已作出决定'],collection:['待领取','办理中','已领取'],payment:['待核对','核对与办理中','已记录付款结果'],waiting:['待跟进','跟进中','已收到结果'],custom:['待开始','进行中','已记录结果']};
export function stageOptions(mode='submission',current='preparing'){
  const names=labels[mode]||labels.task;
  const result=mode==='submission'?{...legacyStages,waiting:'等待外部结果'}:{preparing:names[0],active:names[1],waiting:'等待外部结果',recorded:names[2],blocked:'受阻'};
  const prior={...legacyStages,active:'进行中',waiting:'等待外部结果',recorded:'已记录结果'};
  if(!(current in result)&&prior[current])result[current]=prior[current];
  return result;
}
export function workflowStage(data={}){
  return data.execution_mode==='custom'&&data.phase_label?data.phase_label:stageOptions(data.execution_mode,data.stage)[data.stage]||'待开始';
}
export function milestoneRow(step,esc){
  return `<div class="workflow-milestone" data-milestone-id="${esc(step.id)}" data-original-title="${esc(step.title)}"><label class="check"><input type="checkbox" data-milestone-done ${step.done?'checked':''} aria-label="步骤已完成"><span class="sr-only">已完成</span></label><div class="stack"><input data-milestone-title aria-label="办理步骤" maxlength="160" required value="${esc(step.title)}" placeholder="填写实际需要做的步骤"><input data-milestone-note aria-label="步骤记录" maxlength="500" value="${esc(step.note||'')}" placeholder="结果或备注（选填）"></div><button type="button" class="button small plain" data-remove-milestone aria-label="移除这一步">移除</button></div>`;
}
export function handlingEditor(data,esc){
  const mode=data.execution_mode||'submission';
  return `<section class="workflow-section handling-editor"><label class="field">办理方式<select name="execution_mode">${Object.entries(executionModes).map(([key,label])=>`<option value="${key}" ${key===mode?'selected':''}>${label}</option>`).join('')}</select></label><label class="field" data-custom-phase ${mode==='custom'?'':'hidden'}>当前进展名称<input name="phase_label" maxlength="80" value="${esc(data.phase_label||'')}" placeholder="例如：等抽签、已联系指导老师"></label><details ${(data.milestones||[]).length?'open':''}><summary>我的办理步骤 · ${(data.milestones||[]).filter(s=>s.done).length} / ${(data.milestones||[]).length}</summary><div data-milestones>${(data.milestones||[]).map(s=>milestoneRow(s,esc)).join('')}</div><button type="button" class="button small" data-add-milestone>添加步骤</button></details></section>`;
}
export function readMilestones(form){return [...form.querySelectorAll('[data-milestone-id]')].map(row=>({id:row.dataset.milestoneId,title:row.querySelector('[data-milestone-title]').value.trim(),note:row.querySelector('[data-milestone-note]').value.trim(),done:row.querySelector('[data-milestone-done]').checked}));}
export function syncHandlingFields(form){
  const mode=form.elements.execution_mode.value,submission=mode==='submission';
  const receipt=form.querySelector('.workflow-receipt');
  if(receipt){
    receipt.querySelector('summary').textContent=submission?'提交与结果':'办理结果';
    for(const name of ['receipt','receipt_url'])form.elements[name].closest('label').hidden=!submission&&!form.elements[name].value;
  }
  const materials=form.querySelector('[data-prepared-materials]');if(materials)materials.hidden=!submission&&!materials.querySelector('[name=material]');
}
function syncMilestones(form){
  const steps=readMilestones(form),details=form.querySelector('.handling-editor details');
  details.querySelector('summary').textContent=`我的办理步骤 · ${steps.filter(s=>s.done).length} / ${steps.length}`;
  form.querySelector('[data-add-milestone]').disabled=steps.length>=20;
}
export function installHandlingEditor(esc,persist){
  document.addEventListener('change',event=>{
    const form=event.target.closest('#workflow-form');if(!form||event.target.name!=='execution_mode')return;
    const stage=form.elements.stage,current=stage.value;
    stage.innerHTML=Object.entries(stageOptions(event.target.value,current)).map(([value,label])=>`<option value="${value}" ${value===current?'selected':''}>${esc(label)}</option>`).join('');
    form.querySelector('[data-custom-phase]').hidden=event.target.value!=='custom';syncHandlingFields(form);persist();
  });
  document.addEventListener('input',event=>{
    const row=event.target.closest('[data-milestone-id]');if(!row)return;
    if(event.target.matches('[data-milestone-title]')&&event.target.value.trim()!==row.dataset.originalTitle)row.querySelector('[data-milestone-done]').checked=false;
    syncMilestones(row.closest('form'));
  },true);
  document.addEventListener('click',event=>{
    const form=event.target.closest('#workflow-form');if(!form)return;
    if(event.target.closest('[data-add-milestone]')){
      const list=form.querySelector('[data-milestones]');if(list.children.length>=20)return;
      list.insertAdjacentHTML('beforeend',milestoneRow({id:crypto.randomUUID(),title:'',done:false},esc));
      list.lastElementChild.querySelector('[data-milestone-title]').focus();persist();
    }
    if(event.target.closest('[data-remove-milestone]')){event.target.closest('[data-milestone-id]').remove();persist();}
    syncMilestones(form);
  });
}
