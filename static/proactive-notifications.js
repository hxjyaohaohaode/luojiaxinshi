import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {patchProfile} from './profile-editor.js';

export function parseNotificationTerms(value){return [...new Set(String(value).split(/[、，,;；\n]+/u).map(v=>v.trim()).filter(Boolean))];}
export function evidenceChainMarkup(chain,esc){
  const stamp=value=>{const date=new Date(typeof value==='number'?value*1000:value);return value&&Number.isFinite(date.getTime())?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short',hour12:false}).format(date):'时间未记录';};
  const safeURL=value=>{try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:'';}catch{return '';}};
  return `<details class="details"><summary>原文、附件与版本 · ${chain.documents?.length||0} 份</summary><p class="small muted">${esc(chain.policy||'')}</p>${(chain.documents||[]).map(doc=>{
    const o=doc.origin||{},url=safeURL(o.url),relation={attachment:'原文附件',linked_candidate:'原文链接的关联候选',index_candidate:'同来源检索的关联候选'}[o.relationship]||'原始材料',reading=doc.coverage;
    const unread=reading?.unread_attachments||[];
    return `<details><summary>${esc(doc.name)} · ${doc.active?'当前':'历史'} · ${esc(relation)}${reading?' · '+esc({complete:'已取得材料',review:'材料需核对',partial:'读取有缺口'}[reading.state]||'待核对'):''}</summary>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开原始来源 ↗</a>`:''}<p class="small muted">读取于 ${esc(stamp(o.retrieved_at))} · 内容指纹 ${esc(String(doc.sha256||'').slice(0,12))}</p>${doc.warning?`<p class="small">${esc(doc.warning)}</p>`:''}${doc.missing_attachments?.length?`<p class="small">仍有 ${doc.missing_attachments.length} 份附件未完成读取</p>`:''}${unread.map(item=>`<p class="small"><strong>${esc(item.label||'附件')}</strong>：${esc(item.reason)}</p>`).join('')}${reading?.retained_snapshots?.length?'<p class="small">部分证据本轮未读到，保留的是上次成功取得的快照。</p>':''}${(o.related_search?.errors||[]).map(error=>`<p class="small">${esc(error.error)}</p>`).join('')}</details>`;
  }).join('')}${chain.related_notices?.length?`<p class="small">系统找到的其他关联候选（尚不能据此确认替代效力）：</p><ul>${chain.related_notices.map(n=>`<li><a href="#notice/${encodeURIComponent(n.id)}">${esc(n.title)}</a></li>`).join('')}</ul>`:''}</details>`;
}

export function createProactiveNotifications({state,api,esc,showDialog,toast,onChanged}){
  const $=s=>document.querySelector(s);
  let snapshot=null,dialogOwner=null,sourceRoutes={};
  const noticeRoutes=new WeakMap();
  const deliveryOptions={inherit:'沿用类别与来源偏好',immediate:'按事件时点提醒',digest:'每日汇总',in_app:'仅站内查看',off:'关闭外发'};
  const routeSelect=(name,value)=>`<select name="${name}">${Object.entries(deliveryOptions).map(([key,label])=>`<option value="${key}" ${value===key?'selected':''}>${label}</option>`).join('')}</select>`;
  async function open(){
    const view=captureUiContext(state),[status,matrix,routes]=await Promise.all([api('/proactive/status'),api('/notifications/matrix'),api('/notifications/routes')]);
    if(!view.sameDialog())return;
    snapshot=structuredClone(routes.preferences);sourceRoutes={...snapshot.source_delivery};dialogOwner=state.session.user.id;
    const p=snapshot;
    showDialog('智能通知偏好',`<form id="proactive-preferences" class="stack" data-no-history>
      <label class="field">提醒方式<select name="mode" aria-label="提醒方式">${Object.entries({focused:'重点优先，知悉内容汇总',all:'新收件及时提醒',digest:'每日汇总，临近期限优先'}).map(([key,label])=>`<option value="${key}" ${p.mode===key?'selected':''}>${label}</option>`).join('')}</select></label>
      <fieldset class="stack notification-delivery"><legend>按提醒类别选择节奏</legend>${[['receipt_delivery','新收件'],['task_delivery','本人待办'],['arrangement_delivery','个人安排与课程'],['collaboration_delivery','协作办理'],['source_health_delivery','来源读取异常']].map(([key,label])=>`<label class="field">${label}<select name="${key}">${Object.entries({immediate:'按事件时点提醒',digest:'每日汇总',in_app:'仅站内查看',off:'关闭此类外发'}).map(([value,text])=>`<option value="${value}" ${(p[key]||(['collaboration_delivery','source_health_delivery'].includes(key)?'in_app':'immediate'))===value?'selected':''}>${text}</option>`).join('')}</select></label>`).join('')}<p class="small muted">安排还需在每一项中明确设置提前时间。协作默认仅站内；关闭外发不会删除原记录或修改办理状态。</p></fieldset>
      <details class="details"><summary>按来源设置独立提醒节奏</summary><p class="small muted">${esc(routes.precedence)}</p>${routes.sources.length?`<label class="field">选择来源<select name="delivery_source">${routes.sources.map(source=>`<option value="${esc(source.id)}">${esc(source.title)}</option>`).join('')}</select></label><label class="field">此来源的提醒方式${routeSelect('source_override',sourceRoutes[routes.sources[0].id]||'inherit')}</label><p class="small muted">切换来源可继续编辑，点击保存偏好后一起生效。单个事项可在其追踪与证据链中独立设置。</p>`:'<p class="small muted">当前没有可配置的本人来源，请先在通知来源中添加。</p>'}</details>
      <label class="field">关注关键词<input name="interest_terms" value="${esc(p.interest_terms.join('、'))}" maxlength="850" placeholder="例如：助学金、实习、GIS"></label>
      <label class="field">静默关键词<input name="muted_terms" value="${esc(p.muted_terms.join('、'))}" maxlength="850" placeholder="选填，用顿号或逗号分隔"></label>
      <p class="small muted">关键词影响关注机会和提醒节奏，不代替资格判断。已识别的本人行动，以及已保存待办的期限、变更与跟进继续提醒。</p>
      <div class="form-grid"><label class="field">免打扰开始<input name="quiet_start" type="time" value="${esc(p.quiet_start)}"></label><label class="field">免打扰结束<input name="quiet_end" type="time" value="${esc(p.quiet_end)}"></label></div>
      <label class="check"><input type="checkbox" name="allow_urgent_during_quiet" ${p.allow_urgent_during_quiet?'checked':''}><span>允许已核实的紧急事项在免打扰时段提醒</span></label>
      <label class="field">每日汇总时间（北京时间）<select name="digest_hour">${Array.from({length:24},(_,hour)=>`<option value="${hour}" ${p.digest_hour===hour?'selected':''}>${String(hour).padStart(2,'0')}:00</option>`).join('')}</select></label>
      <details class="details notification-capabilities"><summary>各类提醒支持哪些渠道</summary><p class="small muted">本账号已开启 ${matrix.channels.push.enabled_devices} 台推送设备；邮件渠道${matrix.channels.email.configured?'已配置':'未配置'}，本人${matrix.channels.email.enabled?'已开启':'未开启'}。</p>${matrix.categories.map(item=>`<section><h4>${esc(item.label)}</h4><p class="small">站内 ${item.in_app?'支持':'不支持'} · 手机推送 ${item.push?'支持':'不支持'} · 邮件 ${item.email?'支持':'不支持'}</p><p class="small muted">${esc(item.condition)}</p></section>`).join('')}<p class="small muted">${esc(matrix.device_validation)}</p><p class="small muted" data-device-policy="all_enabled_devices">每台设备均由本人单独开启；同一事件可发送到本人全部已启用设备，每台设备按事件去重。关闭或退出本机不会替其他设备撤销授权。当前没有自动选择主设备。</p>${matrix.events?.length?`<details><summary>事件与依据</summary>${matrix.events.map(event=>`<p class="small"><strong>${esc(event.label)}</strong> · ${esc(event.basis)}</p>`).join('')}</details>`:''}</details>
      <details class="details" data-notification-plan><summary>为什么未提醒 / 当前计划与投递回执</summary><div data-notification-plan-content><p class="small muted">展开后读取当前账号计划。</p></div><button type="button" class="button small" data-notification-plan-refresh>刷新计划</button></details>
      <details class="details"><summary>查看当前接入情况</summary><p class="small">官网订阅：${status.sources.filter(s=>s.platform==='website'&&s.enabled).length} 个已启用；公众号：${status.sources.filter(s=>s.platform==='wechat_public'&&s.capability==='connector_required').length} 个仍需配置文章接收。</p><p class="small">自动整理：${status.automation.enabled&&status.automation.consented?'已开启':'尚未开启'}；等待 ${status.automation.jobs.queued||0} 则，处理中 ${status.automation.jobs.running||0} 则。</p><p class="small muted">发送渠道在提醒中心单独开启；短信当前用于账号验证码。</p></details>
      <div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button type="submit" class="button primary">保存偏好</button></div>
    </form>`);
    const routeForm=$('#proactive-preferences'),sourcePicker=routeForm.elements.delivery_source,modePicker=routeForm.elements.source_override;
    if(sourcePicker){sourcePicker.addEventListener('change',()=>{modePicker.value=sourceRoutes[sourcePicker.value]||'inherit';});modePicker.addEventListener('change',()=>{if(modePicker.value==='inherit')delete sourceRoutes[sourcePicker.value];else sourceRoutes[sourcePicker.value]=modePicker.value;});}
    const planRoot=document.querySelector('[data-notification-plan]');
    planRoot.addEventListener('toggle',()=>{if(planRoot.open&&!planRoot.dataset.loaded)loadPlan(planRoot,matrix);});
    planRoot.querySelector('[data-notification-plan-refresh]').addEventListener('click',()=>loadPlan(planRoot,matrix));
  }
  async function loadPlan(root,matrix){
    if(root.dataset.loading)return;
    root.dataset.loading='1';const view=captureUiContext(state,root),panel=root.querySelector('[data-notification-plan-content]');
    panel.setAttribute('aria-busy','true');panel.innerHTML='<p class="small muted" role="status">正在读取计划与回执…</p>';
    const stamp=value=>value?new Date(value*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未记录';
    try{
      const plan=await api('/notifications/plan?limit=50');if(!view.sameDialog()||!root.isConnected)return;
      root.dataset.loaded='1';
      panel.innerHTML=`<p class="small muted">${esc(plan.note)} · 核对时间 ${esc(stamp(plan.evaluated_at))}</p><h4>当前计划 · 显示 ${plan.items.length} / ${plan.total}</h4>${plan.items.map(item=>`<article class="notification-plan-item"><strong>${esc(item.title)}</strong><p class="small">${esc({task:'本人待办',arrangement:'个人安排',collaboration:'协作办理',receipt:'新收件'}[item.category]||item.category)} · ${esc(stamp(item.due_at))}</p><p class="small muted">${esc(item.policy.reason||'等待执行')}${item.policy.suppressed?' · 当前不外发':item.policy.delayed?' · 已按偏好延后':''}</p></article>`).join('')||'<p class="small muted">当前没有满足条件的外发计划。请核对时间是否已确认、每项安排是否设置提前提醒、类别偏好和设备开关。</p>'}${plan.has_more?'<p class="small muted">这里只显示最近 50 条计划，未把当前范围当作全部。</p>':''}<h4>最近投递回执</h4>${plan.recent.map(item=>`<article class="notification-plan-item"><p class="small">${item.channel==='push'?'手机推送':'邮件'} · ${esc(matrix.receipt_meanings[item.state]||item.state)} · ${esc(stamp(item.finished_at||item.created_at))}</p>${item.error?`<p class="small">${esc(item.error)}</p>`:''}</article>`).join('')||'<p class="small muted">尚无投递回执。</p>'}`;
    }catch(error){if(view.sameDialog()&&root.isConnected)panel.innerHTML=`<p class="alert error" role="alert">计划读取失败：${esc(error.message)}，请点击刷新计划重试。</p>`;}
    finally{delete root.dataset.loading;panel.removeAttribute('aria-busy');}
  }
  async function explain(nid){
    const view=captureUiContext(state),[value,routes]=await Promise.all([api('/proactive/notices/'+encodeURIComponent(nid)),api('/notifications/routes?notice_id='+encodeURIComponent(nid))]);
    if(!view.sameDialog())return;
    const a=value.assessment,labels={near_term:'近期收件汇总',daily_digest:'每日汇总',opportunity_digest:'机会汇总',silent:'静默保留'};
    showDialog('追踪与证据链',`<section class="stack proactive-decision"><strong>${esc(a.tracking?.label||a.label)} · ${esc(a.label)}</strong><p class="small">${esc(a.tracking?.reason||'')}</p><p class="small">内容核对：${esc({passed:'独立核对已通过',needs_review:'有待核对事项',unavailable:'核对未完成',unverified:'尚未完成核对'}[a.quality]||a.quality)}</p><details class="details"><summary>分级与提醒依据</summary><ul class="small">${a.reasons.filter(reason=>reason!==a.tracking?.reason).map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul></details><p class="small">${value.gates?.automatic_receipt?'当前提醒安排：'+esc(labels[a.delivery]||a.delivery):'这则通知由本人保存，不进入自动新收件推送。'}</p>${value.gates?.initial_snapshot?'<p class="small">这是首次订阅时保存的历史基线，保留查阅，静默接收。</p>':''}${value.applicability_reason?`<details class="details"><summary>${a.current_draft?'适用判断的原因':'之前的适用判断（当前待重新核对）'}</summary><p class="small">${esc(value.applicability_reason)}</p></details>`:''}${(a.tracking?.expired_actions?.length||a.tracking?.past_events?.length)?`<details class="details"><summary>时效判断的原文依据</summary>${[...(a.tracking.expired_actions||[]),...(a.tracking.past_events||[])].map(t=>`<p class="small"><strong>${esc(t.title)}</strong></p>${(t.evidence||[]).map(e=>`<blockquote class="small">${esc(e.quote)}</blockquote><p class="small muted">${esc(e.locator||'原文')}</p>`).join('')}`).join('')}</details>`:''}${evidenceChainMarkup(value.evidence_chain||{},esc)}<form id="proactive-notice-route" class="stack" data-no-history data-id="${esc(nid)}"><label class="field">这一事项的独立提醒节奏${routeSelect('notice_override',routes.notice?.mode||'inherit')}</label><p class="small muted">${esc(routes.precedence)} 当前生效：${esc(deliveryOptions[routes.notice?.effective_mode]||'沿用类别偏好')}。范围、资格和是否存在已核对事件仍需满足，设置立即提醒不会补造事件。</p><button type="submit" class="button small">保存本事项提醒方式</button></form><form id="proactive-feedback" class="stack" data-no-history data-id="${esc(nid)}" data-version="${value.notice_version}" data-feedback-version="${a.feedback?.version||0}"><label class="field">纠正推荐结果<select name="mode" aria-label="纠正推荐结果">${Object.entries({auto:'由系统自动判断',include:'保留到与你相关的通知',exclude:'移出相关通知与新收件提醒'}).map(([mode,label])=>`<option value="${mode}" ${mode===a.feedback?.mode?'selected':''}>${label}</option>`).join('')}</select></label><label class="field">补充说明（选填）<input name="note" maxlength="1000" value="${esc(a.feedback?.note||'')}"></label><p class="small muted">纠正会同步推荐与新收件提醒，原文与资格判断保留。个人待办在待办页管理，补充原文可返回详情操作。</p><div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button type="submit" class="button primary small">保存纠正</button></div></form><button class="button small" data-action="settings-notification">修改通知偏好</button></section>`);
    noticeRoutes.set($('#proactive-notice-route'),{preferences:structuredClone(routes.preferences),owner:state.session.user.id});
  }
  document.addEventListener('submit',async event=>{
    if(event.target.id==='proactive-notice-route'){
      event.preventDefault();const form=event.target,view=captureUiContext(state,form),finish=beginFormFeedback(form),base=noticeRoutes.get(form);if(!finish)return;
      try{
        if(!base||base.owner!==state.session?.user?.id)throw Error('账号已变化，请重新打开事项');
        const overrides={...base.preferences.notice_delivery},mode=form.elements.notice_override.value,nid=form.dataset.id;
        if(mode==='inherit')delete overrides[nid];else overrides[nid]=mode;
        const profile=await patchProfile(api,{notification_preferences:base.preferences},{notification_preferences:{...base.preferences,notice_delivery:overrides}});
        if(!view.sameUser())return;state.session.user.profile.notification_preferences=profile.notification_preferences;
        if(view.sameDialog()){base.preferences=structuredClone(profile.notification_preferences);form.querySelector('.form-error')?.remove();toast('本事项提醒方式已保存');}
      }catch(error){if(view.sameDialog()){let note=form.querySelector('.form-error');if(!note){note=document.createElement('p');note.className='alert error form-error';note.setAttribute('role','alert');form.prepend(note);}note.textContent=error.message+(error.status===409?'；当前填写已保留，请关闭后重新打开此事项核对最新偏好。':'');}}finally{finish();}
      return;
    }
    if(event.target.id==='proactive-feedback'){
      event.preventDefault();const form=event.target,view=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;
      try{
        const data=new FormData(form),nid=form.dataset.id;
        await api('/proactive/notices/'+encodeURIComponent(nid)+'/feedback',{method:'PUT',json:{notice_version:Number(form.dataset.version),version:Number(form.dataset.feedbackVersion),mode:data.get('mode'),note:data.get('note')}});
        if(!view.sameUser())return;
        await onChanged?.(nid);
        if(view.sameDialog())await explain(nid);
        toast('纠正已同步到相关通知和后续新收件提醒');
      }catch(error){if(view.sameDialog())toast(error.message,true);}
      finally{finish();}
      return;
    }
    const form=event.target;if(form.id!=='proactive-preferences')return;
    event.preventDefault();const view=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;
    try{
      if(dialogOwner!==state.session?.user?.id)throw Error('账号已变化，请重新打开通知偏好');
      const data=new FormData(form),value={...snapshot,mode:data.get('mode'),digest_hour:Number(data.get('digest_hour')),
        receipt_delivery:data.get('receipt_delivery'),source_health_delivery:data.get('source_health_delivery'),source_delivery:{...sourceRoutes},task_delivery:data.get('task_delivery'),arrangement_delivery:data.get('arrangement_delivery'),collaboration_delivery:data.get('collaboration_delivery'),allow_urgent_during_quiet:data.has('allow_urgent_during_quiet'),
        quiet_start:data.get('quiet_start'),quiet_end:data.get('quiet_end'),
        interest_terms:parseNotificationTerms(data.get('interest_terms')),muted_terms:parseNotificationTerms(data.get('muted_terms'))};
      const profile=await patchProfile(api,{notification_preferences:snapshot},{notification_preferences:value});
      if(!view.sameUser())return;
      state.session.user.profile.notification_preferences=profile.notification_preferences;
      if(view.sameDialog())$('#dialog').close();toast('通知偏好已保存');
    }catch(error){
      if(view.sameDialog()){
        let note=form.querySelector('.form-error');if(!note){note=document.createElement('div');note.className='alert error form-error';note.setAttribute('role','alert');form.prepend(note);}
        note.textContent=error.message;
        if(error.status===409&&!form.querySelector('[data-proactive-reload]')){const button=document.createElement('button');button.type='button';button.className='button small';button.dataset.proactiveReload='';button.textContent='读取最新偏好';button.addEventListener('click',()=>open().catch(e=>toast(e.message,true)));note.append(button);}
        note.scrollIntoView({block:'nearest'});
      }
    }finally{finish();}
  });
  return {open,explain};
}
