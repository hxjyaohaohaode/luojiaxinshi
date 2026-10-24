import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {createMemoryIntents} from './memory-intents.js';
import {createMemoryDrafts} from './memory-drafts.js';
import {memoryListText,memoryTimestamp} from './memory-list-text.js';
import {memoryNodeIcon,memoryEntryIcon} from './memory-icons.js';

const kinds={preference:'偏好',constraint:'约束',decision:'决定',fact:'事实',episode:'经历',skill:'方法',intention:'计划',summary:'概览'};
const states={active:'正常使用',pending:'暂时不用',conflict:'说法不明确，先不用',needs_review:'自动检查中',cooling:'近期没用到',source_changed:'来源有变或已不用',archived:'已归档',inactive:'已停用',expired:'已过期',scheduled:'还没生效'};
const date=value=>memoryTimestamp(value,true);
const options=(esc,items,value)=>Object.entries(items).map(([key,label])=>`<option value="${key}" ${key===value?'selected':''}>${esc(label)}</option>`).join('');

// Native adaptations of the supplied Velora File Tree / Sidebar and Be UI
// Breadcrumb. Search, drafts and transactions use this application's APIs.
export function createMemoryWorkbench({state,api,esc,icon,studio,onCatalog,toast,ask,showDialog}){
  const $=q=>document.querySelector(q),intents=createMemoryIntents(),drafts=createMemoryDrafts();
  let owner=null,node='',root='',page=0,selected='',mode='tree',revision=0,timer,controller=null;
  let query={tree:'',session:''},searchScope='folder',viewType='auto',stateFilter='all',sort='recent';
  let tree=new Map(),expanded=new Set(),rows={memories:[],passages:[],projects:[]},summary={},loading=new Set(),more=new Map(),checked=new Set();
  let navDirty=true,lastToken='',polling=false,pendingUpdate=false,pendingWrites=0,returnFocus=null;
  let indexing=false,lastPollAt=0;
  const narrow=()=>matchMedia('(max-width:1200px)').matches;
  function current(){
    const id=state.session?.user?.id||null;
    if(id!==owner){
      owner=id;drafts.select(id);node='';root='';query={tree:'',session:''};page=0;selected='';mode='tree';viewType='auto';stateFilter='all';sort='recent';searchScope='folder';revision++;
      tree.clear();expanded.clear();loading.clear();more.clear();checked.clear();lastToken='';navDirty=true;pendingUpdate=false;indexing=false;lastPollAt=0;
      controller?.abort();overlay(false);
    }
    return id;
  }
  async function write(path,payload,method='POST'){
    const id=current(),headers=await intents.headers(id,method+path,payload);
    if(id!==state.session?.user?.id)throw Error('账号切换了，重新打开记忆页看看吧。');
    const request=new AbortController(),timeout=setTimeout(()=>request.abort(),25000);pendingWrites++;
    try{const result=await api(path,{method,json:payload,headers,signal:request.signal});intents.complete(id,headers['Idempotency-Key']);return result;}
    catch(error){if(error.status===0)throw Error('网络断了一下，还不确定刚才有没有保存成功。先别改内容，再试一次会自动核对，不会重复保存。');throw error;}
    finally{clearTimeout(timeout);pendingWrites--;}
  }
  function frame(){return `<div id="memory-shell" class="memory-tree-page">
    <header class="memory-tree-head"><button class="button memory-nav-toggle" data-tree-action="toggle-nav" aria-expanded="false" aria-controls="memory-tree-sidebar">${icon('folder')} 目录</button><div class="memory-auto-line"><span class="memory-mode-dot"></span><strong id="memory-auto-mode">AI 自动维护</strong><span id="memory-tree-counts"></span><button class="icon-button" data-tree-action="refresh" aria-label="刷新记忆" title="刷新记忆">${icon('history')}</button></div><button class="button primary" data-memory-action="new">${icon('plus')} 添加记忆</button><button type="button" class="icon-button memory-manage-button" data-tree-action="manage" aria-label="记忆管理" title="记忆管理">${icon('settings')}</button></header>
    <div id="memory-update-message" class="memory-update-message" role="status" hidden></div>
    <div class="memory-tree-layout"><aside class="memory-tree-nav" id="memory-tree-sidebar"><div class="memory-tree-nav-title"><strong>记忆目录</strong><button class="icon-button" data-tree-action="folder-edit" aria-label="编辑当前目录">⋯</button><button class="icon-button" data-tree-action="folder" aria-label="新建子目录">${icon('plus')}</button></div><div id="memory-tree-nav" role="tree" aria-label="记忆目录"></div><button class="memory-session-nav" data-tree-action="sessions">${icon('history')} 会话与工作记忆 <span id="memory-short-count"></span></button></aside>
    <section class="memory-tree-main" aria-label="当前目录的记忆"><nav id="memory-breadcrumbs" class="memory-breadcrumbs" aria-label="记忆路径"></nav>
    <div class="memory-search-line"><label class="memory-tree-search">${icon('search')}<span class="sr-only">搜索记忆</span><input id="memory-search" type="search" maxlength="1000" placeholder="搜索内容、项目、目录或资料"></label><label class="sr-only" for="memory-search-scope">搜索范围</label><select id="memory-search-scope" aria-label="搜索范围"><option value="folder">当前目录</option><option value="all">全部记忆</option></select></div>
    <div id="memory-tree-filters" class="memory-tree-filters"><label>内容<select id="memory-view-type">${options(esc,{auto:'自动显示',all:'全部内容',memories:'可编辑记忆',passages:'资料原文'},viewType)}</select></label><label>状态<select id="memory-state-filter">${options(esc,{all:'全部状态',active:'正常使用',held:'系统暂缓',inactive:'停用或归档'},stateFilter)}</select></label><label>排序<select id="memory-sort">${options(esc,{recent:'最近更新',oldest:'最早更新'},sort)}</select></label></div>
    <div class="memory-tree-results"><span id="memory-match-count" role="status"></span><label class="memory-check-page"><input id="memory-check-page" type="checkbox">选择本页记忆</label></div>
    <div id="memory-bulk-bar" class="memory-bulk-bar" hidden><span id="memory-selected-count"></span><button class="button small" data-tree-action="move-many">移动</button><button class="button small" data-tree-action="archive-many">归档</button><button class="button small" data-tree-action="activate-many">启用</button><button class="button small danger" data-tree-action="forget-many">遗忘</button><button class="button small" data-tree-action="uncheck">取消选择</button></div>
    <div id="memory-load-status" role="status" class="memory-load-status"></div><div id="memory-items" class="memory-tree-rows"></div><div id="memory-pagination" class="memory-tree-pagination"></div></section>
    <div class="memory-detail-backdrop" data-tree-action="dismiss-detail" hidden></div><aside id="memory-detail-pane" class="memory-tree-detail" aria-label="记忆详情" tabindex="-1" hidden></aside></div>
    </div>`;}
  function nav(){
    if(!$('#memory-tree-nav'))return;
    const focused=document.activeElement?.closest('#memory-tree-nav [data-tree-id]')?.dataset.treeId;
    for(const n of tree.values())n.item_count=n.subtree_count??n.item_count;
    const branch=(parent,depth=0)=>[...tree.values()].filter(n=>n.parent_id===parent).sort((a,b)=>b.system-a.system||a.title.localeCompare(b.title,'zh')).map(n=>{
      const open=expanded.has(n.id),hasChildren=n.children>0;
      return `<div role="treeitem" aria-level="${depth+1}" aria-selected="${mode==='tree'&&node===n.id}" ${hasChildren?`aria-expanded="${open}"`:''} data-tree-id="${esc(n.id)}"><div class="memory-tree-node"><button class="memory-tree-disclosure" tabindex="-1" data-tree-expand="${esc(n.id)}" aria-label="${open?'收起':'展开'} ${esc(n.title)}" ${hasChildren?'':'disabled'}><span class="memory-tree-chevron ${open?'is-open':''}">›</span></button><button class="memory-tree-label" data-tree-node="${esc(n.id)}" tabindex="${mode==='tree'&&node===n.id?0:-1}" title="${esc(n.title)}">${memoryNodeIcon(n,open)}<span class="memory-tree-name">${esc(n.title)}</span>${n.item_count?`<small>${n.item_count}</small>`:''}</button></div>${open?`<div role="group">${branch(n.id,depth+1)}</div>`:''}</div>`;
    }).join('')+(more.has(parent)?`<button class="button small" data-tree-more="${esc(parent)}">加载更多目录…</button>`:'');
    $('#memory-tree-nav').innerHTML=`<div role="treeitem" aria-level="1" aria-selected="${mode==='tree'&&node===root}" aria-expanded="true" data-tree-id="${esc(root)}"><div class="memory-tree-node memory-tree-root"><button class="memory-tree-label" data-tree-node="${esc(root)}" tabindex="${mode==='session'||node===root?0:-1}">${memoryNodeIcon({node_key:'root'})}<span class="memory-tree-name">全部记忆</span></button></div><div role="group">${branch(root,1)}</div></div>`;
    $('.memory-session-nav')?.setAttribute('aria-current',mode==='session'?'page':'false');
    // Collapsing a selected descendant must leave one reachable tab stop.
    let focusId=focused||(mode==='tree'?node:root),button;
    for(let depth=0;depth<12;depth++){
      button=$(`#memory-tree-nav [data-tree-node="${CSS.escape(focusId||root)}"]`);
      if(button)break;
      focusId=tree.get(focusId)?.parent_id||root;
    }
    if(button){for(const b of document.querySelectorAll('#memory-tree-nav [data-tree-node]'))b.tabIndex=b===button?0:-1;if(focused)button.focus({preventScroll:true});}
  }
  function forgetCachedChildren(id){
    for(const child of [...tree.values()].filter(n=>n.parent_id===id)){forgetCachedChildren(child.id);tree.delete(child.id);}
  }
  async function children(id,offset=0,ticket=revision){
    const user=current(),context=captureUiContext(state);if(loading.has(id))return;loading.add(id);
    try{
      const data=await api('/memory/tree?'+new URLSearchParams({parent_id:id,offset}));
      if(user!==current()||ticket!==revision||!context.sameRoute())return;
      if(!offset){const keep=new Set(data.nodes.map(n=>n.id));for(const old of [...tree.values()].filter(n=>n.parent_id===id&&!keep.has(n.id))){forgetCachedChildren(old.id);tree.delete(old.id);}}
      for(const n of data.nodes)tree.set(n.id,n);
      if(data.has_more)more.set(id,data.next_offset);else more.delete(id);
      expanded.add(id);nav();
    }finally{loading.delete(id);}
  }
  function bulkBar(){
    const box=$('#memory-check-page');if(!box)return;
    const count=rows.memories.length;box.disabled=mode==='session'||count===0;box.checked=count>0&&checked.size===count;box.indeterminate=checked.size>0&&!box.checked;
    $('.memory-check-page').hidden=mode==='session'||count===0;
    $('#memory-bulk-bar').hidden=!checked.size;$('#memory-selected-count').textContent=`已选 ${checked.size} 条`;
    const activate=$('[data-tree-action="activate-many"]');if(activate){activate.disabled=rows.memories.some(m=>checked.has(m.id)&&m.review_status!=='accepted');activate.title=activate.disabled?'有几条依据不够，补充或修改内容后再启用':'';}
  }
  function pagination(total){
    $('#memory-pagination').innerHTML=total>50?`<button class="button small" data-tree-action="previous" ${page===0?'disabled':''}>上一页</button><span>第 ${page+1} / ${Math.ceil(total/50)} 页</span><button class="button small" data-tree-action="next" ${(page+1)*50>=total?'disabled':''}>下一页</button>`:'';
  }
  function list(){
    if(mode==='session'){sessionList();return;}
    const all=[...rows.memories.map(m=>({id:m.id,title:m.content,text:m.content,kind:kinds[m.kind],symbol:memoryEntryIcon(m),state:states[m.state]||'已保存',active:m.state==='active',updated:m.updated_at,locked:m.locked,source:['resource','source_claim'].includes(m.origin),editable:true,path:m.path})),
      ...(rows.passages||[]).map(p=>({id:p.id,title:p.title,text:p.content,kind:'资料原文',symbol:memoryEntryIcon(p),state:p.locator,active:true,updated:p.created_at,source:true,path:p.path}))];
    for(const m of all){if(m.editable){const excerpt=memoryListText(m.text);m.title=excerpt.title;m.text=excerpt.preview;}if(rows.settings?.mode==='off'&&m.active){m.state='已暂停使用';m.active=false;}}
    const order=new Map((rows.order||all).map((r,i)=>[r.id,i]));all.sort((a,b)=>(order.get(a.id)||0)-(order.get(b.id)||0));
    $('#memory-items').innerHTML=all.map(m=>`<div class="memory-selectable-row">${m.editable?`<label class="memory-row-check"><span class="sr-only">选择：${esc(m.title.slice(0,35))}</span><input type="checkbox" data-tree-check="${esc(m.id)}" ${checked.has(m.id)?'checked':''}></label>`:'<span class="memory-row-check-spacer"></span>'}<button class="memory-tree-row ${selected===m.id?'is-selected':''}" data-tree-record="${esc(m.id)}" aria-pressed="${selected===m.id}"><span class="memory-row-symbol ${m.source?'is-source':''}">${m.symbol}</span><span class="memory-row-body"><span class="memory-row-title">${esc(m.title.slice(0,100))}</span><span class="memory-row-preview">${esc(m.text.slice(0,150))}</span><span class="memory-row-meta"><span>${esc(m.kind)}</span><span class="${m.active?'is-active':''}">${esc(m.state)}</span>${m.locked?'<span>已保护</span>':''}${drafts.has(m.id)?'<span class="memory-draft-badge">有草稿</span>':''}</span>${query.tree||searchScope==='all'?`<span class="memory-row-path">${esc(m.path||'')}</span>`:''}</span><time class="memory-row-time" title="${esc(date(m.updated))}">${esc(memoryTimestamp(m.updated))}</time></button></div>`).join('')||`<div class="memory-tree-empty">${icon('doc')}<h2>${query.tree?'没找到匹配的内容':'这里还空着'}</h2><p>${query.tree?'换个关键词，或者扩大搜索范围试试。':'平时的对话、通知、资料和办事进展会慢慢积累到这里，你也可以直接添加想记住的内容。'}</p><div class="memory-detail-buttons">${query.tree?'<button class="button small" data-tree-action="clear-search">清空搜索</button>':''}${node!==root||stateFilter!=='all'||viewType!=='all'?'<button class="button small" data-tree-action="search-all">查看全部记忆</button>':''}<button class="button small" data-memory-action="new">添加记忆</button></div></div>`;
    const overview=viewType==='auto'&&!query.tree&&!tree.get(node)?.node_key?.startsWith('source');
    $('#memory-match-count').textContent=`${rows.matched||0} 条内容${query.tree&&searchScope==='folder'?' · 当前目录及子目录':overview?' · 这里是概览，搜索可以查全文':''}`;
    pagination(rows.matched);bulkBar();
  }
  function sessionList(){
    $('#memory-items').innerHTML=(rows.items||[]).map(s=>`<article class="memory-session-entry"><div class="memory-row-meta"><span>${esc(s.title)}</span><span>${s.lifetime==='turn'?'只用于这一轮':'只在这个对话里'}</span>${s.edited_by_user?'<span>我改过</span>':''}</div><p class="memory-content">${esc(s.content)}</p><p class="small muted">保留至 ${esc(date(s.expires_at))}${s.promoted_id?' · 已变成长期记忆':''}</p><div class="memory-detail-buttons"><a class="button small" href="#chat/${encodeURIComponent(s.conversation_id)}">继续对话</a><button class="button small" data-memory-studio="working" data-id="${esc(s.conversation_id)}">目标与工作记录</button><button class="button small" data-memory-life="edit-session" data-id="${esc(s.id)}">编辑条件</button>${s.promoted_id?'':`<button class="button small" data-memory-life="promote" data-id="${esc(s.id)}">长期保留</button>`}<button class="button small danger" data-memory-life="forget-session" data-id="${esc(s.id)}">遗忘</button></div></article>`).join('')||`<div class="memory-tree-empty"><h2>${query.session?'没找到匹配的临时要求':'还没有对话里的临时要求'}</h2><p>临时要求只在对应的对话和保留期内用，不会因为出现在这里就变成长期习惯。</p>${query.session?'<button class="button small" data-tree-action="clear-search">清空搜索</button>':''}</div>`;
    $('#memory-match-count').textContent=`${rows.matched||0} 条临时要求`;pagination(rows.matched);bulkBar();
  }
  function overlay(open){
    const pane=$('#memory-detail-pane'),modal=!!(open&&pane?.classList.contains('is-visible')&&location.hash.split('/')[0]==='#memory'&&narrow());
    document.body.classList.toggle('memory-detail-open',modal);
    if(!pane)return;
    pane.setAttribute('role',modal?'dialog':'complementary');if(modal)pane.setAttribute('aria-modal','true');else pane.removeAttribute('aria-modal');
    const backdrop=$('.memory-detail-backdrop');if(backdrop)backdrop.hidden=!modal;
    for(const el of document.querySelectorAll('.memory-tree-main,.memory-tree-nav,.memory-tree-head,.memory-auto-line,.memory-manage-button'))el.inert=modal;
  }
  function closeMobileNavigation(){
    if(!matchMedia('(max-width:650px)').matches)return;
    $('.memory-tree-layout')?.classList.remove('nav-open');$('[data-tree-action="toggle-nav"]')?.setAttribute('aria-expanded','false');
    const main=$('.memory-tree-main');if(main){main.tabIndex=-1;main.focus({preventScroll:true});}
  }
  function placeholder(){const p=$('#memory-detail-pane');if(p){p.replaceChildren();p.hidden=true;p.removeAttribute('data-entry-id');}$('.memory-tree-layout')?.classList.remove('has-detail');}
  function clearDetail(restoreFocus=false){
    const closed=selected;
    selected='';$('#memory-detail-pane')?.classList.remove('is-visible');overlay(false);placeholder();
    if(restoreFocus)queueMicrotask(()=>{if(location.hash.split('/')[0]==='#memory')($(`[data-tree-record="${CSS.escape(closed)}"]`)||returnFocus)?.focus();});
  }
  function detail(id,{focus=true}={}){
    const previous=!focus&&$('#memory-detail-pane')?.dataset.entryId===id?{open:!!$('.memory-detail-more')?.open,scroll:$('#memory-detail-pane').scrollTop,textScroll:$('.memory-detail-text')?.scrollTop||0}:null;
    selected=id;list();const m=rows.memories.find(m=>m.id===id),p=rows.passages?.find(p=>p.id===id);
    if(!m&&!p){clearDetail();return;}
    const pane=$('#memory-detail-pane');
    pane.innerHTML=`<div class="memory-detail-heading"><span class="memory-detail-tag">${m?esc(kinds[m.kind]):'资料原文'}</span><button class="icon-button" data-tree-action="close-detail" aria-label="关闭详情">×</button></div><h2>${m?'记忆详情':esc(p.title)}</h2><p class="small muted">${m?'第 '+m.version+' 版 · '+date(m.updated_at):esc(p.locator)+' · 原文位置 '+p.start_offset}</p><div class="memory-detail-text memory-content">${esc(m?m.content:p.content)}</div>${m?`${drafts.has(m.id)?'<p class="memory-draft-notice">这条还有没保存的草稿，点“继续编辑草稿”就能接着改。</p>':''}<div class="memory-detail-buttons"><button class="button primary" data-tree-action="edit-inline">${icon('edit')} ${drafts.has(m.id)?'继续编辑草稿':'直接编辑'}</button><button class="button" data-memory-assist="open" data-id="${esc(id)}">AI 修改</button><button class="button" data-tree-action="copy">复制</button></div><p class="memory-detail-note">${esc(states[m.state]||'已保存')} · ${esc(m.scope==='project'?(rows.projects.find(p=>p.id===m.project_id)?.name||'所属项目'):m.scope==='topic'?m.topic:'跨项目通用')}<br>${m.shared?'在同一范围里，别的对话也能用':'只在原来的对话里用'}，AI 会按问题挑着用。</p><button class="memory-detail-link" data-memory-studio="detail" data-id="${esc(id)}">查看来源与修改历史 →</button><details class="memory-detail-more"><summary>位置与更多操作</summary><p>${esc(m.path||'')}</p><div class="stack"><button class="button small" data-tree-action="move">移动到…</button><button class="button small" data-memory-action="edit" data-id="${esc(id)}">分类、范围与有效期</button><button class="button small" data-memory-life="item" data-id="${esc(id)}">记忆层级和跨对话使用</button>${m.review_status==='accepted'?`<button class="button small" data-memory-action="toggle" data-id="${esc(id)}">${m.active&&m.status==='active'?'停用':'启用'}</button>`:''}<button class="button small danger" data-memory-action="delete" data-id="${esc(id)}">遗忘这条记忆</button></div></details>`:`<p class="memory-detail-note">这段内容会跟着原资料自动更新，想改的话去原资料里改就行。</p><div class="memory-detail-buttons"><button class="button" data-tree-action="open-source">查看原始资料</button><button class="button" data-tree-action="copy">复制片段</button></div>`}`;
    pane.hidden=false;$('.memory-tree-layout')?.classList.add('has-detail');pane.classList.add('is-visible');overlay(true);
    pane.dataset.entryId=id;
    if(previous){if($('.memory-detail-more'))$('.memory-detail-more').open=previous.open;pane.scrollTop=previous.scroll;if($('.memory-detail-text'))$('.memory-detail-text').scrollTop=previous.textScroll;}
    if(m?.node_id)pane.querySelector('.memory-detail-more .stack').insertAdjacentHTML('afterbegin','<button class="button small" data-tree-action="locate">打开所在目录</button>');
    if(focus){returnFocus=$(`[data-tree-record="${CSS.escape(id)}"]`);if(narrow())pane.querySelector('[data-tree-action="close-detail"]').focus();}
  }
  function updateNotice(text='',retry=false){
    const el=$('#memory-update-message');if(!el)return;el.hidden=!text;
    el.replaceChildren(document.createTextNode(text));
    if(retry){const button=document.createElement('button');button.className='button small';button.dataset.treeAction='refresh';button.textContent='立即更新';el.append(button);}
  }
  async function render({navigation=false,quiet=false}={}){
    clearTimeout(timer);const user=current(),ticket=++revision,ui=captureUiContext(state);if(!user||location.hash.split('/')[0]!=='#memory')return;
    controller?.abort();controller=new AbortController();const request=controller,timeout=setTimeout(()=>request.abort(),25000);
    if(!$('#memory-shell')||!$('.memory-tree-page')){$('#content').innerHTML=frame();placeholder();navDirty=true;}
    if(navigation)navDirty=true;
    $('#memory-search').value=query[mode];$('#memory-search-scope').value=searchScope;$('#memory-search-scope').hidden=mode==='session';$('#memory-tree-filters').hidden=mode==='session';
    const filters={'memory-view-type':viewType,'memory-state-filter':stateFilter,'memory-sort':sort};for(const [id,value] of Object.entries(filters))$('#'+id).value=value;
    $('.memory-tree-main').setAttribute('aria-busy','true');$('#memory-load-status').textContent=quiet?'':'正在读取…';
    const wantedMode=mode;
    try{
      const params=new URLSearchParams({q:query[mode],offset:page*50,limit:50});
      if(mode==='tree'){if(node&&(searchScope!=='all'||!query.tree))params.set('node_id',node);params.set('view',viewType);params.set('state',stateFilter);params.set('sort',sort);}
      // Read the watermark first: a newer status must not acknowledge entries
      // that were read before indexing committed in another request.
      const watermark=await api('/memory/tree/status',{signal:request.signal});
      const [start,data]=await Promise.all([api('/memory/tree',{signal:request.signal}),api((mode==='session'?'/memory/session-items?':'/memory/tree/entries?')+params,{signal:request.signal})]);
      if(user!==current()||ticket!==revision||!ui.sameRoute()||wantedMode!==mode)return;
      summary={...start,jobs:watermark.jobs};indexing=!!(watermark.jobs.queued||watermark.jobs.running);root=start.root_id;if(!node)node=root;
      if(page>0&&page*50>=data.matched){page=Math.max(0,Math.ceil(data.matched/50)-1);return await render();}
      if(navDirty){tree.clear();more.clear();for(const n of start.nodes)tree.set(n.id,n);}
      else for(const n of start.nodes)tree.set(n.id,n);
      rows={...(mode==='tree'?data:{...data,settings:start.settings,memories:[],passages:[],projects:rows.projects||[]}),lifecycle_counts:start.lifecycle_counts,session_count:start.session_count};
      if(mode==='tree')for(const b of data.breadcrumbs||[])if(b.id!==root)tree.set(b.id,{children:0,item_count:0,...tree.get(b.id),...b});
      if(mode==='tree'){onCatalog(rows);$('#memory-breadcrumbs').innerHTML=(data.breadcrumbs||[]).map((b,i,a)=>`${i?'<span aria-hidden="true">›</span>':''}<button data-tree-node="${esc(b.id)}" ${i===a.length-1?'aria-current="location"':''} title="${esc(b.title)}">${esc(b.title)}</button>`).join('');studio.configure(rows);}
      else {$('#memory-breadcrumbs').innerHTML='<span aria-current="location">会话与工作记忆</span>';studio.configure(rows);}
      checked=new Set([...checked].filter(id=>rows.memories.some(m=>m.id===id)));nav();list();
      if(mode==='tree'&&(summary.jobs.queued||summary.jobs.running)&&$('#memory-items .memory-tree-empty')){
        $('#memory-items .memory-tree-empty h2').textContent='正在自动整理记忆';
        $('#memory-items .memory-tree-empty p').textContent='已有的内容正在整理，不用重新添加。整理好页面会自动更新，你可以先去忙别的。';
      }
      $('#memory-tree-counts').textContent=`${start.source_passages} 个资料片段${watermark.jobs.queued||watermark.jobs.running?' · 正在自动整理':''}`;
      $('#memory-short-count').textContent=start.session_count||'';
      if(rows.settings)$('#memory-auto-mode').textContent={auto:'AI 自动维护',review:'AI 自动维护',manual:'手动添加',off:'记忆已暂停'}[rows.settings.mode]||'AI 自动维护';
      if(selected&&!$('#memory-inline-editor'))detail(selected,{focus:false});
      lastToken=watermark.token;pendingUpdate=false;updateNotice();
      if(navDirty){
        const active=mode==='tree'?(data.breadcrumbs||[]).map(n=>n.id).filter(id=>id!==root):[];
        const targets=[...new Set([...expanded,...active])].slice(0,16);if(!targets.length){const first=start.nodes.find(n=>n.node_key==='layer:long');if(first)targets.push(first.id);}
        const loaded=await Promise.allSettled(targets.map(id=>children(id,0,ticket)));
        if(user===current()&&ticket===revision){navDirty=false;if(loaded.some(r=>r.status==='rejected'&&r.reason.status!==404))updateNotice('有些目录暂时读不出来，点刷新再试试。',true);}
      }
    }catch(error){
      if(user!==current()||ticket!==revision||!ui.sameRoute())return;
      if(error.status===404&&node&&node!==root){node=root;clearDetail();page=0;navDirty=true;return await render();}
      updateNotice(error.message,true);
      if(!$('#memory-items').children.length)$('#memory-items').innerHTML='<div class="memory-tree-empty"><h2>记忆暂时读不出来</h2><p>保存的内容都还在，网络好了再试一次。</p><button class="button" data-tree-action="refresh">再试一次</button></div>';
    }finally{clearTimeout(timeout);if(ticket===revision){$('.memory-tree-main')?.removeAttribute('aria-busy');if($('#memory-load-status'))$('#memory-load-status').textContent='';controller=null;if(indexing)lastPollAt=0;}}
  }
  async function inlineEdit(){
    let editing=rows.memories.find(m=>m.id===selected);if(!editing)return;const draft=drafts.get(editing.id),id=editing.id;
    const pane=$('#memory-detail-pane');pane.hidden=false;$('.memory-tree-layout')?.classList.add('has-detail');pane.innerHTML=`<form id="memory-inline-editor" class="stack" data-memory-id="${esc(id)}" data-version="${draft?.version||editing.version}"><div class="memory-detail-heading"><h2>编辑记忆</h2><button class="icon-button" type="button" data-tree-action="close-detail" aria-label="收起并保留草稿">×</button></div><div data-edit-conflict hidden></div><label class="field">正文<textarea name="content" required maxlength="2000" rows="12">${esc(draft?.content??editing.content)}</textarea></label><p class="small muted" data-draft-status></p><div class="memory-detail-buttons"><button class="button primary" type="submit">保存</button><button class="button" type="button" data-tree-action="cancel-edit">放弃草稿</button><button class="button" type="button" data-copy-draft>复制草稿</button></div></form>`;
    const form=$('#memory-inline-editor'),field=form.elements.content,conflict=form.querySelector('[data-edit-conflict]');
    function saveDraft(){drafts.put(id,field.value,Number(form.dataset.version),editing.content);form.querySelector('[data-draft-status]').textContent=`${Array.from(field.value).length} / 2000 字 · ${drafts.has(id)?'草稿已暂存':'和已保存的内容一样'}`;}
    function compare(latest){
      conflict.hidden=false;conflict.innerHTML=`<p>这条在别的页面改过了，现在是第 ${latest.version} 版。你的草稿还在，对照一下再保存吧。</p><label class="field">最新保存的内容<textarea readonly rows="5">${esc(latest.content)}</textarea></label><button type="button" class="button small" data-use-latest-version>看过了，用我的草稿接着改</button>`;
      form.querySelector('[type="submit"]').disabled=true;
      conflict.querySelector('button').addEventListener('click',()=>{editing=latest;form.dataset.version=latest.version;conflict.hidden=true;form.querySelector('[type="submit"]').disabled=false;saveDraft();field.focus();});
    }
    if(draft&&draft.version!==editing.version)compare(editing);
    field.addEventListener('input',saveDraft);saveDraft();field.focus();
    form.querySelector('[data-copy-draft]').addEventListener('click',()=>copy(field.value));
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(!form.checkValidity())return;const context=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;form.inert=true;
      const payload=Object.fromEntries(['scope','project_id','topic','kind','source_conversation_id','pinned','semantic_key','valid_from','expires_at','labels'].map(k=>[k,editing[k]]));
      try{
        const saved=await write('/memory/items/'+id,{...payload,version:Number(form.dataset.version),content:field.value,active:editing.review_status==='pending'?true:!!editing.active,locked:true},'PUT');
        if(!context.sameUser())return;drafts.remove(id);
        if(context.sameRoute()&&selected===id){form.remove();rows.memories=rows.memories.map(m=>m.id===id?{...m,...saved}:m);await render();}
        toast('改好了。',false,{duration:15000,action:{label:'撤销',run:async()=>{if(!context.sameUser())throw Error('账号切换了，没法撤销原账号的修改。');await write('/memory/items/'+id+'/restore',{version:saved.version,revision:editing.version});if(context.sameRoute())await render({navigation:true});}}});
      }catch(error){
        if(context.sameRoute()&&form.isConnected&&error.status===409){try{const latest=await api('/memory/items/'+id);if(context.sameUser()&&form.isConnected)compare(latest);}catch{}}
        if(context.sameUser())toast(error.message,true);
      }finally{form.inert=false;finish();if(!conflict.hidden)form.querySelector('[type="submit"]').disabled=true;}
    });
  }
  async function copy(text){try{await navigator.clipboard.writeText(text);toast('已复制。');}catch{toast('浏览器没让复制，选中文字手动复制吧。',true);}}
  function attachPicker(form,selectedNode,exclude=''){
    let seq=0,offset=0,pickerTimer;const field=form.querySelector('[data-location-picker]');
    field.innerHTML=`<label class="field">查找目录<input data-location-query type="search" placeholder="输入目录或项目名称"></label><label class="field">目标目录<select name="destination" required><option value="">正在读取目录…</option></select></label><p class="small muted" data-location-status role="status"></p><div class="memory-picker-pages"><button class="button small" type="button" data-location-prev>上一页</button><button class="button small" type="button" data-location-next>下一页</button></div>`;
    const select=field.querySelector('select'),input=field.querySelector('input');let chosen=selectedNode,chosenLabel='当前目录';
    async function load(){
      const ticket=++seq,context=captureUiContext(state,form);field.querySelector('[data-location-status]').textContent='正在寻找目录…';
      try{
        const data=await api('/memory/tree/locations?'+new URLSearchParams({q:input.value,offset,limit:100,...(exclude?{exclude}:{})}));
        if(ticket!==seq||!context.sameDialog())return;
        const found=data.nodes.find(n=>n.id===chosen);if(found)chosenLabel=found.path;
        select.innerHTML=`<option value="">先选一个目标目录</option>${chosen&&!found?`<option value="${esc(chosen)}" selected>${esc(chosenLabel)}</option>`:''}`+data.nodes.map(n=>`<option value="${esc(n.id)}" ${n.id===chosen?'selected':''}>${esc(n.path)}</option>`).join('');
        field.querySelector('[data-location-status]').textContent=`找到 ${data.matched} 个目录 · 看完整路径就能分清同名目录`;
        field.querySelector('[data-location-prev]').disabled=offset===0;field.querySelector('[data-location-next]').disabled=offset+100>=data.matched;
      }catch(error){if(ticket===seq&&context.sameDialog())field.querySelector('[data-location-status]').textContent=error.message;}
    }
    select.addEventListener('change',()=>{chosen=select.value;chosenLabel=select.selectedOptions[0]?.textContent||'';});
    input.addEventListener('input',()=>{offset=0;clearTimeout(pickerTimer);pickerTimer=setTimeout(load,200);});
    field.querySelector('[data-location-prev]').addEventListener('click',()=>{offset=Math.max(0,offset-100);load();});field.querySelector('[data-location-next]').addEventListener('click',()=>{offset+=100;load();});
    load();
  }
  async function submitDialog(form,work,after){
    const context=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;form.inert=true;
    try{const result=await work();if(!context.sameUser())return;if(context.sameDialog())$('#dialog').close();if(context.sameRoute()){if(after)after(result);navDirty=true;await render();}}
    catch(error){if(context.sameUser())toast(error.message,true);}finally{form.inert=false;finish();}
  }
  function folder(){
    const parent=node||root;showDialog('新建子目录',`<form id="memory-folder-form" class="stack"><p class="small muted">会建在当前目录下。AI 也会自动分类，不用提前建好目录。</p><label class="field">名称<input name="title" required maxlength="60" autofocus></label><div class="form-footer"><button class="button primary" type="submit">创建目录</button></div></form>`);
    const form=$('#memory-folder-form');form.addEventListener('submit',e=>{e.preventDefault();submitDialog(form,()=>write('/memory/tree/folders',{parent_id:parent,title:form.elements.title.value}));});
  }
  function moveEntries(items){
    if(!items.length)return;showDialog(items.length>1?`移动 ${items.length} 条记忆`:'移动记忆',`<form id="memory-move-form" class="stack"><p class="small muted">找到目标目录就能移过去，项目、专题和对话的使用范围都不变。</p><div data-location-picker></div><div class="form-footer"><button class="button primary" type="submit">移动</button></div></form>`);
    const form=$('#memory-move-form');attachPicker(form,items.length===1?items[0].node_id:node);
    form.addEventListener('submit',e=>{e.preventDefault();submitDialog(form,()=>write('/memory/tree/placements',{node_id:form.elements.destination.value,items:items.map(m=>({id:m.id,version:m.version}))},'PUT'),()=>{checked.clear();clearDetail();toast(`已移动 ${items.length} 条记忆。`);});});
  }
  function editFolder(){
    const item=tree.get(node);if(!item||item.system){toast('系统分类由 AI 自动维护，你可以在这里建自己的子目录。');return;}
    showDialog('编辑目录',`<form id="memory-folder-edit" class="stack"><label class="field">名称<input name="title" required maxlength="60" value="${esc(item.title)}"></label><div data-location-picker></div><div class="form-footer"><button class="button danger" type="button" data-remove-folder>移除目录，保留内容</button><button class="button primary" type="submit">保存</button></div></form>`);
    const form=$('#memory-folder-edit');attachPicker(form,item.parent_id,item.id);
    form.addEventListener('submit',e=>{e.preventDefault();submitDialog(form,()=>write('/memory/tree/folders/'+item.id,{title:form.elements.title.value,parent_id:form.elements.destination.value,version:item.version},'PUT'));});
    form.querySelector('[data-remove-folder]').addEventListener('click',async()=>{
      const context=captureUiContext(state,form);if(!await ask('移除目录',`“${item.title}”中的记忆、资料和子目录会移到上一级，内容和使用范围都会保留。`,'移除目录'))return;
      if(!context.sameUser())return;
      try{const result=await write('/memory/tree/folders/'+item.id,{version:item.version},'DELETE');if(context.sameRoute()){node=result.parent_id;navDirty=true;clearDetail();await render();}if(context.sameUser())toast('目录移除了，里面的内容都还在。');}catch(error){if(context.sameUser())toast(error.message,true);}
    });
  }
  async function batch(action){
    const items=rows.memories.filter(m=>checked.has(m.id));if(!items.length)return;
    const context=captureUiContext(state);
    if(action==='forget'&&!await ask('遗忘所选记忆',`会遗忘 ${items.length} 条记忆和由它们整理出的内容，以后的回答也不会再用。相关资料或任务不再自动生成记忆；原资料、聊天记录和离线备份都还在。`,'确认遗忘'))return;
    if(!context.sameUser())return;
    await write('/memory/bulk',{action,items:items.map(m=>({id:m.id,version:m.version}))});
    if(!context.sameUser())return;
    if(action==='forget')for(const m of items)drafts.remove(m.id);
    if(context.sameRoute()){checked.clear();clearDetail();navDirty=true;await render();}toast(`已${{archive:'归档',activate:'启用',forget:'遗忘'}[action]} ${items.length} 条记忆。`);
  }
  async function poll(){
    const user=current();if(!user||location.hash.split('/')[0]!=='#memory'||document.visibilityState==='hidden'||polling||controller||pendingWrites)return;
    polling=true;lastPollAt=Date.now();const context=captureUiContext(state);
    try{
      const data=await api('/memory/tree/status');if(user!==current()||!context.sameRoute())return;
      indexing=!!(data.jobs.queued||data.jobs.running);
      if(lastToken&&lastToken!==data.token){
        const interacting=selected||$('#memory-inline-editor')||$('dialog[open]')||checked.size||$('.memory-tools[open]')||document.activeElement?.closest('#memory-tree-nav,.memory-manage-button')||document.activeElement?.matches('#memory-search,[data-tree-check]');
        navDirty=true;if(interacting){pendingUpdate=true;updateNotice('记忆有新变化。你正在改的和选中的都会保留，忙完再刷新列表就好。',true);}else await render({navigation:true,quiet:true});
      }else if(!lastToken)lastToken=data.token;
    }catch{}finally{polling=false;}
  }
  document.addEventListener('input',e=>{if(e.target.id!=='memory-search'||!$('.memory-tree-page')||e.isComposing)return;query[mode]=e.target.value;page=0;checked.clear();clearTimeout(timer);timer=setTimeout(render,250);});
  document.addEventListener('compositionend',e=>{if(e.target.id==='memory-search')e.target.dispatchEvent(new Event('input',{bubbles:true}));});
  document.addEventListener('change',e=>{
    if(!e.target.closest('.memory-tree-page'))return;
    if(e.target.dataset.treeCheck){e.target.checked?checked.add(e.target.dataset.treeCheck):checked.delete(e.target.dataset.treeCheck);bulkBar();return;}
    if(e.target.id==='memory-check-page'){checked=e.target.checked?new Set(rows.memories.map(m=>m.id)):new Set();list();return;}
    if(!['memory-search-scope','memory-view-type','memory-state-filter','memory-sort'].includes(e.target.id))return;
    if(e.target.id==='memory-search-scope')searchScope=e.target.value;if(e.target.id==='memory-view-type')viewType=e.target.value;if(e.target.id==='memory-state-filter')stateFilter=e.target.value;if(e.target.id==='memory-sort')sort=e.target.value;
    page=0;checked.clear();clearDetail();render();
  });
  document.addEventListener('keydown',async e=>{
    if(location.hash.split('/')[0]!=='#memory'||$('dialog[open]'))return;
    const pane=$('#memory-detail-pane');
    if(selected&&narrow()&&pane?.classList.contains('is-visible')){
      if(e.key==='Escape'){e.preventDefault();clearDetail(true);list();return;}
      if(e.key==='Tab'){
        const controls=[...pane.querySelectorAll('button:not(:disabled),a[href],textarea:not(:disabled),input:not(:disabled),select:not(:disabled),summary')].filter(x=>x.getClientRects().length&&!x.closest('[inert]'));
        const first=controls[0],last=controls.at(-1);if(!first){e.preventDefault();pane.focus();}else if(e.shiftKey&&(document.activeElement===first||document.activeElement===pane)){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
      }
      return;
    }
    if(e.key==='/'&&!e.ctrlKey&&!e.metaKey&&!e.target.matches('input,textarea,select,[contenteditable="true"]')){e.preventDefault();$('#memory-search')?.focus();return;}
    if(e.key==='Escape'&&e.target.id==='memory-search'){e.preventDefault();query[mode]='';e.target.value='';page=0;render();return;}
    if(!e.target.closest('#memory-tree-nav'))return;
    const buttons=[...document.querySelectorAll('#memory-tree-nav [data-tree-node]')],i=buttons.indexOf(e.target),id=e.target.dataset.treeNode;
    if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const n={ArrowDown:Math.min(i+1,buttons.length-1),ArrowUp:Math.max(i-1,0),Home:0,End:buttons.length-1}[e.key];buttons[n]?.focus();}
    if(e.key==='ArrowRight'&&id){e.preventDefault();const child=e.target.closest('[data-tree-id]')?.querySelector(':scope > [role="group"] > [data-tree-id] > .memory-tree-node > [data-tree-node]');if((id===root||expanded.has(id))&&child)child.focus();else if(tree.get(id)?.children){try{await children(id);$(`[data-tree-node="${CSS.escape(id)}"]`)?.focus();}catch(error){toast(error.message,true);}}}
    if(e.key==='ArrowLeft'&&id){e.preventDefault();if(id===root)return;if(expanded.has(id)){expanded.delete(id);nav();$(`[data-tree-node="${CSS.escape(id)}"]`)?.focus();}else $(`[data-tree-node="${CSS.escape(tree.get(id)?.parent_id||root)}"]`)?.focus();}
  });
  document.addEventListener('focusin',e=>{if(!e.target.matches('#memory-tree-nav [data-tree-node]'))return;for(const b of document.querySelectorAll('#memory-tree-nav [data-tree-node]'))b.tabIndex=b===e.target?0:-1;});
  document.addEventListener('click',async e=>{
    if(!e.target.closest('.memory-tree-page'))return;
    const target=e.target.closest('[data-tree-node],[data-tree-expand],[data-tree-record],[data-tree-action],[data-tree-more]');if(!target||target.disabled)return;
    const context=captureUiContext(state,target);target.disabled=true;
    try{
      if(target.dataset.treeNode){clearDetail();node=target.dataset.treeNode;mode='tree';page=0;checked.clear();await render();if(context.sameRoute())closeMobileNavigation();if(tree.get(node)?.children&&!expanded.has(node))await children(node);}
      else if(target.dataset.treeMore)await children(target.dataset.treeMore,more.get(target.dataset.treeMore)||0);
      else if(target.dataset.treeExpand){const id=target.dataset.treeExpand;if(expanded.has(id)){expanded.delete(id);nav();}else await children(id);}
      else if(target.dataset.treeRecord)detail(target.dataset.treeRecord);
      else switch(target.dataset.treeAction){
        case 'manage':studio.management(rows);break;
        case 'refresh':await render({navigation:true});break;
        case 'previous':page=Math.max(0,page-1);checked.clear();clearDetail();await render();break;
        case 'next':page++;checked.clear();clearDetail();await render();break;
        case 'sessions':clearDetail();mode='session';page=0;checked.clear();await render();if(context.sameRoute())closeMobileNavigation();break;
        case 'folder':folder();break;
        case 'folder-edit':editFolder();break;
        case 'edit-inline':await inlineEdit();break;
        case 'cancel-edit':drafts.remove(selected);$('#memory-inline-editor')?.remove();detail(selected);break;
        case 'toggle-nav':{const open=$('.memory-tree-layout').classList.toggle('nav-open');target.setAttribute('aria-expanded',String(open));break;}
        case 'close-detail':case 'dismiss-detail':{const id=selected;clearDetail(true);list();if(pendingUpdate){await render({navigation:true,quiet:true});if(context.sameRoute())($(`[data-tree-record="${CSS.escape(id)}"]`)||$('#memory-search'))?.focus();}break;}
        case 'move':moveEntries(rows.memories.filter(m=>m.id===selected));break;
        case 'locate':{const m=rows.memories.find(m=>m.id===selected);if(m){node=m.node_id;query.tree='';searchScope='folder';clearDetail();page=0;await render({navigation:true});}break;}
        case 'move-many':moveEntries(rows.memories.filter(m=>checked.has(m.id)));break;
        case 'archive-many':await batch('archive');break;
        case 'activate-many':await batch('activate');break;
        case 'forget-many':await batch('forget');break;
        case 'uncheck':checked.clear();list();break;
        case 'copy':{const m=rows.memories.find(m=>m.id===selected)||rows.passages.find(p=>p.id===selected);if(m)await copy(m.content);break;}
        case 'clear-search':query[mode]='';page=0;await render();break;
        case 'search-all':clearDetail();node=root;searchScope='all';viewType='auto';stateFilter='all';page=0;await render();break;
        case 'open-source':{const id=selected,d=await api('/memory/passages/'+encodeURIComponent(id));if(context.sameRoute()&&selected===id&&d.href)location.hash=d.href;break;}
      }
    }catch(error){if(context.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  // A pending local index should appear as soon as it is ready; idle pages
  // retain the normal 20-second cadence and editing still defers replacement.
  setInterval(()=>{if(Date.now()-lastPollAt>=(indexing?1000:20000))poll();},1000);
  window.addEventListener('online',poll);document.addEventListener('visibilitychange',poll);window.addEventListener('focus',poll);
  window.addEventListener('hashchange',()=>{current();if(location.hash.split('/')[0]!=='#memory'){controller?.abort();revision++;overlay(false);}});
  matchMedia('(max-width:1200px)').addEventListener('change',()=>overlay(!!selected));
  return {render,write,clearPrivate(){drafts.clear();owner=null;selected='';overlay(false);},
    projectDeleted(){node='';page=0;selected='';tree.clear();expanded.clear();checked.clear();navDirty=true;}};
}
