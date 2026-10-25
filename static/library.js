import {numberMarkup,animateSurface} from './experience-system.js';
import {noticeState,isNoticeOpen} from './notice-intake.js';
import {noticeSearchText,noticeSearchExcerpt} from './notice-search.js';
import {highlightMatch} from './command-search.js';
export const RELEVANCE={matches_known:['和你有关','green'],needs_review:['需确认是否适用','orange'],not_matching:['可能不适用','']};
export const INBOX_INTENTS={all:'全部',act:'要做',decide:'要决定',verify:'要核实',followup:'待跟进',read:'知悉 / 阅读',irrelevant:'可能不适用',closed:'已结束'};
export function filterNotices(items,{query='',status='all',from='',to='',relevance='all',intent='all'}={}){
  const q=query.trim().toLocaleLowerCase();
  const day=n=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n*1000));
  return items.filter(n=>(intent==='all'||n.intent===intent)&&(status==='all'||n.disposition===status||isNoticeOpen(n)&&n.status===status)&&(relevance==='all'||(relevance==='unknown'?!n.applicability:n.applicability===relevance))&&(!q||noticeSearchText(n).toLocaleLowerCase().includes(q))&&(!from||day(n.created_at)>=from)&&(!to||day(n.created_at)<=to));
}

export function groupNotices(items){
  const groups=new Map(),units=[];
  for(const notice of items){
    if(!notice.matter){units.push({notices:[notice]});continue;}
    let unit=groups.get(notice.matter.id);
    if(!unit){unit={matter:notice.matter,notices:[]};groups.set(notice.matter.id,unit);units.push(unit);}
    unit.notices.push(notice);
  }
  return units;
}

