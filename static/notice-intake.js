import {beginFormFeedback} from './ui-request.js';

export const dispositionNames={inbox:'待处理',reference:'仅存资料',not_applicable:'与我无关',closed:'已结束'};
export const isNoticeOpen=n=>(n.disposition||n.handling?.disposition||'inbox')==='inbox';
export function noticeState(n){
  const disposition=n.disposition||n.handling?.disposition||'inbox';
  if(disposition!=='inbox')return [dispositionNames[disposition]||'已收好',''];
  return ({received:['待处理',''],draft:['待核对','orange'],processing:['处理中','blue'],confirmed:['已转为行动','green'],failed:['处理失败','red']})[n.status]||['待处理',''];
}
export function batchEntry(){return {id:crypto.randomUUID(),request_id:crypto.randomUUID(),title:'',body:'',source_label:'',source_url:'',published_at:'',materials_complete:false,target:'',target_version:null,link_preview:'',files:[],saved_id:'',error:''};}
export function prepareEntry(item,files,toTime){
  if(!item.title.trim())throw new Error('请填写通知标题');
  if(!item.body.trim()&&!files.length&&!item.link_preview)throw new Error('请添加正文、附件或已读取的链接');
  if(item.files.length&&!files.length)throw new Error('请重新选择暂存的附件，或明确移除附件记录');
  if(files.length>5||files.some(file=>file.size>5*1024*1024||!file.size))throw new Error('每则通知最多 5 份附件，每份大于 0 且不超过 5 MB');
  const form=new FormData();
  for(const key of ['title','body','source_label','source_url','link_preview','request_id'])form.set(key,item[key]||'');
  if(item.allow_duplicate)form.set('allow_duplicate','true');
  form.set('published_at',toTime(item.published_at)||'');form.set('materials_complete',String(item.materials_complete));
  if(item.target)form.set('version',String(item.target_version));
  files.forEach(file=>form.append('files',file));
  return form;
}

