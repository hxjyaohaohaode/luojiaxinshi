export function scheduledLabel(data){
  const slot=data.scheduled;if(!slot)return '';
  return `${slot.kind==='window'?'办理时段':'活动'} ${slot.start_date}${slot.start_time?' '+slot.start_time:''}${slot.end_date?' — '+slot.end_date+(slot.end_time?' '+slot.end_time:''):''}`;
}
export function taskTimeLabel(data){
  return [data.due_date?'截止 '+data.due_date+(data.due_time?' '+data.due_time:'' ):'',scheduledLabel(data)].filter(Boolean).join(' · ')||(data.planned_at?'已设置个人计划':'未设置期限或时段');
}
export function needsTimingReview(task){
  const d=task.data,mode=task.workflow?.data?.execution_mode;
  return !!((d.due_date&&!d.deadline_confirmed)||(d.scheduled&&!d.scheduled.confirmed)||(!d.due_date&&!d.scheduled&&(!mode||mode==='submission')));
}
export function calendarReady(data){
  return !!(data.due_date||data.planned_at||data.scheduled)&&(!data.due_date||data.deadline_confirmed)&&(!data.scheduled||data.scheduled.confirmed);
}
export function taskOnDay(data,day){
  return data.due_date===day||!!(data.scheduled&&data.scheduled.start_date<=day&&(data.scheduled.end_date||data.scheduled.start_date)>=day);
}
export function scheduledEditor(data,field,esc){
  const slot=data.scheduled||{};
  return `<details class="details task-scheduled" ${data.scheduled?'open':''}><summary>活动时间 / 办理时段${data.scheduled?' · '+esc(slot.start_date):''}</summary><label class="check"><input type="checkbox" name="use_scheduled" ${data.scheduled?'checked':''}>记录原文中的时段</label><fieldset data-scheduled-fields ${data.scheduled?'':'disabled'}><label class="field">时间含义<select name="scheduled_kind"><option value="event">活动发生时间</option><option value="window" ${slot.kind==='window'?'selected':''}>开放办理时段</option></select></label><div class="form-grid">${field('开始日期','scheduled_start_date',slot.start_date||'','date','required')}${field('开始时刻（未写明可留空）','scheduled_start_time',slot.start_time||'','time')}${field('结束日期（未写明可留空）','scheduled_end_date',slot.end_date||'','date')}${field('结束时刻（未写明可留空）','scheduled_end_time',slot.end_time||'','time')}</div><label class="check"><input name="scheduled_confirmed" type="checkbox" ${slot.confirmed?'checked':''}>时段已对照原文核实</label></fieldset></details>`;
}
export function readScheduled(el,base){
  const get=name=>el.querySelector(`[name="${name}"]`);
  if(!get('use_scheduled')?.checked)return null;
  return {kind:get('scheduled_kind').value,start_date:get('scheduled_start_date').value,start_time:get('scheduled_start_time').value||null,end_date:get('scheduled_end_date').value||null,end_time:get('scheduled_end_time').value||null,confirmed:get('scheduled_confirmed').checked,evidence:base.scheduled?.evidence||[]};
}
export function installScheduledEditing(){
  document.addEventListener('change',event=>{
    if(event.target.name==='use_scheduled')event.target.closest('.task-scheduled').querySelector('[data-scheduled-fields]').disabled=!event.target.checked;
  },true);
  document.addEventListener('input',event=>{
    if(event.target.name?.startsWith('scheduled_')&&event.target.name!=='scheduled_confirmed')event.target.closest('.task-scheduled').querySelector('[name=scheduled_confirmed]').checked=false;
  },true);
}
