import {numberMarkup,animateSurface} from './experience-system.js';
import {noticeState,isNoticeOpen} from './notice-intake.js';
import {noticeSearchText,noticeSearchExcerpt} from './notice-search.js';
import {highlightMatch} from './command-search.js';
export const RELEVANCE={matches_known:['和你有关','green'],needs_review:['需确认是否适用','orange'],not_matching:['可能不适用','']};
export const INBOX_INTENTS={all:'全部',act:'要做',decide:'要决定',verify:'要核实',followup:'待跟进',read:'知悉 / 阅读',irrelevant:'可能不适用',closed:'已结束'};
export function noticeOrigins(notice){
  const labels=Array.isArray(notice.origin_labels)?notice.origin_labels.map(v=>String(v||'').trim()).filter(Boolean):[];
  return [...new Set(labels.length?labels:[String(notice.source_label||'').trim()||'个人提交'])];
}
function publishedTimestamp(value){
  if(typeof value!=='string'||!value)return null;
  const dateOnly=/^\d{4}-\d{2}-\d{2}$/.test(value);
  if(dateOnly){const day=new Date(value+'T00:00:00Z');if(!Number.isFinite(day.getTime())||day.toISOString().slice(0,10)!==value)return null;}
  else if(!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value))return null;
  const time=Date.parse(dateOnly?value+'T00:00:00+08:00':value);
  return Number.isFinite(time)?time:null;
}
export function publicationDay(value){
  const timestamp=publishedTimestamp(value);if(timestamp===null)return '';
  if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value;
  return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(timestamp));
}
export function sortNotices(items,sort='published'){
  return [...items].sort((a,b)=>{
    if(sort==='published'){
      const left=publishedTimestamp(a.published_at),right=publishedTimestamp(b.published_at);
      if(left===null&&right!==null)return 1;if(right===null&&left!==null)return -1;
      if(left!==null&&right!==null&&left!==right)return right-left;
    }
    const key=sort==='collected'?'created_at':'updated_at';
    return (Number(b[key])||0)-(Number(a[key])||0);
  });
}
export function sourceOverview(catalog,subscriptions){
  const statuses=new Map((subscriptions||[]).map(item=>[item.source_id,item]));
  const priority={error:0,syncing:1,waiting:2,paused:3,active:4,manual:5};
  return (catalog||[]).filter(entry=>entry.data?.platform==='website').map(entry=>{const item=statuses.get(entry.id)||{};return {id:entry.id,name:entry.data?.name||'未命名来源',
    state:item.state||'manual',enabled:!!item.enabled,checked_at:item.checked_at||null,pending_count:Number(item.pending_count)||0};})
    .sort((a,b)=>(priority[a.state]??6)-(priority[b.state]??6)||a.name.localeCompare(b.name,'zh-CN'));
}
export function sourceHealthSummary(rows){
  if(!rows.length)return '尚未添加网站来源 · 查看详情';
  const enabled=rows.filter(row=>row.enabled).length,failed=rows.filter(row=>row.state==='error').length;
  const pending=rows.filter(row=>row.enabled&&row.state!=='error'&&(row.state==='waiting'||row.state==='syncing'||row.pending_count)).length;
  const paused=rows.filter(row=>row.state==='paused').length;
  return `已开启 ${enabled} 个网站${failed?' · '+failed+' 个检查未完成':''}${pending?' · '+pending+' 个仍在读取或等待':''}${paused?' · '+paused+' 个已暂停':''} · 查看详情`;
}
export function filterNotices(items,{query='',status='all',from='',to='',relevance='all',intent='all',source=''}={}){
  const q=query.trim().toLocaleLowerCase();
  const day=n=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(n*1000));
  return items.filter(n=>(!source||noticeOrigins(n).includes(source))&&(intent==='all'||n.intent===intent)&&(status==='all'||n.disposition===status||isNoticeOpen(n)&&n.status===status)&&(relevance==='all'||(relevance==='unknown'?!n.applicability:n.applicability===relevance))&&(!q||noticeSearchText(n).toLocaleLowerCase().includes(q))&&(!from||day(n.created_at)>=from)&&(!to||day(n.created_at)<=to));
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