export function createNoticeIntakeUI({state,api,esc,icon,toast,showDialog,field,area,drafts,persist,refreshData,onNotice,toTime}){
  const $=s=>document.querySelector(s),key='intake-batch';
  let owner=null,items=[],fileMap=new Map(),generation=0,busy=false,previewRequest=0;
  const sameOwner=session=>!!session&&state.session===session;
  const linkFields=()=>`<div class="notice-link-entry"><label class="field">原文链接<input type="url" data-read-url placeholder="https://…" maxlength="2000"></label><button type="button" class="button" data-read-link>读取链接</button></div><input type="hidden" name="link_preview"><div data-link-preview role="status"></div>`;
  function previewLabel(form,name='已读取的链接材料'){
    const target=form.querySelector('[data-link-preview]');if(!target)return;
    target.innerHTML=form.elements.link_preview.value?`<div class="intake-preview-ready"><span>${esc(name)}</span><button type="button" class="button small plain" data-remove-link>移除链接材料</button></div>`:'';
  }
  function attachSingle(form){
    const head=form.querySelector('.compose-section-heading');
    head.insertAdjacentHTML('afterend',linkFields());
    form.insertAdjacentHTML('beforeend',`<input type="hidden" name="request_id" value="${crypto.randomUUID()}">`);
    head.insertAdjacentHTML('beforebegin','<div class="intake-switch"><a class="button small plain" href="#intake">多则通知 / 补充原事项</a></div>');
  }
  function restoreSingle(form){previewLabel(form);form.dispatchEvent(new Event('input',{bubbles:true}));}
  async function readLink(form,item=null){
    const input=form.querySelector('[data-read-url]'),url=input.value.trim()||form.elements.source_url?.value||'',user=state.session,request=++previewRequest;
    if(!url){input.focus();toast('先填入原文链接',true);return;}
    const button=form.querySelector('[data-read-link]');button.disabled=true;button.textContent='正在读取…';
    try{
      const preview=await api('/intake/link',{method:'POST',json:{url}});
      if(request!==previewRequest||!sameOwner(user)||!form.isConnected)return;
      if(input.value.trim()&&input.value.trim()!==url){toast('网址已改变，请读取新的链接');return;}
      const source=preview.source,origin=source.origin;
      showDialog('核对链接材料',`<div class="stack"><h3>${esc(preview.title||source.name)}</h3><a href="${esc(origin.url)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a>${origin.warnings.length?`<div class="alert">${origin.warnings.map(esc).join('<br>')}</div>`:''}${origin.attachments.length?`<details><summary>原文附件链接 · ${origin.attachments.length}</summary><ul>${origin.attachments.map(url=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url.split('/').pop())}</a></li>`).join('')}</ul></details>`:''}<details open><summary>读取的正文 · ${source.sections.reduce((n,s)=>n+s.text.length,0).toLocaleString()} 字</summary><div class="intake-link-text">${source.sections.map(s=>`<p>${esc(s.text)}</p>`).join('')||'<p>已保存原件，需对照原件核实内容。</p>'}</div></details><div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button type="button" class="button primary" data-use-link>加入这则通知</button></div></div>`);
      const dialog=state.dialogRequest;
      $('#dialog [data-use-link]').addEventListener('click',()=>{
        if(!sameOwner(user)||dialog!==state.dialogRequest||!form.isConnected)return;
        form.elements.link_preview.value=preview.id;
        if(!form.elements.title.value.trim())form.elements.title.value=preview.title||source.name;
        form.elements.source_url.value=origin.url;
        if(item){capture();item.link_preview=preview.id;stage();}
        previewLabel(form,source.name);form.dispatchEvent(new Event('input',{bubbles:true}));persist();$('#dialog').close();
      },{once:true});
    }catch(error){if(sameOwner(user)&&form.isConnected)toast(error.message,true);}
    finally{if(button.isConnected){button.disabled=false;button.textContent='读取链接';}}
  }
  function dispositionPanel(n){
    const value=n.handling?.disposition||'inbox';
    return `<section class="notice-handling" aria-label="通知处理方式"><div><strong>${value==='inbox'?'这则通知怎么处理':esc(dispositionNames[value])}</strong>${n.handling?.note?`<p class="small muted">${esc(n.handling.note)}</p>`:''}</div><div class="row wrap">${(value==='inbox'?['reference','not_applicable',...(n.tasks.length?['closed']:[])]:['inbox']).map(mode=>`<button type="button" class="button small" data-notice-disposition="${mode}" ${n.status==='processing'?'disabled':''}>${mode==='inbox'?'重新处理':dispositionNames[mode]}</button>`).join('')}</div></section>`;
  }
  function decorateNotice(n){
    $('.notice-primary')?.insertAdjacentHTML('afterend',dispositionPanel(n));
    if(!isNoticeOpen(n)){
      const draft=$('#draft-pane');if(draft)draft.hidden=true;
      const steps=$('.notice-steps');if(steps)steps.hidden=true;
      $('.review-grid')?.classList.add('notice-resolved');
    }
  }
  function capture(){
    for(const card of document.querySelectorAll('[data-intake-entry]')){
      const item=items.find(i=>i.id===card.dataset.intakeEntry);if(!item||item.saved_id)continue;
      for(const name of ['title','body','source_label','source_url','published_at','link_preview'])item[name]=card.elements[name].value;
      item.materials_complete=card.elements.materials_complete.checked;
      const selected=card.elements.target.value;
      if(item.target!==selected){item.target=selected;item.target_version=state.notices.find(n=>n.id===selected)?.version??null;}
    }
  }
  function stage(){if(owner&&sameOwner(owner)&&!busy){drafts.stage(key,{items:structuredClone(items)});}}
  function itemHTML(item,index){
    if(item.saved_id)return `<article class="panel intake-saved"><strong>${esc(item.title)}</strong><a class="button small" href="#notice/${encodeURIComponent(item.saved_id)}">继续核对与办理</a><button class="button small plain" type="button" data-intake-remove="${esc(item.id)}">移出收件列表</button></article>`;
    return `<form class="panel stack intake-entry" data-intake-entry="${esc(item.id)}" data-workspace-form="intake-entry"><div class="between"><h2>通知 ${index+1}</h2><button type="button" class="button small plain" data-intake-remove="${esc(item.id)}">移除这一则</button></div><label class="field">保存到<select name="target"><option value="">新建一则通知</option>${item.target&&!state.notices.some(n=>n.id===item.target)?`<option value="${esc(item.target)}" selected>原通知暂不可用，请重新选择</option>`:''}${state.notices.map(n=>`<option value="${esc(n.id)}" ${item.target===n.id?'selected':''}>补充：${esc(n.title)}</option>`).join('')}</select></label>${field('标题','title',item.title,'text','required maxlength="160"')}${linkFields()}${area('正文','body',item.body,4,'maxlength="10000"')}<label class="field">这一则的附件<input type="file" name="files" multiple accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg,.webp,.mp4,.webm"></label><div class="small" data-intake-files>${item.files.length?esc(item.files.join('、')):''}</div>${item.files.length&&!fileMap.has(item.id)?'<div class="alert">附件需要重新选择。<button type="button" class="link-button" data-clear-file-record>移除附件记录</button></div>':''}<div class="form-grid">${field('来源名称','source_label',item.source_label,'text','maxlength="100"')}${field('发布时间（北京时间）','published_at',item.published_at,'datetime-local')}</div>${field('原文地址','source_url',item.source_url,'url','maxlength="2000"')}<label class="check"><input type="checkbox" name="materials_complete" ${item.materials_complete?'checked':''}>正文和关键附件已核对齐全</label>${item.error?`<div class="alert error" role="alert">${esc(item.error)}${item.refresh_target?`<div class="row wrap"><a class="button small" href="#notice/${encodeURIComponent(item.target)}">核对原通知</a><button type="button" class="button small" data-intake-refresh="${esc(item.id)}">刷新原通知版本</button></div>`:''}${item.existing_id?`<div class="row wrap"><a class="button small" href="#notice/${encodeURIComponent(item.existing_id)}">打开已有通知</a><button type="button" class="button small" data-intake-reuse="${esc(item.id)}">使用已有通知</button><button type="button" class="button small" data-intake-retry="${esc(item.id)}">${item.retry_changed?'保存当前修改':'确属另一批次'}</button></div>`:''}</div>`:''}</form>`;
  }
  function draw(){
    const list=$('#intake-entries');if(!list)return;
    list.innerHTML=items.map(itemHTML).join('');
    for(const form of list.querySelectorAll('[data-intake-entry]')){
      form.inert=busy;
      const item=items.find(i=>i.id===form.dataset.intakeEntry);form.elements.link_preview.value=item.link_preview;previewLabel(form);
      const files=fileMap.get(item.id);if(files){const transfer=new DataTransfer();files.forEach(f=>transfer.items.add(f));form.elements.files.files=transfer.files;}
    }
    const remaining=items.filter(i=>!i.saved_id).length;
    $('#intake-save').disabled=!remaining||busy;$('#intake-save').textContent=remaining?`保存 ${remaining} 则通知`:'全部已保存';
    $('#intake-add').disabled=items.length>=12||busy;
  }
  async function render(){
    const user=state.session,route=state.renderId;
    if(owner!==user){owner=user;items=[];fileMap=new Map();busy=false;generation++;}
    const cached=await drafts.load(key);if(!sameOwner(user)||route!==state.renderId)return;
    if(!items.length)items=(cached.payload?.items||[]).slice(0,12);
    if(!items.length)items=[batchEntry()];drafts.activate(key);
    $('#content').innerHTML=`<section class="intake-workspace"><div class="page-title between"><h1>通知收件</h1><a class="button small" href="#new">单则录入</a></div><div class="intake-batch-toolbar"><button type="button" class="button" id="intake-add">${icon('plus')} 再加一则</button><button type="button" class="button primary" id="intake-save">保存通知</button><span class="small muted" id="intake-result" role="status"></span></div><div id="intake-entries" class="intake-entries"></div></section>`;
    draw();stage();
  }
  async function saveBatch(){
    if(busy)return;capture();stage();
    const user=owner,run=++generation,route=state.renderId;
    const pending=items.filter(i=>!i.saved_id);if(!pending.length)return;
    for(const form of document.querySelectorAll('[data-intake-entry]'))if(!form.reportValidity())return;
    const snapshots=pending.map(item=>({item:structuredClone(item),files:[...(fileMap.get(item.id)||[])]}));
    try{for(const s of snapshots)prepareEntry(s.item,s.files,toTime);}catch(error){toast(error.message,true);return;}
    busy=true;$('#intake-save').disabled=true;$('#intake-add').disabled=true;
    for(const form of document.querySelectorAll('[data-intake-entry]'))form.inert=true;
    let saved=0,failed=0;
    try{
      await drafts.flush(key);
      for(const snapshot of snapshots){
        if(!sameOwner(user)||run!==generation)break;
        const item=items.find(i=>i.id===snapshot.item.id);if(!item)continue;
        try{
          const result=await api(item.target?`/notices/${item.target}/supplement`:'/notices',{method:'POST',body:prepareEntry(snapshot.item,snapshot.files,toTime)});
          if(!sameOwner(user)||run!==generation)break;
          item.saved_id=result.id;item.error='';item.existing_id='';saved++;
        }catch(error){
          if(!sameOwner(user)||run!==generation)break;
          item.existing_id=error.detail?.duplicate_id||'';item.refresh_target=!!item.target&&error.status===409&&!item.existing_id;
          item.retry_changed=error.detail?.reason==='request_changed';
          item.error=item.retry_changed?'上一次内容已经保存。可以打开已保存通知；当前修改可作为新的提交继续保存。':item.existing_id?'已有相同材料，请核对已有通知；确属另一批次时可另行保存。':error.message;failed++;
        }
        // Persist each receipt so a partially successful batch resumes only the
        // unfinished entries. Unknown responses reuse the same request ID.
        drafts.stage(key,{items:structuredClone(items)});await drafts.flush(key);
        if(route===state.renderId&&$('#intake-result'))$('#intake-result').textContent=`已保存 ${saved} 则${failed?`，${failed} 则需处理`:''}`;
      }
      if(sameOwner(user))await refreshData();
    }catch(error){if(sameOwner(user))toast(error.message,true);}
    finally{if(sameOwner(user)&&run===generation){busy=false;if(route===state.renderId)draw();}}
  }
  document.addEventListener('click',async event=>{
    const link=event.target.closest('[data-read-link]');if(link){const form=link.closest('form');await readLink(form,items.find(i=>i.id===form.dataset.intakeEntry));return;}
    const removeLink=event.target.closest('[data-remove-link]');if(removeLink){const form=removeLink.closest('form');form.elements.link_preview.value='';previewLabel(form);form.dispatchEvent(new Event('input',{bubbles:true}));persist();return;}
    if(event.target.closest('#intake-add')&&!busy){capture();items.push(batchEntry());stage();draw();$('#intake-entries .intake-entry:last-child [name=title]')?.focus();}
    if(event.target.closest('#intake-save'))await saveBatch();
    const refresh=event.target.closest('[data-intake-refresh]');if(refresh&&!busy){
      capture();const item=items.find(i=>i.id===refresh.dataset.intakeRefresh),session=state.session;refresh.disabled=true;
      try{const n=await api('/notices/'+item.target);if(!sameOwner(session))return;item.target_version=n.version;item.refresh_target=false;item.error='';stage();draw();toast('已读取原通知最新版本，请核对后重新保存补充内容');}
      catch(error){if(sameOwner(session))toast(error.message,true);}finally{if(refresh.isConnected)refresh.disabled=false;}
    }
    const retry=event.target.closest('[data-intake-retry]');if(retry&&!busy){
      capture();const item=items.find(i=>i.id===retry.dataset.intakeRetry);
      item.allow_duplicate=!item.retry_changed;item.request_id=crypto.randomUUID();item.existing_id='';item.error='';item.retry_changed=false;stage();draw();
    }
    const reuse=event.target.closest('[data-intake-reuse]');if(reuse&&!busy){
      capture();const item=items.find(i=>i.id===reuse.dataset.intakeReuse);item.saved_id=item.existing_id;item.error='';stage();draw();
    }
    const remove=event.target.closest('[data-intake-remove]');if(remove&&!busy){capture();fileMap.delete(remove.dataset.intakeRemove);items=items.filter(i=>i.id!==remove.dataset.intakeRemove);stage();draw();}
    const clear=event.target.closest('[data-clear-file-record]');if(clear&&!busy){capture();const item=items.find(i=>i.id===clear.closest('form').dataset.intakeEntry);item.files=[];fileMap.delete(item.id);stage();draw();}
    const disposition=event.target.closest('[data-notice-disposition]');if(disposition){
      const n=state.notice,user=state.session,route=state.renderId,mode=disposition.dataset.noticeDisposition;
      showDialog(mode==='inbox'?'重新处理通知':dispositionNames[mode],`<form class="stack" data-workspace-form="notice-disposition">${area('处理说明（选填）','note',mode==='inbox'?'':n.handling?.note||'',3,'maxlength="1000"')}<div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button type="submit" class="button primary">确认</button></div></form>`);
      const form=$('#dialog form'),dialog=state.dialogRequest;
      form.addEventListener('submit',async event=>{
        event.preventDefault();const finish=beginFormFeedback(form);if(!finish)return;const note=form.elements.note.value;form.inert=true;
        try{const result=await api(`/notices/${n.id}/disposition`,{method:'PUT',json:{version:n.version,disposition:mode,note}});if(!sameOwner(user))return;if(dialog===state.dialogRequest)$('#dialog').close();if(route===state.renderId)onNotice(result);await refreshData();toast('通知处理方式已保存');}
        catch(error){if(sameOwner(user))toast(error.message,true);}finally{form.inert=false;finish();}
      });
    }
  });
  document.addEventListener('input',event=>{if(event.target.closest('[data-intake-entry]')&&!busy){capture();stage();}});
  document.addEventListener('change',event=>{
    const form=event.target.closest('[data-intake-entry]');if(!form||busy)return;
    if(event.target.name==='files'){
      const item=items.find(i=>i.id===form.dataset.intakeEntry),files=[...event.target.files];
      if(files.length>5||files.some(f=>!f.size||f.size>5*1024*1024)){toast('每则最多 5 份附件，每份大于 0 且不超过 5 MB',true);const transfer=new DataTransfer();(fileMap.get(item.id)||[]).forEach(f=>transfer.items.add(f));event.target.files=transfer.files;return;}
      fileMap.set(item.id,files);item.files=files.map(f=>f.name);form.querySelector('[data-intake-files]').textContent=item.files.join('、');form.querySelector('[data-clear-file-record]')?.closest('.alert').remove();
    }
    capture();stage();
  });
  document.addEventListener('submit',event=>{if(event.target.matches('[data-intake-entry]')){event.preventDefault();saveBatch();}});
  return {attachSingle,restoreSingle,decorateNotice,render};
}
