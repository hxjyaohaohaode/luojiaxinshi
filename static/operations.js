/** Owner/admin evidence views; no provider probe is triggered by opening them. */
import {captureUiContext} from './ui-request.js';

export function createOperations({api,state,esc,showDialog,toast}){
  const labels={model:'模型',email_code:'邮箱验证码',sms_code:'短信验证码',email_reminder:'邮件提醒',push_device:'设备推送',public_source:'公开来源',campus_pilot:'校园实践',backup_restore:'备份恢复'};
  const date=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN'):'未观察到';
  async function open(){
    const view=captureUiContext(state),data=await api('/admin/readiness');if(!view.sameDialog())return;
    showDialog('运行就绪与验收证据',`<section class="stack"><p class="small muted">${esc(data.note)}</p><p class="small">版本 ${esc(data.version)} · 前端${data.frontend.bundled?'合并构建已校验':'使用源文件路径'}</p><button type="button" class="button" id="open-operations-monitor">查看运维告警与恢复消息</button>${Object.entries(data.services).map(([key,value])=>`<section class="panel"><h3>${labels[key]}</h3><p class="small">配置：${value.configured?'已填写／本地能力可用':'未配置'}<br>已记录的连接成功：${esc(date(value.last_recorded_acceptance))}<br>端到端证据：${value.end_to_end?esc(({passed:'管理员记录通过',failed:'管理员记录失败',unknown:'管理员记录待核对'})[value.end_to_end.result])+' · '+esc(value.end_to_end.environment):'尚未记录'}</p></section>`).join('')}<details class="details"><summary>后台任务与队列</summary><pre>${esc(JSON.stringify({workers:data.workers,queues:data.queues,database_locks:data.database_locks},null,2))}</pre></details><details class="details"><summary>最近人工验收记录（${data.checks.length}）</summary>${data.checks.map(item=>`<p class="small"><strong>${labels[item.kind]||esc(item.kind)} · ${esc(item.result)}</strong><br>${esc(item.environment)} · ${esc(date(item.observed_at))}<br>${esc(item.evidence)}</p>`).join('')||'<p class="small muted">尚未提交本环境的验收证据。</p>'}</details><details class="details"><summary>记录实际验证结果</summary><form id="operation-evidence" class="stack" data-no-history><label class="field">验证项目<select name="kind">${Object.entries(labels).map(([value,label])=>`<option value="${value}">${label}</option>`).join('')}</select></label><label class="field">观察结论<select name="result"><option value="unknown">待核对</option><option value="passed">本次范围通过</option><option value="failed">本次范围失败</option></select></label><label class="field">实际环境<input name="environment" required minlength="2" maxlength="160" placeholder="例如设备、系统、前后台状态或试点角色"></label><label class="field">观察时间（含时区）<input name="observed_at" required value="${new Date().toISOString()}" maxlength="50"></label><label class="field">证据与观察范围<textarea name="evidence" required minlength="5" maxlength="1000" placeholder="填写实际观察和可复核记录；不写密钥或验证码"></textarea></label><p class="small muted">这是管理员提交的实际观察，系统不把它当作独立第三方验收。</p><button class="button primary" type="submit">保存证据记录</button><p class="form-error" role="alert"></p></form></details></section>`);
    document.querySelector('#open-operations-monitor').addEventListener('click',()=>monitor().catch(error=>toast(error.message,true)));
    const form=document.querySelector('#operation-evidence'),formView=captureUiContext(state,form);
    form.addEventListener('submit',async event=>{
      event.preventDefault();const button=form.querySelector('button[type=submit]');if(button.disabled)return;button.disabled=true;
      try{
        const payload=Object.fromEntries(new FormData(form));
        await api('/admin/readiness/evidence',{method:'POST',json:payload});
        if(formView.sameDialog()){toast('验收证据已记录');await open();}
      }catch(error){if(formView.sameDialog())form.querySelector('.form-error').textContent=error.message;}
      finally{button.disabled=false;}
    });
  }
  async function trace(nid){
    const view=captureUiContext(state),data=await api('/notices/'+encodeURIComponent(nid)+'/trace');if(!view.sameDialog())return;
    const groups=[['收件',data.receipts],['事务与请求',data.actions],['模型处理',data.model_calls],['本人待办',data.tasks],['通道投递',data.deliveries]];
    showDialog('通知处理追踪',`<section class="stack"><p class="small muted">${esc(data.note)}</p><p class="small">关联通知：<code>${esc(data.correlation_notice_id)}</code></p>${groups.map(([label,rows])=>`<details class="details"><summary>${label}（${rows.length}）</summary><pre>${esc(JSON.stringify(rows,null,2))}</pre></details>`).join('')}</section>`);
  }
  async function monitor(){
    const view=captureUiContext(state),data=await api('/admin/monitor');if(!view.sameDialog())return;
    const policy=data.settings,snapshot=data.snapshot;
    const incidentText={open:'待处理',resolved:'本次检查已恢复'},eventText={opened:'新告警',acknowledged:'已确认接手',resolved:'恢复消息'};
    const active=data.incidents.filter(item=>item.state==='open');
    const fields=[['queue_age_minutes','最老到期队列（分钟）',1,10080],['source_failure_minutes','连续采集失败（分钟）',1,10080],['disk_min_free_mb','数据盘最小空闲（MiB）',1,1048576],['backup_age_hours','备份最长间隔（小时）',1,720]];
    const expiries=Object.entries(policy.credential_expiries);
    showDialog('运维告警与恢复消息',`<section class="stack"><p class="small muted">独立管理员站内告警，每60秒检查。确认表示接手；只有后续检查不再触发才产生恢复消息。这里不发送学生提醒。</p><p class="small">最近检查：${esc(date(snapshot?.evaluated_at))} · 当前待处理 ${active.length} 项 · 未读消息 ${data.unread_events} 条</p><div class="button-row"><button class="button" type="button" data-monitor-scan>立即检查</button>${data.events.length?'<button class="button" type="button" data-monitor-seen>将当前及更早消息标为已读</button>':''}</div>${active.map(item=>`<section class="panel"><h3>${esc(item.details.title)}</h3><p class="small">首次发现 ${esc(date(item.opened_at))} · ${item.acknowledged_at?'已确认接手':'尚未确认'}</p><p class="small muted">${esc(item.details.scope||item.details.reason||'达到当前设置的告警阈值；请结合本地日志核查。')}</p>${item.acknowledged_at?'':`<button class="button" type="button" data-monitor-ack="${esc(item.id)}">确认接手</button>`}</section>`).join('')||`<p class="small muted">${snapshot?'本次已知检查未产生待处理告警；未知项目仍须核验。':'尚未运行检查，不能判定正常。'}</p>`}<details class="details"><summary>检查证据与未知项目</summary>${Object.values(snapshot?.measurements||{}).map(item=>`<p class="small"><strong>${esc(item.title)}</strong> · ${esc(({healthy:'本次未触发',problem:'已触发告警',unknown:'未知'})[item.state])}<br>${esc(item.scope||item.reason||'')}${item.oldest_age_seconds!==undefined?'<br>最老等待 '+Math.floor(item.oldest_age_seconds/60)+' 分钟':''}${item.free_bytes!==undefined?'<br>剩余 '+Math.floor(item.free_bytes/1024/1024)+' MiB':''}${item.last_snapshot_at?'<br>最近备份 '+esc(date(item.last_snapshot_at)):''}${item.used_units!==undefined?'<br>当前额度计数 '+item.used_units+' · 阈值 '+(item.threshold_units??'未设置'):''}${item.expires_at?'<br>管理员登记的到期时间 '+esc(date(item.expires_at)):''}</p>`).join('')||'<p class="small muted">等待检查。</p>'}</details><details class="details"><summary>告警、确认与恢复消息（最近${data.events.length}条）</summary>${data.events.map(item=>`<p class="small"><strong>${esc(eventText[item.kind]||item.kind)}</strong> · ${esc(date(item.created_at))}<br>${esc(item.details.title||item.details.meaning||item.details.reason||'当前检查不再触发；请核对是否有配置或授权变化。')}</p>`).join('')||'<p class="small muted">暂无记录。</p>'}</details><details class="details"><summary>检查阈值与凭证期限</summary><form id="monitor-settings" class="stack" data-no-history>${fields.map(([key,label,min,max])=>`<label class="field">${label}<input type="number" name="${key}" required min="${min}" max="${max}" value="${policy[key]}"></label>`).join('')}<label class="field">模型额度计数预算（留空为未知）<input name="quota_budget_units" type="number" min="1" max="100000000" value="${policy.quota_budget_units??''}"></label><p class="small muted">额度计数合计现有AI日额度和Agent滚动额度，用于工程预算告警，不是供应商账单、金额或余额。默认阈值可调整，不代表学校的服务承诺。</p><button class="button primary" type="submit">保存检查阈值</button><p class="form-error" role="alert"></p></form><h3>已登记的凭证期限</h3>${expiries.map(([label,value],index)=>`<p class="small">${esc(label)} · ${esc(date(value))} <button class="button" type="button" data-expiry-remove="${index}">移除监测</button></p>`).join('')||'<p class="small muted">未登记，当前到期状态未知。</p>'}<form id="monitor-expiry" class="stack" data-no-history><label class="field">用途标签<input name="label" required maxlength="80" placeholder="只写用途，不填写密钥"></label><label class="field">供应商明确给出的到期时间（本机时区）<input name="expiry" type="datetime-local" required></label><p class="small muted">仅登记已知期限，临近7天时告警。密钥存在不能证明未过期；同名登记会更新当前期限。</p><button class="button" type="submit">登记期限</button><p class="form-error" role="alert"></p></form></details><details class="details"><summary>已恢复记录（最近${data.incidents.filter(item=>item.state==='resolved').length}项）</summary>${data.incidents.filter(item=>item.state==='resolved').map(item=>`<p class="small">${esc(item.details.title||item.condition_key)} · ${incidentText[item.state]} · ${esc(date(item.resolved_at))}</p>`).join('')}</details></section>`);
    const dialogView=captureUiContext(state,document.querySelector('#monitor-settings'));
    async function run(button,action){
      if(button.disabled)return;button.disabled=true;
      try{await action();if(dialogView.sameDialog())await monitor();}
      catch(error){if(dialogView.sameDialog())toast(error.message,true);}
      finally{button.disabled=false;}
    }
    document.querySelector('[data-monitor-scan]').addEventListener('click',event=>run(event.currentTarget,()=>api('/admin/monitor/scan',{method:'POST'})));
    document.querySelector('[data-monitor-seen]')?.addEventListener('click',event=>run(event.currentTarget,()=>api('/admin/monitor/seen',{method:'POST',json:{through_event_id:Math.max(...data.events.map(item=>item.id))}})));
    document.querySelectorAll('[data-monitor-ack]').forEach(button=>button.addEventListener('click',()=>run(button,()=>api('/admin/monitor/incidents/'+encodeURIComponent(button.dataset.monitorAck)+'/acknowledge',{method:'POST'}))));
    const form=document.querySelector('#monitor-settings');
    form.addEventListener('submit',event=>{
      event.preventDefault();const values=new FormData(form),next={...policy};
      for(const [key] of fields)next[key]=Number(values.get(key));
      next.quota_budget_units=values.get('quota_budget_units')?Number(values.get('quota_budget_units')):null;
      run(form.querySelector('button[type=submit]'),()=>api('/admin/monitor/settings',{method:'PUT',json:{...next,expected_revision:data.settings_revision}}));
    });
    const expiryForm=document.querySelector('#monitor-expiry');
    expiryForm.addEventListener('submit',event=>{
      event.preventDefault();const values=new FormData(expiryForm),label=String(values.get('label')).trim(),expiry=new Date(values.get('expiry')).toISOString();
      run(expiryForm.querySelector('button[type=submit]'),()=>api('/admin/monitor/settings',{method:'PUT',json:{...policy,expected_revision:data.settings_revision,credential_expiries:{...policy.credential_expiries,[label]:expiry}}}));
    });
    document.querySelectorAll('[data-expiry-remove]').forEach(button=>button.addEventListener('click',()=>{
      const next={...policy.credential_expiries};delete next[expiries[Number(button.dataset.expiryRemove)][0]];
      run(button,()=>api('/admin/monitor/settings',{method:'PUT',json:{...policy,expected_revision:data.settings_revision,credential_expiries:next}}));
    }));
  }
  return {open,trace,monitor};
}
