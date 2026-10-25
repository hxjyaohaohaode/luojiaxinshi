/* Push delivery is opt-in per device. Account identity is also checked by the worker. */
const WORKER_PATH='/notification-worker.js';
export function decodePublicKey(value){const text=atob(String(value).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(text,c=>c.charCodeAt(0));}
export function pushUnavailable(env=globalThis){
  if(!env.isSecureContext)return '关闭页面提醒需要 HTTPS 或本机安全地址。';
  if(!env.navigator?.serviceWorker||!env.PushManager||!env.Notification)return '当前浏览器不支持关闭页面提醒；可使用支持推送的浏览器。';
  return '';
}
export function localPushDevice(status,subscription){return (status?.devices||[]).find(device=>device.endpoint===subscription?.endpoint&&device.enabled!==false&&device.enabled!==0)||null;}
export function deliveryText(delivery){
  if(!delivery)return '';
  const state=delivery.state||delivery.status;
  return ({accepted:'最近一次已交给推送服务，尚不能确认设备展示。',pending:'提醒已排队，等待发送。',sending:'提醒正在发送。',leased:'提醒正在发送。',failed:'最近一次推送失败，可刷新状态或重新开启。',cancelled:'最近一次提醒已取消。'})[state]||'';
}
export function createPushNotifications({state,api,esc,toast}){
  let owner=null,epoch=0,config=null,status=null,subscription=null,registration=null,binding=null,loading=null,busy=false,lastError='',feedback='',localEnabled=false;
  let cleanup=Promise.resolve();
  const supported=()=>!pushUnavailable();
  const current=(session,version)=>state.session===session&&owner===session?.user.id&&epoch===version;
  const ownRegistration=reg=>[reg?.active,reg?.waiting,reg?.installing].some(worker=>worker&&new URL(worker.scriptURL,location.origin).pathname===WORKER_PATH);
  async function registered(){if(!navigator.serviceWorker)return null;const reg=await navigator.serviceWorker.getRegistration('/');return ownRegistration(reg)?reg:null;}
  async function ready(reg){
    if(reg.active?.state==='activated')return reg.active;
    const worker=reg.installing||reg.waiting||reg.active;if(!worker)throw Error('提醒服务尚未启动，请重试。');
    await new Promise((resolve,reject)=>{let timer;const check=()=>{if(worker.state==='activated'){finish();resolve();}else if(worker.state==='redundant'){finish();reject(Error('提醒服务更新失败，请重试。'));}};const finish=()=>{clearTimeout(timer);worker.removeEventListener('statechange',check);};timer=setTimeout(()=>{finish();reject(Error('提醒服务启动超时，请重试。'));},10000);worker.addEventListener('statechange',check);check();});
    return reg.active||worker;
  }
  async function message(reg,type,values={}){
    const worker=await ready(reg);
    return new Promise((resolve,reject)=>{const channel=new MessageChannel(),timer=setTimeout(()=>{channel.port1.close();reject(Error('无法确认本机提醒状态，请重试。'));},5000);channel.port1.onmessage=event=>{clearTimeout(timer);channel.port1.close();event.data?.ok?resolve(event.data.binding||null):reject(Error(event.data?.error||'无法更新本机提醒状态。'));};worker.postMessage({type,...values},[channel.port2]);});
  }
  function changed(){document.dispatchEvent(new CustomEvent('campus:push-state',{detail:{enabled:localEnabled}}));render();}
  async function revokeLocal(reg,uid){
    if(!reg)return null;
    let disabled=false;
    try{const result=await message(reg,'CAMPUS_PUSH_DISABLE',{user_id:uid});if(result?.enabled&&result.user_id!==uid)return null;disabled=!result?.enabled;}catch{}
    let sub=null,known=false;try{sub=await reg.pushManager.getSubscription();known=true;}catch{}
    // A successful unsubscribe prevents delivery even when IndexedDB is unavailable.
    let unsubscribed=known&&!sub;try{if(sub)unsubscribed=await sub.unsubscribe();}catch{}
    if(!disabled&&!unsubscribed){await reg.unregister();throw Error('无法确认本机订阅已解除，请在浏览器网站设置中关闭通知。');}
    return sub?.endpoint||null;
  }
  async function refresh(){
    if(!owner||!state.session)return null;if(loading)return loading;
    const session=state.session,version=epoch;
    const request=(async()=>{
      await cleanup.catch(()=>{});if(!current(session,version))return null;
      lastError='';
      try{
        const reg=supported()?await registered():null;
        if(!current(session,version))return null;
        const sub=reg?await reg.pushManager.getSubscription():null;
        const saved=reg?await message(reg,'CAMPUS_PUSH_STATUS'):null;
        if(!current(session,version))return null;
        if(saved?.enabled&&saved.user_id!==owner){await revokeLocal(reg,saved.user_id);if(!current(session,version))return null;}
        registration=reg;subscription=saved?.enabled&&saved.user_id!==owner?null:sub;binding=saved;
        const [cfg,remote]=await Promise.all([api('/push/config'),api('/push/status')]);if(!current(session,version))return null;config=cfg;status=remote;
        localEnabled=!!(subscription&&saved?.enabled&&saved.user_id===owner&&localPushDevice(status,subscription)&&Notification.permission==='granted');
      }catch(error){if(current(session,version)){lastError=error.message;localEnabled=false;}}
      if(current(session,version))changed();return status;
    })().finally(()=>{if(loading===request){loading=null;render();}});
    loading=request;render();return request;
  }
  function start(){const uid=state.session?.user.id;if(!uid)return;if(owner===uid){return;}if(owner)stop();owner=uid;epoch++;config=null;status=null;subscription=null;binding=null;localEnabled=false;lastError='';feedback='';refresh();}
  function markup(){
    const unavailable=pushUnavailable(),device=(status?.devices||[]).find(item=>item.endpoint===subscription?.endpoint),disabled=busy?'disabled':'';
    const headline=busy?'正在更新…':loading?'正在读取本机状态…':localEnabled?'本机已开启':lastError&&subscription?'本机状态待确认':'本机未开启';
    const canEnable=!unavailable&&config?.supported&&config?.public_key&&typeof Notification!=='undefined'&&Notification.permission!=='denied';
    const other=Math.max(0,(status?.devices||[]).filter(item=>item.enabled!==false&&item.enabled!==0).length-(localPushDevice(status,subscription)?1:0));
    return `<section class="push-settings stack" aria-labelledby="push-settings-title"><h3 id="push-settings-title">关闭页面提醒</h3><p class="small" role="status">${headline}${other?` · 其他 ${other} 台设备已开启`:''}</p>
      ${unavailable?`<p class="small muted">${esc(unavailable)}</p>`:typeof Notification!=='undefined'&&Notification.permission==='denied'?'<p class="small muted">通知权限已被拒绝，请在浏览器的网站设置中允许通知，再刷新状态。</p>':config&&!config.supported?'<p class="small muted">当前服务暂不支持推送。</p>':''}
      ${localEnabled?'<p class="small muted">可在关闭本页面后接收。浏览器、系统通知和网络仍会影响送达；退出账号会解除本机订阅。</p>':''}
      ${device?.error?`<p class="alert error">本机最近发送失败：${esc(device.error)}</p>`:''}
      ${device?.last_success?'<p class="small muted">本机最近一次已交给推送服务，尚不能确认设备展示。</p>':''}
      ${status?.last_delivery&&deliveryText(status.last_delivery)?`<p class="small muted">账号最近投递：${esc(deliveryText(status.last_delivery))}</p>`:''}
      ${lastError?`<p class="alert error" role="alert">${esc(lastError)}</p>`:''}${feedback?`<p class="small" role="status">${esc(feedback)}</p>`:''}
      <div class="row wrap">${subscription?`<button type="button" class="button small" data-push-action="disable" ${disabled}>关闭本机提醒</button>`:''}${localEnabled?`<button type="button" class="button small" data-push-action="test" ${disabled}>发送测试提醒</button>`:`<button type="button" class="button small" data-push-action="enable" ${disabled||(!canEnable?'disabled':'')}>开启本机提醒</button>`}<button type="button" class="button small plain" data-push-action="refresh" ${disabled}>刷新状态</button></div></section>`;
  }
  function render(){const host=document.querySelector('[data-push-settings]');if(!host||!host.closest('dialog')?.open)return;const active=document.activeElement?.dataset?.pushAction;host.innerHTML=markup();if(active&&!busy)host.querySelector(`[data-push-action="${active}"]`)?.focus({preventScroll:true});}
  async function enable(){
    if(busy||!owner||!config?.public_key||!supported())return;
    const session=state.session,version=epoch;
    // Request browser permission synchronously from the user's button gesture.
    let permission;try{permission=Notification.permission==='granted'?Promise.resolve('granted'):Notification.requestPermission();}catch(error){lastError=error.message;render();return;}
    busy=true;lastError='';feedback='';render();let reg=null,sub=null,stored=false;
    try{
      if(await permission!=='granted')throw Error('浏览器未允许通知。请在网站设置中允许后重试。');
      await cleanup.catch(()=>{});if(!current(session,version))return;
      reg=await navigator.serviceWorker.register(WORKER_PATH,{scope:'/'});await ready(reg);if(!current(session,version))return;
      sub=await reg.pushManager.getSubscription();if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:decodePublicKey(config.public_key)});
      if(!current(session,version)){await revokeLocal(reg,session.user.id);return;}
      const record=sub.toJSON();await api('/push/subscriptions',{method:'POST',json:{endpoint:record.endpoint,keys:record.keys}});stored=true;
      if(!current(session,version)){await revokeLocal(reg,session.user.id);return;}
      await message(reg,'CAMPUS_PUSH_ENABLE',{user_id:session.user.id});
      if(!current(session,version)){await revokeLocal(reg,session.user.id);return;}
      registration=reg;subscription=sub;localEnabled=true;feedback='本机提醒已开启。';await refresh();
    }catch(error){
      if(reg){await revokeLocal(reg,session.user.id).catch(()=>{});if(stored&&sub&&current(session,version))await api('/push/subscriptions',{method:'DELETE',json:{endpoint:sub.endpoint}}).catch(()=>{});}
      if(current(session,version)){lastError=error.message;localEnabled=false;}
    }finally{if(current(session,version)){busy=false;changed();}}
  }
  async function detachForLogout(){
    const uid=owner||state.session?.user.id;epoch++;loading=null;busy=true;localEnabled=false;changed();
    cleanup=(async()=>{const reg=registration||await registered();const endpoint=await revokeLocal(reg,uid);if(endpoint&&state.session?.user.id===uid){try{await api('/push/subscriptions',{method:'DELETE',json:{endpoint}});}catch(error){feedback='本机提醒已关闭；服务器记录暂未同步，可重新登录后刷新状态。';}}registration=null;subscription=null;binding=null;})();
    try{await cleanup;}finally{busy=false;changed();}
  }
  function stop(){
    const uid=owner;if(!uid)return;owner=null;epoch++;loading=null;localEnabled=false;config=null;status=null;feedback='';lastError='';busy=false;
    cleanup=(async()=>{const reg=registration||await registered();await revokeLocal(reg,uid);registration=null;subscription=null;binding=null;})().catch(error=>{toast(error.message,true);});changed();
  }
  async function disable(){if(busy)return;try{await detachForLogout();feedback='本机提醒已关闭。';await refresh();}catch(error){lastError=error.message;}changed();}
  async function test(){if(busy||!localEnabled||!subscription)return;const session=state.session,version=epoch;busy=true;lastError='';feedback='';render();try{await api('/push/test',{method:'POST',json:{endpoint:subscription.endpoint}});if(current(session,version))feedback='测试提醒已排队。收到系统通知后，可点击它返回；排队不代表已经送达。';}catch(error){if(current(session,version))lastError=error.message;}finally{if(current(session,version)){busy=false;render();}}}
  document.addEventListener('click',event=>{const control=event.target.closest('[data-push-action]');if(!control||control.disabled)return;const action=control.dataset.pushAction;if(action==='enable')enable();else if(action==='disable')disable();else if(action==='test')test();else if(action==='refresh'){feedback='';refresh();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&owner)refresh();});
  return {start,stop,refresh,markup,detachForLogout,enabled:()=>localEnabled};
}
