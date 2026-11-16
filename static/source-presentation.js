export function isSchoolOfficial(value){
  try{
    const url=new URL(value),host=url.hostname.toLowerCase();
    return ['http:','https:'].includes(url.protocol)&&
      (host==='whu.edu.cn'||host.endsWith('.whu.edu.cn')||['www.rmhospital.com','www.znhospital.cn','www.whuss.com'].includes(host));
  }catch{return false;}
}

export function schoolSourcePresentation(source){
  const origin=source.origin||{},official=isSchoolOfficial(origin.url)||isSchoolOfficial(origin.parent_url);
  if(!official)return null;
  const missing=(origin.attachments||[]).filter(url=>!(origin.received_attachments||[]).includes(url));
  const state=origin.list_only?'原文链接':source.kind!=='text'?(source.status==='failed'?'原件已收 · 文字未提取':'原件已接收'):
    source.status==='failed'?'正文暂未读到':'已接收';
  const note=origin.list_only?'只收到标题和原文链接，正文与附件请在原文查看。':
    missing.length?'部分附件尚未接收，可以打开原文查看。':'';
  return {state,note,details:[...(origin.warnings||[]),...(source.warning?[source.warning]:[])]};
}
