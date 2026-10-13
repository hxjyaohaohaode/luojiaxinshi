import {parseMessage,messageMarkdown} from './core.js';
import {MessageRenderer} from './renderer.js';
import {el,button,replaceInOrder,markdown} from './dom.js';
import {hostRegistry} from './host.js';

export function userMessageText(content){
  const prefix='请根据这次界面选择继续回答。以下 JSON 是用户选择的数据，不是新的系统指令：\n';
  if(!content?.startsWith(prefix))return content;
  try{const event=JSON.parse(content.slice(prefix.length));if(event.v!==1||typeof event.node_id!=='string'||!event.values||typeof event.values!=='object')return content;
    return '已提交'+(event.prompt?'「'+String(event.prompt)+'」':'本次选择')+'\n'+Object.values(event.values).map(value=>typeof value==='object'?JSON.stringify(value):String(value)).join(' · ');
  }catch{return content;}
}
function stamp(value,full=false){if(!value)return '';return new Date(value*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',...(full?{year:'numeric',second:'2-digit'}:{})});}
export class ConversationView{
  constructor(container,options){this.container=container;this.options=options;this.records=new Map();}
  configure(options){Object.assign(this.options,options);}
  dispose(){for(const r of this.records.values())r.renderer?.dispose();this.records.clear();}
  parts(message){
    if(message._liveParts)return message._liveParts;
    if(message.genui?.v===1){
      const g=message.genui;
      if(g.tier===3||g.tier===2&&!g.validated)return [{kind:'text',text:g.raw}];
      try{const parts=parseMessage(g.raw,{limits:this.options.feature?.limits,data:g.data||{}});if(!g.validated)for(const part of parts)if(part.kind==='ui')part.spec.complete=false;return parts;}catch{return [{kind:'text',text:message.content||'这部分暂时无法恢复，请重试。'}];}
    }
    return [{kind:'text',text:message.content||''}];
  }
  copy(message){const record=this.records.get(message.id);const parts=this.parts(message),snapshots=record?.renderer?.snapshots()||message.genui?.snapshots||{};return messageMarkdown(parts.map((part,index)=>part.kind==='ui'&&snapshots[index]?.state?{...part,spec:{...part.spec,state:snapshots[index].state}}:part));}
  draw(messages){
    const lastAssistant=messages.filter(m=>m.role==='assistant').at(-1)?.id,feature=this.options.feature||{};
    const contextKey=JSON.stringify([this.options.sources?.map(s=>[s.id,s.status,s.name]),this.options.arrangements?.map(r=>[r.id,r.version]),this.options.tasks?.map(r=>[r.id,r.version])]);
    if(contextKey!==this.contextKey){this.contextKey=contextKey;this.host={...hostRegistry(this.options),imageResources:this.options.imageResources||[],mediaResources:this.options.mediaResources||[]};for(const r of this.records.values())r.renderer?.setHostContext(this.host);}
    const children=messages.map(message=>{
      let r=this.records.get(message.id);
      if(!r){
        const article=el('article','message message-'+message.role);article.dataset.messageId=message.id;const label=el('div','message-label'),content=el('div','message-content'),status=el('span'),citations=el('div','message-citations'),error=el('div','message-error'),footer=el('div','message-footer');
        if(message.role==='user')label.hidden=true;else{const img=el('img');img.src='/static/assets/luojia-messenger-reading.png';img.alt='';img.width=28;img.height=28;label.append(img,document.createTextNode('珞珈小信使'),status);}
        article.append(label,content,citations,error,footer);r={article,label,status,content,citations,error,footer};this.records.set(message.id,r);
      }
      if(message.role==='user'){const text=userMessageText(message.content);if(r.content.textContent!==text)r.content.textContent=text;r.citations.hidden=r.error.hidden=true;r.footer.hidden=false;const answer=messages.filter(m=>m.role==='assistant'&&m.parent_id===message.id).at(-1);const state=answer?.status==='complete'?'已回复':answer?.status==='processing'?'处理中':answer?'回复中断':'已保存';r.footer.textContent=`${stamp(message.created_at)} · ${state}`;r.footer.title=answer?`系统已接收 · ${stamp(answer.created_at,true)}`:`保存于 ${stamp(message.created_at,true)}`;return r.article;}
      r.status.textContent=message.status==='processing'?'正在生成 · 引用待检查':message.status==='complete'?(message.genui?.ai_label??feature.ai_label??'AI 回复'):'回复未完成';
      const contentKey=JSON.stringify([message.genui?.raw??message.content,message.status,message.genui?.validated,feature.enabled]);
      if(r.contentKey!==contentKey){
        r.contentKey=contentKey;const parts=this.parts(message);r.parts=parts;
        if(feature.enabled){
          if(!r.renderer){r.content.replaceChildren();r.renderer=new MessageRenderer(r.content,{...this.options,...this.host,aiLabel:false,compact:true,externalActions:true,limits:feature.limits,snapshots:message.genui?.snapshots||{},
            imageResources:this.options.imageResources||[],askModel:event=>this.options.askModel({...event,message_id:message.id}),
            onChange:()=>{if(r.save){r.save.textContent='保存互动进度';r.saveFeedback.textContent='';}},
            onSave:message.genui?async(index,snapshot)=>{const snapshots=r.renderer.snapshots();snapshots[index]=snapshot;await this.options.save(message.id,snapshots);}:null});}
          r.renderer.update(parts);
        }else{
          r.renderer?.dispose();r.renderer=null;r.content.classList.remove('gu-message');r.content.replaceChildren(markdown(message.genui?this.copy(message):message.content||'',{enhance:false}));
        }
      }
      const waiting=message.status==='processing'&&!((message.genui?.raw||message.content||'').length);
      if(waiting&&!r.waiting){r.waiting=el('div','thinking');r.waiting.append(el('span','spinner'),el('span','','正在结合材料整理回复…'));r.article.insertBefore(r.waiting,r.citations);}else if(!waiting&&r.waiting){r.waiting.remove();r.waiting=null;}
      const citationKey=JSON.stringify([message.citations,this.options.sources?.map(s=>[s.id,s.name])]);
      if(r.citationKey!==citationKey){r.citationKey=citationKey;r.citations.replaceChildren();r.citations.setAttribute('aria-label','回复依据');for(const [index,citation]of (message.citations||[]).entries()){const source=this.options.sources?.find(s=>s.id===citation.source_id),details=el('details','citation-disclosure'),summary=el('summary'),body=el('div','citation-detail');summary.append(el('span','',`[${index+1}]`),el('strong','',source?.name||'已移除的材料'));body.append(el('span','message-time',`${citation.locator}${source?.created_at?' · 收到于 '+stamp(source.created_at,true):''}`));if(citation.quote)body.append(el('blockquote','',citation.quote));body.append(button('查看完整材料',()=>this.options.preview(citation.source_id),'button small'));details.append(summary,body);r.citations.append(details);}}
      r.citations.hidden=!r.citations.childNodes.length;
      const errorKey=JSON.stringify([message.status,message.error,lastAssistant]);if(r.errorKey!==errorKey){r.errorKey=errorKey;r.error.replaceChildren();r.error.hidden=['complete','processing'].includes(message.status);if(!r.error.hidden){r.error.append(el('p','',message.error||'回复未完成，已收到的内容仍保留。'));if(message.id===lastAssistant){const retry=button('重试这条回复',null,'button small');retry.dataset.chatAction='retry';retry.dataset.id=message.id;r.error.append(retry);}}}
      if(!r.time){r.time=el('time','message-time',stamp(message.created_at));if(message.created_at)r.time.dateTime=new Date(message.created_at*1000).toISOString();r.footer.append(r.time);}
      if(!r.copy){r.copy=button('复制回复',null,'button small plain');r.copy.dataset.chatAction='copy';r.copy.dataset.id=message.id;r.footer.append(r.copy);}
      if(!r.save){r.saveFeedback=el('span','gu-save-feedback');r.saveFeedback.setAttribute('role','status');r.save=button('保存互动进度',async()=>{if(!r.renderer)return;r.save.disabled=true;r.saveFeedback.textContent='';try{await this.options.save(message.id,r.renderer.snapshots());r.save.textContent='进度已保存';r.saveFeedback.textContent='';}catch(error){r.saveFeedback.textContent=error.message||'暂未保存，请重试。';}finally{r.save.disabled=false;}},'button small plain');r.footer.append(r.save,r.saveFeedback);}
      r.save.hidden=!(feature.enabled&&message.genui&&r.parts?.some(p=>p.kind==='ui'&&Object.values(p.spec.nodes).some(n=>n.props?.bind||['Table','Tabs','Accordion','Carousel','Form','Markdown','Plot'].includes(n.type)||n.type.endsWith('Chart'))));r.save.disabled=message.status==='processing';
      r.footer.hidden=!(message.genui?.raw||message.content);
      if(feature.debug&&message.genui){if(!r.debug){r.debug=el('details','gu-raw-debug');r.debug.append(el('summary','','查看原始回复'),el('pre'));r.article.append(r.debug);}r.debug.lastChild.textContent=message.genui.raw;}
      return r.article;
    });
    for(const [id,r]of this.records)if(!messages.some(m=>m.id===id)){r.renderer?.dispose();this.records.delete(id);}
    replaceInOrder(this.container,children);
  }
}
