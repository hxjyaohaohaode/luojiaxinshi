import {replacePageNavigation} from './page-navigation.js';
import {preserveChatViewport} from './chat-viewport.js';
import {ComposerAttachments,uploadAttachment} from './composer-attachments.js';
import {MaterialTreeState} from './workspace-tree-state.js';
import {createReplySpeech} from './speech.js';
import {brandMotion} from './motion.js';
import {searchControls,WorkspaceSearch,materialTree,materialFormats} from './workspace-search.js';
import {attachmentPreview} from './attachments.js';
import {dictate,finishDictation} from './dictation.js';
import {ConversationView} from './genui/chat-presenter.js';
import {StreamParser} from './genui/core.js';
import {streamChat} from './genui/transport.js';
import {branchPreview} from './branch-preview.js';
const $=(s,root=document)=>root.querySelector(s);
const $$=(s,root=document)=>[...root.querySelectorAll(s)];
const imageKinds=new Set(['png','jpg','jpeg','webp']);
const videoKinds=new Set(['mp4','webm']);

export function createChatUI({state,api,esc,icon,companion,greeting,toast,showDialog,ask,field,area,drafts,route,memoryUI}){
  const replySpeech=createReplySpeech({api,toast,owner:()=>state.session?.user?.id});
  const lastKey=()=>`luojia:last-chat:${state.session.user.id}`;
  const remember=id=>{try{if(id)localStorage.setItem(lastKey(),id);else localStorage.removeItem(lastKey());}catch{}};
  let current=null,historyItems=[],pollTimer,files=[],sending=false,materialRenderKey='',feedbackTimer;
  let presenter=null,streaming=null,paintFrame=0,hostArrangements=[],hostTasks=[];
  let submission=0,accepting=false,branchDraft=null;
  let attachments=null,creatingConversation=null,composerResize=null;
  let materialSearch=null,historySearch=null,materialMatches=null,historyMatches=[],historyPage=1;
  const materialTreeState=new MaterialTreeState();
  let materialInert=[],materialReturn=null,materialQuery="";
  function setMaterials(open,restore=true){
    const workspace=$('#chat-workspace'),panel=$('#chat-materials');
    materialInert.forEach(([node,previous])=>{if(node.isConnected)node.inert=previous;});materialInert=[];
    document.body.classList.remove('materials-open');
    if(!workspace||!panel)return;
    if(open)document.dispatchEvent(new CustomEvent('reply-materials-open'));preserveChatViewport($('#chat-thread'),()=>workspace.classList.toggle('show-materials',open));$('.materials-toggle')?.setAttribute('aria-expanded',String(open));
    if(open){
      materialReturn=document.activeElement;
      if(matchMedia('(max-width:1000px)').matches){materialInert=$$('.chat-main,.topbar,.sidebar,.mobile-bottom-nav,.workspace-chrome-toggle').map(node=>[node,node.inert]);materialInert.forEach(([node])=>node.inert=true);document.body.classList.add('materials-open');panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');}else{panel.setAttribute('role','complementary');panel.removeAttribute('aria-modal');}
      requestAnimationFrame(()=>$('.materials-close')?.focus({preventScroll:true}));
    }else{panel.removeAttribute('role');panel.removeAttribute('aria-modal');if(restore&&materialReturn?.isConnected)materialReturn.focus();materialReturn=null;}
  }
  document.addEventListener('keydown',event=>{
    if(!$('#chat-workspace.show-materials')||$('#dialog')?.open)return;
    if(event.key==='Escape'){event.preventDefault();setMaterials(false);}
    if(event.key==='Tab'&&document.body.classList.contains('materials-open')){const items=$$('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled)', $('#chat-materials')).filter(el=>el.getClientRects().length);if(!items.length)return;const first=items[0],last=items.at(-1);if(!$('#chat-materials').contains(document.activeElement)||(event.shiftKey&&document.activeElement===first)||(!event.shiftKey&&document.activeElement===last)){event.preventDefault();(event.shiftKey?last:first).focus();}}
  });
  window.addEventListener('hashchange',()=>setMaterials(false,false));
  document.addEventListener('reply-sources-open',()=>setMaterials(false,false));
  matchMedia('(max-width:1000px)').addEventListener('change',()=>{if($('#chat-workspace.show-materials'))setMaterials(true,false);});
  const call=(label,action,extra='',cls='')=>`<button type="button" class="button ${cls}" data-chat-action="${action}" ${{history:'aria-label="历史对话"',new:'aria-label="新对话"','toggle-materials':'aria-label="查看本次材料"'}[action]||''} ${extra}>${label}</button>`;
  const key=()=>branchDraft?'branch:'+branchDraft.originId+':'+branchDraft.messageId:current?'chat:'+current.id:'chat-new';
  const active=cid=>$('#chat-workspace')&&current?.id===cid;
  const sourceStatus=s=>s.status==='failed'?'读取失败':['mp4','webm','mov','avi','wmv','mp3','wav','m4a','ogg','flac'].includes(s.kind)?'原件收到了 · 还没读':imageKinds.has(s.kind)?'图片收到了 · 还没看':s.status==='review'?'已读取 · 建议对照原件':'文字已读取';
  const date=n=>new Date(n*1000).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});

  async function render(id,renderId,branchMessage=null){
    setMaterials(false,false);
    replySpeech.stop();
    let restored=null,catalog=null;
    if(branchMessage&&(!branchDraft||branchDraft.originId!==id||branchDraft.messageId!==branchMessage||branchDraft.owner!==state.session.user.id)){
      const parent=await api('/conversations/'+encodeURIComponent(id));if(renderId!==state.renderId)return;
      branchDraft=branchPreview(parent,branchMessage,state.session.user.id);
    }
    const preview=branchMessage?branchDraft?.preview:null;
    if(preview)id=null;
    else if(id==='new'){remember('new');id=null;}
    else if(!id){
      let recent;try{recent=localStorage.getItem(lastKey());}catch{}
      if(!recent){
        [catalog]=await Promise.all([api('/conversations'),drafts.load('chat-new')]);if(renderId!==state.renderId)return;
        if(!drafts.peek('chat-new').payload?.content)recent=catalog[0]?.id;
      }
      if(recent&&recent!=='new'){
        try{restored=await api('/conversations/'+encodeURIComponent(recent));if(renderId!==state.renderId)return;id=recent;replacePageNavigation('#chat/'+id);}
        catch(error){if(error.status!==404)throw error;remember(null);}
      }
    }
    if(id)remember(id);
    submission++;accepting=false;
    attachments?.dispose();attachments=null;creatingConversation=null;composerResize?.disconnect();
    streaming?.controller.abort();streaming=null;cancelAnimationFrame(paintFrame);paintFrame=0;presenter?.dispose();presenter=null;
    clearTimeout(pollTimer);clearTimeout(feedbackTimer);files=[];sending=false;materialQuery="";materialRenderKey='';materialMatches=null;materialSearch?.dispose();historySearch?.dispose();
    const results=await Promise.all([catalog||api('/conversations'),preview?Promise.resolve(preview):id?(restored||api('/conversations/'+encodeURIComponent(id))):Promise.resolve(null),drafts.load(preview?'branch:'+branchDraft.originId+':'+branchDraft.messageId:id?'chat:'+id:'chat-new'),state.session.genui?.enabled?api('/arrangements'):Promise.resolve([]),state.session.genui?.enabled?api('/tasks'):Promise.resolve([])]);
    if(renderId!==state.renderId)return;
    historyItems=results[0];current=results[1];hostArrangements=results[3];hostTasks=results[4];drafts.activate(key());
    $('#content').innerHTML=`<div id="chat-workspace" class="chat-workspace ${current?'has-conversation':''}">
      <div class="chat-main"><header class="chat-heading"><div><h1 id="conversation-title">${esc(current?.title||'和小信使聊聊')}</h1></div><div class="row compact-row">${call(icon('history')+'<span>历史对话</span>','history','','small')}${call(icon('plus')+'<span>新对话</span>','new','','small')}${call(icon('doc')+'<span>材料</span>','toggle-materials','aria-expanded="false" aria-controls="chat-materials"','small materials-toggle')}</div></header>
      <div class="chat-reading-area"><section class="chat-thread" id="chat-thread" aria-label="和小信使的对话" tabindex="0">${thread()}</section><nav id="chat-turn-rail" class="chat-turn-rail" aria-label="按轮次跳转对话" hidden></nav></div>
      <div class="chat-jump-row"><button type="button" id="chat-jump-latest" class="button small" hidden>回到最新 ↓</button></div>
      <form class="chat-composer" id="chat-composer" data-workspace-form="chat" data-cache-key="${key()}">
        <div id="composer-attachments" class="composer-attachments" aria-label="待发送附件" hidden></div>
        <input id="composer-file-input" type="file" multiple accept="${materialFormats}" hidden>
        <button type="button" class="icon-button composer-plus" data-chat-action="composer-menu" aria-label="添加附件与更多选项" aria-expanded="false" aria-controls="composer-menu">${icon('plus')}</button>
        <div class="composer-entry"><label for="chat-input" class="sr-only">给小信使的消息</label><textarea id="chat-input" name="content" rows="1" maxlength="6000" placeholder="写下问题…" aria-describedby="chat-shortcuts">${esc(drafts.peek(key()).payload?.content||'')}</textarea><button type="button" class="icon-button composer-voice" data-chat-action="dictate" aria-label="语音输入" aria-pressed="false">${icon('mic')}</button><button class="button primary send-button" type="submit" aria-label="发送消息" title="Enter 发送 · Shift + Enter 换行">${icon('arrow')}</button></div>
        <div class="composer-actions" id="composer-menu" hidden>${call(icon('upload')+' 添加文件与图片','pick-attachments','','small plain')}${call(icon('folder')+' 添加文件夹','upload','','small plain')}${call(icon('doc')+' 粘贴通知原文','paste-text','','small plain')}${call(icon('search')+' 查看与搜索材料','toggle-materials','','small plain')}${call('项目与记忆','context-settings','','small plain')}${call('记住我刚才说的','remember','','small plain')}</div>
        <span id="chat-shortcuts" class="sr-only">Enter 发送，Shift 加 Enter 换行。中文输入法选词时不会发送。</span>
        <div class="composer-status sr-only"><span class="autosave-status" role="status"></span><span id="chat-count">${current?.sources.length||0} 份材料 · 仅本人可见</span></div>
      </form>
      <div class="chat-footnote" role="status">${state.session.ai.configured?'回复由 AI 生成，可能有误，重要信息请以学校正式通知为准':'AI 还没有接通 <a href="#settings">去看看</a>'}</div>
      </div><button type="button" class="materials-scrim" data-chat-action="toggle-materials" aria-label="关闭材料面板" tabindex="-1"></button><aside id="chat-materials" class="chat-materials" aria-label="本次对话的材料"><div class="materials-heading"><h2>本次材料</h2><span class="small muted" id="material-total">0</span><button type="button" class="icon-button materials-close" data-chat-action="toggle-materials" aria-label="收起材料">${icon('close')}</button></div>${searchControls({id:"material",esc,icon,kinds:[...new Set(current?.sources.map(s=>s.kind)||[])].map(k=>[k,k.toUpperCase()])})}<div id="material-list"></div><div class="material-actions">${call(icon('plus')+' 添加材料','upload','','small')}${call('转为通知 '+icon('arrow'),'promote','','small primary')}</div>${current?`<div class="conversation-tools">${call('重命名','rename','','small plain')}${call('删除对话','delete','','small plain danger')}</div>`:''}</aside></div>`;
    // The workspace is light. Legacy answer-only themes cannot override its surface.
    $('#chat-thread').dataset.genuiTheme='light';
    const attachmentRender=state.renderId;
    attachments=new ComposerAttachments($('#composer-attachments'),{
      sources:current?.sources||[],ids:drafts.peek(key()).payload?.source_ids||[],
      upload:async(file,onProgress,signal)=>{
        if(!current||branchDraft){creatingConversation??=ensureConversation(attachmentRender).finally(()=>creatingConversation=null);await creatingConversation;}
        if(attachmentRender!==state.renderId||signal.aborted)throw Error('已离开当前对话');
        const cid=current.id,result=await uploadAttachment(cid,current.version,file,{csrf:state.session.csrf,signal,onProgress});
        if(attachmentRender===state.renderId&&active(cid)&&result.version>=current.version){current=result;materialMatches=null;update();}
        return {ids:result.uploaded_source_ids,sources:result.sources};
      },
      remove:async ids=>{for(const id of ids){if(current.messages.some(m=>m.attachments?.some(a=>a.id===id)))continue;current=await api(`/conversations/${current.id}/sources/${id}`,{method:'DELETE',json:{version:current.version}});}update();},
      open:(source,urlOnly)=>urlOnly?`/api/conversations/${current.id}/sources/${source.id}/download?preview=true`:preview(source.id),
      onChange:list=>{if(attachments===list){persist();updateComposerState();}}
    });
    $('#chat-thread').addEventListener('scroll',updateJump,{passive:true});$('#chat-jump-latest').addEventListener('click',()=>{const thread=$('#chat-thread');thread.scrollTop=thread.scrollHeight;updateJump();});
    materialSearch=new WorkspaceSearch($('[data-search-host="material"]'),{api,scope:"materials",conversationId:()=>current?.id,onResult:result=>{materialQuery=result.query||'';materialMatches=new Map(result.items.map(s=>[s.id,s]));materialRenderKey="";drawMaterials();},onError:message=>toast(message,true)});
    composerResize=new ResizeObserver(fitComposer);composerResize.observe($('.chat-main'));
    fitComposer();update();if(current?.processing)schedulePoll(current.id,state.renderId);
  }
  function thread(){
    if(!current?.messages.length)return `<div class="chat-welcome"><div class="welcome-mascot" data-orbit><span class="welcome-orbit orbit-one" aria-hidden="true"></span><span class="welcome-orbit orbit-two" aria-hidden="true"></span><span class="welcome-note note-one" aria-hidden="true">${icon('doc')}</span><span class="welcome-note note-two" aria-hidden="true">${icon('check')}</span>${companion('organize','chat-companion')}</div><h2>${greeting()}，${esc(state.session.user.profile.preferred_name||state.session.user.display_name)}。</h2><div class="scene-choices">${[
      ['doc','读懂一则通知','对象、材料、时间，一个都不漏','请帮我读懂这则通知，指出哪些条件还需要我核实。'],
      ['tasks','理清我的下一步','把要做的事，拆成小小的行动','请根据我上传的材料，帮我列出可以先开始的准备步骤。'],
      ['calendar','一起安排时间','分清正式期限和个人计划','请帮我区分材料中的正式截止时间和可以自己安排的时间。']
    ].map(([i,title,subtitle,prompt])=>`<button type="button" class="scene-choice" data-chat-action="prompt" data-prompt="${esc(prompt)}">${icon(i)}<strong>${title}</strong><span>${subtitle}</span>${icon('arrow')}</button>`).join('')}</div>${historyItems.length?`<div class="recent-chats"><div class="between"><span>接着上次聊</span>${call('全部对话','history','','small plain')}</div>${historyItems.slice(0,2).map(c=>`<a href="#chat/${c.id}">${icon('history')}<span>${esc(c.title)}</span><small>${date(c.updated_at)}</small>${icon('arrow')}</a>`).join('')}</div>`:''}</div>`;
    return '';
  }
  function update(){
    if(!$('#chat-workspace'))return;
    const threadElement=$('#chat-thread'),nearBottom=threadElement.scrollHeight-threadElement.scrollTop-threadElement.clientHeight<110;
    if(!current?.messages.length){presenter?.dispose();presenter=null;threadElement.innerHTML=thread();threadElement.scrollTop=0;}else{drawMessages();if(nearBottom)threadElement.scrollTop=threadElement.scrollHeight;}updateJump();
    $('#conversation-title').textContent=current?.title||'和小信使聊聊';
    $('#conversation-title').classList.remove('sr-only');
    if(current&&!$('.chat-heading [data-chat-action="new"]'))$('.chat-heading .row').insertAdjacentHTML('afterbegin',call(icon('plus')+'<span>新对话</span>','new','','small'));
    if(current&&!$('.conversation-tools'))$('#chat-materials').insertAdjacentHTML('beforeend',`<div class="conversation-tools">${call('重命名','rename','','small plain')}${call('删除对话','delete','','small plain danger')}</div>`);
    $('#chat-workspace').classList.toggle('has-conversation',!!current);
    $('#material-total').textContent=(current?.sources.length||0)+' 份';
    $('#chat-count').textContent=(current?.sources.length||0)+' 份材料 · 仅本人可见';
    drawMaterials();if(branchDraft)for(const b of $$('#material-list [data-chat-action=remove-source]'))b.disabled=true;
    fitComposer();const busy=current?.processing||sending;
    $('#chat-composer').classList.toggle('is-processing',!!busy);
    $('#chat-composer textarea').disabled=false;$('#chat-composer textarea').placeholder=busy?'补充条件，或调整方向…':'写下问题…';
    updateComposerState();
     $$('[data-chat-action="upload"],[data-chat-action="pick-attachments"],[data-chat-action="paste-text"],[data-chat-action="promote"]').forEach(b=>b.disabled=busy);
  }
  function drawMaterials(){
    const target=$('#material-list');if(!target)return;
    const all=current?.sources||[],matched=materialMatches?all.filter(s=>materialMatches.has(s.id)):all;
    const renderKey=JSON.stringify([current?.id,all,materialMatches&&[...materialMatches],!!current?.processing]);if(materialRenderKey===renderKey)return;materialRenderKey=renderKey;
    const kindSelect=$('[data-search-host="material"] [data-search-kind]'),selectedKind=kindSelect?.value||'';
    if(kindSelect){const kinds=[...new Set(all.map(s=>s.kind))];if(selectedKind&&!kinds.includes(selectedKind))kinds.push(selectedKind);kindSelect.innerHTML='<option value="">全部类型</option>'+kinds.map(k=>`<option value="${esc(k)}">${esc(k.toUpperCase())}</option>`).join('');kindSelect.value=selectedKind;}
    materialTreeState.update(target,{scope:current?.id,filtered:!!materialSearch?.hasFilters()},()=>{
    target.innerHTML=matched.length?materialTree(matched,{esc,icon,sourceStatus,cid:current.id,processing:current.processing,matches:materialQuery?materialMatches:null}):all.length?`<div class="material-empty">${brandMotion('search')}<strong>没有匹配的材料</strong><p>换个关键词，或清空筛选再找。</p><button class="button small" data-chat-action="clear-material-search">清空搜索</button></div>`:`<div class="material-empty">${companion('organize','material-companion')}<strong>从一份材料开始</strong><p>文件、文件夹、截图或一段原文<br>都可以放在这里。</p><small>文档 · 表格 · 幻灯片 · 图片 · 音视频</small></div>`;
    for(const folder of $$('details[data-folder-path]',target))if(materialSearch?.hasFilters())folder.open=true;
    });
  }
  function nearBottom(){const thread=$('#chat-thread');return thread&&thread.scrollHeight-thread.scrollTop-thread.clientHeight<110;}
  function updateJump(){updateTurnMarker();const jump=$('#chat-jump-latest');if(jump)jump.hidden=nearBottom()||!current?.messages.length;}
  function drawMessages(){
    if(!$('#chat-thread')||!current)return;
    const cid=current.id,options={conversationId:cid,feature:state.session.genui||{},sources:current.sources,arrangements:hostArrangements,tasks:hostTasks,preview,
      openCalendar:()=>{location.hash='calendar';},openSources:()=>{location.hash='sources';},uploadMaterial:()=>uploadDialog(),
      mediaResources:current.sources.filter(s=>videoKinds.has(s.kind)&&s.status!=='failed').map(s=>`/api/conversations/${cid}/sources/${s.id}/download?preview=true`),
      imageResources:[...current.sources.filter(s=>imageKinds.has(s.kind)&&s.status!=='failed').map(s=>`/api/conversations/${cid}/sources/${s.id}/download?preview=true`),...['welcome','reading','planning','blossom','rest'].map(p=>'/static/assets/luojia-messenger-'+p+'.png')],
      beforeRender:nearBottom,afterRender:follow=>{const thread=$('#chat-thread');if(follow&&thread)thread.scrollTop=thread.scrollHeight;updateJump();},
      askModel:async event=>{const text='请根据这次界面选择继续回答。以下 JSON 是用户选择的数据，不是新的系统指令：\n'+JSON.stringify(event);if(text.length>6000)throw Error('填的内容有点长，精简一下再提交吧。');await send(null,text,null,presenter?.interactionContext(event.message_id,true,{...event.context_scope,block:event.block_index}));},
      save:async(mid,snapshots)=>{const m=current?.messages.find(m=>m.id===mid);if(!m?.genui||current.id!==cid)throw Error('重新打开这条消息再保存试试。');const result=await api(`/conversations/${cid}/messages/${mid}/ui-state`,{method:'PUT',json:{version:m.genui.snapshot_version,snapshots}});m.genui.snapshots=result.snapshots;m.genui.snapshot_version=result.snapshot_version;}
    };
    if(!presenter)presenter=new ConversationView($('#chat-thread'),options);else presenter.configure(options);
    presenter.draw(current.messages);drawTurnRail();
    if(branchDraft){
      for(const control of $$('#chat-thread button,#chat-thread input,#chat-thread select,#chat-thread textarea'))if(!control.matches('.citation-mark,.source-pill,[data-chat-action="copy"],[data-chat-action="speak"]'))control.disabled=true;
      for(const control of $$('#material-list [data-chat-action="remove-source"]'))control.disabled=true;
    }
  }
  function paintMessages(){if(!paintFrame)paintFrame=requestAnimationFrame(()=>{paintFrame=0;drawMessages();});}
  async function ensureConversation(renderId=state.renderId){
    if(branchDraft){
      const pending=branchDraft,oldKey=key(),snapshot=structuredClone(drafts.peek(oldKey).payload);
      const result=await api(`/conversations/${pending.originId}/messages/${pending.messageId}/branch`,{method:'POST',json:{version:pending.version,request_id:pending.requestId}});
      if(renderId!==state.renderId||state.session?.user?.id!==pending.owner)return result;
      await drafts.load('chat:'+result.id);if(renderId!==state.renderId)return result;
      branchDraft=null;current=result;remember(result.id);replacePageNavigation('#chat/'+result.id);$('#content').dataset.page='chat/'+result.id;
      drafts.activate('chat:'+result.id);drafts.stage('chat:'+result.id,{content:$('#chat-input')?.value??snapshot?.content??''});drafts.stage(oldKey,{content:''});
      $('#chat-composer').dataset.cacheKey='chat:'+result.id;presenter?.dispose();presenter=null;update();
      return current;
    }
    if(current)return current;
    const snapshot=structuredClone(drafts.peek('chat-new').payload);
    const result=await api('/conversations',{method:'POST',json:{}});
    if(renderId!==state.renderId)return result;
    await drafts.load('chat:'+result.id);
    if(renderId!==state.renderId)return result;
    current=result;remember(result.id);replacePageNavigation('#chat/'+result.id);$('#content').dataset.page='chat/'+result.id;
    drafts.activate('chat:'+result.id);
    if(snapshot)drafts.stage('chat:'+result.id,snapshot);
    if(JSON.stringify(drafts.peek('chat-new').payload)===JSON.stringify(snapshot))drafts.stage('chat-new',{content:''});
    if($('#chat-composer'))$('#chat-composer').dataset.cacheKey='chat:'+result.id;
    return current;
  }
  function schedulePoll(cid,renderId){
    clearTimeout(pollTimer);pollTimer=setTimeout(async()=>{
      if(renderId!==state.renderId||!active(cid))return;
      try{const result=await api('/conversations/'+cid);if(renderId!==state.renderId||!active(cid))return;if(result.version>current.version||(result.version===current.version&&(result.processing||result.processing!==current.processing))){current=result;update();}if(current.processing)schedulePoll(cid,renderId);}
      catch(e){if(active(cid))toast(e.message,true);}
    },1400);
  }
  async function send(retryId,structuredText=null,regenerateId=null,structuredContext=null){
    const input=$('#chat-input'),inputView=state.renderId;
    if(accepting)throw Error('上一条还在发送，稍等一下再补充。');
    if(!retryId&&!regenerateId)await finishDictation(input);
    if(inputView!==state.renderId||input!==$('#chat-input'))return;
    const rawText=input.value,sourceIds=retryId||regenerateId?[]:attachments?.ids||[],text=structuredText??(rawText.trim()||(sourceIds.length?'请帮我理解这些材料，并整理当前能开始的下一步。':''));
    if(attachments?.busy||attachments?.failed)throw Error('等附件传完再发；没传上的可以重试或移除。');
    if(accepting)throw Error('上一条还在发送，稍等一下再补充。');
    if((sending||current?.processing)&&(retryId||regenerateId))throw Error('回复中也可以直接补充，等回复完再切换或重新生成。');
    if(!retryId&&!regenerateId&&!text){input.focus();return;}
    const steerId=current?.messages.find(m=>m.role==='assistant'&&m.status==='processing')?.id||null;
    const uiContext=branchDraft||retryId||regenerateId?null:structuredContext??presenter?.interactionContext()??null;
    const turn=++submission,renderId=state.renderId,previous=streaming,requestId=crypto.randomUUID();
    let cid=current?.id,cacheKey=key(),pending=null;
    const live=()=>turn===submission&&renderId===state.renderId&&active(cid);
    const acknowledge=()=>{const checkpoint=current?.messages.findLast(m=>m.role==='user'&&m.interaction?.message_id===uiContext?.message_id)?.interaction?.checkpoint;presenter?.markContextSubmitted(uiContext,checkpoint?.status==='saved');if(!retryId&&!regenerateId&&structuredText===null&&input.value===rawText){input.value='';attachments?.clear();drafts.stage(cacheKey,{content:'',source_ids:[]});fitComposer();}};
    accepting=true;sending=true;setComposerMenu(false);update();
    try{
      persist();await drafts.flush(key());await ensureConversation(renderId);if(renderId!==state.renderId||turn!==submission)return;
      cid=current.id;cacheKey=key();clearTimeout(pollTimer);
      const allowExternal=true;
      const payload={version:current.version,content:retryId||regenerateId?'':text,source_ids:sourceIds,request_id:requestId,retry_message_id:retryId||null,regenerate_message_id:regenerateId||null,steer_message_id:steerId,ui_context:uiContext,allow_external_processing:allowExternal};
      let result;
      pending={controller:new AbortController(),cid,renderId,raw:'',parser:null,mid:null,tier:1,expanded:false};streaming=pending;
      await streamChat(cid,payload,{csrf:state.session.csrf,signal:pending.controller.signal,onEvent:(type,data)=>{
        if(!live())return;
        if(type==='start'){
          previous?.controller.abort();current=data.conversation;pending.mid=data.message_id;pending.tier=data.tier;pending.parser=new StreamParser({limits:data.limits,data:data.data});acknowledge();accepting=false;update();
          const thread=$('#chat-thread');thread.scrollTop=thread.scrollHeight;updateJump();input.focus({preventScroll:true});
        }else if(type==='phase'){
          if(data.message_id!==pending.mid)return;const m=current.messages.find(m=>m.id===pending.mid);if(m){m._phase=data.phase;m._phaseLabel=data.label;m._work=data.steps;if(data.data&&!pending.raw){m.genui.data=data.data;pending.parser=new StreamParser({limits:state.session.genui?.limits,data:data.data});}paintMessages();}
        }else if(type==='work'){
          if(data.message_id!==pending.mid)return;const m=current.messages.find(m=>m.id===pending.mid);if(m){m._work=data.steps;paintMessages();}
        }else if(type==='agent'){
          if(data.message_id!==pending.mid)return;const m=current.messages.find(m=>m.id===pending.mid);if(m){m.agent=data.state;paintMessages();}
        }else if(type==='preview'){
          if(data.message_id!==pending.mid)return;
          const m=current.messages.find(m=>m.id===pending.mid);
           if(m){
             if(data.reset){pending.previewBuffer='';pending.holdPreview=!!m._preview;}
             pending.previewBuffer=(pending.previewBuffer||'')+data.text;
             // A rejected draft may restart from zero. Keep its visible text
             // while the status shows correction, then swap once at completion.
             if(!pending.holdPreview||pending.previewBuffer.startsWith(m._preview||'')){
               m._preview=pending.previewBuffer;pending.holdPreview=false;paintMessages();
             }
           }
        }else if(type==='delta'){
          if(!pending.parser||data.message_id!==pending.mid)throw Error('这条回复跟当前消息对不上，已经停止接收。');pending.raw+=data.text;pending.expanded||=!!data.expanded_template;pending.parser.push(data.text);
          const m=current.messages.find(m=>m.id===pending.mid);if(m){m.genui.raw=pending.raw;if(pending.tier===3)m.content=pending.raw;m._liveParts=pending.tier===1||pending.expanded?pending.parser.snapshot():[{kind:'text',text:pending.raw}];paintMessages();}
        }else if(type==='done'){result=data.conversation;current=result;accepting=false;update();}
      }});
      if(!live())return;
      const failedRevision=result?.messages.flatMap(m=>m.versions||[m]).find(m=>m.request_id===requestId&&m.status==='failed');
      if(failedRevision){const message=failedRevision.error||'这次回复没完成，已有内容都留着，可以再试一次。';if(structuredText!==null)throw Error(message);toast(message,true);}
      if(result){current=result;acknowledge();await drafts.flush(cacheKey);if(current.processing)schedulePoll(cid,renderId);}
    }catch(error){
      if(turn!==submission||renderId!==state.renderId)return;
      if(!cid||branchDraft){update();throw error;}
      if(!live())return;
      // Reconcile server acknowledgement without erasing text typed after sending.
      try{const result=await api('/conversations/'+cid);if(!live())return;current=result;
        if(result.messages.some(m=>m.request_id===requestId)){acknowledge();await drafts.flush(cacheKey);}
        if(current.processing)schedulePoll(cid,renderId);
      }catch{/* The local draft survives when acknowledgement is unknown. */}
      if(error.name!=='AbortError')throw error;
    }finally{
      if(turn===submission){if(streaming===pending)streaming=null;accepting=false;sending=false;if(active(cid)&&renderId===state.renderId)update();}
    }
  }
  function setComposerMenu(open){const menu=$('#composer-menu');if(!menu)return;menu.hidden=!open;$('.composer-plus')?.setAttribute('aria-expanded',String(open));}
  document.addEventListener('click',event=>{if(!event.target.closest('#chat-composer'))setComposerMenu(false);if($('#chat-workspace.show-materials')&&!document.body.classList.contains('materials-open')&&!event.target.closest('#chat-materials,[data-chat-action=toggle-materials],#dialog'))setMaterials(false,false);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#composer-menu')&&!$('#composer-menu').hidden){setComposerMenu(false);$('.composer-plus')?.focus();}});
  let railKey='';
  function drawTurnRail(){
    const rail=$('#chat-turn-rail');if(!rail)return;
    const turns=current?.messages.filter(m=>m.role==='user')||[],next=turns.map(m=>m.id).join(',');
    if(railKey!==next||!rail.childElementCount){
      railKey=next;rail.replaceChildren();$('#turn-tooltip')?.remove();
      const tooltip=document.createElement('span');tooltip.className='turn-preview';tooltip.id='turn-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;rail.parentElement.append(tooltip);
      turns.forEach((message,index)=>{
        const button=document.createElement('button');button.type='button';button.className='turn-marker';button.dataset.turnId=message.id;button.setAttribute('aria-label',`第 ${index+1} 轮：${message.content.slice(0,100)}`);
        const show=()=>{const rect=button.getBoundingClientRect();tooltip.textContent=`${index+1} · ${message.content.slice(0,120)}`;tooltip.hidden=false;tooltip.style.right=Math.max(8,innerWidth-rect.left+8)+'px';tooltip.style.top=Math.max(8,Math.min(innerHeight-tooltip.offsetHeight-8,rect.top))+'px';};
        for(const event of ['pointerenter','focus'])button.addEventListener(event,show);
        for(const event of ['pointerleave','blur'])button.addEventListener(event,()=>tooltip.hidden=true);
        button.addEventListener('click',()=>{tooltip.hidden=true;const target=[...$('#chat-thread').children].find(n=>n.dataset.messageId===message.id);target?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});});
        button.addEventListener('keydown',event=>{if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;event.preventDefault();const target=event.key==='Home'?0:event.key==='End'?rail.children.length-1:index+(event.key==='ArrowUp'?-1:1);rail.children[Math.max(0,Math.min(rail.children.length-1,target))]?.focus();});rail.append(button);
      });
      rail.onscroll=()=>tooltip.hidden=true;
    }
    rail.hidden=turns.length<2;updateTurnMarker();
  }
  function updateTurnMarker(){const thread=$('#chat-thread'),rail=$('#chat-turn-rail');if(!thread||!rail)return;const top=thread.getBoundingClientRect().top+64,users=[...thread.children].filter(n=>n.classList.contains('message-user'));const active=users.filter(n=>n.getBoundingClientRect().top<=top).at(-1)||users[0];for(const marker of rail.children)marker.setAttribute('aria-current',String(marker.dataset.turnId===active?.dataset.messageId));}
  function fitComposer(){
    const input=$('#chat-input');if(!input)return;
    // Use the actual workspace height, including a keyboard or resized panel.
    const available=$('.chat-main').clientHeight;
    $('#chat-composer').classList.toggle('is-compact',available<440);
    input.style.height='0px';
    const max=Math.min(144,Math.max(44,available*.18));
    input.style.height=Math.max(44,Math.min(input.scrollHeight,max))+'px';
    input.style.overflowY=input.scrollHeight>max?'auto':'hidden';
  }
  window.addEventListener('resize',fitComposer);
  function updateComposerState(){
    const submit=$('#chat-composer .send-button');if(!submit)return;
    const busy=!!(current?.processing||sending),hasDraft=!!$('#chat-input')?.value.trim()||!!attachments?.ids.length;
    const stop=busy&&!hasDraft,mode=stop?'stop':'send';
    submit.disabled=accepting||(!stop&&(!!attachments?.busy||!!attachments?.failed));
    submit.type=stop?'button':'submit';submit.dataset.chatAction=stop?'cancel':'';
    const label=stop?'停止本次回复':busy?'发送补充消息':'发送消息';
    submit.setAttribute('aria-label',label);submit.title=stop?label:busy?'发送补充，按新要求接着回答':'Enter 发送 · Shift + Enter 换行';
    if(submit.dataset.mode!==mode){submit.dataset.mode=mode;submit.innerHTML=stop?'<span class="stop-square" aria-hidden="true"></span>':'<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-7 7 7-7 7 7"/></svg>';}
  }
  function persist(){const form=$('#chat-composer');if(!form)return;const cacheKey=form.dataset.cacheKey,content=$('#chat-input').value;const snapshot={content,source_ids:attachments?.ids||[]};if(cacheKey.startsWith('branch:')&&!content.trim()&&!snapshot.source_ids.length&&!String(drafts.peek(cacheKey).payload?.content||'').trim())return;if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(cacheKey).payload))drafts.stage(cacheKey,snapshot);}
  function uploadDialog(textOnly=false){
    files=[];showDialog(textOnly?'把原文放在这里':'添加文件与文件夹',`<form id="chat-upload-form" class="stack" data-workspace-form="upload">${textOnly?'':`<div class="upload-options"><label class="upload" id="chat-dropzone">${icon('upload')}<strong>选择文件，或拖入文件与文件夹</strong><span class="small muted">文档、表格、幻灯片、代码、图片、音视频与 ZIP<br>最多 100 份，每份 20 MB，文件夹结构会保留</span><input type="file" id="chat-files" multiple accept="${materialFormats}" aria-label="选择对话材料"></label><label class="button small folder-upload">${icon('folder')} 上传整个文件夹<input type="file" id="chat-folder" webkitdirectory directory multiple hidden></label></div><div id="chat-file-selection"></div>`}${field('材料名称（选填）','label','','text','maxlength="160" placeholder="例如：报名通知、我的课表"')}${area('原文或补充内容','body','',textOnly?9:4,'maxlength="10000" placeholder="粘贴原文，或写下材料中需要注意的地方。"')}<div id="upload-progress" class="upload-progress" role="status" aria-live="polite" hidden></div><p class="small muted">原件会存在这个对话里。材料太长 AI 读不完，或者读取失败时，都会直接告诉你。</p><div class="form-footer"><button type="button" class="button" data-action="close-dialog">暂时不加</button><button type="submit" class="button primary">保存材料 ${icon('arrow')}</button></div></form>`);
  }
  function fileSelection(){
    const list=$('#chat-file-selection');if(list)list.innerHTML=files.map((f,i)=>`<div class="file-chip"><span>${esc(f.webkitRelativePath||f._relativePath||f.name)} <small>${Math.ceil(f.size/1024)} KB</small></span><button type="button" class="icon-button" data-chat-action="unpick-file" data-index="${i}" aria-label="移除 ${esc(f.webkitRelativePath||f._relativePath||f.name)}">${icon('close')}</button></div>`).join('');
  }
  function addFiles(selected){
    const seen=new Set(files.map(f=>(f.webkitRelativePath||f._relativePath||f.name)+':'+f.size+':'+f.lastModified));
    for(const f of selected){const id=(f.webkitRelativePath||f._relativePath||f.name)+':'+f.size+':'+f.lastModified;if(seen.has(id))continue;if(files.length>=100||f.size>20*1024*1024||f.size===0){toast('最多 100 份文件（不能是空文件），每份不超过 20 MB，太大的文件拆开再传吧。',true);continue;}files.push(f);seen.add(id);}
    fileSelection();
  }
  function preview(sid){
    const source=current?.sources.find(s=>s.id===sid);if(!source){toast('这份材料已经移出对话了。之前的回复是按当时的材料写的。',true);return;}
    const url=`/api/conversations/${current.id}/sources/${source.id}/download`;
    showDialog(source.name,'<div id="chat-attachment-preview"></div>');attachmentPreview($('#chat-attachment-preview'),source,url,{api,full:true});
  }
  async function promote(){
    if(!current?.sources.length){toast('先加上通知原文，才能转成通知。',true);return;}
    const catalog=await api('/source-catalog');
    showDialog('选出要办理的通知原文',`<form data-workspace-form="promote" id="chat-promote-form" class="stack"><p class="small muted">只选这则通知的原文和附件就行，简历、课表这类参考资料不用转。小信使的回复不会被当成通知原文。</p>${field('通知标题','title',current.title==='新的校园对话'?'':current.title,'text','required maxlength="160"')}${field('发布来源','source_label','','text','maxlength="100" list="known-sources" placeholder="学院官网、班级群或公众号"')}<datalist id="known-sources">${catalog.map(s=>`<option value="${esc(s.data.name)}">`).join('')}</datalist>${field('原文链接（选填）','source_url','','url','maxlength="2000" placeholder="https://…"')}<fieldset class="material-select"><legend>要转入的材料</legend>${current.sources.filter(s=>!videoKinds.has(s.kind)).map(s=>`<label class="check"><input type="checkbox" name="source_ids" value="${s.id}"><span>${esc(s.name)}<small class="muted"> · ${sourceStatus(s)}</small></span></label>`).join('')}</fieldset><div class="form-footer"><button class="button" type="button" data-action="close-dialog">再想一下</button><button class="button primary" type="submit">保存通知并核对 ${icon('arrow')}</button></div></form>`);
  }
  function historyDialog(){
    historyPage=1;historyMatches=historyItems;showDialog('接着上次的对话',`<div class="history-workspace">${searchControls({id:'chat-history',esc,icon,scope:'history',kinds:[['with-materials','含材料的对话']]})}<div id="chat-history-results" tabindex="0"></div><div id="history-pages" class="calendar-pagination"></div></div>`);
    historySearch?.dispose();historySearch=new WorkspaceSearch($('[data-search-host="chat-history"]'),{api,scope:'history',onResult:result=>{historyMatches=result.items;historyPage=1;historyResults();},onError:message=>toast(message,true)});historyResults();
  }
  function historyResults(){
    const results=$('#chat-history-results');if(!results)return;const pages=Math.max(1,Math.ceil(historyMatches.length/12));historyPage=Math.max(1,Math.min(historyPage,pages));
    results.innerHTML=historyMatches.slice((historyPage-1)*12,historyPage*12).map(c=>`<a class="history-chat" href="#chat/${c.id}" data-action="close-dialog">${icon('history')}<span><strong>${esc(c.title||c.name)}</strong><small>${c.source_count} 份材料 · ${date(c.updated_at)}${c.snippet?' · '+esc(c.snippet.slice(0,70)):''}</small></span>${icon('arrow')}</a>`).join('')||`<div class="history-empty">${brandMotion(historyItems.length?'search':'listening')}<strong>${historyItems.length?'没找到匹配的对话':'每一次交流，都可以在这里找回'}</strong><p>${historyItems.length?'换个关键词，或清空筛选试试。':'从一份材料、一句问题开始就好。'}</p></div>`;
    $('#history-pages').innerHTML=`<button type="button" class="button small" data-chat-action="history-prev" ${historyPage===1?'disabled':''}>上一页</button><span>${historyMatches.length} 段对话 · ${historyPage} / ${pages}</span><button type="button" class="button small" data-chat-action="history-next" ${historyPage===pages?'disabled':''}>下一页</button>`;results.scrollTop=0;
  }
  function shareDialog(mid){const message=current.messages.find(m=>m.id===mid),body=presenter.copy(message);showDialog('分享这条回复',`<div class="stack"><p class="small muted">分享前先看看下面的内容。只会分享这条回复和当前的互动选项；链接 7 天内有效，拿到链接的人都能看。</p><textarea id="reply-share-body" rows="7" maxlength="80000" aria-label="分享内容">${esc(body)}</textarea><div id="reply-share-result" role="status"></div><div class="form-footer">${call('复制内容','share-text',`data-id="${mid}"`,'small')}${call('生成分享链接','share-link',`data-id="${mid}"`,'primary')}</div></div>`);}
  document.addEventListener('click',async event=>{
    const control=event.target.closest('[data-chat-action]');if(!control||control.disabled)return;
    const action=control.dataset.chatAction,id=control.dataset.id;control.disabled=true;
    if(['copy','like','dislike','branch','regenerate','version','share-link'].includes(action)){control.classList.add('request-pending');control.setAttribute('aria-busy','true');}
    try{
      if(branchDraft&&action==='remove-source')return;
      if(action==='composer-menu'){setComposerMenu($('#composer-menu').hidden);}
      else if(action==='dictate'){await dictate($('#chat-input'),control,{api,toast,ask});}
      else if(action==='pick-attachments'){setComposerMenu(false);$('#composer-file-input').click();}
      else if(action==='new'){persist();await drafts.flushAll();remember('new');if(location.hash==='#chat/new')$('#chat-input')?.focus();else location.hash='chat/new';}
      else if(action==='history'){historyItems=await api('/conversations');historyDialog();}
      else if(action==='prompt'){$('#chat-input').value=control.dataset.prompt;persist();$('#chat-input').focus();}
      else if(action==='upload'||action==='paste-text'){setComposerMenu(false);uploadDialog(action==='paste-text');}
      else if(action==='unpick-file'){files.splice(Number(control.dataset.index),1);fileSelection();}
      else if(action==='toggle-materials'){setComposerMenu(false);setMaterials(!$('#chat-workspace').classList.contains('show-materials'));}
      else if(action==='preview')preview(id);
      else if(action==='retry')await send(id);
      else if(action==='agent-approval'){
        await api(`/conversations/${current.id}/agent/approvals/${control.dataset.approval}`,{method:'POST',json:{digest:control.dataset.digest,decision:control.dataset.decision}});
        const message=current.messages.find(m=>m.id===id);if(message?.agent)message.agent.approvals=message.agent.approvals.filter(a=>a.id!==control.dataset.approval);drawMessages();
      }
      else if(action==='undo-operation'){
        control.disabled=true;
        try{await api(`/conversations/${current.id}/agent/operations/${control.dataset.operation}/undo`,{method:'POST'});current=await api('/conversations/'+current.id);drawMessages();}
        finally{if(control.isConnected)control.disabled=false;}
      }
      else if(action==='clear-material-search'){materialSearch.clear();}
      else if(action==='cancel'){submission++;accepting=false;current=await api('/conversations/'+current.id);current=await api('/conversations/'+current.id+'/cancel',{method:'POST',json:{version:current.version}});streaming?.controller.abort();sending=false;update();}
      else if(action==='speak'){const m=current.messages.find(m=>m.id===id);await replySpeech.toggle(id,presenter?.copy(m)||m.content,control);}
      else if(action==='copy'){const m=current.messages.find(m=>m.id===id),text=presenter?.copy(m)||m.content,html=presenter?.copyHTML(m);try{if(html&&window.ClipboardItem)await navigator.clipboard.write([new ClipboardItem({'text/plain':new Blob([text],{type:'text/plain'}),'text/html':new Blob([html],{type:'text/html'})})]);else await navigator.clipboard.writeText(text);control.dataset.feedback='copied';control.setAttribute('aria-label','已复制回复');setTimeout(()=>{if(control.isConnected){delete control.dataset.feedback;control.setAttribute('aria-label','复制回复');}},1800);}catch{try{await navigator.clipboard.writeText(text);toast('复制好了，当前的互动选项也一起带上了。');}catch{toast('浏览器没让复制，选中回复手动复制一下吧。',true);}}}
      else if(action==='like'||action==='dislike'){const message=current.messages.find(m=>m.id===id),value=action==='like'?1:-1;const result=await api(`/conversations/${current.id}/messages/${id}/reaction`,{method:'POST',json:{value:message.reaction===value?0:value}});message.reaction=result.value;drawMessages();toast(result.value===1?'已标记为有帮助':result.value===-1?'已标记为需要改进':'已取消评价');}
      else if(action==='regenerate'){await send(null,null,id);}
      else if(action==='branch'){branchDraft=branchPreview(current,id,state.session.user.id);location.hash=`chat/${current.id}/branch/${id}`;}
      else if(action==='version'){const message=current.messages.find(m=>m.id===id),index=Number(control.dataset.index),version=message?.versions?.[index];if(!version||current.processing)return;if(version.status==='complete'){current=await api(`/conversations/${current.id}/messages/${version.id}/select`,{method:'POST',json:{version:current.version}});}else current.messages=current.messages.map(m=>m.id===id?{...version,versions:message.versions,version_index:index}:m);drawMessages();}
      else if(action==='share')shareDialog(id);
      else if(action==='share-text'){await navigator.clipboard.writeText($('#reply-share-body').value);toast('分享内容已复制。');}
      else if(action==='share-link'){const result=await api(`/conversations/${current.id}/messages/${id}/share`,{method:'POST',json:{body:$('#reply-share-body').value}}),url=new URL(result.url,location.origin).href;$('#reply-share-result').innerHTML=`<label class="field">分享链接<input id="reply-share-url" readonly value="${esc(url)}"></label><div class="row">${call('复制链接','copy-share-url','','small')}${call('撤回链接','revoke-share',`data-token="${result.token}"`,'small plain')}</div>`;}
      else if(action==='copy-share-url'){await navigator.clipboard.writeText($('#reply-share-url').value);toast('链接已复制。');}
      else if(action==='revoke-share'){await api(`/conversations/${current.id}/shares/${control.dataset.token}`,{method:'DELETE'});$('#reply-share-result').textContent='分享链接已撤回。';}
      else if(action==='history-prev'||action==='history-next'){historyPage+=action==='history-prev'?-1:1;historyResults();}
      else if(action==='remove-source'){if(await ask('移除这份材料','这份材料会从对话里移除，之后也不会再发给 AI。之前回复里的文字还在；想彻底清除的话，删掉整个对话。','移除材料')){current=await api(`/conversations/${current.id}/sources/${id}`,{method:'DELETE',json:{version:current.version}});update();materialSearch?.run();toast('材料已移除。');}}
      else if(action==='context-settings'){const routeId=state.renderId;await ensureConversation(routeId);if(routeId!==state.renderId)return;const cid=current.id;await memoryUI.context(cid,async()=>{const result=await api('/conversations/'+cid);if(routeId===state.renderId&&active(cid)){current=result;update();}});}
      else if(action==='remember'){const routeId=state.renderId;await ensureConversation(routeId);if(routeId===state.renderId)await memoryUI.remember(current);}
      else if(action==='promote')await promote();
      else if(action==='rename')showDialog('给对话取个名字',`<form class="stack" data-workspace-form="rename">${field('对话名称','title',current.title,'text','required maxlength="100"')}<div class="form-footer"><button type="submit" class="button primary">保存名称</button></div></form>`);
      else if(action==='delete'){if(branchDraft){branchDraft=null;location.hash='chat/new';}else if(await ask('删除这段对话','会删掉这段对话、里面的材料和没发出去的草稿。已经转成通知的原件和待办不受影响，可以在通知里单独管理。','删除对话')){await api('/conversations/'+current.id,{method:'DELETE',json:{version:current.version}});remember('new');location.hash='chat/new';}}
    }catch(error){toast(error.message,true);}finally{control.disabled=false;control.classList.remove('request-pending');control.removeAttribute('aria-busy');}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target,type=form.dataset.workspaceForm;if(!type||!['chat','upload','promote','rename'].includes(type))return;
    event.preventDefault();
    if(type==='chat'){try{await send();}catch(error){toast(error.message,true);}return;}
    const submit=$('[type=submit]',form);if(!submit||submit.disabled)return;submit.disabled=true;
    form.querySelector('.form-error')?.remove();const routeId=state.renderId,conversationId=current?.id;
    try{
      const fd=new FormData(form);form.inert=true;
      if(type==='upload'){
        if(!files.length&&!fd.get('body')?.trim())throw Error('先选文件、文件夹，或者贴一段原文，再保存。');
        persist();await ensureConversation(routeId);if(routeId!==state.renderId)return;const cid=current.id;
        if(attachments.items.length+files.length+(fd.get('body')?.trim()?1:0)>100)throw Error('每次最多添加 100 份附件。');
        if(fd.get('body')?.trim()){
          const data=new FormData();data.set('version',current.version);data.set('append_only','true');data.set('body',fd.get('body'));data.set('label',fd.get('label')||'');
          const result=await api('/conversations/'+cid+'/sources',{method:'POST',body:data});
          if(routeId!==state.renderId||!active(cid))return;
          if(result.version>=current.version)current=result;
          attachments.adopt(result.sources,result.uploaded_source_ids);materialMatches=null;update();
        }
        attachments.add(files);files=[];$('#dialog').close();$('#chat-input').focus();
        if(routeId===state.renderId)document.dispatchEvent(new CustomEvent('campus:milestone',{detail:'materials-saved'}));
      }else if(type==='promote'){
        const selected=fd.getAll('source_ids');if(!selected.length)throw new Error('至少选一份通知原文吧。');
        const result=await api('/conversations/'+conversationId+'/promote',{method:'POST',json:{version:current.version,title:fd.get('title'),source_label:fd.get('source_label'),source_url:fd.get('source_url'),source_ids:selected}});
        if(routeId===state.renderId){$('#dialog').close();location.hash='notice/'+result.notice_id;}
        toast(result.already_created?'这批材料之前已经转成通知了，已经帮你打开。':'通知原件存好了，接下来看看你要做哪些事。');
      }else if(type==='rename'){
        if(branchDraft){await ensureConversation(routeId);if(routeId!==state.renderId)return;}
        const renamedId=current.id;const result=await api('/conversations/'+renamedId,{method:'PUT',json:{version:current.version,title:fd.get('title')}});if(routeId===state.renderId&&active(renamedId)){current=result;update();$('#dialog').close();}
      }
    }catch(error){if(type==='chat'){toast(error.message,true);return;}let box=$('.form-error',form);if(!box){box=document.createElement('div');box.className='alert error form-error';box.setAttribute('role','alert');form.prepend(box);}box.textContent=error.message;toast(error.message,true);}
    finally{form.inert=false;submit.disabled=false;}
  });
  document.addEventListener('input',e=>{if(e.target.id==='chat-input'){fitComposer();persist();updateComposerState();}});
  function attachFiles(incoming){if(current?.processing||sending){toast('先停下当前回复，再加材料。',true);return;}try{attachments?.add(incoming);}catch(error){toast(error.message,true);}}
  document.addEventListener('change',e=>{if(e.target.id==='composer-file-input'){attachFiles([...e.target.files]);e.target.value='';}else if(['chat-files','chat-folder'].includes(e.target.id)){addFiles([...e.target.files]);e.target.value='';}});
  document.addEventListener('paste',e=>{const incoming=[...(e.clipboardData?.files||[])];if(!incoming.length)return;if(e.target.closest('#chat-composer')){e.preventDefault();attachFiles(incoming);}else if($('#chat-upload-form')){e.preventDefault();addFiles(incoming);}});
  document.addEventListener('dragover',e=>{if(e.target.closest('#chat-composer')&&e.dataTransfer?.types.includes('Files')){e.preventDefault();$('#chat-composer').classList.add('dragging');}});
  document.addEventListener('dragleave',e=>{const form=$('#chat-composer');if(form&&e.target.closest('#chat-composer')&&!form.contains(e.relatedTarget))form.classList.remove('dragging');});
  document.addEventListener('drop',e=>{if(e.target.closest('#chat-composer')){e.preventDefault();$('#chat-composer').classList.remove('dragging');attachFiles([...e.dataTransfer.files]);}});
  document.addEventListener('dragover',e=>{if(e.target.closest('#chat-dropzone')){e.preventDefault();$('#chat-dropzone').classList.add('dragging');}});
  document.addEventListener('dragleave',e=>{if(e.target.closest('#chat-dropzone'))$('#chat-dropzone').classList.remove('dragging');});
  document.addEventListener('drop',async e=>{if(!e.target.closest('#chat-dropzone'))return;e.preventDefault();$('#chat-dropzone').classList.remove('dragging');
    async function walk(entry,prefix=''){if(!entry)return;if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));file._relativePath=prefix+file.name;addFiles([file]);}else if(entry.isDirectory){const reader=entry.createReader();while(files.length<100){const children=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!children.length)break;for(const child of children)await walk(child,prefix+entry.name+'/');}}}
    try{const entries=[...e.dataTransfer.items].map(i=>i.webkitGetAsEntry?.()).filter(Boolean);if(entries.length)for(const entry of entries)await walk(entry);else addFiles([...e.dataTransfer.files]);}catch{toast('有些文件夹没读出来，用“上传整个文件夹”重新选一次试试。',true);}
  });
  document.addEventListener('keydown',e=>{if(e.target.id==='chat-input'&&!e.shiftKey&&e.key==='Enter'&&!e.isComposing&&e.keyCode!==229){e.preventDefault();$('#chat-composer').requestSubmit();}});
  window.addEventListener('hashchange',()=>{composerResize?.disconnect();if(branchDraft&&location.hash!==`#chat/${branchDraft.originId}/branch/${branchDraft.messageId}`)branchDraft=null;submission++;accepting=false;clearTimeout(pollTimer);streaming?.controller.abort();cancelAnimationFrame(paintFrame);paintFrame=0;presenter?.dispose();presenter=null;});
  return {render,persist,preview};
}
