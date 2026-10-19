// Server drafts use optimistic revisions; saving never overwrites another tab.
export function createDraftStore(api, report = () => {}) {
  const entries = new Map();
  const entry = key => {
    if (!entries.has(key)) entries.set(key,{revision:0,payload:null,loaded:false,loading:null,chain:Promise.resolve(),dirty:false,writing:0,sequence:0,generation:0,retired:false,retiring:false,retiringGeneration:null,retirement:null,error:null,timer:null,attempted:null});
    return entries.get(key);
  };
  function notify(key,text,error=false){report(key,text,error);}
  const checkpoint=key=>{const item=entry(key);return {item,generation:item.generation,sequence:item.sequence};};
  const matches=(key,ticket)=>!!ticket&&entries.get(key)===ticket.item&&ticket.item.generation===ticket.generation&&ticket.item.sequence===ticket.sequence;
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
    if(item.retired||(item.retiring&&item.retiringGeneration===item.generation))return;
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
    // A completed business save is already durable. Navigation need not wait
    // for its cache cleanup when there is no newer user input to flush.
    if(item.retiring&&!item.dirty&&!item.writing)return;
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
        if(entries.get(key)!==item)return;
        item.revision=response.revision;
        if(sequence===item.sequence){item.dirty=false;notify(key,'编辑内容已暂存');}
      }).catch(error=>{if(entries.get(key)!==item)return;item.error=error;item.dirty=true;notify(key,'暂存未完成：'+error.message,true);}).finally(()=>{item.writing--;});
    }
    await item.chain;
    if(item.error)throw item.error;
  }
  function retire(key,ticket=checkpoint(key)) {
    const item=entry(key);
    if(!matches(key,ticket))return Promise.resolve(false);
    if(item.retirement)return item.retirement.catch(()=>{}).then(()=>retire(key,ticket));
    item.retiring=true;item.retiringGeneration=ticket.generation;
    clearTimeout(item.timer);
    const work=(async()=>{
      try{
        await flush(key);
        if(!matches(key,ticket))return false;
        let retired=false,failure=null;
        // Delete on the same queue as autosave. A newly opened editor can keep
        // accepting input while this request is pending; its next write follows.
        const cleanup=item.chain.then(async()=>{
          if(!matches(key,ticket))return;
          item.attempted=null;
          const response=await api('/edit-cache/'+encodeURIComponent(key),{method:'PUT',json:{revision:item.revision,payload:null}});
          if(entries.get(key)!==item)return;
          item.revision=response.revision;item.error=null;
          if(matches(key,ticket)){
            item.payload=null;item.retired=true;item.dirty=false;retired=true;
            notify(key,'已正式保存');
          }else item.dirty=true;
        }).catch(error=>{
          if(entries.get(key)!==item)return;
          failure=error;item.error=error;item.retired=matches(key,ticket);item.dirty=!item.retired;
          notify(key,'正式内容已保存，编辑暂存清理未完成：'+error.message,true);
        });
        item.chain=cleanup;
        await cleanup;
        if(failure)throw failure;
        return retired;
      }finally{item.retiring=false;item.retiringGeneration=null;item.retirement=null;}
    })();
    item.retirement=work;return work;
  }
  return {load,stage,flush,retire,checkpoint,peek:key=>entry(key),
    activate:key=>{const item=entry(key);if(item.retired)item.payload=null;item.retired=false;item.generation++;},
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
