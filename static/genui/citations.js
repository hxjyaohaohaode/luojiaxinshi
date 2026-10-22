import {el,button} from './dom.js';
import {safeUrl} from './security.js';
let openView=null;
const kinds={web_page:'已读取网页正文',web_summary:'搜索摘要 · 未读取正文',image:'图片观察 · 请对照原图',material:'资料原文',notice:'通知原文',task:'待办快照',arrangement:'个人日程',memory:'个人记忆',profile:'自填条件',user_input:'用户提供'};
const external=source=>typeof source?.url==='string'&&/^https?:\/\//.test(source.url)?safeUrl(source.url,{hosts:null}):null;
export function readableSnapshot(text,kind){
  if(!['task','arrangement','profile','memory'].includes(kind))return text;
  let record;try{record=JSON.parse(text);}catch{return /^\s*[\[{]/.test(text)?'当时保存的记录摘要不可用，请打开对应记录。':text;}
  if(!record||typeof record!=='object'||Array.isArray(record))return '当时保存的记录摘要不可用，请打开对应记录。';
  if(kind==='memory'&&!record.values&&!record.record_type&&!record.data)return text;
  const values=record.values||record.data||record;
  const labels={title:'事项',details:'说明',due_date:'正式期限',due_time:'截止时刻',start_date:'日期',end_date:'结束日期',start_time:'开始',end_time:'结束',location:'地点',submission:'提交至',materials:'材料',next_step:'下一步',status:'状态',college:'学院',grade:'年级',semester:'学期',content:'内容',notes:'备注'};
  const states={pending:'待完成',done:'已完成',cancelled:'已取消',preparing:'准备中',submitted:'已提交',blocked:'办理受阻'};
  const parts=[];
  for(const [key,label] of Object.entries(labels)){let value=values[key]??record[key];if(value==null||value===''||Array.isArray(value)&&!value.length)continue;if(typeof value==='object'&&!Array.isArray(value))continue;value=Array.isArray(value)?value.filter(v=>typeof v==='string'||typeof v==='number').join('、'):states[value]||String(value);if(value)parts.push(`${label}：${value}`);}
  if(values.deadline_confirmed===false)parts.push('期限待核实');
  const workflow=record.workflow?.data||record.workflow;
  if(workflow&&typeof workflow==='object')for(const [key,label] of Object.entries({stage:'办理进度',outcome:'办理结果',receipt:'回执',next_step:'下一步'}))if(typeof workflow[key]==='string'&&workflow[key])parts.push(`${label}：${states[workflow[key]]||({accepted:'已核实受理',rejected:'未通过',supplement:'待补件'}[workflow[key]])||workflow[key]}`);
  return parts.join(' · ')||'此记录没有可展示的内容，请打开对应记录。';
}

export function citationTarget(source){
  const url=external(source);if(url)return {href:url,external:true};
  const id=String(source?.id||''),kind=source?.evidence_kind;
  const record=id.match(/^(?:task|arra|memo|memory)-([a-zA-Z0-9_-]{1,100})$/)?.[1];
  if(record&&kind==='task')return {href:'#tasks/'+record};
  if(record&&kind==='arrangement')return {href:'#calendar/'+record};
  if(record&&kind==='memory')return {href:'#memory/'+record};
  if(source?.conversation_id&&/^[a-zA-Z0-9_-]{1,100}$/.test(source.conversation_id)&&/^[a-zA-Z0-9_-]{1,100}$/.test(id))return {href:`#chat/${source.conversation_id}/source/${id}`};
  if(typeof source?.href==='string'&&/^#(?:chat|notice|calendar|tasks|memory)(?:\/[a-zA-Z0-9_-]{1,100})*$/.test(source.href))return {href:source.href};
  return null;
}

export function citationEntries(message,sources=[]){
  const byId=new Map([...(sources||[]),...(message.evidence_sources||[])].map(s=>[s.id,s])),entries=new Map();
  (message.citations||[]).forEach((citation,index)=>{const source=byId.get(citation.source_id)||{id:citation.source_id,name:'原材料已移除（保留当时引文）'};if(!entries.has(source.id))entries.set(source.id,{source,quotes:[]});entries.get(source.id).quotes.push({...citation,number:index+1});});
  for(const source of message.evidence_sources||[])if(external(source)&&!entries.has(source.id))entries.set(source.id,{source,quotes:[]});
  return [...entries.values()];
}

export function citationPreview(entry,focusNumber=null){
  const focused=entry.quotes.find(q=>q.number===focusNumber);
  if(!focused&&entry.source.evidence_kind==='user_input')return '本次提问与已提交的界面选择；展开引用原文可核对当时内容。';
  const bodyQuotes=entry.quotes.filter(quote=>!/^Produced\s+By\s+CMS\b/i.test(quote.quote.trim()));
  const substantial=(bodyQuotes.length?bodyQuotes:entry.quotes).reduce((best,quote)=>!best||quote.quote.length>best.quote.length?quote:best,null);
  return (focused||substantial)?.quote||entry.source.preview||'';
}

export class CitationView{
  constructor(content,footer,options){
    this.content=content;this.footer=footer;this.options=options;this.entries=[];
    this.escape=e=>{if(e.key==='Escape'){this.hidePreview();this.close();}};
    this.scroll=()=>this.hidePreview();document.addEventListener('keydown',this.escape);document.addEventListener('scroll',this.scroll,true);
    this.breakpoint=matchMedia('(max-width:850px)');this.resize=()=>{this.hidePreview();if(this.panel)this.open(this.focusNumber);};this.breakpoint.addEventListener('change',this.resize);this.materials=()=>this.close(false);document.addEventListener('reply-materials-open',this.materials);
  }
  update(message,options){
    this.options=options;this.entries=citationEntries(message,options.sources);this.message=message;
    const key=JSON.stringify(this.entries);if(key===this.key){this.decorate();return;}this.key=key;this.footer.replaceChildren();
    if(this.entries.length){
      const web=this.entries.filter(e=>external(e.source)),pill=button('',()=>this.open(),'source-pill');pill.setAttribute('aria-label','查看全部回复来源');pill.setAttribute('aria-expanded','false');
      const marks=el('span','source-site-marks');marks.setAttribute('aria-hidden','true');for(const entry of this.entries.slice(0,3))marks.append(el('span','',this.initial(entry.source)));
      const privateCount=this.entries.length-web.length;pill.append(marks,el('span','',web.length?`${web.length} 个网页${privateCount?' · '+privateCount+' 项资料':''}`:`${this.entries.length} 项依据`),el('span','source-pill-arrow','›'));this.footer.append(pill);this.pill=pill;
    }
    if(this.panel)this.close();this.decorate();
  }
  initial(source){return source.evidence_kind==='user_input'?'你':source.evidence_kind==='profile'?'我':external(source)?(source.site_name||source.name||'网').replace(/\s/g,'').slice(0,1):'文';}
  decorate(){
    if(!this.message?.citations?.length)return;
    const walker=document.createTreeWalker(this.content,NodeFilter.SHOW_TEXT),nodes=[];let n;
    while((n=walker.nextNode()))if(/\[\d+\]/.test(n.textContent)&&!n.parentElement.closest('button,a,pre,code,textarea,svg,select,.gu-chart,.gu-plot'))nodes.push(n);
    for(const node of nodes){const fragment=document.createDocumentFragment();let end=0;for(const match of node.textContent.matchAll(/\[(\d+)\]/g)){const number=Number(match[1]),citation=this.message.citations[number-1];if(!citation)continue;
      fragment.append(document.createTextNode(node.textContent.slice(end,match.index)));const b=button(String(number),()=>{this.hidePreview();this.open(number);},'citation-mark');b.dataset.citation=String(number);b.setAttribute('aria-label',`查看依据 ${number}`);b.setAttribute('aria-haspopup','dialog');b.addEventListener('mouseenter',()=>{if(matchMedia('(hover:hover)').matches)this.showPreview(b,number);});b.addEventListener('focus',()=>this.showPreview(b,number));b.addEventListener('mouseleave',()=>this.deferHide());b.addEventListener('blur',()=>this.deferHide());fragment.append(b);end=match.index+match[0].length;
    }if(end){fragment.append(document.createTextNode(node.textContent.slice(end)));node.replaceWith(fragment);}}
  }
  card(entry,focusNumber=null,compact=false){
    const {source,quotes}=entry,article=el('article','source-result'),meta=el('div','source-result-meta');
    const url=external(source);meta.append(el('span','source-site-icon',this.initial(source)),el('span','source-site-name',source.site_name||(url?new URL(url).hostname:kinds[source.evidence_kind]||'原材料')));
    if(source.published_at)meta.append(el('time','',source.published_at.slice(0,10).replaceAll('-','/')));
    const nums=el('span','source-result-numbers');for(const quote of quotes)nums.append(el('span','',String(quote.number)));meta.append(nums);article.append(meta);
    const local=this.options.sources?.some(s=>s.id===source.id),target=citationTarget(source);
    const title=el(local?'button':target?'a':'strong','source-result-title',source.name);
    if(local){title.type='button';title.addEventListener('click',()=>{this.close(false);this.options.preview(source.id);});}
    else if(target){title.href=target.href;if(target.external){title.target='_blank';title.rel='noopener noreferrer';}else title.addEventListener('click',()=>this.close(false));}
    article.append(title);
    const preview=readableSnapshot(citationPreview(entry,focusNumber),source.evidence_kind);if(preview)article.append(el('p','source-result-preview',compact?preview.slice(0,220):preview));
    if(!compact){
      article.append(el('p','source-result-kind',kinds[source.evidence_kind]||'原材料'));
      if(quotes.length){const detail=el('details','source-quote-details');detail.open=quotes.some(q=>q.number===focusNumber);const snapshot=['task','arrangement','profile','memory'].includes(source.evidence_kind);detail.append(el('summary','',`${source.evidence_kind==='image'?'查看图片依据说明':snapshot?'查看当时记录':'查看引用原文'} · ${quotes.length} 处`));for(const quote of quotes){const block=el('blockquote','source-quote');block.dataset.citationNumber=String(quote.number);if(quote.number===focusNumber)block.classList.add('selected');block.append(el('span','source-quote-label',`[${quote.number}] ${snapshot?'保存时的记录':quote.locator}`),document.createTextNode(readableSnapshot(quote.quote,source.evidence_kind)));detail.append(block);}article.append(detail);}
      if(source.retrieved_at)article.append(el('p','source-result-kind','检索于 '+new Date(source.retrieved_at).toLocaleString('zh-CN')));
      if(this.options.sources?.some(s=>s.id===source.id))article.append(button('查看完整材料',()=>this.options.preview(source.id),'button small plain'));
      else if(target&&!target.external){const link=el('a','button small plain','打开对应记录');link.href=target.href;link.addEventListener('click',()=>this.close(false));article.append(link);}
    }
    return article;
  }
  showPreview(anchor,number){
    if(matchMedia('(max-width:850px)').matches)return;
    const entry=this.entries.find(e=>e.quotes.some(q=>q.number===number));if(!entry)return;
    this.hidePreview();const pop=el('div','source-popover');pop.setAttribute('role','tooltip');pop.id='citation-preview-'+this.message.id+'-'+number;pop.append(this.card(entry,number,true));document.body.append(pop);this.preview=pop;this.anchor=anchor;anchor.setAttribute('aria-describedby',pop.id);
    const r=anchor.getBoundingClientRect(),w=pop.offsetWidth,h=pop.offsetHeight;pop.style.left=Math.max(12,Math.min(innerWidth-w-12,r.left-w/2+r.width/2))+'px';pop.style.top=(r.top>h+16?r.top-h-10:Math.min(innerHeight-h-12,r.bottom+10))+'px';
    pop.addEventListener('mouseenter',()=>clearTimeout(this.hideTimer));pop.addEventListener('mouseleave',()=>this.deferHide());pop.addEventListener('focusin',()=>clearTimeout(this.hideTimer));pop.addEventListener('focusout',()=>this.deferHide());
  }
  deferHide(){clearTimeout(this.hideTimer);this.hideTimer=setTimeout(()=>this.hidePreview(),180);}
  hidePreview(){clearTimeout(this.hideTimer);this.preview?.remove();this.preview=null;this.anchor?.removeAttribute('aria-describedby');this.anchor=null;}
  open(number=null){
    this.hidePreview();const returnFocus=this.panel?this.returnFocus:document.activeElement;if(openView&&openView!==this)openView.close();if(this.panel)this.close(false);
    const reader=this.content.closest('#chat-thread'),anchor=returnFocus?.matches?.('.citation-mark')&&this.content.contains(returnFocus)?returnFocus:number?this.content.querySelector(`[data-citation="${number}"]`):null,anchorTop=anchor?.getBoundingClientRect().top;
    openView=this;this.returnFocus=returnFocus;this.focusNumber=number;const mobile=matchMedia('(max-width:850px)').matches;
    const panel=el(mobile?'dialog':'aside','reply-sources-panel');this.panel=panel;panel.setAttribute('aria-label','回答来源');if(!mobile){panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','false');}
    const header=el('header'),title=el('h2','','回答来源'),close=button('×',()=>this.close(),'icon-button');close.setAttribute('aria-label','关闭回答来源');header.append(title,close);panel.append(header);
    const list=el('div','reply-source-results');for(const entry of this.entries)list.append(this.card(entry,number));panel.append(list);
    if(mobile){document.body.append(panel);panel.addEventListener('cancel',()=>this.close());panel.addEventListener('click',event=>{if(event.target===panel){const r=panel.getBoundingClientRect();if(event.clientY<r.top||event.clientX<r.left||event.clientX>r.right)this.close();}});panel.showModal();}
    else{const workspace=document.querySelector('#chat-workspace');document.dispatchEvent(new CustomEvent('reply-sources-open'));if(workspace){workspace.classList.add('show-evidence');workspace.append(panel);}else{panel.classList.add('standalone');document.body.classList.add('gu-show-sources');document.body.append(panel);}}
    this.pill?.setAttribute('aria-expanded','true');close.focus({preventScroll:true});
    if(!mobile&&reader&&anchorTop!==undefined)requestAnimationFrame(()=>requestAnimationFrame(()=>{if(this.panel&&anchor.isConnected)reader.scrollTop+=anchor.getBoundingClientRect().top-anchorTop;}));
    if(number)requestAnimationFrame(()=>list.querySelector(`[data-citation-number="${number}"]`)?.scrollIntoView({block:'nearest'}));
  }
  close(restore=true){if(!this.panel)return;const anchor=this.returnFocus,reader=this.content.closest('#chat-thread'),top=anchor?.getBoundingClientRect().top;if(this.panel.tagName==='DIALOG'&&this.panel.open)this.panel.close();this.panel.remove();this.panel=null;document.querySelector('#chat-workspace')?.classList.remove('show-evidence');document.body.classList.remove('gu-show-sources');this.pill?.setAttribute('aria-expanded','false');if(openView===this)openView=null;if(restore&&anchor?.isConnected){anchor.focus({preventScroll:true});if(reader&&top!==undefined)requestAnimationFrame(()=>requestAnimationFrame(()=>{if(!this.panel&&anchor.isConnected)reader.scrollTop+=anchor.getBoundingClientRect().top-top;}));}}
  dispose(){this.hidePreview();this.close(false);document.removeEventListener('keydown',this.escape);document.removeEventListener('scroll',this.scroll,true);this.breakpoint.removeEventListener('change',this.resize);document.removeEventListener('reply-materials-open',this.materials);}
}
