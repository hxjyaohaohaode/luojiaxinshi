import {numberMarkup,animateSurface} from './experience-system.js';
export const RELEVANCE={matches_known:['和你有关','green'],needs_review:['需确认是否适用','orange'],not_matching:['可能不适用','']};
export function filterNotices(items,{query='',status='all',from='',to='',relevance='all'}={}){
  const q=query.trim().toLocaleLowerCase();
  const day=n=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n*1000));
  return items.filter(n=>(status==='all'||n.status===status)&&(relevance==='all'||(relevance==='unknown'?!n.applicability:n.applicability===relevance))&&(!q||(n.title+' '+n.source_label).toLocaleLowerCase().includes(q))&&(!from||day(n.created_at)>=from)&&(!to||day(n.created_at)<=to));
}

export function createLibraryUI({state,esc,icon,noticeRow,empty,moveSelection}){
  let owner=null,query='',status='all',from='',to='',relevance='all',page=1,view='cards';
  const $=s=>document.querySelector(s);
  const button=(label,value,disabled=false)=>`<button type="button" class="button small" data-library-page="${value}" ${disabled?'disabled':''}>${label}</button>`;
  function noticeCard(notice) {
    const [label,color]=({received:['待整理',''],draft:['待确认','orange'],confirmed:['已转办','green'],failed:['处理失败','red'],processing:['处理中','blue']})[notice.status]||['待整理',''];
    const date=new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(notice.created_at*1000));
    return `<article class="notice-card notice-row" data-state="${esc(notice.status)}"><div class="notice-card-top"><span class="notice-folder" aria-hidden="true">${icon('doc')}</span><span class="notice-card-pills">${notice.applicability&&RELEVANCE[notice.applicability]?`<span class="pill ${RELEVANCE[notice.applicability][1]}">${RELEVANCE[notice.applicability][0]}</span>`:''}<span class="pill ${color}">${label}</span></span></div><div class="notice-card-content"><button class="link-button" data-action="open-notice" data-id="${esc(notice.id)}">${esc(notice.title)}</button><p>${esc(notice.source_label||'个人提交')}</p></div><div class="notice-card-footer"><span>${date} 收件</span><span>${notice.task_count||0} 项待办</span><a href="#notice/${encodeURIComponent(notice.id)}" aria-label="打开通知 ${esc(notice.title)}">${icon('arrow')}</a></div></article>`;
  }
  function render(){
    if(owner!==state.session.user.id){owner=state.session.user.id;query='';status='all';from='';to='';relevance='all';page=1;view='cards';}
    if(!$('#library-results'))$('#content').innerHTML=`<div class="page-title between"><div><h1>通知资料</h1></div><a href="#new" class="button primary">${icon('plus')} 提交通知</a></div><div class="library-toolbar"><label class="library-search">${icon('search')}<input id="library-search" type="search" placeholder="搜索全部通知标题或来源" aria-label="搜索通知资料" value="${esc(query)}"></label><details class="library-date"><summary>${icon('calendar')} 收件日期 ${from||to?'<span class="dot"></span>':''}</summary><div><label class="field">从<input id="library-from" type="date" value="${from}"></label><label class="field">到<input id="library-to" type="date" value="${to}"></label></div></details></div><div class="library-tabs-row"><div class="tabs" role="tablist" aria-label="通知状态">${[['all','全部'],['received','待整理'],['draft','待确认'],['confirmed','已转办'],['failed','处理失败'],['processing','处理中']].map(([v,l])=>`<button role="tab" type="button" class="tab" data-library-status="${v}">${l}</button>`).join('')}</div><span id="library-count" class="small muted"></span></div><div class="relevance-chips" role="group" aria-label="按与我的关系筛选">${[['all','全部'],['matches_known','和我有关'],['needs_review','需确认是否适用'],['not_matching','可能不适用']].map(([v,l])=>`<button type="button" class="chip" data-library-relevance="${v}" aria-pressed="false">${l}<b data-relevance-count="${v}"></b></button>`).join('')}</div><div id="library-filter-note" class="small muted" role="status"></div><div id="library-results" class="panel flush library-results" role="tabpanel" aria-label="通知结果"></div><div id="library-pages" class="pagination"></div>`;
    if(!$('#library-summary'))$('.library-toolbar').insertAdjacentHTML('beforebegin','<section class="collection-summary" id="library-summary" aria-label="通知收件概览"></section>');
    if(!$('.library-view-toggle'))$('.library-toolbar').insertAdjacentHTML('beforeend',`<div class="view-toggle library-view-toggle" role="group" aria-label="通知展示方式"><button type="button" data-library-view="cards" aria-label="卡片视图">${icon('grid')}<span>卡片</span></button><button type="button" data-library-view="list" aria-label="列表视图">${icon('menu')}<span>列表</span></button></div>`);
    const confirmed=state.notices.filter(n=>n.status==='confirmed').length;
    $('#library-summary').innerHTML=`<div class="collection-stat"><strong>${numberMarkup(state.notices.length)}</strong><span>全部通知</span></div><div class="collection-stat"><strong>${numberMarkup(state.notices.length-confirmed)}</strong><span>尚待核对</span></div><div class="collection-stat"><strong>${numberMarkup(confirmed)}</strong><span>已转为行动</span></div>`;
    update();
  }
  function update(){
    if(!$('#library-results'))return;
    const items=filterNotices(state.notices,{query,status,from,to,relevance}),pages=Math.max(1,Math.ceil(items.length/15));page=Math.max(1,Math.min(page,pages));
    document.querySelectorAll('[data-library-status]').forEach(b=>{const active=b.dataset.libraryStatus===status;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});moveSelection($('.tabs'));
    $('#library-count').textContent=`${items.length} / ${state.notices.length} 则`;
    document.querySelectorAll('[data-library-relevance]').forEach(b=>{const value=b.dataset.libraryRelevance;b.setAttribute('aria-pressed',String(value===relevance));const count=value==='all'?state.notices.length:state.notices.filter(n=>n.applicability===value).length;b.querySelector('b').textContent=count;b.hidden=value!=='all'&&!count&&value!==relevance;});
    $('#library-filter-note').innerHTML=query||status!=='all'||relevance!=='all'||from||to?`<span>${from&&to&&from>to?'开始日期晚于结束日期，请调整范围。':'已按当前条件筛选全部通知。'}</span>${items.length?'<button class="link-button" type="button" data-library-reset>清空筛选</button>':''}`:'';
    const hasFilter=!!(query.trim()||status!=='all'||relevance!=='all'||from||to),emptyKey=items.length?'':hasFilter||state.notices.length?'search':'listening',results=$('#library-results');
    results.classList.toggle('card-view',view==='cards'&&items.length>0);
    document.querySelectorAll('[data-library-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.libraryView===view)));
    if(!emptyKey||results.dataset.emptyKey!==emptyKey)results.innerHTML=items.length?items.slice((page-1)*15,page*15).map(view==='cards'?noticeCard:noticeRow).join(''):empty(hasFilter||state.notices.length?'暂时没有匹配的通知':'先收好第一则通知',hasFilter||state.notices.length?'试试标题中的另一个词，或清空筛选。':'正文、附件和截图可以一起保存，之后随时回来核对。',hasFilter||state.notices.length?'<button class="button small" type="button" data-library-reset>清空筛选</button>':'<a class="button" href="#new">提交第一则通知</a>',false,hasFilter||state.notices.length?'search':'listening');
    results.dataset.emptyKey=emptyKey;
    $('#library-pages').innerHTML=pages>1?`${button('上一页',page-1,page===1)}<span>第 ${page} / ${pages} 页 · 每页 15 则</span>${button('下一页',page+1,page===pages)}`:'';
  }
  document.addEventListener('input',e=>{if(e.target.id==='library-search'){query=e.target.value;page=1;update();}});
  document.addEventListener('change',e=>{if(['library-from','library-to'].includes(e.target.id)){from=$('#library-from').value;to=$('#library-to').value;page=1;update();}});
  document.addEventListener('click',e=>{
    const display=e.target.closest('[data-library-view]');
    if(display){view=display.dataset.libraryView;update();animateSurface($('#library-results'),0);}
    const tab=e.target.closest('[data-library-status]'),pagination=e.target.closest('[data-library-page]');
    if(tab){status=tab.dataset.libraryStatus;page=1;update();}
    const chip=e.target.closest('[data-library-relevance]');
    if(chip){relevance=chip.dataset.libraryRelevance;page=1;update();}
    if(pagination&&!pagination.disabled){page=Number(pagination.dataset.libraryPage);update();$('#library-results').scrollIntoView({block:'nearest'});}
    if(e.target.closest('[data-library-reset]')){query='';status='all';from='';to='';relevance='all';page=1;$('#library-search').value='';$('#library-from').value='';$('#library-to').value='';update();$('#library-search').focus({preventScroll:true});}
  });
  return {render};
}
