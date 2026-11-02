import {beginFormFeedback, captureUiContext} from './ui-request.js';

const $ = (selector, root=document) => root.querySelector(selector);
const roles = {college_admin:'学院管理员', counselor:'辅导员', student:'学生'};
const audienceNames = {college:'全院', grade:'年级', class:'班级'};

function scopeText(scope){
  if(scope.all_college || !scope.grade)return '全院';
  return scope.grade + (scope.class_name ? ' / ' + scope.class_name : '（全年级）');
}
function parseScopes(value){
  return value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean).map(line=>{
    if(line==='全院')return {all_college:true};
    const parts=line.split(/[\/／]/).map(v=>v.trim());
    if(parts.length>2 || !parts[0] || (parts.length===2 && !parts[1]))throw Error('负责范围请每行填写“年级 / 班级”、年级或“全院”');
    return {grade:parts[0],class_name:parts[1]||''};
  });
}
function targetText(item){return item.audience==='college'?'全院':item.grade+(item.audience==='class'?' / '+item.class_name:'（全年级）');}
function requestId(){return 'campus-'+crypto.randomUUID().replaceAll('-','');}

export function createCampusUI({state,api,esc,showDialog,ask,toast,updateAccount}){
  let context=null,members=[],publications=[],collegeId='',editing=null,owner=null;
  let pubPage=1,pubPages=1,pubTotal=0,pubQuery='',renderSequence=0;
  const drafts=new Map();
  const stillCurrent=(id,uid)=>id===state.renderId&&state.session?.user?.id===uid&&location.hash==='#campus';
  const ownRole=()=>context?.membership?.role;
  const canManage=()=>!!context?.site_admin||ownRole()==='college_admin';
  const canPublish=()=>['college_admin','counselor'].includes(ownRole());

  async function render(id=state.renderId){
    const uid=state.session?.user?.id,sequence=++renderSequence;
    const current=()=>sequence===renderSequence&&stillCurrent(id,uid);
    if(owner!==uid){drafts.clear();owner=uid;collegeId='';editing=null;pubPage=1;pubQuery='';}
    const next=await api('/campus/context');if(!current())return;context=next;
    state.session.user.campus_membership=context.membership?{role:context.membership.role,college_name:context.membership.college_name}:null;
    updateAccount();
    if(!context.site_admin)collegeId=context.membership?.college_id||'';
    else if(!collegeId || !context.colleges.some(c=>c.id===collegeId))collegeId=context.membership?.college_id||context.colleges[0]?.id||'';
    const canRead=canManage()||ownRole()==='counselor';
    const [memberResult,pubResult,auditResult]=await Promise.all([
      canRead&&collegeId?api('/campus/members?college_id='+encodeURIComponent(collegeId)):Promise.resolve({members:[]}),
      canPublish()?api('/campus/publications?page='+pubPage+'&page_size=20&q='+encodeURIComponent(pubQuery)):Promise.resolve({items:[]}),
      canManage()&&collegeId?api('/campus/audit?college_id='+encodeURIComponent(collegeId)):Promise.resolve({items:[]})
    ]);
    if(!current())return;
    members=memberResult.members;publications=pubResult.items;
    pubPage=pubResult.page||1;pubPages=pubResult.pages||1;pubTotal=pubResult.total||0;
    const own=context.membership;
    const membership=own?`<strong>${esc(roles[own.role])}</strong> · ${esc(own.college_name)}${own.role==='student'?` · ${esc(own.grade)} / ${esc(own.class_name)}`:''}${own.role==='counselor'?`<p class="small muted">负责范围：${esc(own.scopes.map(scopeText).join('、'))}</p>`:''}`:
      '<span>尚未分配学院身份，请联系学院管理员。你的个人通知和待办可以继续使用。</span>';
    $('#content').innerHTML=`<div class="page-title"><h1>学院工作台</h1></div>
      <section class="campus-section"><h2>我的学院身份</h2><p>${membership}</p>${context.site_admin?'<p class="small muted">你也是系统管理员，可以指定学院管理员；学院发布权限需要另行分配。</p>':''}${own?.role==='student'?'<a class="button small" href="#notices">查看我的通知</a>':''}</section>
      ${context.site_admin&&context.colleges.length>1?`<label class="field campus-college-picker">管理学院<select id="campus-college">${context.colleges.map(c=>`<option value="${esc(c.id)}" ${c.id===collegeId?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>`:''}
      ${canPublish()||canRead?`<nav class="campus-shortcuts row wrap" aria-label="学院工作台快捷入口">${canPublish()?'<button class="button small" type="button" data-campus-action="jump-compose">发布通知</button><button class="button small" type="button" data-campus-action="jump-published">发布记录</button>':''}${canManage()?'<button class="button small" type="button" data-campus-action="jump-manage">设置身份</button>':''}${canRead?'<button class="button small" type="button" data-campus-action="jump-roster">查看成员</button>':''}</nav>`:''}
      ${canPublish()?publicationForm()+publicationList():''}
      ${canManage()?memberForm():''}
      ${canRead?memberList(memberResult.can_manage):''}
      ${canManage()?auditList(auditResult.items):''}`;
    syncMemberFields();syncAudienceFields();
  }

  function memberForm(){
    const item=editing;
    const allowed=context.site_admin?['student','counselor','college_admin']:['student','counselor'];
    const selected=item?.role||'student';
    const scopes=(item?.scopes||[]).map(scope=>scope.all_college?'全院':scope.grade+(scope.class_name?' / '+scope.class_name:'')).join('\n');
    return `<section class="campus-section" id="campus-manage"><div class="between wrap"><h2>${item?'调整学院身份':'设置学院身份'}</h2>${item?'<button class="button small plain" type="button" data-campus-action="cancel-member">取消编辑</button>':''}</div>
      <p class="small muted">先核对对方身份，再输入已注册的账号。本人填写的资料不会自动获得权限。</p>
      <form class="stack" data-workspace-form="campus-member" data-version="${item?.version||0}">
        <div class="form-grid"><label class="field">账号名<input name="username" required maxlength="40" value="${esc(item?.username||'')}" ${item?'readonly':''}></label>
          <label class="field">学院角色<select name="role">${allowed.map(role=>`<option value="${role}" ${selected===role?'selected':''}>${roles[role]}</option>`).join('')}</select></label></div>
        <div class="form-grid" data-campus-student><label class="field">年级<input name="grade" maxlength="40" value="${esc(item?.grade||'')}" placeholder="例如 2026级"></label><label class="field">班级<input name="class_name" maxlength="80" value="${esc(item?.class_name||'')}" placeholder="例如 1班"></label></div>
        <label class="field" data-campus-scopes>负责范围<textarea name="scopes" rows="3" maxlength="3000" placeholder="每行一条：2026级 / 1班；只写年级表示全年级；写“全院”表示全院">${esc(scopes)}</textarea></label>
        <p class="small muted" data-campus-scopes>请明确填写辅导员负责的范围；权限变动立即生效。</p>
        <div><button class="button primary" type="submit">${item?'保存身份':'设置身份'}</button></div>
      </form></section>`;
  }

  function memberList(canEdit){
    return `<section class="campus-section" id="campus-roster"><h2>${ownRole()==='counselor'&&!context.site_admin?'我负责的学生':'学院成员'}</h2>
      <p class="small muted">这里只显示组织身份，不显示个人待办、对话或附件。</p>
      ${members.length?`<div class="campus-search"><label class="field">查找成员<input id="campus-member-search" type="search" placeholder="姓名、账号、年级或班级"></label><span class="small muted" id="campus-member-count" role="status">共 ${members.length} 人</span></div><div class="campus-list">${members.map(m=>`<article class="campus-row" data-campus-member-row data-campus-search="${esc([m.display_name,m.username,roles[m.role],m.grade,m.class_name,...m.scopes.map(scopeText)].join(' ').toLocaleLowerCase())}"><div><strong>${esc(m.display_name)}</strong> <span class="small muted">${esc(m.username)}</span><p class="small">${esc(roles[m.role])}${m.role==='student'?' · '+esc(m.grade)+' / '+esc(m.class_name):m.role==='counselor'?' · '+esc(m.scopes.map(scopeText).join('、')):''}</p></div>${canEdit&&(context.site_admin||m.role!=='college_admin')?`<div class="row wrap"><button class="button small" type="button" data-campus-action="edit-member" data-username="${esc(m.username)}">调整</button><button class="button small plain danger" type="button" data-campus-action="remove-member" data-username="${esc(m.username)}">移除</button></div>`:''}</article>`).join('')}</div>`:'<p class="muted">暂无成员。</p>'}</section>`;
  }

  function audienceOptions(){
    const own=context.membership;
    const scopes=own?.role==='counselor'?own.scopes:[];
    const students=collegeId===own?.college_id?members.filter(m=>m.role==='student'&&(own.role!=='counselor'||scopes.some(s=>s.all_college||(s.grade===m.grade&&(!s.class_name||s.class_name===m.class_name))))):[];
    const grades=[...new Set([...students.map(m=>m.grade),...scopes.map(s=>s.grade)].filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN',{numeric:true}));
    const classes=[...students.map(m=>({grade:m.grade,class_name:m.class_name})),...scopes.filter(s=>s.grade&&s.class_name)];
    return {grades,classes};
  }
  function audienceFields(draft={}){
    const scopes=context.membership?.scopes||[],administrator=ownRole()==='college_admin';
    const all=administrator||scopes.some(s=>s.all_college),grade=all||scopes.some(s=>s.grade&&!s.class_name);
    const options=audienceOptions();
    return `<label class="field">发布范围<select name="audience" required><option value="">请选择范围</option>${all?`<option value="college" ${draft.audience==='college'?'selected':''}>全院</option>`:''}${grade?`<option value="grade" ${draft.audience==='grade'?'selected':''}>指定年级</option>`:''}<option value="class" ${draft.audience==='class'?'selected':''}>指定班级</option></select></label>
      <div class="form-grid"><label class="field" data-campus-grade>年级<input name="grade" list="campus-grade-options" maxlength="40" value="${esc(draft.grade||'')}" placeholder="选择或填写年级"><datalist id="campus-grade-options">${options.grades.map(g=>`<option value="${esc(g)}"></option>`).join('')}</datalist></label><label class="field" data-campus-class>班级<input name="class_name" list="campus-class-options" maxlength="80" value="${esc(draft.class_name||'')}" placeholder="选择或填写班级"><datalist id="campus-class-options"></datalist></label></div><p class="small muted" data-campus-match>可选择已有名称，也可填写；年级和班级须与成员身份完全一致。</p>`;
  }
  function publicationForm(){
    const draft=drafts.get(owner)||{};
    const missing=draft.fileNames?.length?`<p class="small" id="campus-missing-files">切换页面后请重新选择附件：${draft.fileNames.map(esc).join('、')} <button class="button small plain" type="button" data-campus-action="clear-files">不再附加</button></p>`:'';
    return `<section class="campus-section" id="campus-compose"><h2>发布学院通知</h2><p class="small muted">发送给当前已加入对应范围的成员。个人待办和办理记录不会开放给发布者。</p>
      <form class="stack" data-workspace-form="campus-publish" data-request-id="${esc(draft.requestId||'')}" data-missing-files="${draft.fileNames?.length?'1':''}">${audienceFields(draft)}
        <div class="row wrap"><button class="button small" type="button" data-campus-action="preview">查看接收范围</button><span class="small muted" id="campus-audience-preview" role="status"></span></div>
        <label class="field">标题<input name="title" required maxlength="160" value="${esc(draft.title||'')}"></label><label class="field">通知正文<textarea name="body" required maxlength="10000" rows="6">${esc(draft.body||'')}</textarea></label>
        <label class="field">附件（选填，最多 3 份）<input type="file" name="files" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.png,.jpg,.jpeg,.webp"></label>
        ${missing}
        <p class="small muted">单份不超过 5 MB，合计不超过 8 MB。发布后进入对方的通知资料，仍由本人核对；后来加入的成员可在发布记录中补发，补发时也会重试当前范围内未送达的记录。</p>
        <div><button class="button primary" type="submit">核对并发布</button></div>
      </form></section>`;
  }
  function publicationList(){
    const rows=publications.map(p=>`<article class="campus-row"><div><strong>${esc(p.title)}</strong>
      <p class="small muted">${esc(targetText(p))} · ${esc(p.publisher_name)} · ${p.state==='withdrawn'?'已撤回':'已发布'} · 站内收件 ${p.delivery.delivered}/${p.delivery.total}${p.delivery.failed?' · 未送达 '+p.delivery.failed:''}${p.delivery.out_of_scope?' · 已不在范围 '+p.delivery.out_of_scope:''}</p>
      <p class="small campus-excerpt">${esc(p.body)}</p>${p.attachments.length?`<p class="small muted">附件：${p.attachments.map(f=>esc(f.name)).join('、')}</p>`:''}</div>
      <div class="row wrap">${p.state==='published'?`<button class="button small" type="button" data-campus-action="correct" data-id="${esc(p.id)}">更正</button><button class="button small" type="button" data-campus-action="deliver-new" data-id="${esc(p.id)}">补发给新成员</button><button class="button small plain" type="button" data-campus-action="withdraw" data-id="${esc(p.id)}">撤回</button>`:''}${p.delivery.failed?`<button class="button small" type="button" data-campus-action="retry" data-id="${esc(p.id)}">重试未送达</button>`:''}</div></article>`).join('');
    return `<section class="campus-section" id="campus-published"><h2>发布记录</h2><p class="small muted">站内收件不代表已读；这里只显示数量，不显示成员的个人办理状态。</p>
      <div class="campus-search"><label class="field">查找发布记录<input id="campus-publication-search" type="search" maxlength="80" value="${esc(pubQuery)}" placeholder="标题、发布人、年级或班级"></label><button class="button small" type="button" data-campus-action="search-publications">搜索</button>${pubQuery?'<button class="button small plain" type="button" data-campus-action="clear-publications">清除</button>':''}</div>
      ${rows?`<div class="campus-list">${rows}</div>`:`<p class="muted">${pubQuery?'没有找到匹配的发布记录。':'还没有发布过学院通知。'}</p>`}
      <div class="campus-pagination row wrap"><span class="small muted" role="status">共 ${pubTotal} 条 · 第 ${pubPage} / ${pubPages} 页</span><button class="button small" type="button" data-campus-action="publications-prev" ${pubPage<=1?'disabled':''}>上一页</button><button class="button small" type="button" data-campus-action="publications-next" ${pubPage>=pubPages?'disabled':''}>下一页</button></div></section>`;
  }
  function auditList(items){
    const labels={assign_member:'设置学院身份',remove_member:'移除学院身份',publish:'发布通知',correct:'更正通知',withdraw:'撤回通知',deliver_new:'补发通知'};
    return `<section class="campus-section"><details><summary>查看最近的学院操作记录</summary>${items.length?`<ul class="campus-audit">${items.map(item=>`<li>${esc(new Date(item.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))} · ${esc(item.actor_name)} · ${esc(labels[item.action]||item.action)}${item.target_name?' · '+esc(item.target_name):''}</li>`).join('')}</ul>`:'<p class="small muted">暂无操作记录。</p>'}</details></section>`;
  }
  function syncMemberFields(){
    const form=$('[data-workspace-form="campus-member"]');if(!form)return;
    const role=form.elements.role.value;
    form.querySelectorAll('[data-campus-student]').forEach(n=>n.hidden=role!=='student');
    form.querySelectorAll('[data-campus-scopes]').forEach(n=>n.hidden=role!=='counselor');
    form.elements.grade.required=form.elements.class_name.required=role==='student';
    form.elements.scopes.required=role==='counselor';
  }
  function syncAudienceFields(){
    const form=$('[data-workspace-form="campus-publish"]');if(!form)return;
    const target=form.elements.audience.value;
    $('[data-campus-grade]',form).hidden=!['grade','class'].includes(target);
    $('[data-campus-class]',form).hidden=target!=='class';
    $('[data-campus-match]',form).hidden=!['grade','class'].includes(target);
    form.elements.grade.required=['grade','class'].includes(target);form.elements.class_name.required=target==='class';
    refreshClassOptions(form);
    if($('#campus-audience-preview'))$('#campus-audience-preview').textContent='';
  }
  function refreshClassOptions(form){
    const grade=form.elements.grade.value.trim();
    const names=[...new Set(audienceOptions().classes.filter(item=>item.grade===grade).map(item=>item.class_name).filter(Boolean))]
      .sort((a,b)=>a.localeCompare(b,'zh-CN',{numeric:true}));
    $('#campus-class-options',form).innerHTML=names.map(name=>`<option value="${esc(name)}"></option>`).join('');
  }
  function saveDraft(form,changed=true){
    if(changed)delete form.dataset.requestId;
    const prior=drafts.get(owner)||{},files=[...form.elements.files.files];
    const fileNames=files.length?files.map(f=>f.name):(form.dataset.missingFiles==='1'?prior.fileNames||[]:[]);
    drafts.set(owner,{audience:form.elements.audience.value,grade:form.elements.grade.value,class_name:form.elements.class_name.value,
      title:form.elements.title.value,body:form.elements.body.value,requestId:form.dataset.requestId||'',fileNames});
  }
  function audience(form){
    const kind=form.elements.audience.value;
    if(!kind)throw Error('请先选择发布范围');
    return {audience:kind,grade:kind==='college'?'':form.elements.grade.value.trim(),
            class_name:kind==='class'?form.elements.class_name.value.trim():''};
  }
  function correctionDialog(item){
    showDialog('更正学院通知',`<form class="stack" data-workspace-form="campus-correct" data-id="${esc(item.id)}" data-version="${item.version}">
      <p class="small muted">向原接收范围中仍有权限的成员发送更正；保留对方的个人办理记录。发布范围不能在这里扩大。</p>
      <label class="field">标题<input name="title" required maxlength="160" value="${esc(item.title)}"></label><label class="field">通知正文<textarea name="body" required maxlength="10000" rows="6">${esc(item.body)}</textarea></label>
      <label class="check"><input type="checkbox" name="keep_attachments" checked><span>保留原附件</span></label><label class="field">增加或替换附件<input type="file" name="files" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.png,.jpg,.jpeg,.webp"></label><div class="form-footer"><button class="button primary" type="submit">发布更正</button></div></form>`);
  }
  function withdrawalDialog(item){
    showDialog('撤回学院通知',`<form class="stack" data-workspace-form="campus-withdraw" data-id="${esc(item.id)}" data-version="${item.version}"><p>将向原接收范围中仍有权限的成员发送撤回说明，原有个人办理记录保留并需要核对。</p><label class="field">撤回说明<textarea name="reason" required maxlength="1000" rows="4"></textarea></label><div class="form-footer"><button class="button primary" type="submit">确认撤回</button></div></form>`);
  }
  document.addEventListener('change',event=>{
    if(event.target.closest('[data-workspace-form="campus-member"]')&&event.target.name==='role')syncMemberFields();
    if(event.target.closest('[data-workspace-form="campus-publish"]')&&event.target.name==='audience')syncAudienceFields();
    if(event.target.closest('[data-workspace-form="campus-publish"]')&&event.target.name==='files'){
      const form=event.target.form,prior=drafts.get(owner)||{},files=[...form.elements.files.files];
      const same=!!prior.fileNames?.length&&prior.fileNames.length===files.length&&files.every((file,index)=>file.name===prior.fileNames[index]);
      form.dataset.missingFiles='';$('#campus-missing-files')?.remove();saveDraft(form,!same);
    }
    if(event.target.id==='campus-college'){collegeId=event.target.value;editing=null;render().catch(error=>toast(error.message,true));}
  });
  document.addEventListener('input',event=>{
    const form=event.target.closest('[data-workspace-form="campus-publish"]');
    if(form&&event.target.name!=='files'){if(event.target.name==='grade')refreshClassOptions(form);saveDraft(form);if($('#campus-audience-preview'))$('#campus-audience-preview').textContent='';}
    if(event.target.id==='campus-member-search'){
      const query=event.target.value.trim().toLocaleLowerCase();let shown=0;
      document.querySelectorAll('[data-campus-member-row]').forEach(row=>{row.hidden=!row.dataset.campusSearch.includes(query);if(!row.hidden)shown++;});
      $('#campus-member-count').textContent=`显示 ${shown} / ${members.length} 人`;
    }
  });
  document.addEventListener('keydown',event=>{if(event.target.id==='campus-publication-search'&&event.key==='Enter'){event.preventDefault();$('[data-campus-action="search-publications"]')?.click();}});
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-campus-action]');if(!button||button.disabled)return;
    const action=button.dataset.campusAction,item=publications.find(p=>p.id===button.dataset.id),member=members.find(m=>m.username===button.dataset.username);
    const view=captureUiContext(state,button);button.disabled=true;
    try{
      if(action.startsWith('jump-'))$('#campus-'+action.slice(5))?.scrollIntoView({block:'start',behavior:'smooth'});
      else if(['search-publications','clear-publications','publications-prev','publications-next'].includes(action)){
        if(action==='search-publications'){pubQuery=$('#campus-publication-search').value.trim();pubPage=1;}
        else if(action==='clear-publications'){pubQuery='';pubPage=1;}
        else pubPage+=action==='publications-next'?1:-1;
        await render();if(view.sameRoute())$('#campus-published')?.scrollIntoView({block:'start'});
      }
      else if(action==='edit-member'&&member){editing=member;await render();if(view.sameRoute())$('[data-workspace-form="campus-member"]')?.scrollIntoView({block:'start'});}
      else if(action==='cancel-member'){editing=null;await render();}
      else if(action==='clear-files'){const form=button.closest('form');form.dataset.missingFiles='';form.elements.files.value='';$('#campus-missing-files')?.remove();saveDraft(form);}
      else if(action==='remove-member'&&member&&await ask('移除学院身份',`移除 ${member.display_name} 的学院权限；已有个人通知和资料保留。`,'移除')){
        await api('/campus/members/'+encodeURIComponent(member.username),{method:'DELETE',json:{version:member.version}});if(view.sameRoute()){editing=null;await render();}if(view.sameUser())toast('学院身份已移除');
      }else if(action==='preview'){
        const form=button.closest('form'),selected=audience(form),result=await api('/campus/audience-preview',{method:'POST',json:selected});
        if(view.sameRoute()&&form.isConnected&&JSON.stringify(audience(form))===JSON.stringify(selected))$('#campus-audience-preview').textContent=`当前 ${result.total} 人：学生 ${result.students} 人，学院工作人员 ${result.staff} 人`;
      }else if(action==='correct'&&item)correctionDialog(item);
      else if(action==='withdraw'&&item)withdrawalDialog(item);
      else if(action==='retry'&&item){const result=await api('/campus/publications/'+encodeURIComponent(item.id)+'/retry',{method:'POST'});if(view.sameRoute())await render();if(view.sameUser())toast(result.delivery.failed?`仍有 ${result.delivery.failed} 条未送达`:'未送达记录已重试',!!result.delivery.failed);}
      else if(action==='deliver-new'&&item){const result=await api('/campus/publications/'+encodeURIComponent(item.id)+'/deliver-new',{method:'POST'});if(view.sameRoute())await render();if(view.sameUser())toast(`新增 ${result.delivery.added} 名接收成员，${result.delivery.failed?'仍有 '+result.delivery.failed+' 条未送达':'当前记录已处理'}`,!!result.delivery.failed);}
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{button.disabled=false;}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target,kind=form.dataset.workspaceForm;
    if(!['campus-member','campus-publish','campus-correct','campus-withdraw'].includes(kind))return;
    event.preventDefault();const view=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;
    const values=new FormData(form),draftOwner=state.session?.user?.id;form.inert=true;
    try{
      let result;
      if(kind==='campus-member'){
        const role=String(values.get('role'));
        const payload={college_id:collegeId,role,version:Number(form.dataset.version),
          grade:role==='student'?String(values.get('grade')).trim():'',class_name:role==='student'?String(values.get('class_name')).trim():'',
          scopes:role==='counselor'?parseScopes(String(values.get('scopes'))):[]};
        result=await api('/campus/members/'+encodeURIComponent(String(values.get('username')).trim()),{method:'PUT',json:payload});
      }else if(kind==='campus-publish'){
        if(form.dataset.missingFiles==='1')throw Error('请重新选择附件，或点击“不再附加”');
        const selected=audience(form),review=await api('/campus/audience-review',{method:'POST',json:selected});
        if(!view.sameRoute()||!form.isConnected)return;
        const summary=`《${String(values.get('title')).trim()}》将发送至${targetText(selected)}：学生 ${review.students} 人，学院工作人员 ${review.staff} 人。${review.students?'请确认接收范围。':'当前没有学生符合条件，请确认是否仍要发布。'}`;
        if(!await ask('核对接收范围',summary,'确认发布')||!view.sameRoute()||!form.isConnected)return;
        form.dataset.requestId ||= requestId();
        const payload={...selected,title:String(values.get('title')).trim(),body:String(values.get('body')).trim(),request_id:form.dataset.requestId,audience_review:review.review};
        saveDraft(form,false);
        const body=new FormData();body.append('data',JSON.stringify(payload));for(const file of values.getAll('files'))if(file.size)body.append('files',file);
        result=await api('/campus/publications',{method:'POST',body});
      }else if(kind==='campus-correct'){
        const payload={version:Number(form.dataset.version),title:String(values.get('title')).trim(),body:String(values.get('body')).trim(),keep_attachments:values.has('keep_attachments')};
        const body=new FormData();body.append('data',JSON.stringify(payload));for(const file of values.getAll('files'))if(file.size)body.append('files',file);
        result=await api('/campus/publications/'+encodeURIComponent(form.dataset.id)+'/correct',{method:'POST',body});
      }else result=await api('/campus/publications/'+encodeURIComponent(form.dataset.id)+'/withdraw',{method:'POST',json:{version:Number(form.dataset.version),reason:String(values.get('reason')).trim()}});
      if(kind==='campus-publish'&&drafts.get(draftOwner)?.requestId===form.dataset.requestId)drafts.delete(draftOwner);
      if(!view.sameUser())return;
      if(kind==='campus-publish'){pubPage=1;pubQuery='';}
      if(['campus-correct','campus-withdraw'].includes(kind)&&view.sameDialog())$('#dialog').close();
      if(view.sameRoute()){editing=null;await render();}
      if(kind==='campus-member')toast('学院身份已保存');
      else toast(`已处理：站内收件 ${result.delivery.delivered}/${result.delivery.total}${result.delivery.failed?'，未送达 '+result.delivery.failed+'，可在发布记录重试':''}${result.delivery.students===0?'；当前范围没有学生':''}`,!!result.delivery.failed);
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;finish();}
  });
  return {render};
}
