// Other tabs receive only a wake-up signal. Every revision and record comes
// from an authenticated server read, including after a missed signal.
export function installDataSync({state,api,onChange}){
  let session=null,last=null,busy=false,queued=false,timer=null,failures=0,retryAt=0,stopped=false,paused=false,request=null;
  const channel=typeof window.BroadcastChannel==='function'?new window.BroadcastChannel('luojia-workspace-revision'):null;
  function wake(){
    if(stopped||paused||timer!==null)return;
    timer=setTimeout(()=>{timer=null;probe();},80);
  }
  async function probe(){
    const requested=state.session;
    if(stopped||paused||!requested?.user?.id||document.hidden||Date.now()<retryAt)return;
    if(busy){queued=true;return;}
    if(session!==requested){session=requested;last=requested.sync||null;}
    busy=true;
    const controller=new AbortController();
    request=controller;
    const deadline=setTimeout(()=>controller.abort(),10000);
    try{
      const value=await api('/proactive/revision',{signal:controller.signal,headers:{'X-Workspace-Revision':'1'}});
      if(stopped||paused||state.session!==requested)return;
      if(last?.revision!==value.revision){
        const current=value.domains;
        const previous=last?.domains||{};
        const domains=current?new Set([...Object.keys(previous),...Object.keys(current)].filter(key=>previous[key]!==current[key])):null;
        if(await onChange(domains,current)===false)return;
        if(stopped||paused||state.session!==requested)return;
      }
      last=value;failures=0;retryAt=0;
    }catch{
      if(!paused&&!stopped&&state.session===requested)retryAt=Date.now()+Math.min(3000*2**failures++,30000);
    }finally{
      clearTimeout(deadline);request=null;
      busy=false;
      if(queued){queued=false;wake();}
    }
  }
  const interval=setInterval(probe,3000);
  const visible=()=>{if(!document.hidden){retryAt=0;wake();}};
  const hide=()=>{paused=true;clearTimeout(timer);timer=null;request?.abort();};
  const show=()=>{paused=false;visible();};
  if(channel)channel.onmessage=event=>{if(event.data===state.session?.user?.id)wake();};
  document.addEventListener('visibilitychange',visible);
  window.addEventListener('focus',visible);window.addEventListener('online',visible);
  window.addEventListener('pagehide',hide);window.addEventListener('pageshow',show);
  return {probe,wake,notify(){
    if(state.session?.user?.id)channel?.postMessage(state.session.user.id);
    wake();
  },stop(){
    stopped=true;hide();clearInterval(interval);channel?.close();
    document.removeEventListener('visibilitychange',visible);
    window.removeEventListener('focus',visible);window.removeEventListener('online',visible);
    window.removeEventListener('pagehide',hide);window.removeEventListener('pageshow',show);
  }};
}
