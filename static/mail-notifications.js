export function createMailNotifications({state,api,esc,toast}){
  let owner=null,status=null,busy=false,epoch=0;
  const host=()=>document.querySelector('[data-mail-settings]');
  const labels={pending:'等待发送',sending:'发送中',accepted:'服务商已接受，尚未确认收件',uncertain:'提交状态待确认',cancelled:'已取消'};
  function markup(){
    if(owner!==state.session?.user.id){owner=state.session?.user.id;status=null;epoch++;}
    return `<section class="stack"><h3>邮件提醒</h3>${status?`<p class="small">${status.email?esc(status.email):'尚未绑定邮箱'} · ${status.enabled?'已开启':'未开启'}</p>
    ${!status.configured?'<p class="small muted">邮件服务尚未配置，暂时无法开启。</p>':!status.email?'<button class="button small" type="button" data-action="settings-security">先验证邮箱</button>':''}
    ${status.configured&&status.email?`<label class="check"><input type="checkbox" data-mail-consent ${status.enabled?'checked disabled':''}><span>同意将通知摘要、待办期限和更新提醒发送到此邮箱。</span></label><div class="row wrap"><button class="button small" type="button" data-mail-action="${status.enabled?'disable':'enable'}" ${busy?'disabled':''}>${status.enabled?'关闭':'开启'}邮件提醒</button>${status.enabled?'<button class="button small" type="button" data-mail-action="test">发送测试邮件</button>':''}</div>`:''}
    ${status.recent.length?`<p class="small muted">最近投递：${esc(labels[status.recent[0].state]||status.recent[0].state)}${status.recent[0].error?' · '+esc(status.recent[0].error):''}</p>`:''}`:'<p class="small muted">正在读取邮件设置…</p>'}
    <button class="button small plain" type="button" data-mail-action="refresh" ${busy?'disabled':''}>刷新邮件状态</button></section>`;
  }
  function render(){if(host())host().innerHTML=markup();}
  async function refresh(){const uid=state.session?.user.id;if(!uid)return;if(owner!==uid){owner=uid;epoch++;status=null;}const turn=epoch;try{const next=await api('/notifications/email');if(state.session?.user.id===uid&&turn===epoch){status=next;render();}}catch(error){if(state.session?.user.id===uid)toast(error.message,true);}}
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-mail-action]');if(!button||busy)return;const action=button.dataset.mailAction;
    if(action==='refresh'){refresh();return;}
    if(action==='enable'&&!host()?.querySelector('[data-mail-consent]')?.checked){toast('请先确认接收邮件提醒',true);return;}
    const uid=state.session?.user.id;busy=true;
    try{if(action==='test'){await api('/notifications/email/test',{method:'POST'});if(state.session?.user.id===uid)toast('测试邮件已排队，请在收件箱和垃圾邮件中核对');}
      else await api('/notifications/email',{method:'PUT',json:{enabled:action==='enable',accepted_delivery:action==='enable'}});
      if(state.session?.user.id===uid)await refresh();
    }catch(error){if(state.session?.user.id===uid)toast(error.message,true);}finally{busy=false;render();}
  });
  return {markup,refresh};
}
