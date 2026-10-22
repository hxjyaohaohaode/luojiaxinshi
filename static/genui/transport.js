// Fetch POST keeps the application's same-origin cookies and CSRF checks.
export class SSEDecoder{
  constructor(onEvent,{eventBytes=4194304,totalBytes=8388608}={}){this.onEvent=onEvent;this.decoder=new TextDecoder();this.buffer='';this.frame=[];this.frameSize=0;this.total=0;this.last=0;this.eventBytes=eventBytes;this.totalBytes=totalBytes;this.done=false;}
  push(bytes){this.total+=bytes.byteLength;if(this.total>this.totalBytes)throw Error('回复传输超过大小上限，已保留收到的内容。');this.buffer+=this.decoder.decode(bytes,{stream:true});let end;
    while((end=this.buffer.indexOf('\n'))>=0){const line=this.buffer.slice(0,end).replace(/\r$/,'');this.buffer=this.buffer.slice(end+1);this.line(line);}
    if(this.buffer.length>this.eventBytes)throw Error('回复数据行过长，已停止读取。');
  }
  line(line){
    if(line===''){
      if(!this.frame.length)return;const fields=Object.create(null);for(const row of this.frame){const colon=row.indexOf(':');if(colon<0||row.startsWith(':'))continue;const key=row.slice(0,colon),value=row.slice(colon+1).replace(/^ /,'');if(['id','event','data'].includes(key))fields[key]=key==='data'&&fields.data?fields.data+'\n'+value:value;}
      this.frame=[];this.frameSize=0;if(!fields.data)return;const seq=Number(fields.id);if(!Number.isSafeInteger(seq)||seq<1)throw Error('回复序号无效。');if(seq<=this.last)return;if(seq!==this.last+1)throw Error('回复流缺失一段内容，已保留收到的部分。');this.last=seq;
      if(!['start','phase','work','agent','preview','delta','done'].includes(fields.event))throw Error('回复事件暂不支持。');let data;try{data=JSON.parse(fields.data);}catch{throw Error('回复数据未通过解析，已保留收到的内容。');}
      if(fields.event==='agent'&&(typeof data?.message_id!=='string'||typeof data.kind!=='string'||!data.state||typeof data.state.thread_id!=='string'||!Array.isArray(data.state.approvals)||data.state.approvals.length>8||!Array.isArray(data.state.files)))throw Error('工具执行状态无效。');
      if(fields.event==='phase'&&(!['planning','retrieving','searching','coverage','writing','verifying'].includes(data?.phase)||typeof data?.label!=='string'||data.label.length>160))throw Error('回复阶段无效。');
      if((fields.event==='work'||data?.steps!==undefined)&&(!Array.isArray(data.steps)||data.steps.length>48||data.steps.some(s=>!s||typeof s.id!=='string'||typeof s.title!=='string'||s.title.length>80||typeof s.summary!=='string'||s.summary.length>160||!['running','complete','interrupted'].includes(s.state))))throw Error('工作摘要无效。');
      if(['delta','preview'].includes(fields.event)&&(typeof data?.text!=='string'||data.text.length>1048576))throw Error('回复增量无效。');
      if(fields.event==='done')this.done=true;this.onEvent(fields.event,data);return;
    }
    this.frameSize+=new TextEncoder().encode(line).length+1;if(this.frameSize>this.eventBytes)throw Error('回复区段过长，已停止读取。');this.frame.push(line);
  }
  finish(){this.buffer+=this.decoder.decode();if(this.buffer.trim()||this.frame.length||!this.done)throw Error('连接中断，已收到的内容保留，请稍后重试。');}
}
export async function streamChat(cid,payload,{csrf,signal,onEvent}){
  const response=await fetch('/api/conversations/'+encodeURIComponent(cid)+'/messages/stream',{method:'POST',credentials:'same-origin',signal,headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':csrf,'Content-Type':'application/json','Accept':'text/event-stream'},body:JSON.stringify(payload)});
  if(!response.ok){let body;try{body=await response.json();}catch{}const error=new Error(typeof body?.detail==='string'?body.detail:'暂时无法开始回复，请重试。');error.status=response.status;throw error;}
  if(!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw Error('服务未返回流式回复，请刷新后重试。');
  const reader=response.body.getReader(),decoder=new SSEDecoder(onEvent);try{while(true){const item=await reader.read();if(item.done)break;decoder.push(item.value);}decoder.finish();}catch(error){try{await reader.cancel();}catch{}throw error;}finally{reader.releaseLock();}
}
