import {el} from './dom.js';
import {safeUrl} from './security.js';

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
  constructor(parent,before){
    this.root=el('details','work-summary');this.head=el('summary');this.dot=el('span','work-indicator');this.dot.setAttribute('aria-hidden','true');
    this.title=el('span','work-title');this.time=el('span','work-time');this.chevron=el('span','work-chevron','⌄');this.chevron.setAttribute('aria-hidden','true');
    this.head.append(this.dot,this.title,this.time,this.chevron);this.body=el('div','work-body');this.root.append(this.head,this.body);parent.insertBefore(this.root,before);
    this.root.addEventListener('toggle',()=>{if(this.root.open)this.renderDetails();});
  }
  update(message){
    this.message=message;
    const steps=message._work||message.grounding?.steps||[],report=message.grounding||{},running=message.status==='processing';
    this.root.hidden=!steps.length&&!report.status;
    if(this.running&&!running)this.root.open=false;
    this.root.dataset.state=running?'running':message.status==='complete'?'complete':'interrupted';
    this.start=report.started_at||steps[0]?.started_at;this.end=report.checked_at||report.finished_at||steps.at(-1)?.finished_at;
    this.title.textContent=workHeadline(message);
    const clock=()=>{this.time.textContent=this.start?elapsedLabel(this.start,this.running?null:this.end):'';};
    if(this.running!==running){clearInterval(this.timer);this.running=running;if(running)this.timer=setInterval(clock,1000);}
    clock();
    if(this.root.open)this.renderDetails();
  }
  renderDetails(){
    if(!this.message)return;
    const message=this.message,report=message.grounding||{},steps=message._work||report.steps||[],receipt=report.work_summary;
    const key=JSON.stringify([steps,receipt,report.harness?.call_count,message.evidence_sources]);if(key===this.key)return;this.key=key;
    this.body.replaceChildren();
    if(receipt){
      if(receipt.highlights?.length){const highlights=el('ul','work-highlights');for(const text of receipt.highlights)highlights.append(el('li','',text));this.body.append(highlights);}
      const outcomes=el('ul','work-outcomes');
      for(const text of receipt.outcomes||[])outcomes.append(el('li','',text));
      if(outcomes.childNodes.length)this.body.append(outcomes);
      if(receipt.gaps?.length){const gaps=el('ul','work-gaps');for(const gap of receipt.gaps)gaps.append(el('li','',gap));this.body.append(el('strong','','尚缺的信息'),gaps);}
      const sources=(message.evidence_sources||[]).filter(s=>receipt.cited_sources?.includes(s.id));
      if(sources.length){const names=el('ul','work-source-list');for(const source of sources){const li=el('li'),url=source.url&&safeUrl(source.url,{hosts:null});if(url){const link=el('a','',source.name);link.href=url;link.target='_blank';link.rel='noopener noreferrer';li.append(link);}else li.textContent=source.name;names.append(li);}this.body.append(el('strong','','实际引用'),names);}
    }
    const detail=el('details','work-audit');detail.append(el('summary','',`执行记录 · ${steps.length} 项`));
    const list=el('ol','work-steps');
    for(const step of steps){
      const item=el('li','work-step');item.dataset.state=step.state;
      const head=el('div','work-step-heading');head.append(el('strong','',step.title),el('span','work-step-state',step.state==='running'?'进行中':step.state==='complete'?'结束':'未完成'));
      item.append(head);
      if(step.summary&&step.summary!==step.title)item.append(el('p','',step.summary));
      if(step.detail)item.append(el('p','work-subtle',step.detail));
      list.append(item);
    }
    if(receipt){detail.append(list);this.body.append(detail);}else this.body.append(list);
    const calls=report.harness?.call_count;if(calls)this.body.append(el('p','work-subtle',`模型调用 ${calls} 次`));
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
