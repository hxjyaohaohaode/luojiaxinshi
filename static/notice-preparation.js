// Save intake first; one explicit AI request can continue across page navigation.
export function createNoticePreparation({api,getOwner,onStart=()=>{},onResult=()=>{},onError=()=>{}}){
  const pending=new Map();
  const key=id=>`${getOwner()||''}:${id}`;
  function prepare(notice,processingMode='configured'){
    const owner=getOwner(),identity=key(notice.id);
    if(!owner)return Promise.resolve(null);
    if(pending.has(identity))return pending.get(identity);
    if(notice.draft||notice.status==='processing'||notice.status==='confirmed')return Promise.resolve(notice);
    const job=Promise.resolve().then(async()=>{
      if(getOwner()!==owner)return null;
      onStart(notice);
      try{
        const result=await api(`/notices/${encodeURIComponent(notice.id)}/generate`,{method:'POST',json:{version:notice.version,allow_external_processing:true,processing_mode:processingMode}});
        pending.delete(identity);
        if(getOwner()===owner)await onResult(result);
        return result;
      }catch(error){
        pending.delete(identity);
        if(getOwner()===owner){try{await onError(error,notice);}catch{/* A failed refresh must not resend or reject an unobserved background job. */}}
        return null;
      }finally{pending.delete(identity);}
    });
    pending.set(identity,job);
    return job;
  }
  return {prepare,isPending:id=>pending.has(key(id))};
}
