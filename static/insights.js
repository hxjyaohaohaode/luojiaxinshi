// 数据看板：个人完成情况、期限分布、来源与相关性；管理员另有全站匿名计数。
import {numberMarkup, ringMarkup} from './experience-system.js';

const RELEVANCE = [
  ['matches_known', '和你有关', '#2f7d54'],
  ['needs_review', '需要确认是否适用', '#b88a3e'],
  ['not_matching', '可能不适用', '#9aa79f'],
  ['unprocessed', '还没整理', '#d6ddd7'],
  ['unknown', '尚未明确', '#b8c1bc'],
];

function percent(part, total) { return total ? Math.round(part / total * 100) : 0; }

function barChart(rows, {label, value, max, caption, stack}) {
  const top = Math.max(1, max ?? Math.max(...rows.map(row => stack ? stack.reduce((sum, key) => sum + row[key], 0) : row[value])));
  return `<div class="insight-bars" role="img" aria-label="${caption}">${rows.map((row, index) => {
    const parts = stack ? stack.map(key => [key, row[key]]) : [[value, row[value]]];
    const total = parts.reduce((sum, [, n]) => sum + n, 0);
    return `<div class="insight-bar" data-i="${index}"><span class="insight-bar-value">${total || ''}</span><span class="insight-bar-track">${parts.map(([key, n]) => `<i class="seg-${key}" data-height="${(n / top * 100).toFixed(1)}"></i>`).join('')}</span><span class="insight-bar-label">${row[label]}</span></div>`;
  }).join('')}</div>`;
}

function donut(segments, total, caption) {
  let offset = 0;
  const arcs = segments.filter(([, , , n]) => n > 0).map(([key, , color, n]) => {
    const length = n / total * 100, arc = `<circle class="donut-seg" cx="50" cy="50" r="38" pathLength="100" stroke="${color}" stroke-dasharray="${length} ${100 - length}" stroke-dashoffset="${-offset}" data-key="${key}"/>`;
    offset += length; return arc;
  }).join('');
  return `<figure class="insight-donut"><svg viewBox="0 0 100 100" role="img" aria-label="${caption}"><circle cx="50" cy="50" r="38" class="donut-track"/>${arcs}</svg><figcaption><b>${total}</b><span>则通知</span></figcaption></figure>`;
}

