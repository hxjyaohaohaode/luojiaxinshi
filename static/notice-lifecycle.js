const PHASES={unannounced:'等待正式公告',preview:'官方预告',announcement:'正式公告',supplement:'补充说明',publicity:'公示与异议',result:'结果与后续办理'};
const BASES={personal_lead:'本人收集的线索／转述',past_pattern:'往年规律，尚待本次公告',official_preview:'有原文依据的官方预告',official_notice:'有原文依据的正式通知'};
const OUTCOMES={unknown:'尚未核实本人结果',shortlisted:'入围／拟推荐',selected:'入选',not_selected:'未入选',waitlisted:'候补',supplementary:'补录'};
const KINDS={objection:'异议／申诉',confirm_place:'确认名额',collect:'领取',sign:'签约',report:'报到',waitlist:'候补／补录跟进',other:'其他后续行动'};

export function createNoticeLifecycle({state,api,esc,showDialog,toast,onChanged}){
  let sequence=0;
  const options=(values,selected)=>Object.entries(values).map(([key,label])=>`<option value="${key}" ${key===selected?'selected':''}>${esc(label)}</option>`).join('');
  const errorText=(form,message)=>{const target=form.querySelector('[data-lifecycle-error]');if(target){target.textContent=message;target.hidden=false;target.focus();}};
  async function open(noticeId){
    const ticket=++sequence,session=state.session,requested=state.dialogRequest;
    let notice,tracking,matter;
    try{
      [notice,tracking,matter]=await Promise.all([
        api(`/notices/${encodeURIComponent(noticeId)}`),
        api(`/notices/${encodeURIComponent(noticeId)}/lifecycle-tracking`),
        api(`/notices/${encodeURIComponent(noticeId)}/matter`),
      ]);
    }catch(error){if(ticket===sequence&&session===state.session)toast(error.message,true);return;}
    if(ticket!==sequence||session!==state.session||requested!==state.dialogRequest)return;
    const value=tracking.data;
    const ownSources=(notice.sources||[]).filter(source=>source.active!==0);
    const evidence=ownSources.flatMap(source=>(source.sections||[]).flatMap(part=>{
      const chunks=[];for(let start=0;start<part.text.length;start+=1350){
        chunks.push({source_id:source.id,locator:part.locator,quote:part.text.slice(start,start+1500),
          name:source.name+(part.text.length>1500?`（段内片段 ${chunks.length+1}）`:'')});
        if(start+1500>=part.text.length)break;
      }return chunks;
    }));
    const sameEvidence=(a,b)=>a.source_id===b.source_id&&a.locator===b.locator&&a.quote===b.quote;
    const savedEvidence=value.evidence||[];
    for(const saved of savedEvidence)if(!evidence.some(item=>sameEvidence(item,saved)))evidence.push({...saved,name:'已引用的原文（请复核当前版本）'});
    const peers=(matter.group?.members||[]).filter(n=>n.id!==noticeId);
    const peerIds=new Set([noticeId,...peers.map(n=>n.id),...Object.keys(value.related_notice_versions||{})]);
    const knownTasks=[...(tracking.actions||[]).filter(action=>action.task).map(action=>({id:action.task_id,data:action.task})),...(notice.tasks||[]),...(state.tasks||[]).filter(task=>peerIds.has(task.notice_id)&&task.notice_id!==noticeId)];
    const tasks=Array.from(new Map(knownTasks.map(task=>[task.id,task])).values());
    const actions=new Map((value.actions||[]).map(action=>[action.task_id,action.kind]));
    showDialog('公告阶段与后续办理',`<div class="stack notice-lifecycle">
      <header><p class="small muted">${esc(notice.title)}</p><h3>${esc(tracking.phase_label)}</h3><p class="small">原文阶段、本人办理进度和提醒分别记录。公示结束不会自动变成最终结果。</p></header>
      ${tracking.review_required?`<div class="alert" role="status">${(tracking.warnings||[]).map(esc).join('；')}。你的历史记录仍然保留。</div>`:''}
      ${tracking.imported_history?.length?`<details class="lifecycle-evidence"><summary>查看导入的阶段历史（尚未重新核实）</summary>${tracking.imported_history.map(item=>`<section><h4>${esc(PHASES[item.data.phase]||item.data.phase)} · ${esc(OUTCOMES[item.data.outcome]||'尚未核实')}</h4><p class="small">${esc(item.data.note||'')}</p><p class="small muted">历史身份核对备注：${esc(item.data.identity_note||'未记录')}。原窗口、行动和安排仅作为历史保留，不恢复正式结论或提醒。</p>${(item.data.evidence||[]).map(part=>`<blockquote class="small">${esc(part.quote)}<footer>${esc(part.locator)}（导入时的原文引句）</footer></blockquote>`).join('')}</section>`).join('')}</details>`:''}
      ${tracking.objection_window_closed?'<p class="alert">已过记录的异议窗口；这不代表异议已经处理，也不代表名单成为最终结果。</p>':''}
      ${tracking.actions?.length?`<section><h4>已关联的办理记录</h4><ul class="lifecycle-links">${tracking.actions.map(action=>`<li><a href="#tasks/${encodeURIComponent(action.task_id)}">${esc(action.task?.title||'关联行动已移除')}</a><span class="small muted">${esc(action.label)} · ${action.status==='done'?'本人标记完成':action.status==='cancelled'?'已取消':action.status==='missing'?'记录已移除':'待办理'}${action.workflow?.stage==='submitted'?' · 已记录提交':action.workflow?.stage==='accepted'?' · 已记录受理':''}</span>${action.workflow?.receipt?`<p class="small">回执：${esc(action.workflow.receipt)}</p>`:''}</li>`).join('')}</ul></section>`:''}
      <form class="stack" id="notice-lifecycle-form">
        <div class="lifecycle-grid"><label class="field">目前处于什么阶段<select name="phase">${options(PHASES,value.phase)}</select></label><label class="field">这一判断来自哪里<select name="basis">${options(BASES,value.basis)}</select></label></div>
        <p class="small muted" data-phase-help>等待正式公告时，可以安排自己去查进展；这项安排不是学校截止时间。</p>
        <details class="lifecycle-evidence" ${value.basis.startsWith('official')?'open':''}><summary>核对原文依据 <span class="small muted">官方预告、公示和结果必选</span></summary>
          ${evidence.length?evidence.map((item,index)=>`<label class="lifecycle-evidence-row"><input type="checkbox" name="evidence" value="${index}" ${savedEvidence.some(saved=>sameEvidence(saved,item))?'checked':''}><span><strong>${esc(item.name)} · ${esc(item.locator)}</strong><span class="small">${esc(item.quote)}</span></span></label>`).join(''):'<p class="small">尚无可核对的原文段落。请先补充通知原文，不能凭标题确认官方阶段。</p>'}
          <p class="small muted">只记录你选择的原文，不凭相似姓名或采集时间判断适用性。</p>
        </details>
        ${peers.length?`<details><summary>同一事项的相关公告</summary><p class="small muted">勾选本阶段确实依据的通知；各自期限和材料继续独立保留。</p>${peers.map(peer=>`<label class="checkbox-line"><input type="checkbox" name="related" value="${esc(peer.id)}" ${Object.hasOwn(value.related_notice_versions||{},peer.id)?'checked':''}>${esc(peer.title)}</label>`).join('')}</details>`:''}
        <section data-result-fields ${value.phase==='result'?'':'hidden'} class="stack"><h4>本人结果</h4>
          <label class="field">已核对的结果<select name="outcome">${options(OUTCOMES,value.outcome)}</select></label>
          <label class="checkbox-line"><input type="checkbox" name="identity_confirmed" ${value.identity_confirmed?'checked':''}>我已核对名单中的身份，确认确实是本人</label>
          <label class="field">身份核对依据<textarea name="identity_note" rows="2" maxlength="1000" placeholder="例如已对照学号及院系；只需记录必要信息">${esc(value.identity_note||'')}</textarea></label>
        </section>
        <section data-objection-fields ${['publicity','result'].includes(value.phase)?'':'hidden'} class="stack"><h4>公示与异议</h4>
          <label class="field">本人的异议意愿<select name="objection_intent">${options({undecided:'尚未决定',considering:'正在考虑',preparing:'准备提出异议',declined:'不提出异议'},value.objection_intent)}</select></label>
          <div class="lifecycle-grid"><label class="field">原文异议开始日期<input type="date" name="window_start" value="${esc(value.objection_window?.start_date||'')}"></label><label class="field">原文异议结束日期<input type="date" name="window_end" value="${esc(value.objection_window?.end_date||'')}"></label></div>
          <label class="field">原文明示的结束时刻（没有则留空）<input type="time" name="window_time" value="${esc(value.objection_window?.end_time||'')}"></label>
          <p class="small muted">窗口时间必须由上面选中的原文支持。异议材料、提交和受理回执在关联的办理记录中维护。</p>
        </section>
        <details data-actions ${value.phase==='unannounced'?'hidden':''}><summary>关联现有后续行动</summary><p class="small muted">名额确认、领取、签约、报到或候补须使用实际待办；这里不会把旧报名状态当成新的办理结果。</p>
          ${tasks.length?tasks.map(task=>`<label class="field">${esc(task.data?.title||task.title||'本人待办')}<select name="action:${esc(task.id)}"><option value="">不关联</option>${options(KINDS,actions.get(task.id))}</select></label>`).join(''):'<p class="small">还没有可关联的待办。可以先在通知办理区核对并建立行动。</p>'}
        </details>
        <label class="field">跟踪备注<textarea name="note" rows="3" maxlength="2000">${esc(value.note||'')}</textarea></label>
        <p class="form-error" role="alert" tabindex="-1" data-lifecycle-error hidden></p>
        <div class="form-footer"><button type="submit" class="button primary">保存阶段与关联</button></div>
      </form>
      <details class="lifecycle-followup"><summary>设置一次个人跟进</summary><p class="small muted">保存到现有日历；提醒依照你的通知偏好处理。你填写的时间只是本人安排。</p>
        ${tracking.followups?.length?`<ul class="lifecycle-links">${tracking.followups.map(item=>`<li>${esc(item.data?.title||'安排已移除')} <span class="small muted">${esc(item.data?.start_date||'')} ${esc(item.data?.start_time||'')}</span></li>`).join('')}</ul>`:''}
        <form id="notice-lifecycle-followup" class="stack"><label class="field">准备跟进什么<input name="title" maxlength="160" required value="${esc((value.phase==='unannounced'?'查看是否已发布：'+notice.title:'跟进：'+notice.title).slice(0,160))}"></label>
          <label class="field">个人跟进日期<input type="date" name="date" required></label>
          <div class="lifecycle-grid"><label class="field">开始时刻（可留空）<input type="time" name="start"></label><label class="field">结束时刻（与开始一起填写）<input type="time" name="end"></label></div>
          <label class="field">提醒<select name="reminder"><option value="">不设置提醒</option><option value="0">开始时提醒</option><option value="15">提前15分钟</option><option value="60">提前1小时</option></select></label>
          <p class="form-error" role="alert" tabindex="-1" data-lifecycle-error hidden></p><div class="form-footer"><button type="submit" class="button">保存个人跟进</button></div>
        </form>
      </details>
    </div>`);
    const dialog=state.dialogRequest,form=document.querySelector('#notice-lifecycle-form'),followup=document.querySelector('#notice-lifecycle-followup');
    const visible=()=>session===state.session&&ticket===sequence&&dialog===state.dialogRequest&&form.isConnected;
    const updatePhase=()=>{
      const phase=form.elements.phase.value;
      form.querySelector('[data-result-fields]').hidden=phase!=='result';
      form.querySelector('[data-objection-fields]').hidden=!['publicity','result'].includes(phase);
      form.querySelector('[data-actions]').hidden=phase==='unannounced';
      form.querySelector('[data-phase-help]').textContent=phase==='unannounced'?'线索和往年规律仅供个人跟进，不生成正式截止或报名入口。':phase==='publicity'?'公示与最终结果分开；窗口结束后仍需核对正式结果。':'请核对当前版本原文，后续行动保留各自材料、期限和回执。';
    };
    form.elements.phase.addEventListener('change',()=>{const phase=form.elements.phase.value;form.elements.basis.value=phase==='unannounced'?'personal_lead':phase==='preview'?'official_preview':'official_notice';updatePhase();});updatePhase();
    async function changed(message){
      if(!visible())return;
      document.querySelector('#dialog').close();toast(message);await onChanged?.(noticeId);
    }
    form.addEventListener('submit',async event=>{
      event.preventDefault();event.stopPropagation();if(form.inert)return;form.inert=true;
      const fields=new FormData(form),phase=fields.get('phase');
      const selected=fields.getAll('evidence').map(index=>{const {name,...item}=evidence[Number(index)];return item;});
      const related={...value.related_notice_versions};for(const peer of peers)delete related[peer.id];
      fields.getAll('related').forEach(id=>{const peer=peers.find(item=>item.id===id);if(peer)related[id]=peer.version;});
      const actions=phase==='unannounced'?[]:tasks.flatMap(task=>fields.get('action:'+task.id)?[{task_id:task.id,kind:fields.get('action:'+task.id)}]:[]);
      const hasWindow=['publicity','result'].includes(phase)&&(fields.get('window_start')||fields.get('window_end')||fields.get('window_time'));
      const data={...value,phase,basis:fields.get('basis'),evidence:selected,related_notice_versions:related,
        outcome:phase==='result'?fields.get('outcome'):'unknown',identity_confirmed:fields.has('identity_confirmed'),identity_note:fields.get('identity_note'),
        objection_intent:fields.get('objection_intent'),objection_window:hasWindow?{start_date:fields.get('window_start')||null,end_date:fields.get('window_end')||null,end_time:fields.get('window_time')||null,evidence:selected}:null,
        actions,note:fields.get('note')};
      try{await api(`/notices/${encodeURIComponent(noticeId)}/lifecycle-tracking`,{method:'PUT',json:{version:tracking.version,notice_version:notice.version,data}});await changed('阶段与后续关联已保存');}
      catch(error){if(visible())errorText(form,error.status===409?error.message+'。你的填写仍保留在当前窗口；请重新打开核对最新记录后再保存。':error.message);}
      finally{form.inert=false;}
    });
    const requestId=crypto.randomUUID().replaceAll('-','');
    followup.addEventListener('submit',async event=>{
      event.preventDefault();event.stopPropagation();if(followup.inert)return;followup.inert=true;
      const fields=new FormData(followup),date=fields.get('date');
      const arrangement={request_id:requestId,data:{title:fields.get('title'),category:'personal',start_date:date,end_date:date,
        start_time:fields.get('start')||null,end_time:fields.get('end')||null,notes:'个人跟进：'+notice.title+'。不代表学校正式截止时间。',reminder_minutes:fields.get('reminder')===''?null:Number(fields.get('reminder'))}};
      try{await api(`/notices/${encodeURIComponent(noticeId)}/lifecycle-tracking/followup`,{method:'POST',json:{version:tracking.version,notice_version:notice.version,kind:value.phase==='unannounced'?'check_publication':'other',arrangement}});await changed('个人跟进已保存到日历');}
      catch(error){if(visible())errorText(followup,error.message);}
      finally{followup.inert=false;}
    });
  }
  return {open};
}
