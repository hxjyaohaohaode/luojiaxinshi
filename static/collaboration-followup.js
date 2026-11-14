import {beginFormFeedback,captureUiContext} from './ui-request.js';

export function followupLocalTime(value){
  if(!value)return '';
  const date=new Date(value);if(!Number.isFinite(date.getTime()))return '';
  const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
  const get=key=>parts.find(part=>part.type===key)?.value||'';
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
}

export function followupIso(value){
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))throw Error('请填写完整的北京时间。');
  const date=new Date(value+':00+08:00');
  if(!Number.isFinite(date.getTime())||followupLocalTime(date.toISOString())!==value)throw Error('跟进日期或时刻不正确，请重新选择。');
  return date.toISOString();
}

export function createCollaborationFollowup({state,api,esc,showDialog,toast,onChanged=()=>{}}){
  const $=(selector,root=document)=>root.querySelector(selector);
  let active=null,sequence=0,controller=null;
  const valid=item=>item&&active===item&&item.owner===state.session?.user?.id;
  function dispose(){sequence++;controller?.abort();controller=null;active=null;}
  function paint(item,draft){
    if(!active)return;
    active.value=item;
    const current=item.due_at?followupLocalTime(item.due_at).replace('T',' '):'未设置';
    const value=draft===undefined?followupLocalTime(item.due_at):draft;
    showDialog('本人协作跟进',`<section class="collaboration-followup"><p><strong>${esc(item.title)}</strong></p>
      <p class="small muted">${esc(item.note)}</p><p class="small">当前设置：${esc(current)}${item.due_at?'（北京时间）':''}${item.active?(item.overdue?' · 已到跟进时间':' · 等待跟进'):item.due_at?' · 已停止提醒':''}</p>
      <form data-collaboration-followup-form class="stack"><label class="field">下次跟进时间（北京时间）<input type="datetime-local" name="due_at" value="${esc(value)}" min="2000-01-01T00:00" max="2100-12-31T23:59" ${item.can_set?'':'disabled'}></label>
      ${draft===undefined?'':'<p class="alert info">已读取服务器最新设置，你刚才选择的时间仍保留在输入框。请核对后再保存。</p>'}
      ${item.can_set?'':'<p class="small muted">协作已关闭或当前授权失效，可清除原个人安排，不能新增跟进。</p>'}
      <p class="small muted">到期后进入本人站内提醒，并按自己的推送、邮件和免打扰偏好重新计算。这里不会给对方设置截止，也不表示学校已受理。</p>
      <p class="small" data-collaboration-followup-status role="status"></p>
      <div class="row wrap">${item.can_set?'<button class="button primary" type="submit" value="save">保存本人跟进</button>':''}${item.due_at?'<button class="button" type="submit" value="clear">取消本人跟进</button>':''}</div></form></section>`,{replaceHistory:true});
  }
  async function open(caseId,draft){
    dispose();const view=captureUiContext(state),request=sequence;
    controller=new AbortController();
    const item=await api('/collaboration/'+encodeURIComponent(caseId)+'/followup',{signal:controller.signal});
    if(request!==sequence||!view.sameDialog())return false;
    active={id:caseId,owner:state.session?.user?.id,value:item};paint(item,draft);return true;
  }
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!form.hasAttribute('data-collaboration-followup-form'))return;
    event.preventDefault();const entry=active;if(!valid(entry))return;
    const feedback=beginFormFeedback(form);if(!feedback)return;
    const view=captureUiContext(state,form),status=$('[data-collaboration-followup-status]',form);
    try{
      const clear=event.submitter?.value==='clear';
      const due=clear?null:followupIso(form.elements.due_at.value);
      const signature=JSON.stringify([entry.value.version,due]);
      if(entry.signature!==signature){entry.signature=signature;entry.requestId=crypto.randomUUID();}
      const result=await api('/collaboration/'+encodeURIComponent(entry.id)+'/followup',{method:'PUT',json:{version:entry.value.version,due_at:due,request_id:entry.requestId}});
      if(!valid(entry)||!view.sameUser())return;
      if(view.sameDialog())paint(result);
      toast(due?'本人跟进已保存':'本人跟进已取消');onChanged({caseId:entry.id,followup:result});
    }catch(error){
      if(!valid(entry)||!view.sameDialog()||error.name==='AbortError')return;
      status.textContent=error.message||'跟进暂未保存，请稍后重试。';
      if(error.status===409&&!form.querySelector('[data-collaboration-followup-reload]')){
        const button=document.createElement('button');button.type='button';button.className='link-button';
        button.dataset.collaborationFollowupReload='';button.textContent='核对最新时间（保留输入）';status.after(button);
      }
    }finally{feedback();}
  });
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-collaboration-followup-reload]');if(!button||!valid(active))return;
    const entry=active,draft=button.closest('form')?.elements.due_at.value;
    try{await open(entry.id,draft);}catch(error){if(error.name!=='AbortError'&&entry.owner===state.session?.user?.id)toast(error.message||'暂时无法读取当前跟进',true);}
  });
  document.addEventListener('close',event=>{if(event.target.id==='dialog')dispose();},true);
  window.addEventListener('hashchange',dispose);
  return {open,close:dispose};
}
