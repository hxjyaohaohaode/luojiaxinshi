// Server drafts use optimistic revisions; saving never overwrites another tab.
export function createDraftStore(api, report = () => {}) {
  const entries = new Map();
  const entry = key => {
    if (!entries.has(key)) entries.set(key,{revision:0,payload:null,loaded:false,loading:null,chain:Promise.resolve(),dirty:false,writing:0,sequence:0,retired:false,retiring:false,error:null,timer:null,attempted:null});
    return entries.get(key);
  };
  function notify(key,text,error=false){report(key,text,error);}
  async function load(key) {
    const item=entry(key);
    if(item.loaded)return item;
    if(!item.loading)item.loading=api('/edit-cache/'+encodeURIComponent(key)).then(result=>{
      item.revision=result.revision;
      if(!item.dirty&&!item.writing)item.payload=result.payload;
      item.loaded=true;
      return item;
    }).finally(()=>{item.loading=null;});
    return item.loading;
  }
  function stage(key,payload) {
    const item=entry(key);
    if(item.retired||item.retiring)return;
    item.payload=structuredClone(payload);
    item.dirty=true;
    item.sequence++;
    clearTimeout(item.timer);
    notify(key,'正在暂存…');
    item.timer=setTimeout(()=>{flush(key).catch(()=>{});},650);
  }
  async function flush(key) {
    const item=entry(key);
    clearTimeout(item.timer);
    if(item.retired)return;
    if(item.dirty&&!item.retired) {
      const snapshot=structuredClone(item.payload);
      const sequence=item.sequence;
      item.dirty=false;
      item.writing++;
      item.chain=item.chain.then(async()=>{
        if(item.retired)return;
        await load(key);
        if(item.retired)return;
        if(item.error){
          // A lost response may have committed. Reconcile before retrying.
          const remote=await api('/edit-cache/'+encodeURIComponent(key));
          if(remote.revision!==item.revision&&JSON.stringify(remote.payload)!==JSON.stringify(item.attempted)){
            const conflict=new Error('另一页面已更新草稿。本页内容仍保留，请先下载本页编辑后刷新核对');
            conflict.status=409;throw conflict;
          }
          item.revision=remote.revision;item.error=null;
        }
        item.attempted=snapshot;
        const response=await api('/edit-cache/'+encodeURIComponent(key),{method:'PUT',json:{revision:item.revision,payload:snapshot}});
        item.revision=response.revision;
        if(sequence===item.sequence){item.dirty=false;notify(key,'编辑内容已暂存');}
      }).catch(error=>{item.error=error;item.dirty=true;notify(key,'暂存未完成：'+error.message,true);}).finally(()=>{item.writing--;});
    }
    await item.chain;
    if(item.error)throw item.error;
  }
  async function retire(key) {
    const item=entry(key);
    item.retiring=true;
    clearTimeout(item.timer);
    try{
      await flush(key);
      const response=await api('/edit-cache/'+encodeURIComponent(key),{method:'PUT',json:{revision:item.revision,payload:null}});
      item.revision=response.revision;
      item.payload=null;item.retired=true;item.dirty=false;
      notify(key,'已正式保存');
    }finally{item.retiring=false;}
  }
  return {load,stage,flush,retire,peek:key=>entry(key),
    activate:key=>{entry(key).retired=false;},
    pending:()=>[...entries.values()].some(e=>!e.retired&&(e.dirty||e.writing||e.error)),
    flushAll:()=>Promise.all([...entries.keys()].map(flush)),
    clear:()=>{for(const e of entries.values()){clearTimeout(e.timer);e.retired=true;}entries.clear();}
  };
}

export function moveSelection(group, selector='.tab.active') {
  if(!group)return;
  const selected=group.querySelector(selector);
  let indicator=group.querySelector('.selection-indicator');
  if(!selected){if(indicator)indicator.hidden=true;return;}
  const created=!indicator;
  if(created){indicator=document.createElement('span');indicator.className='selection-indicator';indicator.setAttribute('aria-hidden','true');indicator.style.transition='none';group.prepend(indicator);}
  indicator.hidden=false;
  indicator.style.transform=`translate(${selected.offsetLeft}px,${selected.offsetTop}px)`;
  indicator.style.width=selected.offsetWidth+'px';
  indicator.style.height=selected.offsetHeight+'px';
  if(created)requestAnimationFrame(()=>requestAnimationFrame(()=>{if(indicator.isConnected)indicator.style.transition='';}));
}
