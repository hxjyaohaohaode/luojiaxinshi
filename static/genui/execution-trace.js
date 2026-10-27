import {el,button,replaceInOrder} from './dom.js';

const statusText={running:'进行中',complete:'已完成',interrupted:'未完成',failed:'未完成',cancelled:'已停止'};
const stageText={planning:'确认范围',retrieving:'查阅资料',searching:'公开检索',coverage:'覆盖检查',writing:'生成回复',verifying:'独立核验',agent_tool:'工具',subagent:'子任务'};
const finite=value=>typeof value==='number'&&Number.isFinite(value);
export function traceRecords(message,now=Date.now()/1000){
  return (message._work||message.grounding?.steps||[]).map((step,index)=>{
    const start=finite(step.started_at)?step.started_at:null,end=finite(step.finished_at)?step.finished_at:step.state==='running'?now:null;
    return {id:step.id||'step-'+index,order:index+1,stage:step.stage,title:step.title||'执行记录',state:step.state||'interrupted',summary:step.summary||'',detail:step.detail||'',start,end,
      duration:start!==null&&end!==null&&end>=start?end-start:null,lane:step.stage==='agent_tool'||step.stage==='subagent'?'tools':step.stage==='verifying'?'check':'work'};
  });
}
export function traceDuration(seconds){if(!finite(seconds))return '未记录';const n=Math.max(0,seconds);return n<60?`${Number(n.toFixed(1))}秒`:`${Math.floor(n/60)}分${Math.floor(n%60)}秒`;}
const clock=seconds=>seconds===null?'未记录':new Date(seconds*1000).toLocaleTimeString('zh-CN',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});