export function createInsightsUI({state, api, esc, icon, companion}) {
  const $ = selector => document.querySelector(selector);

  let snapshot=null,requestId=0,refreshTimer=0,renderedSnapshot='';
  const dimensionNames={notices:'通知处理',intake:'接入材料',tasks:'本人事项',timing:'期限与活动',progress:'办理跟进'};
  const colors=['#237b70','#7ba7c9','#c4a25f','#a5afb7','#9b8bb1','#c88b70','#87986b','#b7b9bc'];
  function trendChart(rows){
    const maximum=Math.max(1,...rows.map(row=>row.done));
    const points=rows.map((row,index)=>({row,x:(index+.5)*100/Math.max(1,rows.length),y:88-row.done/maximum*68}));
    const path=points.map((p,index)=>(index?'L':'M')+p.x+','+p.y).join(' ');
    return `<div class="insight-trend-plot" role="group" aria-label="近8周完成趋势"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path class="trend-grid" d="M6 20H94 M6 54H94 M6 88H94"/>${points.length?`<path class="trend-area" d="${path} L94,88 L6,88Z"/><path class="trend-line" d="${path}"/>`:''}</svg>${points.map(({row,x,y})=>`<button type="button" class="insight-trend-point" data-insight-selection="trend:${row.week}" data-left="${x}" data-width="${100/Math.max(1,rows.length)}" aria-label="${row.label}起一周，完成${row.done}项"><i data-top="${y}"></i><span data-top="${y}">${row.done}</span></button>`).join('')}</div><div class="insight-trend-labels">${rows.map(row=>`<span>${row.label}</span>`).join('')}</div>`;
  }
  function horizonChart(rows){
    const maximum=Math.max(1,...rows.map(row=>row.confirmed+row.unconfirmed));
    return `<div class="insight-horizon" role="group" aria-label="未来4周期限分布">${rows.map(row=>`<button type="button" class="insight-horizon-column" data-insight-selection="horizon:${row.week}" aria-label="${row.label}，已确认${row.confirmed}项，待确认${row.unconfirmed}项"><span class="insight-column-total">${row.confirmed+row.unconfirmed}</span><span class="insight-column-track"><i class="horizon-confirmed" data-height="${row.confirmed/maximum*100}"></i><i class="horizon-unconfirmed" data-height="${row.unconfirmed/maximum*100}"></i></span><span>${row.label}</span></button>`).join('')}</div>`;
  }
  function horizontal(rows,group){
    const maximum=Math.max(1,...rows.map(row=>row.count));
    return `<div class="insight-horizontal">${rows.map((row,index)=>`<button type="button" class="insight-horizontal-row" data-insight-selection="${group}:${row.key}"><span>${esc(row.label)}</span><span class="insight-horizontal-track"><i data-width="${row.count/maximum*100}" data-color="${colors[index%colors.length]}"></i></span><b>${row.count}</b></button>`).join('')}</div>`;
  }
  function personal(data) {
    const dimensions=data.dimensions||{},find=(group,key)=>dimensions[group]?.find(row=>row.key===key)||{key,label:'',count:0,ids:[]};
    const top=[['notices','all','全部通知'],['tasks','pending','待完成'],['progress','followup','待跟进'],['timing','overdue','已过期']];
    const taskStates=(dimensions.tasks||[]).filter(row=>row.key!=='all');
    const noticeFlow=(dimensions.notices||[]).filter(row=>row.key!=='all'&&row.count>0);
    const taskTotal=taskStates.reduce((sum,row)=>sum+row.count,0);
    const segments=taskStates.map((row,index)=>[row.key,row.label,colors[index%colors.length],row.count]);
    return `<div class="insight-toolbar"><div><h1>数据看板</h1><p class="small muted">更新于 <time>${esc(new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(data.generated_at)))}（北京时间）</time></p></div><button type="button" class="button" data-insight-refresh>${icon('history')}刷新数据</button></div><p data-insight-status role="status" class="small muted"></p>
    <div class="insight-key-metrics">${top.map(([group,key,label])=>`<button type="button" class="insight-key-metric" data-insight-selection="${group}:${key}"><span>${label}</span><strong>${numberMarkup(find(group,key).count)}</strong>${icon('arrow')}</button>`).join('')}</div>
    <div class="insight-chart-grid">
      <section class="insight-chart"><header><h2>近 8 周完成</h2><span>本人事项</span></header>${trendChart(data.trend)}</section>
      <section class="insight-chart"><header><h2>未来 4 周期限</h2><span class="insight-chart-legend"><i class="horizon-confirmed"></i>已确认 <i class="horizon-unconfirmed"></i>待确认</span></header>${horizonChart(data.horizon)}</section>
      <section class="insight-chart"><header><h2>事项状态</h2><span>${taskTotal} 项</span></header><div class="insight-state-layout">${donut(segments,taskTotal,'本人事项状态分布').replace('则通知','项')}<div class="insight-state-legend">${taskStates.map((row,index)=>`<button type="button" data-insight-selection="task-status:${row.key}"><i data-color="${colors[index%colors.length]}"></i><span>${esc(row.label)}</span><b>${row.count}</b></button>`).join('')}</div></div></section>
      <section class="insight-chart"><header><h2>通知处理</h2><span>${data.notices?.total??find('notices','all').count} 则</span></header>${noticeFlow.length?horizontal(noticeFlow,'notices'):'<p class="insight-chart-empty">暂无通知</p>'}</section>
      <section class="insight-chart compact-chart"><header><h2>材料接入</h2><span>同一通知可含多种材料</span></header>${horizontal(dimensions.intake||[],'intake')}</section>
      <section class="insight-chart compact-chart"><header><h2>时间与办理核对</h2></header><div class="insight-checks">${[...(dimensions.timing||[]).filter(row=>row.key!=='overdue').map(row=>['timing',row]),...(dimensions.progress||[]).filter(row=>row.key!=='followup').map(row=>['progress',row])].map(([group,row],index)=>`<button type="button" data-insight-selection="${group}:${row.key}"><i data-color="${colors[index%colors.length]}"></i><span>${esc(row.label)}</span><b>${row.count}</b></button>`).join('')}</div></section>
    </div>`;
  }

  function site(data) {
    return `<section class="insight-site"><header><h3>全站概况</h3><span class="small muted">管理员可见 · 只有匿名计数，不含任何人的通知内容</span></header>
      <div class="insight-grid">
        <article class="insight-card"><h3>注册账号</h3><p class="insight-number">${numberMarkup(data.users.total)}</p><p class="small muted">近 7 天活跃 ${data.users.active_7d}</p></article>
        <article class="insight-card"><h3>收录通知</h3><p class="insight-number">${numberMarkup(data.notices.total)}</p><p class="small muted">近 30 天 ${data.notices.last_30d} · 已转办 ${data.notices.confirmed}</p></article>
        <article class="insight-card"><h3>待办完成率</h3><p class="insight-number">${percent(data.tasks.done, data.tasks.done + data.tasks.pending)}<small>%</small></p><p class="small muted">${data.tasks.done} 已完成 · ${data.tasks.pending} 进行中</p></article>
        <article class="insight-card"><h3>近 30 天 AI 整理</h3><p class="insight-number">${numberMarkup(data.ai_30d.calls)}</p><p class="small muted">${data.ai_30d.failed ? data.ai_30d.failed + ' 次没成功' : '都顺利完成'}</p></article>
      </div></section>`;
  }

  async function render(renderId=state.renderId) {
    if($('#content')?.dataset.page!=='insights'||renderId!==state.renderId)return;
    const ticket=++requestId,owner=state.session;
    if(!owner?.user)return;
    const button=$('[data-insight-refresh]');if(button)button.setAttribute('aria-busy','true');
    const status=$('[data-insight-status]');if(status)status.textContent='正在更新…';
    try {
      const [mine,all]=await Promise.all([api('/insights'),owner.user.role==='admin'?api('/admin/insights').catch(()=>null):null]);
      if(ticket!==requestId||renderId!==state.renderId||owner!==state.session||$('#content')?.dataset.page!=='insights')return;
      snapshot=mine;
      const signature=JSON.stringify([{...mine,generated_at:null},all?{...all,generated_at:null}:null]);
      if(signature===renderedSnapshot&&$('.insight-page [data-insight-refresh]')&&$('.insight-toolbar time')){
        $('.insight-toolbar time').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(mine.generated_at));
        $('[data-insight-status]').textContent='';return;
      }
      const content=$('#content'),scroll=content.scrollTop,windowY=window.scrollY;
      const focused=document.activeElement?.closest('[data-insight-selection],[data-insight-refresh]');
      const focusKey=focused?.dataset.insightSelection,focusRefresh=focused?.hasAttribute('data-insight-refresh');
      $('#content').innerHTML=`<div class="insight-page">${personal(mine)}${all?site(all):''}</div>`;
      renderedSnapshot=signature;
      const page=$('#content .insight-page');
      page.querySelectorAll('[data-i]').forEach(node=>node.style.setProperty('--i',node.dataset.i));
      page.querySelectorAll('[data-height]').forEach(node=>node.style.height=node.dataset.height+'%');
      page.querySelectorAll('[data-width]').forEach(node=>node.style.width=node.dataset.width+'%');
      page.querySelectorAll('[data-color]').forEach(node=>node.style.background=node.dataset.color);
      page.querySelectorAll('[data-left]').forEach(node=>node.style.left=node.dataset.left+'%');
      page.querySelectorAll('[data-top]').forEach(node=>node.style.top=node.dataset.top+'%');
      const restore=focusKey?page.querySelector('[data-insight-selection="'+CSS.escape(focusKey)+'"]'):focusRefresh?page.querySelector('[data-insight-refresh]'):null;
      restore?.focus({preventScroll:true});content.scrollTop=scroll;window.scrollTo({top:windowY,left:window.scrollX,behavior:'instant'});
    } catch(error) {
      if(ticket!==requestId||renderId!==state.renderId||owner!==state.session||$('#content')?.dataset.page!=='insights')return;
      if(!$('.insight-page'))$('#content').innerHTML='<div class="insight-page"><h1>数据看板</h1><p data-insight-status role="status"></p><button type="button" class="button" data-insight-refresh>重试</button></div>';
      $('[data-insight-status]').textContent='更新失败：'+error.message+'；已显示的数据未改动。';
    } finally {
      if(ticket===requestId&&owner===state.session){const current=$('[data-insight-refresh]');if(current){current.disabled=false;current.removeAttribute('aria-busy');}}
    }
  }
  function refresh(){if(!document.hidden&&$('#content')?.dataset.page==='insights'&&$('.insight-page')){const renderId=state.renderId;clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>{if(renderId===state.renderId&&$('#content')?.dataset.page==='insights')render(renderId);},400);}}
  document.addEventListener('click',event=>{
    if(event.target.closest('[data-insight-refresh]'))render(state.renderId);
    const selection=event.target.closest('[data-insight-selection]');
    if(selection&&snapshot){const [group,key]=selection.dataset.insightSelection.split(':'),row=group==='trend'||group==='horizon'?snapshot[group]?.filter(item=>item.week===key).map(item=>({kind:'tasks',ids:item.ids||[],label:(group==='trend'?'完成记录 · ':'期限分布 · ')+item.label}))[0]:snapshot.dimensions?.[group==='task-status'?'tasks':group]?.find(item=>item.key===key);if(row)document.dispatchEvent(new CustomEvent('campus:insight-selection',{detail:{kind:row.kind,ids:[...row.ids],label:row.label}}));}
  });
  document.addEventListener('campus:data-updated',refresh);
  document.addEventListener('visibilitychange',refresh);
  window.addEventListener('focus',refresh);
  setInterval(refresh,60000);
  return {render,refresh};
}
