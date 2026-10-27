import {el} from './dom.js';
import {safeUrl} from './security.js';
let disclosureId=0;

export function elapsedLabel(start,end){
  const seconds=Math.max(0,Math.floor((end||Date.now()/1000)-(start||end||Date.now()/1000)));
  return seconds>=60?`${Math.floor(seconds/60)}分${seconds%60}秒`:`${seconds}秒`;
}

// Render execution details only when opened. Streaming must not rebuild a hidden log.
export function workHeadline(message){
  const receipt=message.grounding?.work_summary;
  if(message.status==='processing'){
    const steps=message._work||message.grounding?.steps||[];
    return [...steps].reverse().find(s=>s.state==='running')?.title||'正在处理';
  }
  if(message.status!=='complete')return '执行未完成';
  if(!receipt)return '处理记录';
  if(receipt.highlights?.[0])return receipt.highlights[0];
  const facts=[];
  if(receipt.cited_sources?.length)facts.push(`引用 ${receipt.cited_sources.length} 个来源`);
  if(receipt.tool_calls)facts.push(`执行 ${receipt.tool_calls} 次工具`);
  if(receipt.ui_components?.length)facts.push('生成互动内容');
  if(receipt.failed_tools)facts.push(`${receipt.failed_tools} 次工具未成功`);
  return facts.join(' · ')||(receipt.verified?'答复已核验':'处理记录');
}

export class WorkSummaryView{
  constructor(parent,before,{openTrace}={}){
    this.openTrace=openTrace;
    this.root=el('section','work-summary');this.head=el('button','work-summary-toggle');this.head.type='button';this.dot=el('span','work-indicator');this.dot.setAttribute('aria-hidden','true');
    this.title=el('span','work-title');this.time=el('span','work-time');this.chevron=el('span','work-chevron','⌄');this.chevron.setAttribute('aria-hidden','true');
    this.head.append(this.dot,this.title,this.time,this.chevron);this.body=el('div','work-body');this.disclosure=el('div','work-disclosure');this.clip=el('div','work-disclosure-clip');this.clip.append(this.body);this.disclosure.append(this.clip);this.disclosure.id='work-disclosure-'+(++disclosureId);this.head.setAttribute('aria-controls',this.disclosure.id);this.root.append(this.head,this.disclosure);parent.insertBefore(this.root,before);
    this.setExpanded(false);this.head.addEventListener('click',()=>this.setExpanded(!this.expanded));
  }
  setExpanded(open){
    if(open)this.renderDetails();
    this.expanded=open;this.root.dataset.expanded=String(open);this.head.setAttribute('aria-expanded',String(open));this.disclosure.inert=!open;this.disclosure.setAttribute('aria-hidden',String(!open));
  }
  update(message){
    this.message=message;
    const steps=message._work||message.grounding?.steps||[],report=message.grounding||{},running=message.status==='processing';
    this.root.hidden=report.planning_mode==='host_acknowledgement'||!steps.length&&!report.status;
    this.root.dataset.state=running?'running':message.status==='complete'?'complete':'interrupted';
    this.start=report.started_at||steps[0]?.started_at;this.end=report.checked_at||report.finished_at||steps.at(-1)?.finished_at;
    this.title.textContent=workHeadline(message);
    const clock=()=>{this.time.textContent=this.start?elapsedLabel(this.start,this.running?null:this.end):'';};
    if(this.running!==running){clearInterval(this.timer);this.running=running;if(running)this.timer=setInterval(clock,1000);}
    clock();
    if(this.expanded)this.renderDetails();
  }
  renderDetails(){
    if(!this.message)return;
    const message=this.message,report=message.grounding||{},steps=message._work||report.steps||[],receipt=report.work_summary;
    if(!this.summaryBody){this.summaryBody=el('div','work-receipt');this.traceLink=el('button','work-trace-link');this.traceLink.type='button';this.traceLink.addEventListener('click',()=>this.openTrace?.(this.message));this.body.append(this.summaryBody,this.traceLink);}
    const key=JSON.stringify([receipt,message.evidence_sources]);
    if(key!==this.key){this.key=key;this.summaryBody.replaceChildren();
    if(receipt){
      if(receipt.highlights?.length){const highlights=el('ul','work-highlights');for(const text of receipt.highlights)highlights.append(el('li','',text));this.summaryBody.append(highlights);}
      // Per-tool outcomes live in the trace and real operation cards. Repeating
      // every receipt here makes even a short summary taller than the answer.
      if(receipt.gaps?.length){const gaps=el('ul','work-gaps');for(const gap of receipt.gaps)gaps.append(el('li','',gap));this.summaryBody.append(el('strong','','尚缺的信息'),gaps);}
      const sources=(message.evidence_sources||[]).filter(s=>receipt.cited_sources?.includes(s.id));
      if(sources.length){const names=el('ul','work-source-list');for(const source of sources){const li=el('li'),url=source.url&&safeUrl(source.url,{hosts:null});if(url){const link=el('a','',source.name);link.href=url;link.target='_blank';link.rel='noopener noreferrer';li.append(link);}else li.textContent=source.name;names.append(li);}this.summaryBody.append(el('strong','','实际引用'),names);}
    }
    }
    this.traceLink.textContent=`查看执行轨迹 · ${steps.length} 项 ↗`;this.traceLink.hidden=!steps.length||!this.openTrace;
  }
  dispose(){clearInterval(this.timer);this.root.remove();}
}

export function webPreviews(sources){
  const web=(sources||[]).filter(s=>['web_page','web_summary'].includes(s.evidence_kind)&&safeUrl(s.url,{hosts:null}));
  if(!web.length)return null;
  const section=el('section','web-previews');section.setAttribute('aria-label','检索网页预览');
  section.append(el('p','web-previews-label','来源网页'));
  const grid=el('div','web-preview-grid');
  for(const source of web.slice(0,8)){
    const card=el('a','web-preview');card.href=source.url;card.target='_blank';card.rel='noopener noreferrer';
    const meta=el('span','web-preview-meta');meta.append(el('span','',new URL(source.url).hostname),el('span','',source.evidence_kind==='web_page'?'已读取正文':'仅搜索摘要'));
    card.append(meta,el('strong','',source.name),el('p','',source.preview||'打开原网页查看完整内容。'));
    if(source.published_at)card.append(el('span','work-subtle','来源标注日期：'+source.published_at));
    card.append(el('span','web-preview-open','查看来源 ↗'));grid.append(card);
  }
  section.append(grid);return section;
}
