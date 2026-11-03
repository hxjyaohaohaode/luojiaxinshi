// Preparation lives next to the user's files and real submission records.
export function mountHandlingAssistant(host,{task,state,api,esc,onSave,onChange=()=>{},savedDraft=null}){
  const owner=state.session?.user?.id,dialog=state.dialogRequest;
  const current=()=>host.isConnected&&owner===state.session?.user?.id&&dialog===state.dialogRequest;
  let preview=null,busy=false,requestId=crypto.randomUUID(),requestBody='',uploadId=crypto.randomUUID(),uploadBody='';
  host.innerHTML=`<details class="handling-assistant"><summary>让小信使帮我准备</summary><div class="stack"><div class="form-grid"><label class="field">需要哪种帮助<select data-assist-purpose><option value="material">材料内容草稿 / 原表填写建议</option><option value="message">提交或咨询消息</option><option value="questions">合并缺项，拟好询问</option></select></label><label class="field" data-assist-requirement-field>对应材料<select data-assist-requirement><option value="">本步骤的准备内容</option>${task.data.materials.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('')}</select></label></div><details><summary>补充本次已知信息（选填）</summary><label class="field">用于草稿的个人信息<textarea data-assist-context rows="3" maxlength="3000" placeholder="例如：本人姓名、申请意向，或已有材料情况；不必重复通知原文。不要填写密码或验证码。"></textarea></label></details><label class="check"><input type="checkbox" data-assist-consent><span>同意将本通知、办理要求、必要个人条件及本次补充交给小米 MiMo，准备一份草稿</span></label><div class="row wrap"><button type="button" class="button primary" data-assist-generate>帮我准备</button><button type="button" class="button small plain" data-assist-load>读取已保存结果</button></div><p class="small" data-assist-status role="status"></p><div data-assist-preview></div></div></details>`;
  const $=selector=>host.querySelector(selector);
  if(task.data.materials.length) $('[data-assist-requirement]').value=task.data.materials[0];
  const message=(text,error=false)=>{if(!current())return;$('[data-assist-status]').textContent=text;$('[data-assist-status]').classList.toggle('error',error);};
  function snapshot(){return preview?{request_id:preview.request_id,title:$('[data-assist-title]')?.value||preview.title,body:$('[data-assist-body]')?.value||preview.body}:null;}
  function show(result){
    if(!current())return;
    preview=result;uploadId=crypto.randomUUID();uploadBody='';
    const previous=savedDraft?.request_id===result.request_id?savedDraft:null;
    $('[data-assist-preview]').innerHTML=`<section class="assistance-preview stack"><div class="between"><strong>准备草稿</strong><span class="pill">等你核对</span></div><p class="small route-unknown" data-assist-missing></p><label class="field">草稿名称<input data-assist-title maxlength="160" value="${esc(previous?.title||result.title)}"></label><label class="field">草稿内容<textarea data-assist-body rows="9" maxlength="16000">${esc(previous?.body||result.body)}</textarea></label><details><summary>生成时参考的原文</summary>${result.evidence.map(e=>`<blockquote><span class="small muted">${esc(e.locator)}</span><p>${esc(e.quote)}</p></blockquote>`).join('')}<a href="#notice/${task.notice_id}">查看完整通知 ↗</a></details><label class="check"><input type="checkbox" data-assist-reviewed><span>将当前内容作为待核对草稿保存到本人材料</span></label><div class="row wrap"><button type="button" class="button primary" data-assist-save>保存为本人草稿</button><button type="button" class="button" data-assist-download>下载文字草稿</button><button type="button" class="button small plain" data-assist-new>重新准备一份</button></div><p class="small muted">按原表要求填写、补齐个人信息后再实际提交。这里保存的是本人准备文件。</p></section>`;
    remainingFields();
    $('[data-assist-preview]').closest('details').open=true;
  }
  function remainingFields(){
    if(!preview||!$('[data-assist-missing]'))return;
    const body=$('[data-assist-body]').value;
    const missing=body===preview.body?preview.missing_fields:[...new Set([...body.matchAll(/【待(?:填写|补充|确认)[：:]\s*([^】]+)】/g)].map(match=>match[1]))];
    const node=$('[data-assist-missing]');node.hidden=!missing.length;node.textContent=missing.length?'还需补充：'+missing.join('、')+'。可继续准备其他已知内容。':'';
  }
  async function load(){
    if(busy)return;
    try{const result=await api(`/tasks/${task.id}/assistance`);if(!current())return;if(result.status==='ready')show(result);else message('当前步骤还没有可复用的准备草稿。');}
    catch(error){message(error.message,true);}
  }
  async function generate(){
    if(busy||!current())return;
    if(!$('[data-assist-consent]').checked){message('请先同意本次 AI 处理，再开始准备。',true);$('[data-assist-consent]').focus();return;}
    const purpose=$('[data-assist-purpose]').value;
    const body={task_version:task.version,workflow_version:task.workflow.version,purpose,
      requirement:purpose==='material'?$('[data-assist-requirement]').value:'',personal_context:$('[data-assist-context]').value.trim(),allow_external_processing:true,
      processing_mode:state.session.ai.notice_modes?.some(mode=>mode.id==='daily')?'daily':'configured'};
    const serialized=JSON.stringify(body);if(requestBody&&requestBody!==serialized)requestId=crypto.randomUUID();requestBody=serialized;
    busy=true;$('[data-assist-generate]').disabled=true;message('正在对照原文准备，可以继续查看材料和办理要求；失败不会自动重发。');
    try{const result=await api(`/tasks/${task.id}/assistance`,{method:'POST',json:{...body,request_id:requestId}});if(current()){show(result);message('草稿已准备好，补齐需要的内容后可以保存或下载。');}}
    catch(error){message(error.message+'；可先读取已保存结果。若需重新请求，请点“重新准备一份”。',true);if(current()&&!$('[data-assist-new]'))$('[data-assist-preview]').innerHTML='<button type="button" class="button small" data-assist-new>重新准备一份</button>';}
    finally{busy=false;if(current())$('[data-assist-generate]').disabled=false;}
  }
  function content(){const value=snapshot();return '[本人准备草稿 · 待核对]\n'+value.title+'\n\n'+value.body+'\n\n此文件由本人核对后再按原通知渠道提交。';}
  const filename=()=>('草稿_'+($('[data-assist-title]').value.trim()||'办理准备')).replace(/[\\/:*?"<>|\x00-\x1f]/g,'_')+'.txt';
  host.addEventListener('input',event=>{if(event.target.matches('[data-assist-title],[data-assist-body]')){remainingFields();onChange();}else if(event.target.matches('[data-assist-context]'))$('[data-assist-consent]').checked=false;});
  host.addEventListener('change',event=>{if(event.target.matches('[data-assist-purpose],[data-assist-requirement]')){$('[data-assist-consent]').checked=false;$('[data-assist-requirement-field]').hidden=$('[data-assist-purpose]').value!=='material';}});
  host.addEventListener('click',async event=>{
    if(event.target.closest('[data-assist-generate]'))void generate();
    if(event.target.closest('[data-assist-load]'))void load();
    if(event.target.closest('[data-assist-new]')&&!busy){requestId=crypto.randomUUID();requestBody='';$('[data-assist-consent]').checked=false;message('已开始新的一次准备。核对输入并勾选授权后点击“帮我准备”。');$('[data-assist-generate]').focus();}
    if(event.target.closest('[data-assist-download]')&&preview){const url=URL.createObjectURL(new Blob([content()],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=filename();a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    if(event.target.closest('[data-assist-save]')&&preview&&!busy){
      if(!$('[data-assist-reviewed]').checked){message('请确认将当前内容作为待核对草稿保存。',true);return;}
      busy=true;const control=$('[data-assist-save]');control.disabled=true;message('正在保存本人草稿…');
      try{const text=content(),body=JSON.stringify([preview.request_id,filename(),text]);
        const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
        uploadId=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');uploadBody=body;
        await onSave({...preview,filename:filename(),text,uploadId});if(current()){message('已保存到下方本人材料，可继续完善、上传新版本，再记录实际提交。');onChange();}}
      catch(error){message(error.message,true);}
      finally{busy=false;if(current())control.disabled=false;}
    }
  });
  void load();
  return {snapshot};
}
