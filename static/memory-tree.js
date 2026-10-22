import {captureUiContext} from './ui-request.js';
import {createMemoryIntents} from './memory-intents.js';

const kinds={preference:'偏好',constraint:'约束',decision:'决定',fact:'事实',episode:'经历',skill:'方法',intention:'计划',summary:'概览'};
const states={active:'正在使用',pending:'系统暂缓使用',conflict:'存在歧义，暂不使用',needs_review:'自动检查中',cooling:'已冷却',source_changed:'等待来源更新',archived:'已归档',inactive:'已停用',expired:'已过期',scheduled:'尚未生效'};
const date=value=>value?new Date(value*1000).toLocaleString():'';

// Adapted interaction concepts: Velora File Tree (nested disclosure/indent),
// Be UI Breadcrumb (stable landmark/current location), native list/detail split.
// No upstream React/Motion code or dependencies are bundled.
export function createMemoryWorkbench({state,api,esc,icon,studio,onCatalog,toast,showDialog}){
  const $=q=>document.querySelector(q),intents=createMemoryIntents();
  let owner=null,node='',root='',query='',page=0,selected='',mode='tree',revision=0,timer;
  let tree=new Map(),expanded=new Set(),rows={memories:[],passages:[],projects:[]},summary={},loading=new Set(),more=new Map(),drafts=new Map();
  const current=()=>{const id=state.session?.user?.id;if(id!==owner){owner=id;node='';root='';query='';page=0;selected='';mode='tree';tree.clear();expanded.clear();loading.clear();more.clear();drafts.clear();}return id;};
  async function write(path,payload,method='POST'){
    const id=current(),headers=await intents.headers(id,method+path,payload);
    if(id!==state.session?.user?.id)throw Error('账号已变化，请重新打开记忆。');
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),25000);
    try{return await api(path,{method,json:payload,headers,signal:controller.signal});}
    catch(error){if(error.status===0)throw Error('本次结果尚未确认，请重试同一操作，或刷新查看已保存内容。');throw error;}
    finally{clearTimeout(timeout);}
  }
  function frame(){return `<div id="memory-shell" class="memory-tree-page">
    <header class="memory-tree-head"><div><span class="memory-eyebrow">你的个人知识与上下文</span><h1>记忆</h1><p>自动积累、按需想起，也随时由你改写。</p></div><button class="button" data-memory-action="new">${icon('plus')} 添加记忆</button></header>
    <div class="memory-auto-line" role="status"><span class="memory-mode-dot"></span><strong id="memory-auto-mode">AI 自动维护</strong><span id="memory-tree-counts"></span><button class="button small" data-tree-action="refresh">刷新</button></div>
    <div class="memory-tree-layout"><aside class="memory-tree-nav"><div class="memory-tree-nav-title"><strong>记忆目录</strong><button class="icon-button" data-tree-action="folder-edit" aria-label="编辑当前目录">⋯</button><button class="icon-button" data-tree-action="folder" aria-label="新建子目录">${icon('plus')}</button></div><div id="memory-tree-nav" role="tree" aria-label="记忆目录"></div><button class="memory-session-nav" data-tree-action="sessions">${icon('history')} 会话与工作记忆 <span id="memory-short-count"></span></button><p class="memory-tree-nav-note">AI 负责分类与选用。移动目录保留原来的使用范围。</p></aside>
    <section class="memory-tree-main" aria-label="当前目录的记忆"><nav id="memory-breadcrumbs" class="memory-breadcrumbs" aria-label="记忆路径"></nav><label class="memory-tree-search">${icon('search')}<span class="sr-only">搜索当前记忆目录</span><input id="memory-search" type="search" maxlength="1000" placeholder="搜索内容、项目或资料" value="${esc(query)}"></label><div class="memory-tree-results"><span id="memory-match-count" role="status"></span><span>按最近更新</span></div><div id="memory-items" class="memory-tree-rows"></div><div id="memory-pagination" class="memory-tree-pagination"></div></section>
    <aside id="memory-detail-pane" class="memory-tree-detail" aria-label="记忆详情"><div class="memory-detail-placeholder">${icon('doc')}<h2>每一条记忆，都有来处</h2><p>选择内容查看全文、直接编辑，或告诉 AI 要修改哪一部分。</p></div></aside></div>
    <details class="memory-tree-settings"><summary>自动维护与设置</summary><div id="memory-management"></div></details></div>`;}
  function nav(){
    if(!$('#memory-tree-nav'))return;
    const branch=(parent,depth=0)=>[...tree.values()].filter(n=>n.parent_id===parent).map(n=>{
      const open=expanded.has(n.id),children=n.children>0;
      return `<div role="treeitem" aria-level="${depth+1}" aria-selected="${node===n.id}" ${children?`aria-expanded="${open}"`:''} data-tree-id="${esc(n.id)}"><div class="memory-tree-node" style="--tree-depth:${depth}"><button class="memory-tree-disclosure" data-tree-expand="${esc(n.id)}" aria-label="${open?'收起':'展开'} ${esc(n.title)}" ${children?'':'disabled'}><span class="memory-tree-chevron ${open?'is-open':''}">›</span></button><button class="memory-tree-label" data-tree-node="${esc(n.id)}" tabindex="${node===n.id?0:-1}" title="${esc(n.title)}">${icon('doc')}<span>${esc(n.title)}</span>${n.item_count?`<small>${n.item_count}</small>`:''}</button></div>${open?`<div role="group">${branch(n.id,depth+1)}</div>`:''}</div>`;
    }).join('')+(more.has(parent)?`<button class="button small" data-tree-more="${esc(parent)}">继续载入目录…</button>`:'');
    $('#memory-tree-nav').innerHTML=`<div role="treeitem" aria-level="1" aria-selected="${node===root}" aria-expanded="true" data-tree-id="${esc(root)}"><div class="memory-tree-node"><button class="memory-tree-label" data-tree-node="${esc(root)}" tabindex="${node===root?0:-1}">${icon('grid')}<span>全部记忆</span></button></div><div role="group">${branch(root,1)}</div></div>`;
  }
  async function children(id,offset=0){
    if(loading.has(id))return;loading.add(id);const user=current(),ticket=revision,view=captureUiContext(state);
    try{const data=await api('/memory/tree?parent_id='+encodeURIComponent(id)+'&offset='+offset);if(user!==current()||ticket!==revision||!view.sameRoute())return;for(const n of data.nodes)tree.set(n.id,n);if(data.has_more)more.set(id,data.next_offset);else more.delete(id);expanded.add(id);nav();}
    finally{loading.delete(id);}
  }
  function list(){
    const memories=rows.memories.map(m=>({id:m.id,title:m.content,text:m.content,kind:kinds[m.kind],state:states[m.state]||'已保存',active:m.state==='active',updated:m.updated_at,locked:m.locked,source:m.origin==='source_claim'||m.origin==='resource'}));
    const passages=(rows.passages||[]).map(p=>({id:p.id,title:p.title,text:p.content,kind:'资料片段',state:p.locator,active:true,updated:p.created_at,source:true}));
    $('#memory-items').innerHTML=[...memories,...passages].map(m=>`<button class="memory-tree-row ${selected===m.id?'is-selected':''}" data-tree-record="${esc(m.id)}" aria-pressed="${selected===m.id}"><span class="memory-row-symbol ${m.source?'is-source':''}">${icon(m.source?'doc':'history')}</span><span class="memory-row-body"><span class="memory-row-title">${esc(m.title.slice(0,82))}</span><span class="memory-row-preview">${esc(m.text.slice(0,150))}</span><span class="memory-row-meta"><span>${esc(m.kind)}</span><span class="${m.active?'is-active':''}">${esc(m.state)}</span>${m.locked?'<span>本人保护</span>':''}</span></span><span class="memory-row-time">${esc(date(m.updated).split(' ')[0])}</span></button>`).join('')||`<div class="memory-tree-empty">${icon('doc')}<h2>${query?'这里没有匹配的内容':'记忆会在这里慢慢生长'}</h2><p>${query?'换一个关键词，或回到全部记忆继续搜索。':'对话、通知、资料、项目说明和办理进展会自动积累到合适的位置。'}</p></div>`;
    $('#memory-match-count').textContent=`${rows.matched||0} 条内容`;
    $('#memory-pagination').innerHTML=rows.matched>50?`<button class="button small" data-tree-action="previous" ${page===0?'disabled':''}>上一页</button><span>第 ${page+1} 页</span><button class="button small" data-tree-action="next" ${(page+1)*50>=rows.matched?'disabled':''}>下一页</button>`:'';
  }
  function breadcrumbs(){
    $('#memory-breadcrumbs').innerHTML=(rows.breadcrumbs||[]).map((b,i,a)=>`${i?'<span aria-hidden="true">›</span>':''}<button data-tree-node="${esc(b.id)}" ${i===a.length-1?'aria-current="location"':''}>${esc(b.title)}</button>`).join('');
  }
  function clearDetail(){
    retainDraft();selected='';const pane=$('#memory-detail-pane');if(!pane)return;
    pane.classList.remove('is-visible');pane.innerHTML=`<div class="memory-detail-placeholder">${icon('doc')}<h2>每一条记忆，都有来处</h2><p>选择内容查看全文、直接编辑，或告诉 AI 要修改哪一部分。</p></div>`;
  }
  function retainDraft(){
    const form=$('#memory-inline-editor');if(form)drafts.set(form.dataset.memoryId,{content:form.elements.content.value,version:Number(form.dataset.version)});
  }
  function detail(id){
    retainDraft();selected=id;list();const m=rows.memories.find(m=>m.id===id),p=rows.passages?.find(p=>p.id===id);
    const pane=$('#memory-detail-pane');if(!m&&!p){pane.innerHTML='<p class="muted">此条目已变化，请刷新目录。</p>';return;}
    pane.innerHTML=`<div class="memory-detail-heading"><span class="memory-detail-tag">${m?esc(kinds[m.kind]):'资料知识'}</span><button class="icon-button" data-tree-action="close-detail" aria-label="关闭详情">×</button></div><h2>${m?'记忆详情':esc(p.title)}</h2><p class="small muted">${m?'第 '+m.version+' 版 · '+date(m.updated_at):esc(p.locator)+' · 原文位置 '+p.start_offset}</p><div class="memory-detail-text memory-content">${esc(m?m.content:p.content)}</div>${m?`<div class="memory-detail-buttons"><button class="button primary" data-tree-action="edit-inline">${icon('edit')} 直接编辑</button><button class="button" data-memory-assist="open" data-id="${esc(id)}">AI 修改</button></div><p class="memory-detail-note">${esc(states[m.state]||'已保存')} · ${esc(m.scope==='project'?(rows.projects.find(p=>p.id===m.project_id)?.name||'所属项目'):m.scope==='topic'?m.topic:'跨项目通用')}<br>AI 按当前问题选择相关记忆。</p><button class="memory-detail-link" data-memory-studio="detail" data-id="${esc(id)}">查看来源与修改历史 →</button><details class="memory-detail-more"><summary>位置与更多操作</summary><div class="stack"><button class="button small" data-tree-action="move">移动到…</button><button class="button small" data-memory-action="edit" data-id="${esc(id)}">分类、范围与有效期</button>${m.review_status==='accepted'?`<button class="button small" data-memory-action="toggle" data-id="${esc(id)}">${m.active&&m.status==='active'?'停用':'启用'}</button>`:''}<button class="button small danger" data-memory-action="delete" data-id="${esc(id)}">遗忘这条记忆</button></div></details>`:`<p class="memory-detail-note">此片段自动跟随原资料更新。资料中的陈述保留来源身份，不能成为用户偏好或越过访问范围。</p><button class="memory-detail-link" data-tree-action="open-source">查看原始资料 →</button>`}`;
    pane.classList.add('is-visible');
  }
  async function render(){
    clearTimeout(timer);
    const user=current(),ticket=++revision,ui=captureUiContext(state);if(!user||location.hash!=='#memory')return;
    if(!$('#memory-shell')||!$('.memory-tree-page'))$('#content').innerHTML=frame();
    try{
      const [start,data]=await Promise.all([api('/memory/tree'),api('/memory/tree/entries?'+new URLSearchParams({...(node?{node_id:node}:{}),q:query,offset:page*50,limit:50}))]);
      if(user!==current()||ticket!==revision||!ui.sameRoute())return;
      summary=start;root=start.root_id;if(!node)node=root;for(const n of start.nodes)tree.set(n.id,n);
      rows=data;onCatalog(rows);nav();breadcrumbs();list();
      $('#memory-tree-counts').textContent=`${start.source_passages} 个资料片段 · 自动分类与版本跟踪`;
      $('#memory-short-count').textContent=start.session_count||'';
      $('#memory-auto-mode').textContent={auto:'AI 自动维护',review:'AI 自动维护',manual:'手动积累',off:'记忆已暂停'}[rows.settings.mode]||'AI 自动维护';
      $('#memory-management').innerHTML=studio.panel(rows);
      if(selected&&!$('#memory-inline-editor'))detail(selected);
      if(!expanded.size){const first=start.nodes.find(n=>n.node_key==='layer:long');if(first)await children(first.id);}
    }catch(error){if(user===current()&&ticket===revision&&ui.sameRoute())toast(error.message,true);}
  }
  async function sessions(){
    clearTimeout(timer);
    const user=current(),ticket=++revision,view=captureUiContext(state);clearDetail();mode='session';const result=await api('/memory/session-items?limit=100');
    if(user!==current()||ticket!==revision||!view.sameRoute()||!$('#memory-items'))return;
    $('#memory-breadcrumbs').innerHTML='<span aria-current="location">会话与工作记忆</span>';
    $('#memory-match-count').textContent=`${result.total??result.items.length} 条会话条件`;
    $('#memory-pagination').innerHTML='';
    $('#memory-items').innerHTML=result.items.map(s=>`<article class="memory-session-entry"><div class="memory-row-meta"><span>${esc(s.title)}</span><span>${s.lifetime==='turn'?'仅本轮':'本会话'}</span></div><p class="memory-content">${esc(s.content)}</p><div class="memory-detail-buttons"><a class="button small" href="#chat/${encodeURIComponent(s.conversation_id)}">继续对话</a><button class="button small" data-memory-studio="working" data-id="${esc(s.conversation_id)}">目标与工作记录</button><button class="button small" data-memory-life="edit-session" data-id="${esc(s.id)}">编辑条件</button></div></article>`).join('')||'<div class="memory-tree-empty"><h2>暂时没有会话条件</h2><p>短期目标与临时要求会自动保留在相应会话中，过期后自动清理。</p></div>';
  }
  function inlineEdit(){
    const m=rows.memories.find(m=>m.id===selected);if(!m)return;const draft=drafts.get(m.id);
    $('#memory-detail-pane').innerHTML=`<form id="memory-inline-editor" class="stack" data-memory-id="${esc(m.id)}" data-version="${draft?.version||m.version}"><h2>编辑记忆</h2><p class="small muted">你的修改会受到保护，历史版本可追溯。</p><label class="field">正文<textarea name="content" required maxlength="2000" rows="12">${esc(draft?.content??m.content)}</textarea></label><div class="memory-detail-buttons"><button class="button primary" type="submit">保存</button><button class="button" type="button" data-tree-action="cancel-edit">取消</button></div></form>`;
    $('#memory-inline-editor textarea').focus();
    $('#memory-inline-editor').addEventListener('submit',async e=>{
      e.preventDefault();const view=captureUiContext(state,e.currentTarget),form=e.currentTarget;form.inert=true;
      const payload=Object.fromEntries(['scope','project_id','topic','kind','source_conversation_id','pinned','version','semantic_key','valid_from','expires_at','labels'].map(k=>[k,m[k]]));
      try{await write('/memory/items/'+m.id,{...payload,version:Number(form.dataset.version),content:new FormData(form).get('content'),active:m.review_status==='pending'?true:!!m.active,locked:true},'PUT');drafts.delete(m.id);if(view.sameRoute()){form.remove();await render();}if(view.sameUser())toast('修改已保存。');}
      catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  function folder(){
    const view=captureUiContext(state);showDialog('新建子目录',`<form id="memory-folder-form" class="stack"><p class="small muted">在当前目录下创建。记忆默认由 AI 整理；你也可以自由安排。</p><label class="field">名称<input name="title" required maxlength="60"></label><div class="form-footer"><button class="button primary" type="submit">创建目录</button></div></form>`);
    $('#memory-folder-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,dialog=captureUiContext(state,form);form.inert=true;try{await api('/memory/tree/folders',{method:'POST',json:{parent_id:node||root,title:new FormData(form).get('title')}});if(dialog.sameDialog())$('#dialog').close();if(view.sameRoute()){await children(node||root);await render();}}catch(error){if(dialog.sameUser())toast(error.message,true);}finally{form.inert=false;}});
  }
  function locations(selectedNode){
    const nodes=[{id:root,title:'全部记忆'},...[...tree.values()].filter(n=>n.id!==root)];
    return nodes.map(n=>`<option value="${esc(n.id)}" ${n.id===selectedNode?'selected':''}>${esc(n.title)}</option>`).join('');
  }
  function moveEntry(){
    const m=rows.memories.find(m=>m.id===selected);if(!m)return;
    showDialog('移动记忆',`<form id="memory-move-form" class="stack"><p class="small muted">目录用于整理。原来的项目、专题和访问范围保持不变。</p><label class="field">放入目录<select name="destination">${locations(node)}</select></label><p class="small muted">可先在左侧展开需要的目录，它们会出现在这里。</p><div class="form-footer"><button class="button primary" type="submit">移动</button></div></form>`);
    $('#memory-move-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,view=captureUiContext(state,form);form.inert=true;try{await write('/memory/items/'+m.id+'/placement',{node_id:new FormData(form).get('destination'),version:m.version},'PUT');if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render();if(view.sameUser())toast('目录已更新。');}catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}});
  }
  function editFolder(){
    const item=tree.get(node);if(!item||item.system){toast('系统目录会自动维护；可在目录下添加自己的子目录。');return;}
    showDialog('编辑目录',`<form id="memory-folder-edit" class="stack"><label class="field">名称<input name="title" required maxlength="60" value="${esc(item.title)}"></label><label class="field">上级目录<select name="parent_id">${locations(item.parent_id)}</select></label><div class="form-footer"><button class="button primary" type="submit">保存</button></div></form>`);
    $('#memory-folder-edit').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,view=captureUiContext(state,form);form.inert=true;try{const data=await api('/memory/tree/folders/'+item.id,{method:'PUT',json:{title:new FormData(form).get('title'),parent_id:new FormData(form).get('parent_id'),version:item.version}});tree.set(data.id,{...tree.get(data.id),...data});if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render();}catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}});
  }
  document.addEventListener('input',e=>{if(e.target.id!=='memory-search'||!$('.memory-tree-page'))return;query=e.target.value;page=0;mode='tree';clearTimeout(timer);timer=setTimeout(render,250);});
  document.addEventListener('keydown',async e=>{
    if(!e.target.closest('#memory-tree-nav'))return;
    const buttons=[...document.querySelectorAll('#memory-tree-nav [data-tree-node]')],i=buttons.indexOf(e.target),id=e.target.dataset.treeNode;
    if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const n={ArrowDown:Math.min(i+1,buttons.length-1),ArrowUp:Math.max(i-1,0),Home:0,End:buttons.length-1}[e.key];buttons[n]?.focus();}
    if(e.key==='ArrowRight'&&id){e.preventDefault();const child=[...tree.values()].find(n=>n.parent_id===id);if(expanded.has(id)&&child){document.querySelector(`[data-tree-node="${child.id}"]`)?.focus();}else if(tree.get(id)?.children){await children(id);document.querySelector(`[data-tree-node="${id}"]`)?.focus();}}
    if(e.key==='ArrowLeft'&&id){e.preventDefault();if(expanded.has(id)){expanded.delete(id);nav();document.querySelector(`[data-tree-node="${id}"]`)?.focus();}else document.querySelector(`[data-tree-node="${tree.get(id)?.parent_id||root}"]`)?.focus();}
  });
  document.addEventListener('focusin',e=>{if(!e.target.matches('#memory-tree-nav [data-tree-node]'))return;for(const b of document.querySelectorAll('#memory-tree-nav [data-tree-node]'))b.tabIndex=b===e.target?0:-1;});
  document.addEventListener('click',async e=>{
    if(!e.target.closest('.memory-tree-page'))return;
    const target=e.target.closest('[data-tree-node],[data-tree-expand],[data-tree-record],[data-tree-action],[data-tree-more]');if(!target||target.disabled)return;
    const view=captureUiContext(state,target);target.disabled=true;
    try{
      if(target.dataset.treeNode){clearDetail();node=target.dataset.treeNode;mode='tree';page=0;await render();if(tree.get(node)?.children&&!expanded.has(node))await children(node);}
      else if(target.dataset.treeMore){await children(target.dataset.treeMore,more.get(target.dataset.treeMore)||0);}
      else if(target.dataset.treeExpand){const id=target.dataset.treeExpand;if(expanded.has(id)){expanded.delete(id);nav();}else await children(id);}
      else if(target.dataset.treeRecord)detail(target.dataset.treeRecord);
      else switch(target.dataset.treeAction){
        case 'refresh':mode==='session'?await sessions():await render();break;
        case 'previous':page=Math.max(0,page-1);await render();break;
        case 'next':page++;await render();break;
        case 'sessions':await sessions();break;
        case 'folder':folder();break;
        case 'folder-edit':editFolder();break;
        case 'edit-inline':inlineEdit();break;
        case 'cancel-edit':drafts.delete(selected);$('#memory-inline-editor')?.remove();detail(selected);break;
        case 'close-detail':clearDetail();list();break;
        case 'move':moveEntry();break;
        case 'open-source':{const p=rows.passages.find(p=>p.id===selected);const d=await api('/memory/passages/'+encodeURIComponent(p.id));if(view.sameRoute()&&selected===p.id&&d.href)location.hash=d.href;break;}
      }
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  return {render,write,projectDeleted(){node='';page=0;selected='';tree.clear();expanded.clear();}};
}
