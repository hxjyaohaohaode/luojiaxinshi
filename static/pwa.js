export function installationAdvice(env=globalThis){
  const standalone=env.matchMedia?.('(display-mode: standalone)').matches||env.navigator?.standalone;
  if(standalone)return '已在独立窗口中打开。';
  const ua=env.navigator?.userAgent||'',ios=/iPad|iPhone|iPod/.test(ua)||(/Macintosh/.test(ua)&&env.navigator?.maxTouchPoints>1);
  if(ios)return '在 Safari 中打开，选择“分享”→“添加到主屏幕”，然后从桌面图标进入。系统支持且授权后可开启通知。';
  if(/MicroMessenger|\bQQ\//.test(ua))return '请先用菜单中的“在浏览器中打开”，再使用浏览器的安装或添加到桌面功能。';
  return '在浏览器菜单中选择“安装应用”或“添加到主屏幕”。桌面 Chrome / Edge 可安装，Mac Safari 可选择“添加到程序坞”；具体入口以浏览器提供为准。';
}
export function createPWA({showDialog}){
  let installPrompt=null;
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;});
  window.addEventListener('appinstalled',()=>{installPrompt=null;});
  if(isSecureContext&&navigator.serviceWorker)navigator.serviceWorker.register('/notification-worker.js',{scope:'/'}).catch(()=>{});
  function open(){showDialog('添加到桌面',`<div class="stack"><p>${installationAdvice()}</p>${installPrompt?'<button type="button" class="button primary" data-pwa-install>安装珞珈信使</button>':''}<p class="small muted">通知整理、资料同步和验证码需要联网。离线时不会缓存或展示你的私人通知。安装后请到“提醒”中开启通知，并用一条测试提醒确认实际送达。</p></div>`);}
  document.addEventListener('click',async event=>{if(event.target.closest('[data-pwa-open]'))open();if(event.target.closest('[data-pwa-install]')&&installPrompt){const pending=installPrompt;installPrompt=null;await pending.prompt();}});
  return {open};
}
