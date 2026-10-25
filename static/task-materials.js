// Personal outputs are independent from the notice's original attachments.
export function mountTaskMaterials(host,{task,api,state,esc,timeInput,toTime,onSubmission,savedDraft=null,onChange=()=>{}}){
  const owner=state.session?.user?.id,dialog=state.dialogRequest;
  let bundle=null,replacing=null,busy=false,requestId=crypto.randomUUID();
  let submissionDraft=savedDraft||{};
  const draftFields=['channel','time','receipt','url','note'];
  function snapshot(){
    if(!host.querySelector('[data-submission-channel]'))return submissionDraft;
    return {request_id:requestId,values:Object.fromEntries(draftFields.map(key=>[key,host.querySelector('[data-submission-'+key+']').value])),confirmed:host.querySelector('[data-submission-confirm]').checked,
      files:Object.fromEntries([...host.querySelectorAll('[data-submission-file]')].map(node=>[node.dataset.submissionFile,{checked:node.checked,version:host.querySelector(`[data-submission-version="${node.dataset.submissionFile}"]`).value}])),
      external:[...host.querySelectorAll('[data-submission-external]:checked')].map(node=>node.value),open:host.querySelector('.personal-submission-editor').open};
  }
  function restoreDraft(value){
    for(const key of draftFields)if(value.values?.[key]!==undefined)host.querySelector('[data-submission-'+key+']').value=value.values[key];
    host.querySelector('[data-submission-confirm]').checked=!!value.confirmed;
    for(const node of host.querySelectorAll('[data-submission-file]')){const selected=value.files?.[node.dataset.submissionFile];if(selected){node.checked=selected.checked;host.querySelector(`[data-submission-version="${node.dataset.submissionFile}"]`).value=selected.version;}}
    for(const node of host.querySelectorAll('[data-submission-external]'))node.checked=!!value.external?.includes(node.value);
    host.querySelector('.personal-submission-editor').open=!!value.open;
    if(value.request_id)requestId=value.request_id;
  }
  const current=()=>host.isConnected&&owner===state.session?.user?.id&&dialog===state.dialogRequest;
  const mode=()=>host.closest('form')?.elements.execution_mode.value;
  const syncMode=()=>{host.hidden=mode()!=='submission'&&!task.data.materials.length&&!bundle?.materials.length;const editor=host.querySelector('.personal-submission-editor');if(editor)editor.hidden=mode()!=='submission';};
  if(!document.querySelector('[data-task-material-style]')){
    const link=document.createElement('link');link.rel='stylesheet';link.href=new URL('./task-materials.css',import.meta.url).href;link.dataset.taskMaterialStyle='';document.head.append(link);
  }
  const message=(text,error=false)=>{const node=host.querySelector('[data-material-status]');if(node){node.textContent=text;node.classList.toggle('error',error);}};
  const formatDate=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short',hour12:false}).format(new Date(typeof value==='number'?value*1000:value));
  const url=version=>esc(version.download_url);
  const versionMarkup=version=>`<div class="personal-file-version"><div class="between"><span>版本 ${version.version} · ${esc(version.name)} · ${Math.ceil(version.size/1024)} KB</span><a class="button small plain" href="${url(version)}">下载</a></div>${version.image_preview?`<img class="personal-file-preview" loading="lazy" src="${url(version)}?preview=true" alt="${esc(version.name)}">`:version.preview?`<pre class="personal-file-text">${esc(version.preview)}</pre>`:''}${version.warning?`<p class="small muted">${esc(version.warning)}</p>`:''}</div>`;
  function render(){
    if(!current())return;
    submissionDraft=snapshot();
    const requirements=bundle.requirements,submissions=bundle.submissions;
    host.innerHTML=`<div class="between"><h3>本人办理材料</h3><div class="row wrap"><span class="small muted">${bundle.materials.length} 份</span>${bundle.materials.length?`<a class="button small" href="/api/tasks/${task.id}/materials/package">下载材料包</a>`:''}</div></div><div class="personal-file-list">${bundle.materials.map(material=>{
      const latest=material.versions[0];return `<article class="personal-file"><div class="between"><div><strong>${esc(latest.name)}</strong><p class="small muted">${esc(material.requirement||'其他补充材料')}${material.requirement&&!material.matches_requirement?' · 原要求已变化，请核对归属':''}</p></div><button type="button" class="button small plain" data-replace-material="${material.id}">上传新版本</button></div><div class="row wrap small"><span>版本 ${latest.version} · ${Math.ceil(latest.size/1024)} KB</span><a href="${url(latest)}">下载当前文件</a><span>${formatDate(latest.created_at)}</span></div>${latest.image_preview?`<img class="personal-file-preview" loading="lazy" src="${url(latest)}?preview=true" alt="${esc(latest.name)}">`:''}${latest.preview||latest.warning?`<details><summary>查看文件内容</summary>${latest.preview?`<pre class="personal-file-text">${esc(latest.preview)}</pre>`:''}${latest.warning?`<p class="small muted">${esc(latest.warning)}</p>`:''}</details>`:''}${material.versions.length>1?`<details><summary>历史版本 · ${material.versions.length-1}</summary>${material.versions.slice(1).map(versionMarkup).join('')}</details>`:''}</article>`;
    }).join('')}</div><div class="personal-material-upload"><label class="field">对应材料要求<select data-material-requirement><option value="">其他补充材料</option>${requirements.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('')}</select></label><label class="field">本人准备的文件<input type="file" data-material-file accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg,.webp,.mp4,.webm"></label><div class="row wrap"><button type="button" class="button" data-upload-material>保存本人材料</button><button type="button" class="button plain" data-cancel-replacement hidden>取消新版本</button><span class="small muted">每份最多 5 MB</span></div></div><p class="small" data-material-status role="status"></p><details class="personal-submission-editor"><summary>记录本次提交</summary><div class="stack"><div class="form-grid"><label class="field">实际提交渠道<input data-submission-channel maxlength="200" value="${esc(task.data.submission||'')}" placeholder="学院系统、邮件或线下办公室"></label><label class="field">实际提交时间（北京时间）<input type="datetime-local" data-submission-time value="${esc(timeInput(new Date().toISOString()))}"></label></div><label class="field">提交情况或凭证编号<textarea data-submission-receipt rows="2" maxlength="2000" placeholder="记录已发生的提交和凭证"></textarea></label><label class="field">凭证链接（选填）<input type="url" data-submission-url maxlength="2000"></label><div class="personal-submitted-files"><strong class="small">这次提交的文件版本</strong>${bundle.materials.map(material=>`<label class="personal-submitted-file"><input type="checkbox" data-submission-file="${material.id}" ${material.matches_requirement?'checked':''}><span>${esc(material.requirement||'其他补充材料')}</span><select data-submission-version="${material.id}" aria-label="${esc(material.requirement||'补充材料')}提交版本">${material.versions.map(version=>`<option value="${version.version}">版本 ${version.version} · ${esc(version.name)}</option>`).join('')}</select></label>`).join('')||'<p class="small muted">尚未上传本次文件；在外部提交的材料可在下方记录。</p>'}</div>${requirements.length?`<details><summary>已在外部提交、未附文件的材料</summary>${requirements.map(value=>`<label class="check"><input type="checkbox" data-submission-external value="${esc(value)}"><span>${esc(value)}</span></label>`).join('')}</details>`:''}<label class="field">本次备注（选填）<textarea data-submission-note rows="2" maxlength="2000"></textarea></label><label class="check"><input type="checkbox" data-submission-confirm><span>以上是本人实际提交记录，尚不代表学校受理。</span></label><button type="button" class="button primary" data-record-submission>记录本次提交</button></div></details><details class="personal-submission-history" ${submissions.length?'open':''}><summary>本人提交记录 · ${submissions.length}</summary>${submissions.map(record=>`<article class="personal-submission"><div class="between"><strong>${esc(record.data.channel)}</strong><a class="button small plain" href="/api/tasks/${task.id}/materials/package?submission_id=${encodeURIComponent(record.id)}">下载此次提交包</a></div><p class="small">${formatDate(record.data.submitted_at)} · 本人记录</p><p>${esc(record.data.receipt)}</p>${record.data.receipt_url?`<a href="${esc(record.data.receipt_url)}" target="_blank" rel="noopener noreferrer">查看凭证</a>`:''}${record.data.files.map(file=>`<p class="small"><a href="${url(file)}">${esc(file.name)} · 版本 ${file.version}</a>${file.requirement?' · '+esc(file.requirement):''}</p>`).join('')}${record.data.external_requirements.length?`<p class="small">外部提交：${esc(record.data.external_requirements.join('、'))}</p>`:''}${record.data.note?`<p class="small">${esc(record.data.note)}</p>`:''}</article>`).join('')}</details>`;
  }
  host.closest('form').addEventListener('change',event=>{if(event.target.name==='execution_mode')syncMode();});
  async function load(){
    host.innerHTML='<p class="small" role="status">正在读取本人材料…</p>';
    try{const result=await api(`/tasks/${task.id}/materials`);if(!current())return;bundle=result;render();restoreDraft(submissionDraft);syncMode();}
    catch(error){if(current())host.innerHTML=`<p class="alert error" role="alert">${esc(error.message)}</p><button type="button" class="button small" data-reload-materials>重新读取材料</button>`;}
  }
  async function upload(){
    if(busy||!bundle)return;
    const file=host.querySelector('[data-material-file]').files[0];
    if(!file){message('请选择本人准备的文件',true);return;}
    if(!file.size||file.size>5*1024*1024){message('每份材料须大于 0 字节且不超过 5 MB',true);return;}
    const button=host.querySelector('[data-upload-material]'),form=new FormData();
    form.set('file',file);form.set('task_version',String(task.version));form.set('requirement',host.querySelector('[data-material-requirement]').value);form.set('request_id',requestId);
    if(replacing){form.set('material_id',replacing.id);form.set('expected_version',String(replacing.version));}
    busy=true;button.disabled=true;message('正在保存本人材料…');
    try{const result=await api(`/tasks/${task.id}/materials`,{method:'POST',body:form});if(!current())return;bundle=result;replacing=null;requestId=crypto.randomUUID();render();restoreDraft(submissionDraft);syncMode();onChange();message('本人材料已保存');}
    catch(error){if(current())message(error.message,true);}
    finally{busy=false;if(current())host.querySelector('[data-upload-material]').disabled=false;}
  }
  function collect(){
    if(busy)throw Error('材料还在上传，请稍后记录提交');
    if(!bundle)throw Error('请先读取当前材料');
    const value=selector=>host.querySelector(selector).value.trim();
    const channel=value('[data-submission-channel]'),submitted_at=toTime(value('[data-submission-time]')),receipt=value('[data-submission-receipt]'),receipt_url=value('[data-submission-url]');
    if(channel.length<2)throw Error('请填写实际提交渠道');
    if(!submitted_at)throw Error('请填写实际提交时间');
    if(receipt.length<2)throw Error('请填写实际提交情况或凭证编号');
    if(!host.querySelector('[data-submission-url]').checkValidity())throw Error('凭证链接格式不正确');
    if(!host.querySelector('[data-submission-confirm]').checked)throw Error('请确认这是本人实际提交记录');
    return {request_id:requestId,channel,submitted_at,receipt,receipt_url,note:value('[data-submission-note]'),confirmed:true,
      files:[...host.querySelectorAll('[data-submission-file]:checked')].map(node=>({material_id:node.dataset.submissionFile,version:Number(host.querySelector(`[data-submission-version="${node.dataset.submissionFile}"]`).value)})),
      external_requirements:[...host.querySelectorAll('[data-submission-external]:checked')].map(node=>node.value)};
  }
  host.addEventListener('change',event=>{if(event.target.matches('[data-material-file],[data-material-requirement]')&&!busy)requestId=crypto.randomUUID();});
  host.addEventListener('input',()=>{submissionDraft=snapshot();onChange();});
  host.addEventListener('change',()=>{submissionDraft=snapshot();onChange();});
  host.addEventListener('click',event=>{
    const replace=event.target.closest('[data-replace-material]');
    if(replace&&!busy){const selected=bundle.materials.find(item=>item.id===replace.dataset.replaceMaterial);if(selected.requirement&&!selected.matches_requirement){message('原材料要求已变化，请按当前要求另建材料；旧文件仍可下载',true);return;}replacing=selected;const select=host.querySelector('[data-material-requirement]');select.value=replacing.requirement;select.disabled=true;host.querySelector('[data-cancel-replacement]').hidden=false;host.querySelector('[data-upload-material]').textContent='保存新版本';requestId=crypto.randomUUID();message('为“'+replacing.versions[0].name+'”上传新版本');host.querySelector('[data-material-file]').click();}
    if(event.target.closest('[data-cancel-replacement]')&&!busy){replacing=null;host.querySelector('[data-material-requirement]').disabled=false;host.querySelector('[data-cancel-replacement]').hidden=true;host.querySelector('[data-upload-material]').textContent='保存本人材料';requestId=crypto.randomUUID();message('');}
    if(event.target.closest('[data-upload-material]'))upload();
    if(event.target.closest('[data-reload-materials]'))load();
    if(event.target.closest('[data-record-submission]')){try{onSubmission(collect());}catch(error){message(error.message,true);}}
  });
  syncMode();load();
  return {collect,snapshot};
}
