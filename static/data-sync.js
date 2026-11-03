// Server revisions are owner-scoped. Signals contain no documents or credentials.
// Never replace an edited form in response to background activity.
export function installDataSync({state,api,onChange}){
  let owner=null,last='',busy=false;
  async function probe(){
    const session=state.session,uid=session?.user?.id;
    if(!uid||document.hidden||busy)return;
    if(owner!==uid){owner=uid;last='';}
    busy=true;
    try{
      const value=await api('/proactive/revision');
      if(state.session!==session||state.session?.user?.id!==uid)return;
      if(last!==value.revision){
        if(await onChange()===false)return;
        if(state.session!==session)return;
      }
      last=value.revision;
    }catch{ /* Existing content stays available; retry on the next visible tick. */ }
    finally{busy=false;}
  }
  const timer=setInterval(probe,15000);
  const visible=()=>{if(!document.hidden)probe();};
  document.addEventListener('visibilitychange',visible);
  window.addEventListener('focus',visible);window.addEventListener('online',visible);
  return {probe,stop(){clearInterval(timer);document.removeEventListener('visibilitychange',visible);window.removeEventListener('focus',visible);window.removeEventListener('online',visible);}};
}