// Factual receipts and timing only. No prompt bodies, private reasoning or raw
// tool arguments are fetched or inferred to fill this view.
export class ExecutionTraceView{
  constructor(){
    this.root=el('section','execution-trace');this.root.setAttribute('aria-label','本轮执行轨迹');this.mode='steps';this.query='';this.selected=null;this.buttons=new Map();
    const toolbar=el('div','trace-toolbar');this.heading=el('strong');const modes=el('div','trace-modes');modes.setAttribute('role','group');modes.setAttribute('aria-label','轨迹视图');
    for(const [mode,label]of [['steps','步骤'],['time','耗时']]){const control=button(label,()=>{this.mode=mode;this.paint();},'trace-mode');control.dataset.traceMode=mode;this.buttons.set(mode,control);modes.append(control);}
    this.search=el('input','trace-search');this.search.type='search';this.search.placeholder='搜索执行记录';this.search.setAttribute('aria-label','搜索执行记录');this.search.addEventListener('input',()=>{this.query=this.search.value;this.paint();});toolbar.append(this.heading,modes,this.search);
    this.overview=el('div','trace-overview');this.overview.setAttribute('aria-label','实际执行时间线');
    this.layout=el('div','trace-layout');this.list=el('ol','trace-list');this.detail=el('section','trace-detail');this.detail.hidden=true;this.detail.setAttribute('aria-label','执行详情');this.layout.append(this.list,this.detail);
    this.empty=el('p','trace-empty','没有匹配的执行记录');this.empty.setAttribute('role','status');this.models=el('details','trace-models');this.root.append(toolbar,this.overview,this.layout,this.empty,this.models);
    this.list.addEventListener('keydown',event=>{if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;const controls=[...this.list.querySelectorAll('button')],index=controls.indexOf(event.target);if(index<0)return;event.preventDefault();controls[event.key==='Home'?0:event.key==='End'?controls.length-1:Math.max(0,Math.min(controls.length-1,index+(event.key==='ArrowDown'?1:-1)))]?.focus({preventScroll:true});});
  }
  update(message){this.records=traceRecords(message);this.calls=message.grounding?.harness?.calls||[];this.heading.textContent=`执行轨迹 · ${this.records.length} 项`;this.paint();}
  choose(id){this.selected=this.selected===id?null:id;this.paint();}
  paint(){
    if(!this.records)return;
    for(const [mode,control]of this.buttons)control.setAttribute('aria-pressed',String(mode===this.mode));
    const query=this.query.trim().toLocaleLowerCase(),records=this.records.filter(record=>!query||[record.title,record.summary,record.detail,stageText[record.stage],statusText[record.state]].join(' ').toLocaleLowerCase().includes(query));
    this.root.dataset.mode=this.mode;this.empty.hidden=!!records.length;
    const starts=this.records.map(record=>record.start).filter(finite),ends=this.records.map(record=>record.end).filter(finite),start=Math.min(...starts),end=Math.max(...ends),span=Math.max(end-start,1);
    this.overview.replaceChildren();this.overview.hidden=this.mode!=='time'||!starts.length||!ends.length;
    if(!this.overview.hidden)for(const [lane,label]of [['work','处理'],['tools','工具'],['check','核验']]){
      const entries=records.filter(record=>record.lane===lane&&record.start!==null&&record.end!==null);if(!entries.length)continue;
      const row=el('div','trace-track-row'),track=el('div','trace-track');row.append(el('span','trace-track-label',label),track);
      for(const record of entries){const segment=button('',()=>this.choose(record.id),'trace-segment');segment.dataset.state=record.state;segment.dataset.lane=lane;segment.setAttribute('aria-label',record.title+'，'+traceDuration(record.duration)+'，'+(statusText[record.state]||'未完成'));segment.setAttribute('aria-pressed',String(this.selected===record.id));segment.title=segment.getAttribute('aria-label');segment.style.left=Math.max(0,(record.start-start)/span*100)+'%';segment.style.width=Math.max(0,(record.end-record.start)/span*100)+'%';track.append(segment);}this.overview.append(row);
    }
    const nodes=[];this.rows??=new Map();const ids=new Set();
    for(const [index,record]of records.entries()){
      ids.add(record.id);let row=this.rows.get(record.id);
      if(!row){const li=el('li'),control=button('',()=>this.choose(record.id),'trace-record');row={li,control,number:el('span','trace-number'),title:el('span','trace-record-title'),state:el('span','trace-state'),time:el('span','trace-time')};control.append(row.number,row.title,row.state,row.time);li.append(control);this.rows.set(record.id,row);}
      row.control.dataset.state=record.state;row.control.setAttribute('aria-pressed',String(this.selected===record.id));row.control.setAttribute('aria-expanded',String(this.selected===record.id));row.number.textContent=String(record.order).padStart(2,'0');row.title.textContent=record.title;row.state.textContent=statusText[record.state]||'未完成';row.time.textContent=traceDuration(record.duration);nodes.push(row.li);
    }
    for(const id of this.rows.keys())if(!ids.has(id))this.rows.delete(id);replaceInOrder(this.list,nodes);
    const record=records.find(record=>record.id===this.selected);this.detail.hidden=!record;this.layout.classList.toggle('has-selection',!!record);
    const detailKey=JSON.stringify(record);if(detailKey!==this.detailKey){this.detailKey=detailKey;this.detail.replaceChildren();if(record){const head=el('div','trace-detail-head'),close=button('×',()=>{const id=this.selected;this.selected=null;this.paint();this.rows.get(id)?.control.focus({preventScroll:true});},'icon-button');close.setAttribute('aria-label','关闭执行详情');head.append(el('strong','',record.title),close);const facts=el('dl');for(const [label,value]of [['状态',statusText[record.state]||'未完成'],['类型',stageText[record.stage]||'执行'],['开始',clock(record.start)],['结束',record.state==='running'?'进行中':clock(record.end)],['耗时',traceDuration(record.duration)]]){facts.append(el('dt','',label),el('dd','',value));}this.detail.append(head,facts);if(record.summary&&record.summary!==record.title)this.detail.append(el('p','trace-result',record.summary));if(record.detail)this.detail.append(el('p','trace-subtle',record.detail));}}
    const callsKey=JSON.stringify(this.calls);if(this.callsKey!==callsKey){this.callsKey=callsKey;const open=this.models.open;this.models.replaceChildren(el('summary','',`模型耗时 · ${this.calls.length} 次调用`));this.models.hidden=!this.calls.length;const list=el('ul');for(const call of this.calls){const item=el('li');item.append(el('span','',stageText[call.stage]||'模型调用'),el('span','trace-time',traceDuration(call.elapsed_seconds)),el('span','trace-state',statusText[call.status]||'未完成'));list.append(item);}this.models.append(list);this.models.open=open;}
  }
}