export function createLibraryUI({state,api,esc,icon,noticeRow,empty,moveSelection}){
  let owner=null,query='',status='all',from='',to='',relevance='all',intent='all',page=1,view='cards';
  let grouped=true;
  let searchSequence=0,searchTimer=null,searchResult=null,searchQuery='',searchError='',searching=false;
  const $=s=>document.querySelector(s);
  const button=(label,value,disabled=false)=>`<button type="button" class="button small" data-library-page="${value}" ${disabled?'disabled':''}>${label}</button>`;
  function clearSearch(){clearTimeout(searchTimer);searchSequence++;searchResult=null;searchQuery='';searchError='';searching=false;}
  function queueSearch(immediate=false){
    clearSearch();
    const term=query.trim();if(!term||!api){update();return;}
    searching=true;update();
    const sequence=searchSequence,session=state.session,route=state.renderId;
    const current=()=>sequence===searchSequence&&session===state.session&&route===state.renderId&&query.trim()===term&&!!$('#library-results');
    searchTimer=setTimeout(async()=>{
      try{
        const results=await api('/notices/search?q='+encodeURIComponent(term));
        if(!current())return;
        searchResult=results;searchQuery=term;searching=false;update();
      }catch(error){if(current()){searchError=error.message;searching=false;update();}}
    },immediate?0:180);
  }
  const snippet=notice=>{
    if(!query.trim())return '';
    const text=noticeSearchExcerpt(notice,query);if(!text)return '';
    return `<p class="notice-search-excerpt">${notice.search_source?`<span class="notice-search-source">${esc(notice.search_source)} · </span>`:''}${highlightMatch(text,query,esc)}</p>`;
  };
  function noticeCard(notice) {
    const [label,color]=noticeState(notice);
    const date=new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(notice.created_at*1000));
    return `<a class="notice-card notice-row" href="#notice/${encodeURIComponent(notice.id)}" aria-label="打开通知 ${esc(notice.title)}" data-state="${esc(notice.status)}"><div class="notice-card-top"><span class="notice-folder" aria-hidden="true">${icon('doc')}</span><span class="notice-card-pills">${notice.applicability&&RELEVANCE[notice.applicability]?`<span class="pill ${RELEVANCE[notice.applicability][1]}">${RELEVANCE[notice.applicability][0]}</span>`:''}<span class="pill ${color}">${label}</span></span></div><div class="notice-card-content"><span class="link-button">${esc(notice.title)}</span><p>${esc(notice.source_label||'个人提交')}</p>${snippet(notice)}</div><div class="notice-card-footer"><span>${date} 收件</span><span>${notice.task_count||0} 项待办</span><span class="notice-card-arrow" aria-hidden="true">${icon('arrow')}</span></div></a>`;
  }
  function matterCard(unit){
    return `<article class="notice-card matter-library-card"><span class="pill">同一事项 · ${unit.matter.member_count} 则通知</span><a class="link-button" href="#notice/${encodeURIComponent(unit.notices[0].id)}">${esc(unit.matter.title)}</a><p class="small muted">${unit.notices.length} 则符合当前筛选</p><details><summary>查看组内通知</summary><ul>${unit.notices.map(n=>`<li><a href="#notice/${encodeURIComponent(n.id)}">${esc(n.title)}</a><span class="small muted"> · ${INBOX_INTENTS[n.intent]||''}</span>${snippet(n)}</li>`).join('')}</ul></details></article>`;
  }
  function render(){
    if(owner!==state.session.user.id){owner=state.session.user.id;clearSearch();query='';status='all';from='';to='';relevance='all';intent='all';page=1;view='cards';grouped=true;}
    if(!$('#library-results'))$('#content').innerHTML=`<div class="page-title between"><div><h1>通知资料</h1></div><a href="#new" class="button primary">${icon('plus')} 收通知</a></div><div class="library-toolbar"><label class="library-search">${icon('search')}<input id="library-search" type="search" placeholder="搜索标题、正文、附件或材料" aria-label="搜索通知资料" value="${esc(query)}"></label><details class="library-date"><summary>${icon('calendar')} 收件日期 ${from||to?'<span class="dot"></span>':''}</summary><div><label class="field">从<input id="library-from" type="date" value="${from}"></label><label class="field">到<input id="library-to" type="date" value="${to}"></label></div></details></div><div class="library-tabs-row"><div class="tabs" role="tablist" aria-label="通知状态">${[['all','全部'],['received','待处理'],['draft','待确认'],['confirmed','已转办'],['reference','仅存资料'],['not_applicable','与我无关'],['closed','已结束'],['failed','处理失败'],['processing','处理中']].map(([v,l])=>`<button role="tab" type="button" class="tab" data-library-status="${v}">${l}</button>`).join('')}</div><span id="library-count" class="small muted"></span></div><div class="relevance-chips" role="group" aria-label="按与我的关系筛选">${[['all','全部'],['matches_known','和我有关'],['needs_review','需确认是否适用'],['not_matching','可能不适用']].map(([v,l])=>`<button type="button" class="chip" data-library-relevance="${v}" aria-pressed="false">${l}<b data-relevance-count="${v}"></b></button>`).join('')}</div><div id="library-filter-note" class="small muted" role="status"></div><div id="library-results" class="panel flush library-results" role="tabpanel" aria-label="通知结果"></div><div id="library-pages" class="pagination"></div>`;
    if(!$('#library-summary'))$('.library-toolbar').insertAdjacentHTML('beforebegin','<section class="collection-summary" id="library-summary" aria-label="通知收件概览"></section>');
    if(!$('.library-view-toggle'))$('.library-toolbar').insertAdjacentHTML('beforeend',`<div class="view-toggle library-view-toggle" role="group" aria-label="通知展示方式"><button type="button" data-library-view="cards" aria-label="卡片视图">${icon('grid')}<span>卡片</span></button><button type="button" data-library-view="list" aria-label="列表视图">${icon('menu')}<span>列表</span></button></div>`);
    $('#library-summary').classList.add('inbox-intents');
    if(!$('.library-refine')){
      const refine=document.createElement('details');refine.className='library-refine';
      refine.innerHTML='<summary>更多筛选</summary>';
      const tabs=$('.library-tabs-row');tabs.before(refine);
      refine.querySelector('summary').append($('#library-count'));
      refine.append(tabs,$('.relevance-chips'));
      refine.open=status!=='all'||relevance!=='all';
    }
    $('#library-summary').innerHTML=Object.entries(INBOX_INTENTS).map(([key,label])=>`<button type="button" class="collection-stat" data-library-intent="${key}" aria-pressed="${key===intent}"><strong>${numberMarkup(key==='all'?state.notices.length:state.notices.filter(n=>n.intent===key).length)}</strong><span>${label}</span></button>`).join('');
    update();if(query.trim())queueSearch(true);
  }
  function update(){
    if(!$('#library-results'))return;
    const hasGroups=state.notices.some(n=>n.matter);
    if(hasGroups&&!$('[data-library-group]'))$('.library-toolbar').insertAdjacentHTML('beforeend','<button type="button" class="button small" data-library-group aria-pressed="true">按事项归组</button>');
    const groupButton=$('[data-library-group]');if(groupButton){groupButton.hidden=!hasGroups;groupButton.setAttribute('aria-pressed',String(grouped));}

    const selected=state.insightSelection?.kind==='notices'?state.insightSelection:null;
    const remote=query.trim()&&api,base=remote?(searchQuery===query.trim()?searchResult||[]:[]):state.notices;
    const items=filterNotices(base.filter(n=>!selected||selected.ids.includes(n.id)),{query:remote?'':query,status,from,to,relevance,intent}),units=grouped?groupNotices(items):items.map(n=>({notices:[n]})),pages=Math.max(1,Math.ceil(units.length/15));page=Math.max(1,Math.min(page,pages));
    document.querySelectorAll('[data-library-intent]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.libraryIntent===intent)));
    document.querySelectorAll('[data-library-status]').forEach(b=>{const active=b.dataset.libraryStatus===status;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});moveSelection($('.tabs'));
    $('#library-count').textContent=searching?'正在查找…':searchError?'查找失败':`${items.length} / ${state.notices.length} 则`;
    document.querySelectorAll('[data-library-relevance]').forEach(b=>{const value=b.dataset.libraryRelevance;b.setAttribute('aria-pressed',String(value===relevance));const count=value==='all'?state.notices.length:state.notices.filter(n=>n.applicability===value).length;b.querySelector('b').textContent=count;b.hidden=value!=='all'&&!count&&value!==relevance;});
    $('#library-filter-note').innerHTML=selected||query||status!=='all'||relevance!=='all'||intent!=='all'||from||to?`<span>${selected?'数据看板 · '+esc(selected.label)+' · ':''}${intent!=='all'?INBOX_INTENTS[intent]+' · ':''}${from&&to&&from>to?'开始日期晚于结束日期，请调整范围。':'已按当前条件筛选全部通知。'}</span><button class="link-button" type="button" data-library-reset>清空筛选</button>`:'';
    if(searching||searchError){
      const results=$('#library-results');results.classList.remove('card-view');results.dataset.emptyKey='';results.setAttribute('aria-busy',String(searching));
      results.innerHTML=searching?'<p class="notice-search-status" role="status">正在查找通知正文和附件…</p>':`<div class="notice-search-status" role="alert">${esc(searchError)} <button type="button" class="button small" data-library-search-retry>重试</button></div>`;$('#library-pages').innerHTML='';return;
    }
    $('#library-results').removeAttribute('aria-busy');
    const hasFilter=!!(selected||query.trim()||status!=='all'||relevance!=='all'||intent!=='all'||from||to),emptyKey=items.length?'':hasFilter||state.notices.length?'search':'listening',results=$('#library-results');
    results.classList.toggle('card-view',view==='cards'&&items.length>0);
    document.querySelectorAll('[data-library-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.libraryView===view)));
    if(!emptyKey||results.dataset.emptyKey!==emptyKey)results.innerHTML=items.length?units.slice((page-1)*15,page*15).map(unit=>unit.matter?matterCard(unit):(view==='cards'?noticeCard:n=>`<div class="notice-search-list-row">${noticeRow(n)}${query.trim()?`<a class="notice-search-detail" href="#notice/${encodeURIComponent(n.id)}">${snippet(n)}</a>`:''}</div>`)(unit.notices[0])).join(''):empty(hasFilter||state.notices.length?'暂时没有匹配的通知':'先收好第一则通知',hasFilter||state.notices.length?'换一个正文或附件中的词，或清空筛选。':'正文、附件和截图可以一起保存，之后随时回来核对。',hasFilter||state.notices.length?'<button class="button small" type="button" data-library-reset>清空筛选</button>':'<a class="button" href="#new">收第一则通知</a>',false,hasFilter||state.notices.length?'search':'listening');
    results.dataset.emptyKey=emptyKey;
    $('#library-pages').innerHTML=pages>1?`${button('上一页',page-1,page===1)}<span>第 ${page} / ${pages} 页 · 每页 15 项</span>${button('下一页',page+1,page===pages)}`:'';
  }
  document.addEventListener('input',e=>{if(e.target.id==='library-search'){query=e.target.value;page=1;if(!e.isComposing)queueSearch();}});
  document.addEventListener('compositionend',e=>{if(e.target.id==='library-search'){query=e.target.value;page=1;queueSearch();}});
  document.addEventListener('change',e=>{if(['library-from','library-to'].includes(e.target.id)){from=$('#library-from').value;to=$('#library-to').value;page=1;update();}});
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-library-group]')){grouped=!grouped;page=1;update();return;}
    const intentButton=e.target.closest('[data-library-intent]');if(intentButton){intent=intentButton.dataset.libraryIntent;status='all';relevance='all';state.insightSelection=null;page=1;update();return;}
    if(e.target.closest('[data-library-search-retry]')){queueSearch(true);return;}
    const display=e.target.closest('[data-library-view]');
    if(display){view=display.dataset.libraryView;update();animateSurface($('#library-results'),0);}
    const tab=e.target.closest('[data-library-status]'),pagination=e.target.closest('[data-library-page]');
    if(tab){state.insightSelection=null;status=tab.dataset.libraryStatus;page=1;update();}
    const chip=e.target.closest('[data-library-relevance]');
    if(chip){relevance=chip.dataset.libraryRelevance;page=1;update();}
    if(pagination&&!pagination.disabled){page=Number(pagination.dataset.libraryPage);update();$('#library-results').scrollIntoView({block:'nearest'});}
    if(e.target.closest('[data-library-reset]')){state.insightSelection=null;clearSearch();query='';status='all';from='';to='';relevance='all';intent='all';page=1;$('#library-search').value='';$('#library-from').value='';$('#library-to').value='';update();$('#library-search').focus({preventScroll:true});}
  });
  return {render,resetFilters(){clearSearch();query='';status='all';from='';to='';relevance='all';intent='all';page=1;}};
}