export function createLibraryUI({state,api,esc,icon,noticeRow,empty,moveSelection,refreshData}){
  let owner=null,query='',status='all',from='',to='',relevance='all',intent='all',source='',sort='published',page=1,view='cards';
  let grouped=true;
  let searchSequence=0,searchTimer=null,searchResult=null,searchQuery='',searchError='',searching=false,sourceSequence=0;
  let websiteSources=[],sourceBusy=false,refreshSequence=0;
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
  const collectedDay=notice=>{
    const date=new Date(Number(notice.created_at)*1000);
    return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date):'';
  };
  function sourceMeta(notice){
    const published=publicationDay(notice.published_at),collected=collectedDay(notice);
    return `${published?published+(noticeOrigins(notice).length>1?' 原记录发布':' 发布'):'发布时间未标注'}${collected?' · '+collected+' 收录':''}`;
  }
  function noticeCard(notice) {
    const [label,color]=noticeState(notice);
    const origins=noticeOrigins(notice).join('、'),meta=sourceMeta(notice),flags=[notice.pending_intake_updates?'来源有更新':'',notice.source_review_count?'材料需核对':''].filter(Boolean);
    const excerpt=!query.trim()&&notice.source_excerpt?`<p class="student-notice-excerpt"><span>原文节选 · </span>${esc(String(notice.source_excerpt).replace(/\s+/g,' ').trim())}</p>`:'';
    const accessible=`打开通知 ${notice.title}，${origins}，${meta}，${label}${flags.length?'，'+flags.join('，'):''}`;
    return `<a class="notice-card notice-row" href="#notice/${encodeURIComponent(notice.id)}" aria-label="${esc(accessible)}" data-state="${esc(notice.status)}"><div class="notice-card-top"><span class="notice-folder" aria-hidden="true">${icon('doc')}</span><span class="notice-card-pills">${notice.applicability&&RELEVANCE[notice.applicability]?`<span class="pill ${RELEVANCE[notice.applicability][1]}">${RELEVANCE[notice.applicability][0]}</span>`:''}<span class="pill ${color}">${label}</span>${flags.map(flag=>`<span class="pill orange">${flag}</span>`).join('')}</span></div><div class="notice-card-content"><span class="link-button">${esc(notice.title)}</span><p>${esc(origins)}</p>${query.trim()?snippet(notice):excerpt}</div><div class="notice-card-footer"><span>${esc(meta)}</span><span>${notice.task_count||0} 项待办</span><span class="notice-card-arrow" aria-hidden="true">${icon('arrow')}</span></div></a>`;
  }
  function matterCard(unit){
    return `<article class="notice-card matter-library-card"><span class="pill">同一事项 · ${unit.matter.member_count} 则通知</span><a class="link-button" href="#notice/${encodeURIComponent(unit.notices[0].id)}">${esc(unit.matter.title)}</a><p class="small muted">${unit.notices.length} 则符合当前筛选</p><details><summary>查看组内通知</summary><ul>${unit.notices.map(n=>`<li><a href="#notice/${encodeURIComponent(n.id)}">${esc(n.title)}</a><span class="small muted"> · ${INBOX_INTENTS[n.intent]||''}</span>${snippet(n)}</li>`).join('')}</ul></details></article>`;
  }
  function sourceHealthMarkup(rows){
    if(!rows.length)return '<p class="small muted">还没有添加网站来源。可以选择学校或学院官网，并按需开启自动接收。</p>';
    const labels={active:'自动接收已开启',syncing:'正在检查',waiting:'等待首次检查',error:'最近检查未完成',paused:'已暂停',manual:'未开启自动接收'};
    const checked=value=>{const date=new Date(Number(value)*1000);return value&&Number.isFinite(date.getTime())?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date):'';};
    return `<div class="student-source-list">${rows.slice(0,3).map(item=>`<div class="student-source-status" data-state="${esc(item.state)}"><strong>${esc(item.name)}</strong><span>${esc(labels[item.state]||'状态待核对')}${item.checked_at?' · 检查于 '+esc(checked(item.checked_at)):''}${item.pending_count?' · 等待读取 '+item.pending_count+' 则':''}</span></div>`).join('')}</div>${rows.length>3?`<p class="small muted">另有 ${rows.length-3} 个官网来源，可在来源页查看。</p>`:''}`;
  }
  async function loadSourceHealth(){
    const target=$('#library-source-health'),uid=state.session?.user?.id,route=state.renderId,sequence=++sourceSequence;
    if(!target||!api)return;
    target.innerHTML='<p class="small muted">正在读取网站来源状态…</p>';
    try{
      const [catalog,subscriptions]=await Promise.all([api('/source-catalog'),api('/source-subscriptions')]);
      if(sequence!==sourceSequence||state.session?.user?.id!==uid||state.renderId!==route||!$('#library-source-health'))return;
      websiteSources=sourceOverview(catalog,subscriptions);
      if($('#library-source-summary'))$('#library-source-summary').textContent=sourceHealthSummary(websiteSources);
      $('#library-source-health').innerHTML=sourceHealthMarkup(websiteSources);
      if($('#library-refresh-web'))$('#library-refresh-web').disabled=sourceBusy||!websiteSources.some(item=>item.enabled);
    }catch(error){
      if(sequence!==sourceSequence||state.session?.user?.id!==uid||state.renderId!==route||!$('#library-source-health'))return;
      if($('#library-source-summary'))$('#library-source-summary').textContent='暂时无法读取来源状态 · 展开重试';
      $('#library-source-health').innerHTML='<p class="small">暂时无法读取网站来源状态，已收到的通知仍可查看。 <button class="link-button" type="button" data-library-source-retry>重试</button></p>';
    }
  }
  async function refreshWebsites(){
    if(sourceBusy||!api)return;
    const selected=websiteSources.filter(item=>item.enabled),uid=state.session?.user?.id,sequence=++refreshSequence;
    if(!selected.length)return;
    const current=()=>sequence===refreshSequence&&state.session?.user?.id===uid;
    const feedback=message=>{if(current()&&$('#library-refresh-result'))$('#library-refresh-result').textContent=message;};
    if(selected.length>20){feedback('已开启的网站来源超过 20 个，请到来源页分批检查。');return;}
    sourceBusy=true;if($('#library-refresh-web'))$('#library-refresh-web').disabled=true;
    feedback(`正在检查 ${selected.length} 个已开启的网站来源…`);
    const failures=[],pending=[];let done=0;
    try{
      for(const item of selected){
        if(!current())return;
        try{
          const result=await api('/source-catalog/'+encodeURIComponent(item.id)+'/refresh',{method:'POST'});
          if(!current())return;
          if(!result||!result.enabled||result.error||result.state==='error'||result.state==='paused')failures.push(item.name);
          else if(result.state==='syncing'||result.state==='waiting'||result.pending_count)pending.push(item.name);
          else done++;
        }catch(error){if(!current())return;failures.push(item.name);}
      }
      if(!current())return;
      let listUpdated=false;
      if(refreshData&&$('#library-results')){
        try{await refreshData();if(current()&&$('#library-results')){render();listUpdated=true;}}catch(error){/* Keep the existing list and report refresh failure below. */}
      }
      if(!current())return;
      if($('#library-source-health'))await loadSourceHealth();
      if(!current())return;
      feedback(`检查完成：${done} 个已完成${pending.length?'，'+pending.length+' 个仍在读取':''}${failures.length?'，'+failures.length+' 个未完成':''}。${listUpdated?'通知列表已更新。':'通知列表未刷新，请重新打开页面查看。'}${failures.length?' 可到来源页查看原因。':''}`);
    }finally{
      if(current()){sourceBusy=false;if($('#library-refresh-web'))$('#library-refresh-web').disabled=!websiteSources.some(item=>item.enabled);}
    }
  }
  function render(){
    if(owner!==state.session.user.id){owner=state.session.user.id;clearSearch();sourceSequence++;refreshSequence++;websiteSources=[];sourceBusy=false;query='';status='all';from='';to='';relevance='all';intent='all';source='';sort='published';page=1;view='cards';grouped=true;}
    const mounted=!$('#library-results');
    if(mounted)$('#content').innerHTML=`<div class="page-title between"><div><h1>通知资料</h1></div><a href="#new" class="button primary">${icon('plus')} 收通知</a></div>
      <section class="student-source-panel" aria-label="网站来源状态"><div class="student-source-heading"><strong>网站来源状态</strong><div class="row wrap"><button class="button small" type="button" id="library-refresh-web" data-library-refresh-web disabled>检查新通知</button><a class="link-button" href="#sources">管理来源 →</a></div></div><details class="student-source-details"><summary id="library-source-summary">正在读取网站来源状态…</summary><div id="library-source-health" role="status"><p class="small muted">正在读取网站来源状态…</p></div></details><p class="small muted" id="library-refresh-result" role="status"></p></section>
      <div class="library-toolbar"><label class="library-search">${icon('search')}<input id="library-search" type="search" placeholder="搜索标题、正文、附件或材料" aria-label="搜索通知资料" value="${esc(query)}"></label><details class="library-date"><summary>${icon('calendar')} 收件日期 ${from||to?'<span class="dot"></span>':''}</summary><div><label class="field">从<input id="library-from" type="date" value="${from}"></label><label class="field">到<input id="library-to" type="date" value="${to}"></label></div></details></div>
      <div class="student-inbox-controls"><label class="field">按来源查看<select id="library-source" aria-label="按来源查看"></select></label><label class="field">排序<select id="library-sort" aria-label="通知排序"><option value="published">发布时间（最新）</option><option value="collected">收录时间（最新）</option><option value="updated">最近更新</option></select></label><p class="small muted" id="library-sort-note"></p></div>
      <div class="library-tabs-row"><div class="tabs" role="tablist" aria-label="通知状态">${[['all','全部'],['received','待处理'],['draft','待确认'],['confirmed','已转办'],['reference','仅存资料'],['not_applicable','与我无关'],['closed','已结束'],['failed','处理失败'],['processing','处理中']].map(([v,l])=>`<button role="tab" type="button" class="tab" data-library-status="${v}">${l}</button>`).join('')}</div><span id="library-count" class="small muted"></span></div><div class="relevance-chips" role="group" aria-label="按与我的关系筛选">${[['all','全部'],['matches_known','和我有关'],['needs_review','需确认是否适用'],['not_matching','可能不适用']].map(([v,l])=>`<button type="button" class="chip" data-library-relevance="${v}" aria-pressed="false">${l}<b data-relevance-count="${v}"></b></button>`).join('')}</div><div id="library-filter-note" class="small muted" role="status"></div><div id="library-results" class="panel flush library-results" role="tabpanel" aria-label="通知结果"></div><div id="library-pages" class="pagination"></div>`;
    if(!$('#library-summary'))$('.library-toolbar').insertAdjacentHTML('beforebegin','<section class="collection-summary" id="library-summary" aria-label="通知收件概览"></section>');
    if(!$('#library-unreviewed-note'))$('#library-summary').insertAdjacentHTML('afterend','<p class="small muted student-unreviewed-note" id="library-unreviewed-note"></p>');
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
    const counts=Object.fromEntries(Object.keys(INBOX_INTENTS).map(key=>[key,key==='all'?state.notices.length:state.notices.filter(n=>n.intent===key).length]));
    $('#library-summary').innerHTML=Object.entries(INBOX_INTENTS).filter(([key])=>key==='all'||counts[key]||key===intent).map(([key,label])=>`<button type="button" class="collection-stat" data-library-intent="${key}" aria-pressed="${key===intent}"><strong>${numberMarkup(counts[key])}</strong><span>${label}</span></button>`).join('');
    const unreviewed=state.notices.filter(n=>n.status==='received'&&isNoticeOpen(n)&&!n.applicability).length;
    $('#library-unreviewed-note').textContent=unreviewed?`${unreviewed} 则通知尚未判断是否适合你；“要核实”不等于都需要办理。`:'';
    update();if(query.trim())queueSearch(true);if(mounted)loadSourceHealth();
  }
  function update(){
    if(!$('#library-results'))return;
    const sourceCounts=new Map();
    for(const notice of state.notices)for(const label of noticeOrigins(notice))sourceCounts.set(label,(sourceCounts.get(label)||0)+1);
    if(source&&!sourceCounts.has(source))source='';
    const options='<option value="">全部来源</option>'+[...sourceCounts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'zh-CN')).map(([label,count])=>`<option value="${esc(label)}">${esc(label)} · ${count} 则</option>`).join('');
    if($('#library-source').innerHTML!==options)$('#library-source').innerHTML=options;
    $('#library-source').value=source;$('#library-sort').value=sort;
    $('#library-sort-note').textContent=sort==='published'?'按原记录发布时间排序；未标注的排在后面，可切换按收录时间查看。':sort==='collected'?'按加入本账号的时间排序。':'按通知记录最近更新的时间排序，不等同于原文发布时间。';
    const hasGroups=state.notices.some(n=>n.matter);
    if(hasGroups&&!$('[data-library-group]'))$('.library-toolbar').insertAdjacentHTML('beforeend','<button type="button" class="button small" data-library-group aria-pressed="true">按事项归组</button>');
    const groupButton=$('[data-library-group]');if(groupButton){groupButton.hidden=!hasGroups;groupButton.setAttribute('aria-pressed',String(grouped));}

    const selected=state.insightSelection?.kind==='notices'?state.insightSelection:null;
    const remote=query.trim()&&api,base=remote?(searchQuery===query.trim()?searchResult||[]:[]):state.notices;
    const items=sortNotices(filterNotices(base.filter(n=>!selected||selected.ids.includes(n.id)),{query:remote?'':query,status,from,to,relevance,intent,source}),sort),units=grouped?groupNotices(items):items.map(n=>({notices:[n]})),pages=Math.max(1,Math.ceil(units.length/15));page=Math.max(1,Math.min(page,pages));
    document.querySelectorAll('[data-library-intent]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.libraryIntent===intent)));
    document.querySelectorAll('[data-library-status]').forEach(b=>{const active=b.dataset.libraryStatus===status;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});moveSelection($('.tabs'));
    $('#library-count').textContent=searching?'正在查找…':searchError?'查找失败':`${items.length} / ${state.notices.length} 则`;
    document.querySelectorAll('[data-library-relevance]').forEach(b=>{const value=b.dataset.libraryRelevance;b.setAttribute('aria-pressed',String(value===relevance));const count=value==='all'?state.notices.length:state.notices.filter(n=>n.applicability===value).length;b.querySelector('b').textContent=count;b.hidden=value!=='all'&&!count&&value!==relevance;});
    $('#library-filter-note').innerHTML=selected||query||status!=='all'||relevance!=='all'||intent!=='all'||source||from||to?`<span>${selected?'数据看板 · '+esc(selected.label)+' · ':''}${source?'来源：'+esc(source)+' · ':''}${intent!=='all'?INBOX_INTENTS[intent]+' · ':''}${from&&to&&from>to?'开始日期晚于结束日期，请调整范围。':'已按当前条件筛选全部通知。'}</span><button class="link-button" type="button" data-library-reset>清空筛选</button>`:'';
    if(searching||searchError){
      const results=$('#library-results');results.classList.remove('card-view');results.dataset.emptyKey='';results.setAttribute('aria-busy',String(searching));
      results.innerHTML=searching?'<p class="notice-search-status" role="status">正在查找通知正文和附件…</p>':`<div class="notice-search-status" role="alert">${esc(searchError)} <button type="button" class="button small" data-library-search-retry>重试</button></div>`;$('#library-pages').innerHTML='';return;
    }
    $('#library-results').removeAttribute('aria-busy');
    const hasFilter=!!(selected||query.trim()||status!=='all'||relevance!=='all'||intent!=='all'||source||from||to),emptyKey=items.length?'':hasFilter||state.notices.length?'search':'listening',results=$('#library-results');
    results.classList.toggle('card-view',view==='cards'&&items.length>0);
    document.querySelectorAll('[data-library-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.libraryView===view)));
    if(!emptyKey||results.dataset.emptyKey!==emptyKey)results.innerHTML=items.length?units.slice((page-1)*15,page*15).map(unit=>unit.matter?matterCard(unit):(view==='cards'?noticeCard:n=>`<div class="notice-search-list-row">${noticeRow(n)}<p class="student-list-meta">${esc(sourceMeta(n))}${n.pending_intake_updates?' · 来源有更新':''}${n.source_review_count?' · 材料需核对':''}</p>${query.trim()?`<a class="notice-search-detail" href="#notice/${encodeURIComponent(n.id)}">${snippet(n)}</a>`:''}</div>`)(unit.notices[0])).join(''):empty(hasFilter||state.notices.length?'暂时没有匹配的通知':'先收好第一则通知',hasFilter||state.notices.length?'换一个正文或附件中的词，或清空筛选。':'订阅学校或学院官网，也可以自行保存正文、附件和截图。',hasFilter||state.notices.length?'<button class="button small" type="button" data-library-reset>清空筛选</button>':'<a class="button" href="#sources">选择通知来源</a>',false,hasFilter||state.notices.length?'search':'listening');
    results.dataset.emptyKey=emptyKey;
    $('#library-pages').innerHTML=pages>1?`${button('上一页',page-1,page===1)}<span>第 ${page} / ${pages} 页 · 每页 15 项</span>${button('下一页',page+1,page===pages)}`:'';
  }
  document.addEventListener('input',e=>{if(e.target.id==='library-search'){query=e.target.value;page=1;if(!e.isComposing)queueSearch();}});
  document.addEventListener('compositionend',e=>{if(e.target.id==='library-search'){query=e.target.value;page=1;queueSearch();}});
  document.addEventListener('change',e=>{
    if(['library-from','library-to'].includes(e.target.id)){from=$('#library-from').value;to=$('#library-to').value;page=1;update();}
    else if(e.target.id==='library-source'){source=e.target.value;page=1;update();}
    else if(e.target.id==='library-sort'){sort=e.target.value;page=1;update();}
  });
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-library-refresh-web]')){refreshWebsites();return;}
    if(e.target.closest('[data-library-source-retry]')){loadSourceHealth();return;}
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
    if(e.target.closest('[data-library-reset]')){state.insightSelection=null;clearSearch();query='';status='all';from='';to='';relevance='all';intent='all';source='';page=1;$('#library-search').value='';$('#library-from').value='';$('#library-to').value='';update();$('#library-search').focus({preventScroll:true});}
  });
  return {render,resetFilters(){clearSearch();query='';status='all';from='';to='';relevance='all';intent='all';source='';page=1;}};
}
