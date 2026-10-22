import {captureUiContext} from './ui-request.js';
import {moveSelection} from './continuity.js';
import {createMemoryIntents} from './memory-intents.js';

const views={all:'全部记忆',pending:'待核对',attention:'需要更新',session:'会话暂存',activity:'整理记录'};
const kinds={preference:'偏好',constraint:'约束',decision:'决定',fact:'本人信息',episode:'经历',skill:'方法',intention:'计划',summary:'概览'};
const states={active:'正常使用',pending:'等待本人核对',conflict:'存在不同说法',needs_review:'需要重新确认',cooling:'已冷却',source_changed:'来源已变化',archived:'已归档',inactive:'已停用',expired:'已过期',scheduled:'尚未生效'};
const eventNames={created:'形成记忆',promoted:'长期保存',cooling:'进入冷却',feedback:'使用反馈',forgotten:'主动遗忘',forgotten_all:'清空记忆',configured:'人工调整',forgotten_session:'会话遗忘',reflected:'复盘提议',session_edited:'会话修订',reflection_retry:'确认重试复盘'};
const stamp=value=>value?new Date(value*1000).toLocaleString():'尚无记录';

export function createMemoryWorkbench({state,api,esc,icon,studio,onCatalog,toast,ask}){
  const $=selector=>document.querySelector(selector);
  let owner=null,view='all',scope='all',project='',kind='all',tier='all',query='',page=0;
  let catalog={projects:[],memories:[]},health=null,lifecycle=null,request=0,controller=null,timer=null;
  let selection=new Map(),undo=null,eventCursor=null,eventRows=[],loadingEvents=false;
  const intents=createMemoryIntents();
  const button=(text,action,extra='')=>`<button type="button" class="button small" data-memory-work="${action}" ${extra}>${text}</button>`;
  function currentOwner(){
    const id=state.session?.user?.id;
    if(id!==owner){owner=id;view='all';scope='all';project='';kind='all';tier='all';query='';page=0;selection.clear();undo=null;eventRows=[];eventCursor=null;}
    return id;
  }
  async function write(path,payload,method='POST'){
    const id=currentOwner(),headers=await intents.headers(id,method+path,payload);
    if(id!==state.session?.user?.id)throw Error('账号已变化，本次操作未继续。');
    const timeout=new AbortController(),timer=setTimeout(()=>timeout.abort(),25000);
    try{return await api(path,{method,json:payload,headers,signal:timeout.signal});}
    catch(error){if(error.status===0){const uncertain=new Error('本次操作结果尚未确认，请重试同一操作，或重新载入核对。');uncertain.status=0;throw uncertain;}throw error;}
    finally{clearTimeout(timer);}
  }
  function frame(){
    return `<div class="memory-page memory-workbench" id="memory-shell">
      <header class="memory-workbench-head"><div><a class="small muted" href="#settings">个人与账号</a><h1>我的记忆</h1><p class="muted">查看与修订偏好、项目条件和会话进展。</p></div><button type="button" class="button primary" data-memory-action="new">${icon('plus')} 新建记忆</button></header>
      <section id="memory-overview" class="memory-overview" aria-label="记忆状态概览"></section>
      <div id="memory-management"></div>
      <div class="memory-workbench-tabs tabs" role="tablist" aria-label="记忆工作区">${Object.entries(views).map(([key,label])=>`<button type="button" class="tab" role="tab" data-memory-view="${key}" id="memory-tab-${key}" aria-controls="memory-pane" aria-selected="${key===view}" tabindex="${key===view?0:-1}">${label}<span data-view-count="${key}"></span></button>`).join('')}</div>
      <div id="memory-feedback" class="memory-workbench-feedback" role="status" hidden></div>
      <div class="memory-workbench-layout"><aside id="memory-scope-rail" class="memory-scope-rail" aria-label="按范围浏览"></aside>
        <section id="memory-pane" class="memory-pane" role="tabpanel" aria-labelledby="memory-tab-${view}" tabindex="0">
          <div class="memory-query-bar"><label class="memory-search-box">${icon('search')}<span class="sr-only">查找记忆</span><input type="search" id="memory-search" placeholder="查找内容、项目或标签" maxlength="1000" value="${esc(query)}"></label><label class="memory-kind-filter"><span class="sr-only">记忆类型</span><select id="memory-kind"><option value="all">所有类型</option>${Object.entries(kinds).map(([key,label])=>`<option value="${key}" ${kind===key?'selected':''}>${label}</option>`).join('')}</select></label><label class="memory-tier-filter"><span class="sr-only">记忆层级</span><select id="memory-tier"><option value="all">所有层级</option><option value="long_term" ${tier==='long_term'?'selected':''}>长期记忆</option><option value="episodic" ${tier==='episodic'?'selected':''}>经历记录</option></select></label></div>
          <div class="memory-results-heading"><p id="memory-match-count" class="small muted" role="status">正在载入记忆…</p><label id="memory-select-page" class="check"><input type="checkbox" id="memory-select-all"><span>选择本页</span></label></div>
          <div id="memory-batch-bar" class="memory-batch-bar" hidden></div>
          <div id="memory-items" class="memory-items"></div><div id="memory-pagination" class="memory-pagination"></div>
        </section></div></div>`;
  }
  function overview(){
    const counts=catalog.state_counts||{},attention=health?.attention??['conflict','needs_review','cooling','source_changed','expired'].reduce((n,key)=>n+(counts[key]||0),0);
    const cells=[['active','已启用',counts.active||0,'按问题和范围选用'],['pending','待核对',counts.pending||0,'推断与新归纳先确认'],['attention','需要更新',attention,'检查时效、冲突与来源'],['session','会话暂存',health?.session_count??catalog.session_count??0,'保留本轮与会话条件']];
    $('#memory-overview').innerHTML=cells.map(([key,label,value,note])=>`<div class="memory-stat"><span>${label}</span><strong>${Number(value)}</strong><small>${note}</small></div>`).join('');
    const numbers={all:catalog.total,pending:counts.pending||0,attention,session:health?.session_count??catalog.session_count??0};
    for(const element of document.querySelectorAll('[data-view-count]'))element.textContent=numbers[element.dataset.viewCount]??'';
    const toolsOpen=!!$('#memory-management .memory-tools')?.open;
    $('#memory-management').innerHTML=studio.panel(catalog);
    $('#memory-management .memory-tools').open=toolsOpen;
    const rail=$('#memory-scope-rail');rail.hidden=['session','activity'].includes(view);
    rail.innerHTML=`<div class="memory-rail-heading"><strong>使用范围</strong><button type="button" class="icon-button" data-memory-action="project-new" aria-label="新建项目">${icon('plus')}</button></div><nav class="memory-rail-nav" aria-label="记忆范围">${[['all','全部范围',catalog.total||0],['global','通用',catalog.counts?.global||0],['project','项目',catalog.counts?.project||0],['topic','专题',catalog.counts?.topic||0]].map(([key,label,count])=>`<button type="button" data-memory-scope="${key}" aria-pressed="${scope===key&&!project}">${icon(key==='all'?'grid':'doc')}<span>${label}</span><small>${count}</small></button>`).join('')}</nav><details class="memory-project-navigation" open><summary>我的项目 <span>${catalog.projects.length}</span></summary><div class="memory-project-branches">${catalog.projects.map(p=>`<div><button type="button" data-memory-project-filter="${esc(p.id)}" aria-pressed="${project===p.id}" title="${esc(p.description||p.name)}">${esc(p.name)}</button><button type="button" class="memory-project-edit icon-button" data-memory-action="project-edit" data-id="${esc(p.id)}" aria-label="编辑项目 ${esc(p.name)}">${icon('edit')}</button></div>`).join('')||'<p class="small muted">课程、比赛和申请可以分别建项目。</p>'}</div></details><p class="small muted memory-scope-hint">范围决定在哪里可用，是否采用还取决于当前问题。</p>`;
    for(const tab of document.querySelectorAll('[data-memory-view]')){const active=tab.dataset.memoryView===view;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
    $('#memory-pane').setAttribute('aria-labelledby','memory-tab-'+view);
    $('.memory-workbench-layout').classList.toggle('memory-wide-pane',rail.hidden);
    moveSelection($('.memory-workbench-tabs'));
    for(const element of document.querySelectorAll('.memory-kind-filter,.memory-tier-filter,#memory-select-page'))element.hidden=['session','activity'].includes(view);
    $('.memory-query-bar').hidden=view==='activity';
  }
  function cards(items){
    return items.map(item=>`<article class="memory-card memory-record ${item.state!=='active'?'memory-inactive':''}" data-memory-record="${esc(item.id)}"><div class="memory-record-top"><label class="memory-record-select"><input type="checkbox" data-memory-select="${esc(item.id)}" ${selection.has(item.id)?'checked':''}><span class="sr-only">选择${esc(item.content.slice(0,24))}</span></label><span class="memory-status memory-status-${esc(item.state)}">${esc(states[item.state]||'待检查')}</span><span class="memory-record-kind">${esc(kinds[item.kind])}</span></div><p class="memory-content memory-record-content">${esc(item.content)}</p><p class="memory-record-scope">${icon('doc')}${esc(item.scope==='project'?(catalog.projects.find(p=>p.id===item.project_id)?.name||'所属项目'):item.scope==='topic'?'专题 · '+item.topic:'跨项目通用')}<span>${item.tier==='episodic'?'经历记录':'长期记忆'}</span></p>${studio.meta(item)}${item.state==='conflict'?'<p class="memory-conflict">同一范围存在不同说法，确认前暂停调用。</p>':''}<div class="memory-record-footer"><small>第 ${item.version} 版 · ${esc(stamp(item.updated_at))}</small><div class="memory-record-main-actions"><button type="button" class="button small" data-memory-action="edit" data-id="${esc(item.id)}">编辑</button><button type="button" class="button small" data-memory-assist="open" data-id="${esc(item.id)}">AI 修改</button><button type="button" class="button small" data-memory-studio="detail" data-id="${esc(item.id)}">来源与历史</button></div></div>${studio.controls(item)}<details class="memory-record-more"><summary>管理这条记忆</summary><div class="memory-studio-actions">${item.review_status==='pending'?'':`<button type="button" class="button small" data-memory-action="toggle" data-id="${esc(item.id)}">${item.active&&item.status==='active'?'停用':'重新确认使用'}</button>`}${item.state==='conflict'?`<button type="button" class="button small" data-memory-action="resolve" data-id="${esc(item.id)}">保留此条并停用冲突项</button>`:''}<button type="button" class="button small danger" data-memory-action="delete" data-id="${esc(item.id)}">遗忘这条记忆</button></div></details></article>`).join('');
  }
  function empty(text,detail){return `<div class="memory-empty"><span class="empty-symbol">${icon('history')}</span><strong>${text}</strong><p>${detail}</p>${button(query?'清空查找':'查看全部记忆','clear')}</div>`;}
  function sessions(items){
    const names={goal:'会话目标',request:'本次请求',preference:'会话偏好',constraint:'会话约束',fact:'会话条件',decision:'本次决定',intention:'当前计划',episode:'本次经历'};
    return items.map(item=>`<article class="memory-session-entry memory-session-card"><div class="between"><strong>${esc(names[item.kind]||'会话片段')}</strong><span class="pill">${item.lifetime==='turn'?'仅本轮':'会话内'}</span></div><p class="memory-content">${esc(item.content)}</p><p class="small muted">${esc(item.title)} · 保留至 ${esc(stamp(item.expires_at))}${item.edited_by_user?' · 本人已修订':''}</p>${item.edited_by_user?`<details class="memory-policy"><summary>查看形成时的原话</summary><p class="memory-content">${esc(item.original_content)}</p></details>`:''}<div class="memory-studio-actions"><a class="button small" href="#chat/${encodeURIComponent(item.conversation_id)}">原对话</a><button type="button" class="button small" data-memory-life="edit-session" data-id="${esc(item.id)}">编辑条件</button>${item.promoted_id?'<span class="pill">已长期保存</span>':`<button type="button" class="button small" data-memory-life="promote" data-id="${esc(item.id)}">确认长期保存</button>`}<button type="button" class="button small" data-memory-life="forget-session" data-id="${esc(item.id)}">遗忘片段</button></div></article>`).join('');
  }
  function timeline(){
    const jobs=(lifecycle?.reflection_jobs||[]).map(job=>`<article class="memory-job"><div class="between"><strong>模型语义复盘</strong><span class="pill">${esc({queued:job.not_before>Date.now()/1000?'等待额度恢复':'等待空闲',running:'正在处理',done:'已完成',failed:'需要处理',cancelled:'条件已变化'}[job.state]||job.state)}</span></div><p class="small muted">${esc(stamp(job.created_at))} · ${job.proposal_count} 条待核对提议${job.not_before>Date.now()/1000?' · 最早 '+esc(stamp(job.not_before)):''}</p>${job.state==='failed'?`<p class="small">上次请求未完成，可能已产生费用；重新请求需要本人确认。</p><button type="button" class="button small" data-memory-life="retry-reflection" data-id="${esc(job.id)}" data-finished="${job.finished_at}">核对后重新请求</button>`:''}</article>`).join('');
    return `<div class="memory-activity"><div class="memory-activity-intro"><h2>形成、修订与整理</h2><p class="small muted">展示真实动作与来源检查结果。模型复盘${lifecycle?.settings?.semantic_reflection?'已开启':'默认关闭'}，本地整理单独运行。</p>${button('检查保留期与晋升','maintain')}</div>${health?`<div class="memory-quality-facts"><span>有来源关联 <strong>${health.with_evidence}</strong></span><span>本人锁定 <strong>${health.human_locked}</strong></span><span>自动记录待补来源 <strong>${health.automatic_without_evidence}</strong></span><span>失败本地作业 <strong>${health.jobs?.failed||0}</strong></span></div>`:''}${jobs?'<div class="memory-jobs">'+jobs+'</div>':''}<ol class="memory-timeline">${eventRows.map(event=>`<li><span class="memory-timeline-dot" aria-hidden="true"></span><time datetime="${new Date(event.created_at*1000).toISOString()}">${esc(stamp(event.created_at))}</time><div><strong>${esc(eventNames[event.event]||'记忆管理')}</strong><p>${esc(event.reason)}</p></div></li>`).join('')}</ol>${eventRows.length?'':'<p class="muted">还没有形成或修订记录。</p>'}${eventCursor?button('加载更早的记录','older-events'):''}</div>`;
  }
  function batchBar(){
    const box=$('#memory-batch-bar');if(!box)return;box.hidden=selection.size===0;
    box.innerHTML=`<strong>已选 ${selection.size} 条</strong><div>${[['archive','归档'],['activate','重新确认使用'],['lock','锁定'],['unlock','解锁'],['forget','遗忘']].map(([key,label])=>button(label,'batch',`data-operation="${key}"`)).join('')}${button('取消选择','clear-selection')}</div>`;
    const all=$('#memory-select-all');if(all){all.checked=catalog.memories.length>0&&selection.size===catalog.memories.length;all.indeterminate=selection.size>0&&!all.checked;}
  }
  function notice(text,error=false,allowUndo=false){
    const element=$('#memory-feedback');if(!element)return;element.hidden=false;element.classList.toggle('is-error',error);
    element.innerHTML=`<span>${esc(text)}</span>${allowUndo?button('撤销本次归档','undo'):''}`;
  }
  async function render(){
    const id=currentOwner(),ticket=++request,generation=state.renderId;
    if(location.hash!=='#memory')return;
    clearTimeout(timer);controller?.abort();controller=new AbortController();const signal=controller.signal;
    if(!$('#memory-shell')){$('#content').innerHTML=frame();$('#memory-items').innerHTML='<p class="memory-loading" role="status">正在读取你的记忆…</p>';}
    const pane=$('#memory-pane');pane.setAttribute('aria-busy','true');
    try{
      const params=new URLSearchParams({q:query,scope,kind,tier,limit:'50',offset:String(page*50),status:['pending','attention'].includes(view)?view:'all'});
      if(project)params.set('project_id',project);
      const results=await Promise.allSettled([api('/memory?'+params,{signal}),api('/memory/health',{signal}),view==='activity'?api('/memory/lifecycle',{signal}):Promise.resolve(null),view==='activity'?api('/memory/events',{signal}):view==='session'?api('/memory/session-items?'+new URLSearchParams({q:query,limit:'50',offset:String(page*50)}),{signal}):Promise.resolve(null)]);
      if(ticket!==request||id!==state.session?.user?.id||generation!==state.renderId||location.hash!=='#memory')return;
      if(results[0].status==='rejected')throw results[0].reason;
      catalog=results[0].value;onCatalog(catalog);health=results[1].status==='fulfilled'?results[1].value:null;
      if(results[2].status==='fulfilled'&&results[2].value)lifecycle=results[2].value;
      if(['activity','session'].includes(view)&&results[3].status==='rejected')throw results[3].reason;
      if(view==='activity'&&results[2].status==='rejected')throw results[2].reason;
      const focused=document.activeElement;
      const restoreFocus=focused?.closest('#memory-management,#memory-items,#memory-pagination,#memory-scope-rail');
      const focusAttributes=restoreFocus?[...focused.attributes].filter(attribute=>attribute.name.startsWith('data-')).map(attribute=>[attribute.name,attribute.value]):[];
      const openRecords=[...document.querySelectorAll('[data-memory-record]')].map(element=>[element.dataset.memoryRecord,[...element.querySelectorAll(':scope > details')].map(details=>details.open)]);
      overview();
      let matched=catalog.matched;
      if(view==='activity'){
        eventRows=results[3].value.items;eventCursor=results[3].value.next_cursor;$('#memory-items').innerHTML=timeline();
        $('#memory-match-count').textContent='记录按时间排列；不保留已遗忘的正文。';
      }else if(view==='session'){
        const result=results[3].value;matched=result.matched;$('#memory-items').innerHTML=sessions(result.items)||empty('当前没有会话片段','临时要求会保留在所属会话；到期后退出使用。');
        $('#memory-match-count').textContent=`${matched} 个会话片段 · 每页最多 50 个`;
      }else{
        const live=new Map(catalog.memories.map(item=>[item.id,item]));selection=new Map([...selection].filter(([key,item])=>live.get(key)?.version===item.version));
        $('#memory-items').innerHTML=cards(catalog.memories)||empty(query?'没有匹配的记忆':view==='pending'?'暂时没有待核对提议':view==='attention'?'当前没有需要更新的记录':'让重要的条件，有处可寻',query?'试试其他关键词，或清空查找。':'可以保存偏好与项目条件，也可以先从对话中形成记忆。');
        $('#memory-match-count').textContent=`共 ${matched} 条${scope!=='all'||query?'匹配记忆':''} · 第 ${page+1} 页`;
      }
      $('#memory-items').classList.toggle('memory-activity-list',view==='activity');
      $('#memory-pagination').innerHTML=view==='activity'||matched<=50?'':`${button('上一页','page','data-step="-1" '+(page===0?'disabled':''))}<span>第 ${page+1} / ${Math.max(1,Math.ceil(matched/50))} 页</span>${button('下一页','page','data-step="1" '+((page+1)*50>=matched?'disabled':''))}`;
      batchBar();
      for(const [key,values] of openRecords){const card=document.querySelector('[data-memory-record="'+CSS.escape(key)+'"]');if(card)[...card.querySelectorAll(':scope > details')].forEach((details,index)=>{details.open=!!values[index];});}
      if(restoreFocus&&focusAttributes.length&&(!focused.isConnected||document.activeElement===document.body)){
        const selector=focusAttributes.map(([key,value])=>'['+key+'="'+CSS.escape(value)+'"]').join('');
        const replacement=$('#memory-shell')?.querySelector(selector);if(replacement)replacement.focus({preventScroll:true});else pane.focus({preventScroll:true});
      }
      if(!health)notice('记忆列表已载入，状态检查暂时不可用；可以稍后重新载入。',true);
    }catch(error){
      if(ticket===request&&id===state.session?.user?.id&&generation===state.renderId&&location.hash==='#memory'){
        $('#memory-items').innerHTML=`<div class="memory-load-error" role="alert"><strong>暂时无法载入记忆</strong><p>${esc(error.message)}</p>${button('重新载入','reload')}</div>`;
      }
    }finally{if(ticket===request&&pane.isConnected)pane.setAttribute('aria-busy','false');}
  }
  function change(next){view=next;page=0;selection.clear();undo=null;const feedback=$('#memory-feedback');if(feedback)feedback.hidden=true;render();}
  async function batch(action,entries,reverse=false){
    const ui=captureUiContext(state),payload={action,items:entries.map(({id,version})=>({id,version})).sort((a,b)=>a.id.localeCompare(b.id))};
    if(!entries.length)return;
    if(action==='forget'&&!await ask('遗忘选中的记忆',`将遗忘 ${entries.length} 条及依赖内容，并撤销相关旧回答的后续记忆用途。原聊天原文和离线备份仍保留。此操作不能通过撤销归档恢复。`,'确认遗忘'))return;
    if(!ui.sameUser())return;
    const bar=$('#memory-batch-bar');if(bar)bar.inert=true;
    try{
      const result=await write('/memory/bulk',payload);
      if(!ui.sameRoute())return;
      selection.clear();undo=action==='archive'&&entries.every(item=>item.active&&item.status==='active'&&item.state==='active')?{items:result.items,owner,expires:Date.now()+60000}:null;
      await render();
      if(ui.sameRoute())notice(reverse?'已撤销本次归档。':`已${{archive:'归档',activate:'重新确认使用',lock:'锁定',unlock:'解锁',forget:'遗忘'}[action]} ${result.count} 条记忆。`,false,!!undo);
    }catch(error){
      if(!ui.sameRoute())return;
      notice(error.status===0?'操作结果尚未确认，请重试同一操作或重新载入核对；不会重复写入。':error.message,true);
      if(error.status===409){selection.clear();await render();}
    }finally{if(bar?.isConnected)bar.inert=false;}
  }
  document.addEventListener('input',event=>{
    if(event.target.id!=='memory-search'||!event.target.closest('#memory-shell'))return;
    query=event.target.value;page=0;selection.clear();clearTimeout(timer);controller?.abort();request++;
    timer=setTimeout(render,180);
  });
  document.addEventListener('change',event=>{
    if(!event.target.closest('#memory-shell'))return;
    if(event.target.id==='memory-kind'||event.target.id==='memory-tier'){kind=$('#memory-kind').value;tier=$('#memory-tier').value;page=0;selection.clear();render();}
    if(event.target.id==='memory-select-all'){
      selection=event.target.checked?new Map(catalog.memories.map(item=>[item.id,item])):new Map();
      for(const box of document.querySelectorAll('[data-memory-select]'))box.checked=selection.has(box.dataset.memorySelect);batchBar();
    }
    if(event.target.matches('[data-memory-select]')){
      const item=catalog.memories.find(item=>item.id===event.target.dataset.memorySelect);
      if(item){if(event.target.checked)selection.set(item.id,item);else selection.delete(item.id);batchBar();}
    }
  });
  document.addEventListener('keydown',event=>{
    if(!event.target.closest('.memory-workbench-tabs'))return;
    const tabs=[...document.querySelectorAll('[data-memory-view]')],index=tabs.findIndex(tab=>tab.dataset.memoryView===view);
    const next={ArrowRight:(index+1)%tabs.length,ArrowLeft:(index-1+tabs.length)%tabs.length,Home:0,End:tabs.length-1}[event.key];
    if(next===undefined)return;event.preventDefault();tabs[next].focus();change(tabs[next].dataset.memoryView);
  });
  document.addEventListener('click',async event=>{
    const root=event.target.closest('#memory-shell');if(!root)return;
    const tab=event.target.closest('[data-memory-view]');if(tab){change(tab.dataset.memoryView);return;}
    const filter=event.target.closest('[data-memory-scope]');if(filter){scope=filter.dataset.memoryScope;project='';page=0;selection.clear();await render();return;}
    const chosenProject=event.target.closest('[data-memory-project-filter]');if(chosenProject){scope='project';project=chosenProject.dataset.memoryProjectFilter;page=0;selection.clear();await render();return;}
    const target=event.target.closest('[data-memory-work]');if(!target||target.disabled)return;
    const action=target.dataset.memoryWork,context=captureUiContext(state,target);target.disabled=true;
    try{
      if(action==='reload')await render();
      else if(action==='stat')change(target.dataset.view);
      else if(action==='clear'){query='';scope='all';project='';kind='all';tier='all';$('#memory-search').value='';$('#memory-kind').value='all';$('#memory-tier').value='all';change('all');}
      else if(action==='page'){page=Math.max(0,page+Number(target.dataset.step));selection.clear();await render();}
      else if(action==='clear-selection'){selection.clear();for(const box of document.querySelectorAll('[data-memory-select]'))box.checked=false;batchBar();}
      else if(action==='batch')await batch(target.dataset.operation,[...selection.values()]);
      else if(action==='undo'&&undo&&undo.owner===state.session?.user?.id){if(Date.now()>undo.expires)notice('撤销时限已过，可以选中条目重新确认使用。',true);else await batch('activate',undo.items,true);}
      else if(action==='maintain'){await api('/memory/lifecycle/maintain',{method:'POST'});if(context.sameRoute())await render();}
      else if(action==='older-events'&&eventCursor&&!loadingEvents){
        const ui=captureUiContext(state);loadingEvents=true;
        try{const result=await api('/memory/events?cursor='+encodeURIComponent(eventCursor));if(ui.sameRoute()&&view==='activity'){eventRows.push(...result.items);eventCursor=result.next_cursor;$('#memory-items').innerHTML=timeline();}}finally{loadingEvents=false;}
      }
    }catch(error){if(context.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  return {render,write,projectDeleted(id){if(project===id){project='';page=0;selection.clear();undo=null;}}};
}
