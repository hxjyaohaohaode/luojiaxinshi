// A small, evidence-bound reading order. It never changes eligibility or tasks.
export function noticeFocusModel(notice,now=Date.now()){
  const draft=notice.draft,quality=draft?.quality?.status;
  const candidates=(draft?.tasks||[]).filter(task=>task.scope!=='other').flatMap(task=>{
    const result=[];
    if(task.due_date&&task.deadline_evidence?.length)result.push({label:'原文截止',date:task.due_date,time:task.due_time||'',title:task.title});
    if(task.scheduled?.start_date&&task.scheduled.evidence?.length)result.push({label:task.scheduled.kind==='window'?'办理开始':'活动时间',date:task.scheduled.start_date,time:task.scheduled.start_time||'',title:task.title});
    return result;
  }).map(item=>({...item,at:Date.parse(item.date+'T'+(item.time||'23:59:59')+'+08:00')})).filter(item=>Number.isFinite(item.at));
  candidates.sort((a,b)=>Number(a.at<now)-Number(b.at<now)||a.at-b.at);
  const shared=notice.assessment?.focus;
  const next=shared?(shared.key_time?{...shared.key_time,at:Number(shared.key_time.at)*1000}:null):candidates[0]||null;
  const issues=draft?.quality?.issues?.length||0,updates=(notice.intake_updates||[]).filter(item=>item.state==='pending').length;
  const label=notice.tracking?.label;
  const historical=['elapsed','entry_closed','event_date_passed','cancelled'].includes(notice.tracking?.state);
  const concern=quality==='unavailable'?'独立核对未完成':quality==='needs_review'?`${issues||'部分'}项内容需核对`:'';
  return {next,concern,updates,historical,label,urgent:!!next&&next.label==='原文截止'&&next.at>=now&&next.at-now<=86400000,
    relevance:draft?.applicability==='not_matching'?'可能不适用':draft?.applicability==='matches_known'?'与已知条件相符':draft?'适用条件尚不完整':''};
}

export function noticeFocus(notice,{esc,now=Date.now()}){
  const m=noticeFocusModel(notice,now);
  if(!m.next&&!m.concern&&!m.updates&&!m.historical&&!m.relevance)return '';
  const date=m.next?m.next.date.replaceAll('-','/')+(m.next.time?' '+m.next.time:''):'';
  return `<section class="notice-focus ${m.urgent?'is-urgent':''}" aria-label="这则通知的重点">
    ${m.next?`<div class="notice-key-time"><span>${esc(m.next.label)}</span><strong>${esc(date)}</strong>${m.urgent?'<span class="notice-urgency">24 小时内</span>':''}</div>`:''}
    <div class="notice-focus-status">${m.historical?`<span>${esc(m.label)}</span>`:m.relevance?`<span>${esc(m.relevance)}</span>`:''}${m.concern?`<button type="button" class="notice-attention" data-action="focus-notice-quality">${esc(m.concern)} ↗</button>`:''}${m.updates?`<button type="button" class="notice-attention" data-action="focus-notice-context">来源有 ${m.updates} 次修订 ↗</button>`:''}</div>
  </section>`;
}
