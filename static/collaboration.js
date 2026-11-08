import {beginFormFeedback,captureUiContext} from './ui-request.js';

const states={sent:'待接收',accepted:'办理中',supplement:'待补件',resubmitted:'已补交，待接收',resolved:'协作办结',withdrawn:'已撤回'};
const actions={send:'发起协作',accept:'接收办理',request_supplement:'退回补件',resubmit:'补交材料',resolve:'保存办结回执',withdraw:'撤回协作'};
const date=value=>new Intl.DateTimeFormat('zh-CN',{dateStyle:'short',timeStyle:'short',timeZone:'Asia/Shanghai'}).format(new Date(value*1000));

export function createCollaborationUI({state,api,esc,showDialog,toast}){
  const $=selector=>document.querySelector(selector);
  let side='recipient',page=1,owner=null,record=null,sequence=0,saving=false;
  function choices(files){
    if(!files?.length)return '';
    const fields=files.map(file=>'<label class="check"><input type="checkbox" name="shared_file" value="'+esc(file.material_id)+':'+file.version+'"><span>'+esc(file.name)+' · 第 '+file.version+' 版</span></label>');
    return '<fieldset class="stack" data-collaboration-files><legend>选择要分享的材料版本</legend>'+fields.join('')+'</fieldset>';
  }
  function history(item){
    const entries=item.events.map(event=>{
      const files=event.files.map(file=>file.download_url?
        '<p><a href="'+esc(file.download_url)+'" download>'+esc(file.name)+'</a> <span class="small muted">'+Math.ceil(file.size/1024)+' KB</span></p>':
        '<p class="small muted">'+esc(file.name)+' · 已移除分享</p>');
      return '<li><div><strong>'+esc(actions[event.action]||event.action)+' · '+esc(event.actor)+'</strong><time>'+date(event.created_at)+'</time></div><p class="collaboration-note">'+esc(event.note)+'</p>'+files.join('')+'</li>';
    });
    return '<ol class="workflow-timeline">'+entries.join('')+'</ol>';
  }
  function actionForm(item,note=''){
    if(!item.actions.length)return note?'<p class="small muted">这次输入已保留</p><p class="collaboration-note">'+esc(note)+'</p>':'';
    const options=item.actions.map(key=>'<option value="'+key+'">'+actions[key]+'</option>').join('');
    return '<form data-workspace-form="collaboration" data-case-id="'+esc(item.id)+'" data-version="'+item.version+'" data-request-id="'+crypto.randomUUID()+'" class="stack">'+
      '<label class="field">下一步<select name="action">'+options+'</select></label>'+
      '<label class="field">办理说明或回执<textarea name="note" rows="3" maxlength="2000">'+esc(note)+'</textarea></label>'+
      choices(item.file_choices)+'<div class="form-footer"><button type="submit" class="button primary">确认操作</button></div></form>';
  }
  function status(item){
    return states[item.state]+(item.recipient_available?'':' · 原接收范围已变更');
  }
  function paint(item){
    $('#content').innerHTML='<section class="stack collaboration-page"><div class="page-title"><a class="small" href="#collaboration">返回协作办理</a><h1>'+esc(item.title)+'</h1></div>'+
      '<section class="panel stack" aria-label="协作状态"><p data-collaboration-status role="status">'+status(item)+'</p>'+
      '<p class="small muted">发起人 '+esc(item.sender)+' · 接收人 '+esc(item.recipient)+'</p>'+
      (item.task_id?'<a class="small" href="#tasks/'+esc(item.task_id)+'">打开我的原事项</a>':'')+
      '<p class="small muted">这里记录站内协作。校方手续请按原通知渠道办理。</p>'+
      '<div data-collaboration-action>'+actionForm(item)+'</div></section>'+
      '<section class="panel stack" aria-label="办理记录"><h2>办理记录</h2><div data-collaboration-history>'+history(item)+'</div></section></section>';
  }
  function receive(item){
    const previous=record,root=$('[data-collaboration-action]'),form=root?.querySelector('form');
    record=item;
    $('[data-collaboration-status]').textContent=status(item);
    $('[data-collaboration-history]').innerHTML=history(item);
    if(saving||previous.version===item.version&&previous.recipient_available===item.recipient_available)return;
    if(form&&(form.elements.note.value||form.querySelector('input[name="shared_file"]:checked')||form.contains(document.activeElement))){
      form.querySelector('[type="submit"]').disabled=true;
      if(!root.querySelector('[data-collaboration-rebase]')){
        root.insertAdjacentHTML('afterbegin','<p class="alert info" role="status">另一端已更新。你的填写仍在。 <button type="button" class="link-button" data-collaboration-rebase>按最新状态继续</button></p>');
      }
    }else root.innerHTML=actionForm(item);
  }
  async function render(renderId=state.renderId,cid='',canApply=()=>true){
    const session=state.session,request=++sequence;
    if(owner!==session?.user?.id){
      owner=session?.user?.id;
      side=['college_admin','counselor'].includes(session?.user.campus_membership?.role)?'recipient':'sender';
      page=1;record=null;
    }
    const valid=()=>request===sequence&&renderId===state.renderId&&session===state.session&&canApply();
    if(cid){
      const item=await api('/collaboration/'+encodeURIComponent(cid)).catch(error=>{
        if(error.status===404)return null;
        throw error;
      });
      if(!valid())return false;
      if(!item){
        record=null;
        $('#content').innerHTML='<section class="panel stack"><h1>这项协作当前不可访问</h1><a href="#collaboration">返回协作办理</a></section>';
      }else if(record?.id===item.id&&$('[data-collaboration-action]'))receive(item);
      else {record=item;paint(item);}
      return true;
    }
    const result=await api('/collaboration?side='+side+'&page='+page);
    if(!valid())return false;
    record=null;
    const tabs=[['recipient','收到的'],['sender','我发起的']].map(([key,label])=>
      '<button type="button" class="button small '+(key===side?'primary':'')+'" data-collaboration-side="'+key+'" aria-pressed="'+(key===side)+'">'+label+'</button>');
    const rows=result.items.map(item=>'<a class="change-list-item" href="#collaboration/'+esc(item.id)+'"><span><strong>'+esc(item.title)+'</strong><small>'+
      esc(side==='sender'?item.recipient:item.sender)+' · '+date(item.updated_at)+'</small></span><span class="pill">'+esc(states[item.state])+'</span></a>');
    $('#content').innerHTML='<section class="stack collaboration-page"><div class="page-title"><h1>协作办理</h1></div>'+
      '<div class="row wrap" role="group" aria-label="协作方向">'+tabs.join('')+'</div><div class="panel flush">'+
      (rows.length?rows.join(''):'<p class="small muted collaboration-empty">当前没有协作记录。可以从个人待办发起协作。</p>')+
      '</div><div class="pagination">'+(page>1?'<button class="button small" data-collaboration-page="-1">上一页</button>':'')+
      (result.has_more?'<button class="button small" data-collaboration-page="1">下一页</button>':'')+'</div></section>';
    return true;
  }
  async function start(tid){
    const view=captureUiContext(state);
    const item=await api('/collaboration/tasks/'+encodeURIComponent(tid)+'/options');
    if(!view.sameDialog())return;
    if(!item.recipients.length){
      showDialog('协作办理','<p>当前没有为你的学院和班级授权的接收人。可以继续记录个人办理进度。</p>');
      return;
    }
    const options=item.recipients.map(person=>'<option value="'+esc(person.id)+'">'+esc(person.display_name)+' · '+(person.role==='counselor'?'负责范围内的辅导员':'学院管理员')+'</option>');
    showDialog('发起协作','<form data-workspace-form="collaboration" data-task-id="'+esc(tid)+'" data-version="'+item.version+'" data-request-id="'+crypto.randomUUID()+'" class="stack">'+
      '<p><strong>'+esc(item.title)+'</strong></p><label class="field">接收人<select name="recipient_id">'+options.join('')+'</select></label>'+
      '<label class="field">需要对方协助什么<textarea name="note" rows="3" maxlength="2000" required></textarea></label>'+
      choices(item.files)+'<p class="small muted">对方能看到这项标题、说明和你勾选的材料版本。</p>'+
      '<div class="form-footer"><button type="submit" class="button primary">发送给所选接收人</button></div></form>');
  }
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-collaboration-start],[data-collaboration-side],[data-collaboration-page],[data-collaboration-rebase]');
    if(!button||button.disabled)return;
    button.disabled=true;
    try{
      if(button.dataset.collaborationStart)await start(button.dataset.collaborationStart);
      else if(button.hasAttribute('data-collaboration-rebase')&&record){
        const root=$('[data-collaboration-action]');
        const form=root.querySelector('form'),selection=new FormData(form);
        root.innerHTML=actionForm(record,selection.get('note'));
        const next=root.querySelector('form');
        if(next&&record.actions.includes(selection.get('action')))next.elements.action.value=selection.get('action');
        for(const input of root.querySelectorAll('[name=shared_file]'))input.checked=selection.getAll('shared_file').includes(input.value);
      }else{
        if(button.dataset.collaborationSide){side=button.dataset.collaborationSide;page=1;}
        else page+=Number(button.dataset.collaborationPage);
        await render();
      }
    }catch(error){toast(error.message,true);}finally{button.disabled=false;}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;if(form.dataset.workspaceForm!=='collaboration')return;
    event.preventDefault();
    const finish=beginFormFeedback(form);
    if(!finish)return;
    const view=captureUiContext(state,form),values=new FormData(form),cid=form.dataset.caseId;
    const files=(!cid||values.get('action')==='resubmit'?values.getAll('shared_file'):[]).map(value=>{
      const [material_id,version]=value.split(':');
      return {material_id,version:Number(version)};
    });
    const payload={request_id:form.dataset.requestId,note:values.get('note'),files};
    if(cid)Object.assign(payload,{version:Number(form.dataset.version),action:values.get('action')});
    else Object.assign(payload,{task_id:form.dataset.taskId,task_version:Number(form.dataset.version),recipient_id:values.get('recipient_id')});
    saving=true;form.inert=true;
    try{
      const item=await api(cid?'/collaboration/'+encodeURIComponent(cid)+'/actions':'/collaboration',{method:'POST',json:payload});
      if(!view.sameUser())return;
      toast(cid?'协作记录已保存':'协作已发出');
      if(view.sameRoute()&&form.isConnected){
        if(!cid){if(view.sameDialog())$('#dialog').close();location.hash='#collaboration/'+item.id;}
        else{record=item;paint(item);}
      }
    }catch(error){
      if(!view.sameUser()||!form.isConnected)return;
      let panel=form.querySelector('[data-collaboration-error]');
      if(!panel){panel=document.createElement('p');panel.className='alert error';panel.dataset.collaborationError='';panel.setAttribute('role','alert');form.prepend(panel);}
      panel.textContent=error.message;
      if(error.detail?.case_id){
        const link=document.createElement('a');link.href='#collaboration/'+encodeURIComponent(error.detail.case_id);link.textContent=' 查看已有协作';panel.append(link);
      }
    }finally{saving=false;form.inert=false;finish();}
  });
  document.addEventListener('change',event=>{
    const input=event.target;
    if(input.name!=='action'||input.form?.dataset.workspaceForm!=='collaboration')return;
    const files=input.form.querySelector('[data-collaboration-files]');
    if(files){files.hidden=input.value!=='resubmit';files.disabled=files.hidden;}
  });
  return {render,saving:()=>saving};
}
