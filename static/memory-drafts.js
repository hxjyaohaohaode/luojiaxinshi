// Unsaved text stays in this tab's session storage, partitioned by account.
// Storage being unavailable must never prevent editing or saving.
export function createMemoryDrafts(storage){
  if(storage===undefined)try{storage=globalThis.sessionStorage;}catch{storage=null;}
  const prefix='campus-memory-drafts-v1:';let owner=null,values=new Map();
  function persist(){
    if(!owner)return;
    try{if(values.size)storage?.setItem(prefix+owner,JSON.stringify([...values]));else storage?.removeItem(prefix+owner);}catch{}
  }
  function select(user){
    if(owner===user)return;
    if(owner)try{storage?.removeItem(prefix+owner);}catch{}
    owner=user;values.clear();
    try{
      // A different account must not inherit another account's draft on reload.
      for(const key of Object.keys(storage||{}))if(key.startsWith(prefix)&&key!==prefix+user)storage.removeItem(key);
      if(user){
        const raw=JSON.parse(storage?.getItem(prefix+user)||'[]');
        if(Array.isArray(raw))for(const entry of raw.slice(-20)){
          const [id,d]=entry||[];
          if(typeof id==='string'&&typeof d?.content==='string'&&d.content.length<=4000&&Number.isInteger(d.version)&&d.version>0&&d.at>Date.now()-7*86400000)values.set(id,d);
        }
      }
    }catch{}
    persist();
  }
  return {select,get:id=>values.get(id),has:id=>values.has(id),
    put(id,content,version,base=''){
      if(content===base){values.delete(id);persist();return;}
      values.delete(id);values.set(id,{content,version,base,at:Date.now()});
      while(values.size>20)values.delete(values.keys().next().value);
      persist();
    },remove(id){values.delete(id);persist();},clear(){if(owner)try{storage?.removeItem(prefix+owner);}catch{}values.clear();owner=null;}
  };
}
