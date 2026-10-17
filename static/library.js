import {contextHint} from './motion.js';
export function filterNotices(items,{query='',status='all',from='',to=''}={}){
  const q=query.trim().toLocaleLowerCase();
  const day=n=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n*1000));
  return items.filter(n=>(status==='all'||n.status===status)&&(!q||(n.title+' '+n.source_label).toLocaleLowerCase().includes(q))&&(!from||day(n.created_at)>=from)&&(!to||day(n.created_at)<=to));
}

export function createLibraryUI({state,esc,icon,noticeRow,empty,moveSelection}){
  let owner=null,query='',status='all',from='',to='',page=1;
  const $=s=>document.querySelector(s);
  const button=(label,value,disabled=false)=>`<button type="button" class="button small" data-library-page="${value}" ${disabled?'disabled':''}>${label}</button>`;
  function render(){
    if(owner!==state.session.user.id){owner=state.session.user.id;query='';status='all';from='';to='';page=1;}
    if(!$('#library-results'))$('#content').innerHTML=`<div class="page-title between"><div><div class="eyebrow">原文、附件和进展都在这里</div><h1>通知资料</h1><p>找回一则通知，接着上次核对的地方继续。</p></div><a href="#new" class="button primary">${icon('plus')} 提交通知</a></div><div class="library-toolbar"><label class="library-search">${icon('search')}<input id="library-search" type="search" placeholder="搜索全部通知标题或来源" aria-label="搜索通知资料" value="${esc(query)}"></label><details class="library-date"><summary>${icon('calendar')} 收件日期 ${from||to?'<span class="dot"></span>':''}</summary><div><label class="field">从<input id="library-from" type="date" value="${from}"></label><label class="field">到<input id="library-to" type="date" value="${to}"></label></div></details></div><div class="library-tabs-row"><div class="tabs" role="tablist" aria-label="通知状态">${[['all','全部'],['received','待整理'],['draft','待确认'],['confirmed','已转办'],['failed','处理失败'],['processing','处理中']].map(([v,l])=>`<button role="tab" type="button" class="tab" data-library-status="${v}">${l}</button>`).join('')}</div><span id="library-count" class="small muted"></span></div><div id="library-filter-note" class="small muted" role="status"></div><div id="library-results" class="panel flush library-results" role="tabpanel" aria-label="通知结果"></div><div id="library-pages" class="pagination"></div>`;
    update();
  }
  function update(){
    if(!$('#library-results'))return;
    const items=filterNotices(state.notices,{query,status,from,to}),pages=Math.max(1,Math.ceil(items.length/15));page=Math.max(1,Math.min(page,pages));
    document.querySelectorAll('[data-library-status]').forEach(b=>{const active=b.dataset.libraryStatus===status;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});moveSelection($('.tabs'));
    $('#library-count').textContent=`${items.length} / ${state.notices.length} 则`;
    $('#library-filter-note').innerHTML=query||status!=='all'||from||to?`<span>${from&&to&&from>to?'开始日期晚于结束日期，请调整范围。':'已按当前条件筛选全部通知。'}</span>${items.length?'<button class="link-button" type="button" data-library-reset>清空筛选</button>':''}`:'';
    const hasFilter=!!(query.trim()||status!=='all'||from||to),emptyKey=items.length?'':hasFilter||state.notices.length?'search':'listening',results=$('#library-results');
    if(!emptyKey||results.dataset.emptyKey!==emptyKey)results.innerHTML=items.length?items.slice((page-1)*15,page*15).map(noticeRow).join(''):empty(hasFilter||state.notices.length?'暂时没有匹配的通知':'先收好第一则通知',hasFilter||state.notices.length?'试试标题中的另一个词，或清空筛选。':'正文、附件和截图可以一起保存，之后随时回来核对。',hasFilter||state.notices.length?'<button class="button small" type="button" data-library-reset>清空筛选</button>':'<a class="button" href="#new">提交第一则通知</a>',false,hasFilter||state.notices.length?'search':'listening');
    results.dataset.emptyKey=emptyKey;
    $('#library-pages').innerHTML=pages>1?`${button('上一页',page-1,page===1)}<span>第 ${page} / ${pages} 页 · 每页 15 则</span>${button('下一页',page+1,page===pages)}`:'';
  }
  document.addEventListener('input',e=>{if(e.target.id==='library-search'){query=e.target.value;page=1;update();}});
  document.addEventListener('change',e=>{if(['library-from','library-to'].includes(e.target.id)){from=$('#library-from').value;to=$('#library-to').value;page=1;update();}});
  document.addEventListener('click',e=>{
    const tab=e.target.closest('[data-library-status]'),pagination=e.target.closest('[data-library-page]');
    if(tab){status=tab.dataset.libraryStatus;page=1;update();}
    if(pagination&&!pagination.disabled){page=Number(pagination.dataset.libraryPage);update();$('#library-results').scrollIntoView({block:'nearest'});}
    if(e.target.closest('[data-library-reset]')){query='';status='all';from='';to='';page=1;$('#library-search').value='';$('#library-from').value='';$('#library-to').value='';update();$('#library-search').focus({preventScroll:true});}
  });
  return {render};
}
