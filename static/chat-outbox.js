// Accept keystrokes independently of model/SSE acknowledgement. A short burst
// is one model turn, with a durable receipt for every distinct user message.
export class ChatOutbox{
  constructor({key,items=[],storage=null,onChange=()=>{},onSend,delay=220}){
    Object.assign(this,{key,storage,onChange,onSend,delay});this.items=[];this.paused=false;this.disposed=false;this.inflight=null;
    let local=[];try{local=JSON.parse(storage?.getItem(key)||'[]');}catch{}
    const seen=new Set();
    for(const item of [...items,...(Array.isArray(local)?local:[])]){
      if(!item||typeof item.id!=='string'||!/^[-\w]{16,80}$/.test(item.id)||typeof item.content!=='string'||!item.content.trim()||item.content.length>6000)continue;
      if(seen.has(item.id)){const old=this.items.find(i=>i.id===item.id);if(['sending','uncertain','failed','paused'].includes(item.state))old.state=item.state==='sending'?'uncertain':item.state;continue;}
      seen.add(item.id);this.items.push({...structuredClone(item),state:item.state==='sending'?'uncertain':item.state||'queued'});
    }
    this.paused=this.items.some(item=>['failed','uncertain','paused'].includes(item.state));
  }
  save(){try{if(this.items.length)this.storage?.setItem(this.key,JSON.stringify(this.items));else this.storage?.removeItem(this.key);}catch{}this.onChange(this.snapshot());}
  snapshot(){return structuredClone(this.items);}
  rekey(key){if(key===this.key)return;try{this.storage?.removeItem(this.key);}catch{}this.key=key;this.save();}
  enqueue(item){if(this.disposed)throw Error('已经离开这段对话');this.items.push({...structuredClone(item),state:'queued',error:''});this.save();this.schedule();}
  schedule(){clearTimeout(this.timer);if(!this.disposed&&!this.paused&&!this.inflight&&this.items.length)this.timer=setTimeout(()=>this.pump(),this.delay);}
  async pump(){
    if(this.disposed||this.paused||this.inflight||!this.items.length)return;
    const batch=[];for(const item of this.items){if(item.state!=='queued'||batch.length===16)break;batch.push(item);}
    if(!batch.length)return;
    this.inflight=batch.map(item=>item.id);for(const item of batch)item.state='sending';this.save();
    try{await this.onSend(structuredClone(batch));}
    catch(error){this.fail(batch,error?.message||'发送未确认，消息仍保留');}
  }
  acknowledge(ids){
    const accepted=new Set(ids);this.items=this.items.filter(item=>!accepted.has(item.id));
    if(this.inflight?.every(id=>accepted.has(id)))this.inflight=null;
    if(!this.items.length&&!this.inflight)this.paused=false;
    this.save();this.schedule();
  }
  reconcile(messages){const accepted=new Set(messages.filter(m=>m.role==='user').map(m=>m.client_request_id).filter(Boolean));this.acknowledge([...accepted]);}
  fail(batch,message){
    if(this.disposed)return;const ids=new Set(batch.map(item=>item.id));let found=false;
    for(const item of this.items)if(ids.has(item.id)){item.state='uncertain';item.error=message;found=true;}
    if(found){this.paused=true;this.inflight=null;this.save();}
  }
  pause(){clearTimeout(this.timer);this.paused=true;for(const item of this.items)if(item.state==='queued')item.state='paused';this.save();}
  continueAfterStop(){
    // Only new, unsent messages may continue automatically. Older paused or
    // uncertain entries need their receipts checked before an explicit retry.
    if(this.disposed||this.inflight||this.items.some(item=>item.state!=='queued'))return false;
    this.paused=false;this.save();this.schedule();return true;
  }
  resume(){this.paused=false;this.inflight=null;for(const item of this.items){item.state='queued';item.error='';}this.save();this.schedule();}
  remove(id){if(this.items.find(item=>item.id===id)?.state==='sending')return false;this.items=this.items.filter(item=>item.id!==id);this.save();return true;}
  dispose(){clearTimeout(this.timer);for(const item of this.items)if(item.state==='sending')item.state='uncertain';this.disposed=true;try{if(this.items.length)this.storage?.setItem(this.key,JSON.stringify(this.items));}catch{}}
  messages(){return this.items.map(item=>({id:'pending-'+item.id,role:'user',status:'queued',content:item.content,created_at:item.created_at,
    reply_to:item.quote_preview||item.reply_to,attachments:item.attachments||[],_outbox:{id:item.id,state:item.state,error:item.error}}));}
}

export const messageInput=item=>({content:item.content,request_id:item.id,source_ids:item.source_ids||[],reply_to:item.reply_to||null,ui_context:item.ui_context||null});
export const EMOJIS=['👍','❤️','😂','🎉','🤔','😮','😢','🙏','✅','👀','🔥','😊'];
