import {brandMotion} from '../motion.js';
import {parseMessage,messageMarkdown} from './core.js';
import {MessageRenderer} from './renderer.js';
import {el,button,replaceInOrder,markdown} from './dom.js';
import {hostRegistry} from './host.js';
import {WorkSummaryView} from './work-view.js';
import {CitationView} from './citations.js';
import {submittedMessageText as userMessageText} from './interaction.js';

export {userMessageText};
function stamp(value,full=false){if(!value)return '';return new Date(value*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',...(full?{year:'numeric',second:'2-digit'}:{})});}
const replyPaths={copy:'M9 9h11v12H9z M15 9V3H3v12h6',like:'M8 10v11H3V10z M8 10l4-8h2v7h6a2 2 0 0 1 2 2l-2 8a2 2 0 0 1-2 2H8',dislike:'M8 14V3H3v11z M8 14l4 8h2v-7h6a2 2 0 0 0 2-2l-2-8a2 2 0 0 0-2-2H8',branch:'M6 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4 M18 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4 M6 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4 M6 7v10 M6 13h6a6 6 0 0 0 6-6',regenerate:'M20 7a9 9 0 1 0 1 8 M20 2v5h-5',share:'M12 16V3 M7 8l5-5 5 5 M5 12v9h14v-9',previous:'m14 6-6 6 6 6',next:'m10 6 6 6-6 6',save:'M5 3h14v19l-7-4-7 4z'};
function replyAction(action,label){const b=button('',null,'button small plain reply-action');b.setAttribute('aria-label',label);b.title=label;const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS(svg.namespaceURI,'path');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');path.setAttribute('d',replyPaths[action]);svg.append(path);b.append(svg);return b;}
function replyHostContext(host,record,options){return {...host,linkResources:record.linkResources||[],hostActions:{...host.hostActions,open_sources:{run:()=>record.citationView?.entries?.length?record.citationView.open():options.openSources?.()}}};}
export class ConversationView{
  constructor(container,options){this.container=container;this.options=options;this.records=new Map();}
  configure(options){Object.assign(this.options,options);}
  interactionContext(messageId=null,force=false,scope=null){
    const messages=messageId?this.messages?.filter(m=>m.id===messageId):[...(this.messages||[])].reverse().sort((a,b)=>Number(b.id===this.interactionOrigin)-Number(a.id===this.interactionOrigin));
    for(const message of messages||[]){if(message.role!=='assistant'||message.status!=='complete'||!message.genui?.validated)continue;const renderer=this.records.get(message.id)?.renderer,previous=new Map();for(const user of this.messages||[])if(user.role==='user'&&user.interaction?.message_id===message.id)for(const selected of user.interaction.selections||[])previous.set(selected.block+':'+(selected.path||selected.view_key||selected.node)+':'+(selected.field||''),selected);renderer?.reconcileSelections([...previous.values()]);const blocks=renderer?.interaction(force,scope);if(blocks&&(force||this.submittedContexts?.get(message.id)!==JSON.stringify(blocks)))return {v:1,message_id:message.id,snapshot_version:message.genui.snapshot_version??0,blocks};}
    return null;
  }
  markContextSubmitted(context,saved=false){if(context){this.submittedContexts??=new Map();this.submittedContexts.set(context.message_id,JSON.stringify(context.blocks));if(saved){const record=this.records.get(context.message_id);if(record?.saveFeedback)record.saveFeedback.textContent='本次提交的选择已保存';}}}
  dispose(){for(const r of this.records.values()){r.renderer?.dispose();r.work?.dispose();r.citationView?.dispose();}this.records.clear();}
  parts(message){
    if(message._liveParts)return message._liveParts;
    if(message.genui?.v===1){
      const g=message.genui;
      if(g.tier===3||g.tier===2&&!g.validated)return [{kind:'text',text:g.raw}];
      try{const parts=parseMessage(g.raw,{limits:this.options.feature?.limits,data:g.data||{}});if(!g.validated)for(const part of parts)if(part.kind==='ui')part.spec.complete=false;return parts;}catch{return [{kind:'text',text:message.content||'这部分暂时无法恢复，请重试。'}];}
    }
    return [{kind:'text',text:message.content||''}];
  }
  copy(message){const record=this.records.get(message.id);const parts=this.parts(message),snapshots=record?.renderer?.snapshots()||message.genui?.snapshots||{};return messageMarkdown(parts,snapshots);}
  copyHTML(message){
    const record=this.records.get(message.id);if(!record)return '';
    const original=record.content,clone=original.cloneNode(true),controls=[...original.querySelectorAll('input,textarea,select')];
    [...clone.querySelectorAll('input,textarea,select')].forEach((node,index)=>{const value=controls[index];node.replaceWith(document.createTextNode(value.type==='checkbox'?(value.checked?'☑':'☐'):value.tagName==='SELECT'?value.selectedOptions[0]?.textContent||value.value:value.value));});
    clone.querySelectorAll('.citation-mark').forEach(node=>node.replaceWith(document.createTextNode('['+node.dataset.citation+']')));
    clone.querySelectorAll('[hidden]').forEach(node=>node.remove());
    clone.querySelectorAll('button[role=radio],button[role=tab]').forEach(node=>{if(node.getAttribute('aria-checked')==='true'||node.getAttribute('aria-selected')==='true'){const labels=[...node.querySelectorAll('.gu-choice-label,.gu-choice-description')].map(e=>e.textContent);node.replaceWith(document.createTextNode(labels.length?labels.join(' — '):node.textContent));}else node.remove();});
    clone.querySelectorAll('button,script,style,.gu-save-feedback,.gu-actions').forEach(node=>node.remove());
    clone.querySelectorAll('img,video,audio').forEach(node=>{if(node.src?.includes('/api/'))node.replaceWith(document.createTextNode(node.alt||'媒体原件请回到对话查看'));});
    const sourceSvg=[...original.querySelectorAll('svg')];clone.querySelectorAll('svg').forEach((svg,index)=>{const source=sourceSvg[index];if(!source)return;const old=[source,...source.querySelectorAll('*')];[svg,...svg.querySelectorAll('*')].forEach((node,i)=>{const style=getComputedStyle(old[i]);for(const key of ['fill','stroke','stroke-width','font-size','font-family'])node.setAttribute(key,style.getPropertyValue(key));});});
    return `<div style="font-family:system-ui,sans-serif;line-height:1.8;color:#242424">${clone.innerHTML}</div>`;
  }
  draw(messages){
    this.messages=messages;
    const lastAssistant=messages.filter(m=>m.role==='assistant').at(-1)?.id,activeMessage=messages.find(m=>m.role==='assistant'&&m.status==='processing')?.id,feature=this.options.feature||{};
    const contextKey=JSON.stringify([this.options.sources?.map(s=>[s.id,s.status,s.name]),this.options.arrangements?.map(r=>[r.id,r.version]),this.options.tasks?.map(r=>[r.id,r.version])]);
    if(contextKey!==this.contextKey){this.contextKey=contextKey;this.host={...hostRegistry(this.options),imageResources:this.options.imageResources||[],mediaResources:this.options.mediaResources||[]};for(const r of this.records.values())r.renderer?.setHostContext(replyHostContext(this.host,r,this.options));}
    const children=messages.map(message=>{
      let r=this.records.get(message.id);
      if(!r){
        const article=el('article','message message-'+message.role);article.dataset.messageId=message.id;const label=el('div','message-label'),content=el('div','message-content'),status=el('span'),citations=el('div','message-citations'),error=el('div','message-error'),footer=el('div','message-footer');
        if(message.role==='user')label.hidden=true;else{const img=el('img');img.src='/static/assets/luojia-messenger-reading.png';img.alt='';img.width=28;img.height=28;label.append(img,document.createTextNode('珞珈小信使'),status);}
        article.append(label,content,citations,error,footer);r={article,label,status,content,citations,error,footer};this.records.set(message.id,r);
      }
      if(message.role==='user'){
        const text=userMessageText(message.content,message.interaction),key=JSON.stringify([text,message.interaction]);
        if(r.userKey!==key){r.userKey=key;r.content.replaceChildren(document.createTextNode(text));const selections=message.interaction?.selections;
          if(selections?.length){const details=el('details','message-selection-context'),summary=el('summary','','附带当前界面选择 · '+selections.length+' 项'),list=el('dl');for(const item of selections){const row=el('div');row.append(el('dt','',item.label),el('dd','',item.display??(typeof item.value==='object'?JSON.stringify(item.value):String(item.value??'未选择'))));list.append(row);}details.append(summary,list);if(message.interaction.checkpoint?.status==='conflict')details.append(el('p','','这些选择已用于本次问题。旧界面在另一页面有较新进度，已保留那份进度。'));r.content.append(details);}
        }
        r.citations.hidden=r.error.hidden=true;r.footer.hidden=false;const answer=messages.filter(m=>m.role==='assistant'&&m.parent_id===message.id).at(-1);const state=answer?.status==='complete'?'已回复':answer?.status==='processing'?'处理中':answer?'回复中断':'已保存';r.footer.textContent=`${stamp(message.created_at)} · ${state}`;r.footer.title=answer?`系统已接收 · ${stamp(answer.created_at,true)}`:`保存于 ${stamp(message.created_at,true)}`;return r.article;
      }
      const links=message.status==='complete'&&message.genui?.validated?(message.evidence_sources||[]).map(source=>source.url).filter(url=>typeof url==='string'):[];
      if(JSON.stringify(links)!==JSON.stringify(r.linkResources)){r.linkResources=links;r.renderer?.setHostContext(replyHostContext(this.host,r,this.options));}
      const redirected=message.status==='cancelled'&&message.error?.includes('按更新后的问题继续'),lastVersion=message.versions?.at(-1),keptPrevious=message.status==='complete'&&lastVersion?.id!==message.id&&['failed','cancelled'].includes(lastVersion?.status);
      r.status.textContent=message.status==='processing'?(message._phaseLabel||((message.genui?.raw||message.content)?'正在书写…':this.options.sources?.length?'正在对照材料…':'正在思考…')):message.status==='complete'?(keptPrevious?'新版本未完成，已保留上一版':''):redirected?'已按补充继续':'回复未完成';
      const active=message.status==='processing'&&message.id===activeMessage;
      if(!r.work)r.work=new WorkSummaryView(r.article,r.content);r.work.update(message);
      if(active&&(message._work?.length||message.grounding?.steps?.length))r.status.textContent='处理中';
      const pose=active?(message._phase==='writing'?'writing':message._phase==='verifying'||message._phase==='searching'||message._phase==='retrieving'?'search':(message.genui?.raw||message.content)?'writing':this.options.sources?.length?'search':'thinking'):message.status==='complete'?'complete':'rest';
      if(r.pose!==pose){r.pose=pose;const avatar=r.label.querySelector('img');avatar.src='/static/assets/luojia-messenger-'+pose+'.png';avatar.dataset.replyPose=pose;}
      const contentKey=JSON.stringify([message.genui?.raw??message.content,message.status,message.genui?.validated,feature.enabled]);
      if(r.contentKey!==contentKey){
        r.contentKey=contentKey;const parts=this.parts(message);r.parts=parts;
        if(feature.enabled){
          if(!r.renderer){r.content.replaceChildren();r.renderer=new MessageRenderer(r.content,{...this.options,...replyHostContext(this.host,r,this.options),aiLabel:false,compact:true,externalActions:true,limits:feature.limits,snapshots:message.genui?.snapshots||{},
            imageResources:this.options.imageResources||[],askModel:event=>this.options.askModel({...event,message_id:message.id}),
            onChange:()=>{this.interactionOrigin=message.id;if(r.save){r.save.textContent='保存互动进度';r.saveFeedback.textContent='';}},
            onContentRendered:()=>r.citationView?.decorate(),
            afterRender:follow=>{r.citationView?.decorate();this.options.afterRender?.(follow);},
            onSave:message.genui?async(index,snapshot)=>{const snapshots=r.renderer.snapshots();snapshots[index]=snapshot;await this.options.save(message.id,snapshots);}:null});}
          r.renderer.update(parts);
        }else{
          r.renderer?.dispose();r.renderer=null;r.content.classList.remove('gu-message');r.content.replaceChildren(markdown(message.genui?this.copy(message):message.content||'',{enhance:false}));
        }
      }
      const waiting=message.status==='processing'&&!((message.genui?.raw||message.content||'').length)&&!(message._work?.length||message.grounding?.steps?.length);
      if(waiting&&!r.waiting){r.waiting=el('div','thinking');const visual=el('span');visual.innerHTML=brandMotion('mesh','',{priority:3});r.waiting.append(visual,el('span','','正在结合材料整理回复…'));r.article.insertBefore(r.waiting,r.citations);}else if(!waiting&&r.waiting){r.waiting.remove();r.waiting=null;}if(r.waiting)r.waiting.lastChild.textContent=message._phaseLabel||'正在结合材料整理回复…';
      if(!r.citationView)r.citationView=new CitationView(r.content,r.citations,this.options);r.citationView.update(message,this.options);
      r.citations.hidden=!r.citations.childNodes.length;
      const errorKey=JSON.stringify([message.status,message.error,lastAssistant]);if(r.errorKey!==errorKey){r.errorKey=errorKey;r.error.replaceChildren();r.error.hidden=redirected||['complete','processing'].includes(message.status);if(!r.error.hidden){r.error.append(el('p','',message.error||'回复未完成，已收到的内容仍保留。'));if(message.id===lastAssistant){const retry=button('重试这条回复',null,'button small');retry.dataset.chatAction='retry';retry.dataset.id=message.id;r.error.append(retry);}}}
      if(!r.time){r.time=el('time','message-time',stamp(message.created_at));if(message.created_at)r.time.dateTime=new Date(message.created_at*1000).toISOString();r.footer.append(r.time);}
      if(!r.copy){r.copy=replyAction('copy','复制回复');r.copy.dataset.chatAction='copy';r.copy.dataset.id=message.id;r.footer.append(r.copy);}
      const toolsKey=JSON.stringify([message.id,message.status,message.reaction,message.versions?.map(v=>v.id),message.version_index]);
      if(r.toolsKey!==toolsKey){r.toolsKey=toolsKey;r.tools?.remove();r.tools=el('div','reply-tools');
        for(const [action,label,pressed]of [['like','这条回答有帮助',message.reaction===1],['dislike','这条回答没有帮助',message.reaction===-1],['branch','从这条回复开启分支',false],['regenerate','重新生成回复',false],['share','分享回复',false]]){const b=replyAction(action,label);b.dataset.chatAction=action;b.dataset.id=message.id;b.disabled=message.status!=='complete';if(['like','dislike'].includes(action))b.setAttribute('aria-pressed',String(pressed));r.tools.append(b);}
        if(message.versions?.length>1){const index=message.version_index??message.versions.findIndex(v=>v.id===message.id),pager=el('span','reply-versions');for(const [step,label]of [[-1,'‹'],[1,'›']]){const b=replyAction(step<0?'previous':'next',step<0?'上一版回复':'下一版回复');b.dataset.chatAction='version';b.dataset.id=message.id;b.dataset.index=index+step;b.setAttribute('aria-label',step<0?'上一版回复':'下一版回复');b.disabled=active||index+step<0||index+step>=message.versions.length;pager.append(b);if(step===-1)pager.append(el('span','',`${index+1} / ${message.versions.length}`));}r.tools.append(pager);}
        r.footer.append(r.tools);
      }
      if(!r.save){r.saveFeedback=el('span','gu-save-feedback');r.saveFeedback.setAttribute('role','status');r.save=button('保存互动进度',async()=>{if(!r.renderer)return;r.save.disabled=true;r.saveFeedback.textContent='';try{await this.options.save(message.id,r.renderer.snapshots());r.renderer.markSaved();r.save.textContent='进度已保存';r.saveFeedback.textContent='';}catch(error){r.saveFeedback.textContent=error.message||'暂未保存，请重试。';}finally{r.save.disabled=false;}},'button small plain');r.footer.append(r.save,r.saveFeedback);}
      r.save.hidden=!(feature.enabled&&message.genui&&r.parts?.some(p=>p.kind==='ui'&&Object.values(p.spec.nodes).some(n=>n.props?.bind||['Table','Tabs','Accordion','Carousel','Form','Markdown','Plot'].includes(n.type)||n.type.endsWith('Chart'))));r.save.disabled=message.status==='processing';
      r.footer.hidden=!(message.genui?.raw||message.content||message.versions?.length>1);
      if(feature.debug&&message.genui){if(!r.debug){r.debug=el('details','gu-raw-debug');r.debug.append(el('summary','','查看原始回复'),el('pre'));r.article.append(r.debug);}r.debug.lastChild.textContent=message.genui.raw;}
      return r.article;
    });
    for(const [id,r]of this.records)if(!messages.some(m=>m.id===id)){r.renderer?.dispose();r.work?.dispose();r.citationView?.dispose();this.records.delete(id);}
    replaceInOrder(this.container,children);
  }
}
