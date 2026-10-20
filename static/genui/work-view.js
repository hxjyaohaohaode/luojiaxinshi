import {el} from './dom.js';
import {safeUrl} from './security.js';

export function elapsedLabel(start,end){
  const seconds=Math.max(0,Math.floor((end||Date.now()/1000)-(start||end||Date.now()/1000)));
  return seconds>=60?`${Math.floor(seconds/60)}分${seconds%60}秒`:`${seconds}秒`;
}

// All copy is server execution metadata. No hidden reasoning or model-generated HTML.
export class WorkSummaryView{
  constructor(parent,before){
    this.root=el('details','work-summary');this.head=el('summary');this.dot=el('span','work-indicator');this.dot.setAttribute('aria-hidden','true');
    this.title=el('span','work-title');this.time=el('span','work-time');this.chevron=el('span','work-chevron','⌄');this.chevron.setAttribute('aria-hidden','true');
    this.head.append(this.dot,this.title,this.time,this.chevron);this.body=el('div','work-body');this.root.append(this.head,this.body);parent.insertBefore(this.root,before);
  }
  update(message){
    const steps=message._work||message.grounding?.steps||[],report=message.grounding||{},running=message.status==='processing';
    this.root.hidden=!steps.length&&!report.status;
    if(this.running===undefined)this.root.open=false;
    if(this.running&&!running)this.root.open=false;
    this.running=running;this.root.dataset.state=running?'running':message.status==='complete'?'complete':'interrupted';
    this.start=report.started_at||steps[0]?.started_at;this.end=report.checked_at||report.finished_at||steps.at(-1)?.finished_at;
    this.title.textContent=running?(steps.at(-1)?.title||'正在处理'):message.status==='complete'?'工作摘要':message.error?.includes('按更新后的问题继续')?'工作已转向':'工作记录 · 未完成';
    const clock=()=>{this.time.textContent=(this.start?elapsedLabel(this.start,running?null:this.end):'');};clock();
    clearInterval(this.timer);if(running)this.timer=setInterval(clock,1000);
    const key=JSON.stringify([steps,report,message.evidence_sources]);if(key===this.key)return;this.key=key;this.body.replaceChildren();
    const list=el('ol','work-steps');
    for(const step of steps){
      const item=el('li','work-step');item.dataset.state=step.state;
      const scoped=step.stage==='retrieving'&&report.retrieval?.local_scope==='message';
      const head=el('div','work-step-heading'),state=el('span','work-step-state',step.state==='running'?'进行中':step.state==='complete'?'已结束':'已中断');
      const summary=scoped?'核对限定消息中的材料与后续补充。':step.summary;
      head.append(el('strong','',scoped?'核对限定消息材料':step.title),state);item.append(head,el('p','',step.state==='running'?summary:summary.replace(/^正在/,'').replace(/…+$/,'')));
      if(step.tools?.length){const tools=el('div','work-tools');for(const name of scoped?['限定材料核对']:step.tools)tools.append(el('span','',name));item.append(tools);}
      list.append(item);
    }
    if(steps.length)this.body.append(list);
    if(report.retrieval){
      const counts=report.retrieval.scanned||{},scope=el('div','work-evidence');
      scope.append(el('p','',report.retrieval.local_scope==='message'?`本轮只核对限定消息中的材料与补充，选取 ${report.retrieval.selected_sources||0} 个来源。`:`检索范围：${counts.materials||0} 份资料、${counts.notices||0} 份通知、${counts.tasks||0} 项待办、${counts.arrangements||0} 项日程；选取 ${report.retrieval.selected_sources||0} 个本地来源。`));
      const web=report.web||{};scope.append(el('p','',web.status==='searched'?`联网取得 ${web.source_count||0} 个来源，读取 ${web.pages_read||0} 个网页正文。`:web.status==='not_needed'?'本轮未联网：'+web.reason:'本轮联网未取得可核验结果。'));
      if(web.queries?.length)scope.append(el('p','work-subtle','公开检索词：'+web.queries.join('；')));
      if(web.followup?.status==='unavailable')scope.append(el('p','work-subtle','补充联网未取得结果，相关缺口仍需核实。'));
      if(report.retrieval.context_limited||web.coverage?.context_limited)scope.append(el('p','work-subtle','按相关性选取段落，存在内容上限，未将全部资料逐字发送给模型。'));
      const audit=el('details','work-audit');audit.open=!!this.auditExpanded;audit.append(el('summary','','查看覆盖与核验明细'));audit.addEventListener('toggle',()=>this.auditExpanded=audit.open);
      if(report.coverage_check?.items?.length){const check=el('ul','work-coverage');for(const item of report.coverage_check.items){check.append(el('li','',`${item.requirement}：${{supported:'有相关证据',partial:'部分覆盖',missing:'证据不足'}[item.status]||'待检查'}${item.gap?'；'+item.gap:''}`));}audit.append(check);}
      if(report.coverage_check?.personal_fit)audit.append(el('p','work-subtle','个人条件检查：'+report.coverage_check.personal_fit));
      for(const conflict of report.coverage_check?.conflicts||[])audit.append(el('p','work-subtle','差异：'+conflict));
      if(audit.childNodes.length>1)scope.append(audit);
      const names=el('ul','work-source-list');for(const source of (message.evidence_sources||[]).filter(s=>!['user_input','profile'].includes(s.evidence_kind))){const li=el('li'),url=source.url&&safeUrl(source.url,{hosts:null});if(url){const link=el('a','',source.name);link.href=url;link.target='_blank';link.rel='noopener noreferrer';li.append(link);}else li.textContent=source.name;names.append(li);}if(names.childNodes.length)scope.append(el('p','work-subtle','本轮选取的来源'),names);
      scope.append(el('p','work-subtle',report.status==='checked'?'已检查引文并独立复核正文与互动内容。检索和模型复核不能保证零错误，重要期限与资格请核对原发布方。':'回答尚未通过完整核验。'));
      this.body.append(scope);
    }
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
