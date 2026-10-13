import {formatAnswer} from './message-format.js';
const $=(s,root=document)=>root.querySelector(s);
const $$=(s,root=document)=>[...root.querySelectorAll(s)];
const imageKinds=new Set(['png','jpg','jpeg','webp']);

export function createChatUI({state,api,esc,icon,companion,greeting,toast,showDialog,ask,field,area,drafts,route}){
  let current=null,historyItems=[],pollTimer,files=[],sending=false,consent=false;
  let materialInert=[],materialReturn=null;
  function setMaterials(open,restore=true){
    const workspace=$('#chat-workspace'),panel=$('#chat-materials');
    materialInert.forEach(([node,previous])=>{if(node.isConnected)node.inert=previous;});materialInert=[];
    document.body.classList.remove('materials-open');
    if(!workspace||!panel)return;
    workspace.classList.toggle('show-materials',open);$('.materials-toggle')?.setAttribute('aria-expanded',String(open));
    if(open){
      materialReturn=document.activeElement;
      materialInert=$$('.chat-main,.topbar,.sidebar,.mobile-bottom-nav').map(node=>[node,node.inert]);materialInert.forEach(([node])=>node.inert=true);
      document.body.classList.add('materials-open');panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');
      requestAnimationFrame(()=>$('.materials-close')?.focus());
    }else{panel.removeAttribute('role');panel.removeAttribute('aria-modal');if(restore&&materialReturn?.isConnected)materialReturn.focus();materialReturn=null;}
  }
  document.addEventListener('keydown',event=>{
    if(!$('#chat-workspace.show-materials')||$('#dialog')?.open)return;
    if(event.key==='Escape'){event.preventDefault();setMaterials(false);}
    if(event.key==='Tab'){const items=$$('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled)', $('#chat-materials')).filter(el=>el.getClientRects().length);if(!items.length)return;const first=items[0],last=items.at(-1);if(!$('#chat-materials').contains(document.activeElement)||(event.shiftKey&&document.activeElement===first)||(!event.shiftKey&&document.activeElement===last)){event.preventDefault();(event.shiftKey?last:first).focus();}}
  });
  window.addEventListener('hashchange',()=>setMaterials(false,false));
  const call=(label,action,extra='',cls='')=>`<button type="button" class="button ${cls}" data-chat-action="${action}" ${{history:'aria-label="历史对话"',new:'aria-label="新对话"','toggle-materials':'aria-label="查看本次材料"'}[action]||''} ${extra}>${label}</button>`;
  const key=()=>current?'chat:'+current.id:'chat-new';
  const active=cid=>$('#chat-workspace')&&current?.id===cid;
  const sourceStatus=s=>s.status==='failed'?'读取失败':imageKinds.has(s.kind)?'图片已收到 · 待视觉核对':s.status==='review'?'已解析 · 需核对':'文字已读取';
  const date=n=>new Date(n*1000).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});

  async function render(id,renderId){
    setMaterials(false,false);
    clearTimeout(pollTimer);files=[];sending=false;consent=false;
    const results=await Promise.all([api('/conversations'),id?api('/conversations/'+encodeURIComponent(id)):Promise.resolve(null),drafts.load(id?'chat:'+id:'chat-new')]);
    if(renderId!==state.renderId)return;
    historyItems=results[0];current=results[1];drafts.activate(key());
    $('#content').innerHTML=`<div id="chat-workspace" class="chat-workspace ${current?'has-conversation':''}">
      <div class="chat-main"><header class="chat-heading"><div><h1 id="conversation-title">${esc(current?.title||'和小信使聊聊')}</h1></div><div class="row compact-row">${call(icon('history')+'<span>历史对话</span>','history','','small')}${current?call(icon('plus')+'<span>新对话</span>','new','','small'):''}${call(icon('doc')+'<span>材料</span>','toggle-materials','aria-expanded="false" aria-controls="chat-materials"','small materials-toggle')}</div></header>
      <section class="chat-thread" id="chat-thread" aria-label="与校园助手的对话" tabindex="0">${thread()}</section>
      <div id="chat-processing" role="status" aria-live="polite"></div>
      <form class="chat-composer" id="chat-composer" data-workspace-form="chat" data-cache-key="${key()}">
        <label for="chat-input" class="sr-only">给小信使的消息</label><textarea id="chat-input" name="content" rows="3" maxlength="6000" placeholder="写下问题，或添加通知与附件…">${esc(drafts.peek(key()).payload?.content||'')}</textarea>
        <div class="composer-actions"><div class="row compact-row">${call(icon('plus')+'<span>添加材料</span>','upload','','small plain')}${call(icon('doc')+'<span>粘贴原文</span>','paste-text','','small plain')}</div><div class="row compact-row"><span class="composer-shortcut">Ctrl / ⌘ + Enter</span><button class="button primary send-button" type="submit" aria-label="发送消息">发送 ${icon('arrow')}</button></div></div>
        <div class="composer-context"><label class="check"><input type="checkbox" id="chat-consent"><span>允许将本会话材料、历史与必要个人条件交给模型处理</span></label></div>
        <div class="composer-status"><span class="autosave-status" role="status"></span><span id="chat-count">${current?.sources.length||0} 份材料 · 仅本人可见</span></div>
      </form>
      <div class="chat-footnote">${state.session.ai.configured?'回答用于辅助理解，重要日期与资格请对照原文。':'AI 待配置：现在可以保存问题和材料，填写 API 后继续回复。'}<a href="#settings">${state.session.ai.configured?'个人条件':'查看配置'}</a></div>
      </div><button type="button" class="materials-scrim" data-chat-action="toggle-materials" aria-label="关闭材料面板" tabindex="-1"></button><aside id="chat-materials" class="chat-materials" aria-label="本次对话的材料"><div class="materials-heading"><h2>本次材料</h2><span class="small muted" id="material-total">0</span><button type="button" class="icon-button materials-close" data-chat-action="toggle-materials" aria-label="收起材料">${icon('close')}</button></div><p class="small muted">放在这里的内容，才会成为这次对话的依据。</p><div id="material-list"></div><div class="material-actions">${call(icon('plus')+' 添加材料','upload','','small')}${call('转为通知 '+icon('arrow'),'promote','','small primary')}</div>${current?`<div class="conversation-tools">${call('重命名','rename','','small plain')}${call('删除对话','delete','','small plain danger')}</div>`:''}</aside></div>`;
    update();if(current?.processing)schedulePoll(current.id,state.renderId);
  }
  function thread(){
    if(!current?.messages.length)return `<div class="chat-welcome"><div class="welcome-mascot">${companion('welcome','chat-companion')}</div><h2>${greeting()}，${esc(state.session.user.display_name)}。</h2><p>长长的通知，慢慢读。<br class="mobile-only">重要的下一步，我们一起找。</p><div class="scene-choices">${[
      ['doc','读懂一则通知','对象、材料、时间，一个都不漏','请帮我读懂这则通知，指出哪些条件还需要我核实。'],
      ['tasks','理清我的下一步','把要做的事，拆成小小的行动','请根据我上传的材料，帮我列出可以先开始的准备步骤。'],
      ['calendar','一起安排时间','分清正式期限和个人计划','请帮我区分材料中的正式截止时间和可以自己安排的时间。']
    ].map(([i,title,subtitle,prompt])=>`<button type="button" class="scene-choice" data-chat-action="prompt" data-prompt="${esc(prompt)}">${icon(i)}<strong>${title}</strong><span>${subtitle}</span>${icon('arrow')}</button>`).join('')}</div>${historyItems.length?`<div class="recent-chats"><div class="between"><span>接着上次聊</span>${call('全部对话','history','','small plain')}</div>${historyItems.slice(0,3).map(c=>`<a href="#chat/${c.id}">${icon('history')}<span>${esc(c.title)}</span><small>${date(c.updated_at)}</small>${icon('arrow')}</a>`).join('')}</div>`:''}</div>`;
    const lastAssistant=current.messages.filter(m=>m.role==='assistant').at(-1)?.id;
    return current.messages.map(m=>m.role==='user'?`<article class="message message-user"><div class="message-label">你</div><div class="message-content">${esc(m.content)}</div></article>`:
      `<article class="message message-assistant" data-message-id="${m.id}"><div class="message-label"><img src="/static/assets/luojia-messenger-reading.png" alt="" width="28" height="28">珞珈小信使<span>${m.status==='complete'?'AI 回复':m.status==='processing'?'正在阅读与思考':'回复未完成'}</span></div>${m.status==='complete'?`<div class="message-content">${formatAnswer(m.content)}</div>${m.citations.length?`<div class="message-citations" aria-label="回复依据">${m.citations.map((c,i)=>call(`[${i+1}] ${esc(current.sources.find(s=>s.id===c.source_id)?.name||'已移除的材料')} · ${esc(c.locator)}`,'preview',`data-id="${c.source_id}"`,'small')).join('')}</div>`:''}<div class="message-footer">${call('复制回复','copy',`data-id="${m.id}"`,'small plain')}<span>辅助理解 · 核对后再行动</span></div>`:m.status==='processing'?'<div class="thinking"><span class="spinner"></span><span>正在结合本次材料整理回复…</span></div>':`<div class="message-error"><p>${esc(m.error)}</p>${m.id===lastAssistant?call('重试这条回复','retry',`data-id="${m.id}"`,'small'):''}</div>`}</article>`).join('');
  }
  function update(){
    if(!$('#chat-workspace'))return;
    const threadElement=$('#chat-thread'),nearBottom=threadElement.scrollHeight-threadElement.scrollTop-threadElement.clientHeight<110;
    threadElement.innerHTML=thread();if(!current?.messages.length)threadElement.scrollTop=0;else if(nearBottom)threadElement.scrollTop=threadElement.scrollHeight;
    $('#conversation-title').textContent=current?.title||'和小信使聊聊';
    $('#conversation-title').classList.toggle('sr-only',!current);
    if(current&&!$('.chat-heading [data-chat-action="new"]'))$('.chat-heading .row').insertAdjacentHTML('afterbegin',call(icon('plus')+'<span>新对话</span>','new','','small'));
    if(current&&!$('.conversation-tools'))$('#chat-materials').insertAdjacentHTML('beforeend',`<div class="conversation-tools">${call('重命名','rename','','small plain')}${call('删除对话','delete','','small plain danger')}</div>`);
    $('#chat-workspace').classList.toggle('has-conversation',!!current);
    $('#material-total').textContent=(current?.sources.length||0)+' 份';
    $('#chat-count').textContent=(current?.sources.length||0)+' 份材料 · 仅本人可见';
    $('#material-list').innerHTML=current?.sources.length?current.sources.map(s=>`<div class="material-item"><button type="button" class="material-open" data-chat-action="preview" data-id="${s.id}">${imageKinds.has(s.kind)&&s.status!=='failed'?`<img class="material-thumb" src="/api/conversations/${current.id}/sources/${s.id}/download?preview=true" alt="${esc(s.name)}的缩略图" loading="lazy">`:`<span class="material-type">${s.kind==='text'?'文':esc(s.kind.toUpperCase())}</span>`}<span><strong>${esc(s.name)}</strong><small class="${s.status==='failed'?'text-error':''}">${sourceStatus(s)}</small></span></button><button type="button" class="icon-button" data-chat-action="remove-source" data-id="${s.id}" aria-label="移除 ${esc(s.name)}" ${current.processing?'disabled':''}>${icon('close')}</button></div>`).join(''):'<div class="material-empty"><span>'+icon('upload')+'</span><strong>给对话一点依据</strong><p>通知、截图、课表或申请要求<br>都可以从这里加入。</p><small>PDF · Word · TXT · 图片</small></div>';
    const busy=current?.processing||sending;
    $('#chat-processing').innerHTML=current?.processing?`<div class="processing-strip"><span>消息已保存，正在等待模型回复</span>${call('停止本次回复','cancel','','small plain')}</div>`:'';
    $('#chat-composer textarea').disabled=busy;
    $('#chat-composer [type=submit]').disabled=busy;
    $$('[data-chat-action="upload"],[data-chat-action="paste-text"],[data-chat-action="promote"]').forEach(b=>b.disabled=busy);
  }
  async function ensureConversation(renderId=state.renderId){
    if(current)return current;
    const snapshot=structuredClone(drafts.peek('chat-new').payload);
    const result=await api('/conversations',{method:'POST',json:{}});
    if(renderId!==state.renderId)return result;
    await drafts.load('chat:'+result.id);
    if(renderId!==state.renderId)return result;
    current=result;history.replaceState(null,'','#chat/'+result.id);$('#content').dataset.page='chat/'+result.id;
    drafts.activate('chat:'+result.id);
    if(snapshot)drafts.stage('chat:'+result.id,snapshot);
    if(JSON.stringify(drafts.peek('chat-new').payload)===JSON.stringify(snapshot))drafts.stage('chat-new',{content:''});
    if($('#chat-composer'))$('#chat-composer').dataset.cacheKey='chat:'+result.id;
    return current;
  }
  function schedulePoll(cid,renderId){
    clearTimeout(pollTimer);pollTimer=setTimeout(async()=>{
      if(renderId!==state.renderId||!active(cid))return;
      try{const result=await api('/conversations/'+cid);if(renderId!==state.renderId||!active(cid))return;if(result.version>current.version||(result.version===current.version&&result.processing!==current.processing)){current=result;update();}if(current.processing)schedulePoll(cid,renderId);}
      catch(e){if(active(cid))toast(e.message,true);}
    },1400);
  }
  async function send(retryId){
    const form=$('#chat-composer'),input=$('#chat-input'),rawText=input.value,text=rawText.trim();
    if(sending||current?.processing)return;
    if(!retryId&&!text){input.focus();throw new Error('写下一句问题，或者先添加一份材料吧。');}
    consent=$('#chat-consent').checked;
    if(state.session.ai.configured&&!consent){$('#chat-consent').focus();throw new Error('请先确认允许向模型发送本次对话材料。');}
    persist();await drafts.flush(key());
    const renderId=state.renderId;await ensureConversation(renderId);if(renderId!==state.renderId)return;
    const cid=current.id,cacheKey=key(),requestId=crypto.randomUUID();sending=true;update();
    const startedVersion=current.version;schedulePoll(cid,renderId);
    try{
      const result=await api('/conversations/'+cid+'/messages',{method:'POST',json:{version:startedVersion,content:retryId?'':text,request_id:requestId,retry_message_id:retryId||null,allow_external_processing:consent}});
      if(!retryId&&drafts.peek(cacheKey).payload?.content===rawText){drafts.stage(cacheKey,{content:''});await drafts.flush(cacheKey);}
      if(active(cid)&&renderId===state.renderId){current=result;if(!retryId)input.value='';sending=false;update();$('#chat-thread').scrollTop=$('#chat-thread').scrollHeight;input.focus();if(current.processing)schedulePoll(cid,renderId);}
    }catch(error){
      // A disconnected HTTP response is not proof that the message failed to save.
      if(active(cid)&&renderId===state.renderId){
        try{const result=await api('/conversations/'+cid);current=result;
          if(result.messages.some(m=>m.request_id===requestId)&&!retryId){input.value='';drafts.stage(cacheKey,{content:''});await drafts.flush(cacheKey);}
          if(current.processing)schedulePoll(cid,renderId);
        }catch{/* Keep the local draft if its server state could not be verified. */}
      }
      throw error;
    }finally{if(active(cid)&&renderId===state.renderId){sending=false;update();}}
  }
  function persist(){const form=$('#chat-composer');if(!form)return;const cacheKey=form.dataset.cacheKey,content=$('#chat-input').value;const snapshot={content};if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(cacheKey).payload))drafts.stage(cacheKey,snapshot);}
  function uploadDialog(textOnly=false){
    files=[];showDialog(textOnly?'把原文放在这里':'给这次对话添加材料',`<form id="chat-upload-form" class="stack" data-workspace-form="upload">${textOnly?'':`<label class="upload" id="chat-dropzone">${icon('upload')}<strong>选择文件，也可以拖入或粘贴截图</strong><span class="small muted">PDF / DOCX / TXT / PNG / JPEG / WebP<br>每次最多 5 份，每份 5 MB</span><input type="file" id="chat-files" multiple accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp" aria-label="选择对话材料"></label><div id="chat-file-selection"></div>`}${field('材料名称（选填）','label','','text','maxlength="160" placeholder="例如：报名通知、我的课表"')}${area('原文或补充内容','body','',textOnly?9:4,'maxlength="10000" placeholder="粘贴完整内容；链接仅能作为出处，不能替代正文。"')}<p class="small muted">材料会保存在本次对话，只有你可以查看。添加个人资料时，请只保留本次问题需要的部分。</p><div class="form-footer"><button type="button" class="button" data-action="close-dialog">暂时不加</button><button type="submit" class="button primary">保存材料 ${icon('arrow')}</button></div></form>`);
  }
  function fileSelection(){
    const list=$('#chat-file-selection');if(list)list.innerHTML=files.map((f,i)=>`<div class="file-chip"><span>${esc(f.name)} <small>${Math.ceil(f.size/1024)} KB</small></span><button type="button" class="icon-button" data-chat-action="unpick-file" data-index="${i}" aria-label="移除 ${esc(f.name)}">${icon('close')}</button></div>`).join('');
  }
  function addFiles(selected){
    const seen=new Set(files.map(f=>f.name+':'+f.size+':'+f.lastModified));
    for(const f of selected){const id=f.name+':'+f.size+':'+f.lastModified;if(seen.has(id))continue;if(files.length>=5||f.size>5*1024*1024||f.size===0){toast('每次最多 5 份非空文件，每份不超过 5 MB。',true);continue;}files.push(f);seen.add(id);}
    fileSelection();
  }
  function preview(sid){
    const source=current?.sources.find(s=>s.id===sid);if(!source){toast('这份材料已移出当前对话。旧回复请按当时的材料核对。',true);return;}
    const url=`/api/conversations/${current.id}/sources/${source.id}/download`;
    showDialog(source.name,`<div class="stack"><div class="between"><span class="pill">${sourceStatus(source)}</span><a class="button small" href="${url}" download>下载原件 ${icon('down')}</a></div>${source.warning?`<div class="alert">${esc(source.warning)}</div>`:''}${imageKinds.has(source.kind)&&source.status!=='failed'?`<a href="${url}?preview=true" target="_blank" rel="noopener noreferrer" class="image-preview-link"><img class="source-image-preview" src="${url}?preview=true" alt="${esc(source.name)}原图"><span>打开原尺寸图片 ↗</span></a>`:''}${source.sections.map(s=>`<section class="source-section"><span class="locator">${esc(s.locator)}</span>${esc(s.text)}</section>`).join('')}${!source.sections.length&&!imageKinds.has(source.kind)?'<p>没有可读取的文字。请补充正文，或重新上传可读文件。</p>':''}</div>`);
  }
  async function promote(){
    if(!current?.sources.length){toast('先添加原文材料，才能转为通知。',true);return;}
    const catalog=await api('/source-catalog');
    showDialog('选择需要办理的通知原文',`<form data-workspace-form="promote" id="chat-promote-form" class="stack"><p class="small muted">只选择这则通知的原文与附件。个人简历、课表等参考资料不必转入。助手的聊天回复不会作为正式原文。</p>${field('通知标题','title',current.title==='新的校园对话'?'':current.title,'text','required maxlength="160"')}${field('发布来源','source_label','','text','maxlength="100" list="known-sources" placeholder="学院官网、班级群或公众号"')}<datalist id="known-sources">${catalog.map(s=>`<option value="${esc(s.data.name)}">`).join('')}</datalist>${field('原文链接（选填）','source_url','','url','maxlength="2000" placeholder="https://…"')}<fieldset class="material-select"><legend>转入的原始材料</legend>${current.sources.map(s=>`<label class="check"><input type="checkbox" name="source_ids" value="${s.id}"><span>${esc(s.name)}<small class="muted"> · ${sourceStatus(s)}</small></span></label>`).join('')}</fieldset><div class="form-footer"><button class="button" type="button" data-action="close-dialog">再想一下</button><button class="button primary" type="submit">保存通知并核对 ${icon('arrow')}</button></div></form>`);
  }
  function historyDialog(){
    showDialog('接着上次的对话',`<div class="stack"><label class="field">查找对话<input id="chat-history-search" placeholder="搜索全部历史标题"></label><div id="chat-history-results"></div></div>`);historyResults('');
  }
  function historyResults(query){$('#chat-history-results').innerHTML=historyItems.filter(c=>c.title.toLowerCase().includes(query.toLowerCase())).map(c=>`<a class="history-chat" href="#chat/${c.id}">${icon('history')}<span><strong>${esc(c.title)}</strong><small>${c.source_count} 份材料 · ${date(c.updated_at)}</small></span>${icon('arrow')}</a>`).join('')||'<div class="empty compact"><p>还没有匹配的对话。可以从一份材料、一句问题开始。</p></div>';}
  document.addEventListener('click',async event=>{
    const control=event.target.closest('[data-chat-action]');if(!control||control.disabled)return;
    const action=control.dataset.chatAction,id=control.dataset.id;control.disabled=true;
    try{
      if(action==='new'){persist();await drafts.flushAll();location.hash='chat';}
      else if(action==='history'){historyItems=await api('/conversations');historyDialog();}
      else if(action==='prompt'){$('#chat-input').value=control.dataset.prompt;persist();$('#chat-input').focus();}
      else if(action==='upload'||action==='paste-text')uploadDialog(action==='paste-text');
      else if(action==='unpick-file'){files.splice(Number(control.dataset.index),1);fileSelection();}
      else if(action==='toggle-materials'){setMaterials(!$('#chat-workspace').classList.contains('show-materials'));}
      else if(action==='preview')preview(id);
      else if(action==='retry')await send(id);
      else if(action==='cancel'){current=await api('/conversations/'+current.id);current=await api('/conversations/'+current.id+'/cancel',{method:'POST',json:{version:current.version}});sending=false;update();}
      else if(action==='copy'){const m=current.messages.find(m=>m.id===id);try{await navigator.clipboard.writeText(m.content);toast('回复已复制，引用仍可在对话里查看。');}catch{toast('浏览器未允许复制，请选中回复手动复制。',true);}}
      else if(action==='remove-source'){if(await ask('移除这份材料','此材料将从当前对话移除，之后不再发送给模型。旧回复中的文字仍保留；需要完整清除时请删除对话。','移除材料')){current=await api(`/conversations/${current.id}/sources/${id}`,{method:'DELETE',json:{version:current.version}});update();toast('材料已移除。');}}
      else if(action==='promote')await promote();
      else if(action==='rename')showDialog('给对话取个名字',`<form class="stack" data-workspace-form="rename">${field('对话名称','title',current.title,'text','required maxlength="100"')}<div class="form-footer"><button type="submit" class="button primary">保存名称</button></div></form>`);
      else if(action==='delete'){if(await ask('删除这段对话','将删除这段对话、材料和未发送草稿。已经转为通知的独立原件与待办仍保留，可在通知资料中另行管理。','删除对话')){await api('/conversations/'+current.id,{method:'DELETE',json:{version:current.version}});location.hash='chat';}}
    }catch(error){toast(error.message,true);}finally{control.disabled=false;}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target,type=form.dataset.workspaceForm;if(!type||!['chat','upload','promote','rename'].includes(type))return;
    event.preventDefault();const submit=$('[type=submit]',form);if(submit.disabled)return;submit.disabled=true;
    const routeId=state.renderId,conversationId=current?.id;
    try{
      if(type==='chat'){await send();return;}
      const fd=new FormData(form);form.inert=true;
      if(type==='upload'){
        persist();await ensureConversation(routeId);if(routeId!==state.renderId)return;const cid=current.id;
        const data=new FormData();data.set('version',current.version);data.set('body',fd.get('body'));data.set('label',fd.get('label'));files.forEach(f=>data.append('files',f));
        const result=await api('/conversations/'+cid+'/sources',{method:'POST',body:data});
        if(routeId===state.renderId&&active(cid)){current=result;update();$('#dialog').close();$('#chat-input').focus();}
        toast(result.added_count?`已收到 ${result.added_count} 份材料${result.duplicate_count?'，相同材料已自动合并':''}。可以接着问了。`:'这几份材料已经在对话里，无需重复上传。');
        if(routeId===state.renderId)document.dispatchEvent(new CustomEvent('campus:milestone',{detail:'materials-saved'}));
      }else if(type==='promote'){
        const selected=fd.getAll('source_ids');if(!selected.length)throw new Error('请选择至少一份通知原文。');
        const result=await api('/conversations/'+conversationId+'/promote',{method:'POST',json:{version:current.version,title:fd.get('title'),source_label:fd.get('source_label'),source_url:fd.get('source_url'),source_ids:selected}});
        if(routeId===state.renderId){$('#dialog').close();location.hash='notice/'+result.notice_id;}
        toast(result.already_created?'这批材料已经转成通知，已打开原记录。':'通知原件已保存，接下来核对本人事项。');
      }else if(type==='rename'){
        const result=await api('/conversations/'+conversationId,{method:'PUT',json:{version:current.version,title:fd.get('title')}});if(routeId===state.renderId&&active(conversationId)){current=result;update();$('#dialog').close();}
      }
    }catch(error){let box=$('.form-error',form);if(!box){box=document.createElement('div');box.className='alert error form-error';box.setAttribute('role','alert');form.prepend(box);}box.textContent=error.message;toast(error.message,true);}
    finally{form.inert=false;submit.disabled=!!current?.processing;if(type!=='chat')submit.disabled=false;}
  });
  document.addEventListener('input',e=>{if(e.target.id==='chat-input')persist();if(e.target.id==='chat-history-search')historyResults(e.target.value);});
  document.addEventListener('change',e=>{if(e.target.id==='chat-files'){addFiles([...e.target.files]);e.target.value='';}});
  document.addEventListener('paste',e=>{if(!$('#chat-upload-form'))return;const incoming=[...(e.clipboardData?.files||[])];if(incoming.length){e.preventDefault();addFiles(incoming);}});
  document.addEventListener('dragover',e=>{if(e.target.closest('#chat-dropzone')){e.preventDefault();$('#chat-dropzone').classList.add('dragging');}});
  document.addEventListener('dragleave',e=>{if(e.target.closest('#chat-dropzone'))$('#chat-dropzone').classList.remove('dragging');});
  document.addEventListener('drop',e=>{if(e.target.closest('#chat-dropzone')){e.preventDefault();$('#chat-dropzone').classList.remove('dragging');addFiles([...e.dataTransfer.files]);}});
  document.addEventListener('keydown',e=>{if(e.target.id==='chat-input'&&(e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();$('#chat-composer').requestSubmit();}});
  window.addEventListener('hashchange',()=>clearTimeout(pollTimer));
  return {render,persist};
}
