import {renderCampusDeliveryEvidence} from './campus-delivery-evidence.js';
import {createCampusRoster} from './campus-roster.js';
import {beginFormFeedback, captureUiContext} from './ui-request.js';
import {createCampusPublicationSubmission} from './campus-publication-submission.js';

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
function targetText(item){return !item.audience?'尚未选择范围':item.audience==='college'?'全院':item.grade+(item.audience==='class'?' / '+item.class_name:'（全年级）');}
function requestId(){return 'campus-'+crypto.randomUUID().replaceAll('-','');}

export function createCampusUI({state,api,esc,showDialog,ask,toast,updateAccount}){
  let context=null,members=[],publications=[],collegeId='',editing=null,owner=null;
  let pubPage=1,pubPages=1,pubTotal=0,pubQuery='',renderSequence=0;
  let detailPublication=null;
  let auditAction='',auditCursor='',auditPrevious=[],auditNext='',auditHasMore=false;
  let serverDrafts=[],draftTimer,deliveryTimer,draftWrites=Promise.resolve();
  const drafts=new Map();
  const submission=createCampusPublicationSubmission({api,owner:()=>state.session?.user?.id});
  const roster=createCampusRoster({state,api,esc,showDialog,toast});
  const stillCurrent=(id,uid)=>id===state.renderId&&state.session?.user?.id===uid&&(/^#campus(?:\/[^/]+)?$/.test(location.hash)||(location.hash==='#dashboard'&&state.workContext==='college'));
  const ownRole=()=>context?.membership?.role;
  const siteMode=()=>state.workContext==='system'&&!!context?.site_admin;
  const canManage=()=>siteMode()||ownRole()==='college_admin';
  const canPublish=()=>state.workContext==='college'&&['college_admin','counselor'].includes(ownRole());

  async function render(id=state.renderId,section=location.hash.startsWith('#campus/')?location.hash.split('/')[1]:'home'){
    if(section==='home'){pubPage=1;pubQuery='';}
    const uid=state.session?.user?.id,sequence=++renderSequence;
    const current=()=>sequence===renderSequence&&stillCurrent(id,uid);
    if(owner!==uid){clearTimeout(draftTimer);clearTimeout(deliveryTimer);serverDrafts=[];drafts.clear();owner=uid;collegeId='';editing=null;pubPage=1;pubQuery='';auditAction='';auditCursor='';auditPrevious=[];auditNext='';auditHasMore=false;}
    const next=await api('/campus/context');if(!current())return;context=next;
    state.session.user.campus_membership=context.membership?Object.fromEntries(
      ['role','college_name','grade','class_name','version'].map(key=>[key,context.membership[key]])
    ):null;
    updateAccount();
    if(!siteMode())collegeId=context.membership?.college_id||'';
    else if(!collegeId || !context.colleges.some(c=>c.id===collegeId))collegeId=context.membership?.college_id||context.colleges[0]?.id||'';
    const canRead=canManage()||ownRole()==='counselor';
    const [memberResult,pubResult,auditResult,draftResult,pendingPublication]=await Promise.all([
      canRead&&collegeId&&['home','members','publish'].includes(section)?api('/campus/members?college_id='+encodeURIComponent(collegeId)):Promise.resolve({members:[]}),
      canPublish()&&['home','records'].includes(section)?api('/campus/publications?page='+pubPage+'&page_size=20&q='+encodeURIComponent(pubQuery)):Promise.resolve({items:[]}),
      canManage()&&collegeId&&section==='audit'?api('/campus/audit?college_id='+encodeURIComponent(collegeId)+'&page_size=100'+(auditCursor?'&before_id='+encodeURIComponent(auditCursor):'')+'&action='+encodeURIComponent(auditAction)):Promise.resolve({items:[]}),
      canPublish()&&section==='publish'?api('/campus/drafts'):Promise.resolve({items:[]}),
      canPublish()&&section==='publish'?submission.load():Promise.resolve(null)
    ]);
    if(!current())return;
    if(pendingPublication&&!drafts.has(uid))drafts.set(uid,structuredClone(pendingPublication.draft));
    members=memberResult.members;publications=pubResult.items;serverDrafts=draftResult.items;if(section==='audit'){auditNext=auditResult.next_cursor||'';auditHasMore=!!auditResult.has_more;}
    if(ownRole()==='counselor'&&!siteMode())members=members.filter(m=>m.role==='student'&&context.membership.scopes.some(s=>s.all_college||s.grade===m.grade&&(!s.class_name||s.class_name===m.class_name)));
    pubPage=pubResult.page||1;pubPages=pubResult.pages||1;pubTotal=pubResult.total||0;
    const own=context.membership;
    const membership=own?`<strong>${esc(roles[own.role])}</strong> · ${esc(own.college_name)}${own.role==='student'?` · ${esc(own.grade)} / ${esc(own.class_name)}`:''}${own.role==='counselor'?`<p class="small muted">负责范围：${esc(own.scopes.map(scopeText).join('、'))}</p>`:''}`:
      siteMode()?`<span>系统管理员 · ${esc(context.colleges.find(c=>c.id===collegeId)?.name||'学院权限管理')}</span>`:'<span>尚未分配学院身份，请联系学院管理员。你的个人通知和待办可以继续使用。</span>';
    const available=[['home','概览'],...(canPublish()?[['publish','发布通知'],['records','发布记录']]:[]),...(canRead?[['members',siteMode()?'学院与权限':'学院成员']]:[]),...(canManage()?[['audit','权限记录']]:[])];
    if(!available.some(([key])=>key===section))section='home';
    const failed=publications.reduce((sum,p)=>sum+Number(p.delivery?.failed||0),0);
    const home=`<section class="role-home" data-home-context="college"><header class="home-heading"><div><h1>${own?.role==='counselor'?'学院事务':'学院管理'}</h1><div class="home-context">${membership}</div></div>${canPublish()?'<a class="button primary small" href="#campus/publish">发布通知</a>':''}</header><div class="home-counts"><span>负责范围成员 <b>${members.length}</b></span><span>已发布 <b>${pubTotal}</b></span>${canPublish()?`<span>本页未送达 <b>${failed}</b></span>`:''}</div><section class="home-section"><h2>常用操作</h2><div class="home-link-list">${canPublish()?'<a href="#campus/publish"><span>准备通知与核对接收范围</span><span>→</span></a><a href="#campus/records"><span>送达、更正与撤回</span><span>→</span></a>':''}${canRead?'<a href="#campus/members"><span>查看负责范围内的成员</span><span>→</span></a>':''}${canManage()?'<a href="#campus/audit"><span>查看权限调整记录</span><span>→</span></a>':''}</div></section>${!canRead?'<p class="small muted">你的个人通知和待办在“我的事务”中查看。</p><a class="button small" href="#notices">查看我的通知</a>':''}</section>`;
    $('#content').innerHTML=`<div class="campus-workspace">${section==='home'?'':`<h1 class="sr-only">${esc(available.find(([key])=>key===section)?.[1]||'学院事务')}</h1>`}
      ${section==='home'?home:`<header class="campus-context-line"><div>${membership}</div><a class="button small plain" href="#dashboard">首页</a></header>`}
      ${siteMode()&&context.colleges.length>1?`<label class="field campus-college-picker">管理学院<select id="campus-college">${context.colleges.map(c=>`<option value="${esc(c.id)}" ${c.id===collegeId?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>`:''}
      ${section!=='home'?`<nav class="campus-sections" aria-label="学院事务">${available.filter(([key])=>key!=='home').map(([key,label])=>`<a href="#campus/${key}" ${section===key?'aria-current="page"':''}>${label}</a>`).join('')}</nav>`:''}
      ${section==='publish'&&canPublish()?publicationForm():''}
      ${section==='records'&&canPublish()?publicationList():''}
      ${section==='members'&&canManage()?`<button type="button" class="button small" data-campus-action="roster">批量录入与规范化成员</button><details class="campus-member-editor" ${editing?'open':''}><summary>${editing?'调整成员身份':'添加成员 / 分配学院身份'}</summary>${memberForm()}</details>`:''}
      ${section==='members'&&canRead?memberList(memberResult.can_manage):''}
      ${section==='audit'&&canManage()?auditList(auditResult.items):''}</div>`;
    syncMemberFields();syncAudienceFields();scheduleDeliveryRefresh(id,uid);
  }

  function memberForm(){
    const item=editing;
    const allowed=siteMode()?['student','counselor','college_admin']:['student','counselor'];
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
    return `<section class="campus-section" id="campus-roster"><h2>${ownRole()==='counselor'&&!siteMode()?'我负责的学生':'学院成员'}</h2>
      <p class="small muted">这里只显示组织身份，不显示个人待办、对话或附件。</p>
      ${members.length?`<div class="campus-search"><label class="field">查找成员<input id="campus-member-search" type="search" placeholder="姓名、账号、年级或班级"></label><span class="small muted" id="campus-member-count" role="status">共 ${members.length} 人</span></div><div class="campus-list">${members.map(m=>`<article class="campus-row" data-campus-member-row data-campus-search="${esc([m.display_name,m.username,roles[m.role],m.grade,m.class_name,...m.scopes.map(scopeText)].join(' ').toLocaleLowerCase())}"><div><strong>${esc(m.display_name)}</strong> <span class="small muted">${esc(m.username)}</span><p class="small">${esc(roles[m.role])}${m.role==='student'?' · '+esc(m.grade)+' / '+esc(m.class_name):m.role==='counselor'?' · '+esc(m.scopes.map(scopeText).join('、')):''}</p></div>${canEdit&&(siteMode()||m.role!=='college_admin')?`<div class="row wrap"><button class="button small" type="button" data-campus-action="edit-member" data-username="${esc(m.username)}">调整</button><button class="button small plain danger" type="button" data-campus-action="remove-member" data-username="${esc(m.username)}">移除</button></div>`:''}</article>`).join('')}</div>`:'<p class="muted">暂无成员。</p>'}</section>`;
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
  function policyFieldsTime(value){return new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）';}
  function policyFields(item={}){
    const policy=item.publication_policy||item,stamp=policy.valid_until?new Date(Date.parse(policy.valid_until)+8*60*60*1000).toISOString().slice(0,19):'';
    return `<details class="details"><summary>有效期与历史参考（可选）</summary><label class="field">发布方标注的有效期（北京时间）<input type="datetime-local" name="valid_until" step="1" value="${esc(stamp)}"></label><label class="check"><input type="checkbox" name="reference_only" ${policy.reference_only?'checked':''}><span>仅作历史参考，不发送新的外部通知</span></label><p class="small muted">只填写发布方明确给出的有效期；未填写不推测截止时间。历史或过期资料补发时会再次确认，站内记录保留参考标记。</p></details>`;
  }
  function readPolicy(form){return {valid_until:form.elements.valid_until?.value?form.elements.valid_until.value+'+08:00':null,reference_only:!!form.elements.reference_only?.checked};}
  function publicationForm(){
    const draft=drafts.get(owner)||{id:'draft-'+crypto.randomUUID(),version:0};drafts.set(owner,draft);
    draft.fileNames ||= draft.pending_attachment_names||[];
    const savedFiles=(draft.attachments||[]).map(file=>`<li>${esc(file.name)} · ${Math.ceil(file.size/1024)} KB${file.warning?' · '+esc(file.warning):''}</li>`).join('');
    const missing=draft.fileNames?.length?`<p class="small" id="campus-missing-files">切换页面后请重新选择附件：${draft.fileNames.map(esc).join('、')} <button class="button small plain" type="button" data-campus-action="clear-files">不再附加</button></p>`:'';
    return `<section class="campus-section" id="campus-compose"><h2>发布学院通知</h2><p class="small muted">发送给当前已加入对应范围的成员。个人待办和办理记录不会开放给发布者。</p>
      <details class="details campus-drafts"><summary>我的发布草稿 · ${serverDrafts.length} 份</summary><p class="small muted">草稿只对本人开放，保存后可在其他设备继续；未核对并确认发布前不会送达学生。</p><div class="campus-list">${serverDrafts.map(item=>`<article class="campus-row"><div><strong>${esc(item.title||'未填写标题')}</strong><p class="small muted">${esc(new Date(item.updated_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))} · 第 ${item.version} 版 · ${item.attachments.length} 份附件</p></div><div class="row wrap"><button class="button small" type="button" data-campus-action="open-draft" data-id="${esc(item.id)}">继续编辑</button><button class="button small plain danger" type="button" data-campus-action="delete-draft" data-id="${esc(item.id)}">删除草稿</button></div></article>`).join('')||'<p class="small muted">暂无服务器草稿</p>'}</div><button class="button small" type="button" data-campus-action="new-draft">新建另一份草稿</button></details>
      ${publicationRecoveryMarkup()}
      <form class="stack" data-workspace-form="campus-publish" data-draft-id="${esc(draft.id)}" data-draft-version="${draft.version||0}" data-request-id="${esc(draft.requestId||'')}" data-missing-files="${draft.fileNames?.length?'1':''}">${audienceFields(draft)}
        <div class="row wrap"><button class="button small" type="button" data-campus-action="preview">查看接收范围</button><span class="small muted" id="campus-audience-preview" role="status"></span></div>
        <label class="field">标题<input name="title" required maxlength="160" value="${esc(draft.title||'')}"></label><label class="field">通知正文<textarea name="body" required maxlength="10000" rows="4">${esc(draft.body||'')}</textarea></label>
        ${policyFields(draft)}
        <label class="field">附件（选填，最多 3 份）<input type="file" name="files" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.png,.jpg,.jpeg,.webp"></label>
        ${missing}
        <div data-campus-saved-files>${savedAttachmentFields(draft.attachments||[])}</div>
        <div class="row wrap"><button class="button small" type="button" data-campus-action="save-draft">保存草稿</button><span class="small muted" data-campus-draft-status role="status">${draft.version?'已保存第 '+draft.version+' 版':'尚未保存'}</span></div>
        <p class="small muted">单份不超过 5 MB，合计不超过 8 MB。发布后进入对方的通知资料，仍由本人核对；后来加入的成员可在发布记录中补发，补发时也会重试当前范围内未送达的记录。</p>
        <div><button class="button primary" type="submit">${submission.pending()?'重试上次确认的发布':'核对并发布'}</button></div>
      </form></section>`;
  }
  function publicationRecoveryMarkup(){
    const intent=submission.pending();if(!intent)return '';
    return `<section class="alert info stack" data-campus-publication-recovery role="status"><strong>上次确认的发布尚未返回结果</strong><p>《${esc(intent.payload.title)}》 · ${esc(targetText(intent.payload))}。重试后，已发布的会显示同一发布记录；尚未发布的会按上次确认的正文、附件与范围继续发布。下方的新输入不会发送。</p><div class="row wrap"><button type="button" class="button small" data-campus-action="recover-publication">重试上次确认的发布</button><button type="button" class="button small plain" data-campus-action="review-publication">重新核对范围并继续上次发布</button><button type="button" class="button small plain danger" data-campus-action="cancel-publication">停止尚未完成的发布</button></div><p class="small muted">若范围核对已过期，可重新核对原范围。修改正文会另存为新草稿，上次确认的发布内容不会被替换。停止操作不会撤回已经发布的通知。</p></section>`;
  }
  function updatePublicationRecovery(){
    const previous=$('[data-campus-publication-recovery]'),markup=publicationRecoveryMarkup();
    if(previous){if(markup)previous.outerHTML=markup;else previous.remove();}
    else if(markup)$('[data-workspace-form="campus-publish"]')?.insertAdjacentHTML('beforebegin',markup);
    const submit=$('[data-workspace-form="campus-publish"] [type=submit]');if(submit)submit.textContent=markup?'重试上次确认的发布':'核对并发布';
  }
  function separateSubmittedDraft(form,pending=submission.pending()){
    if(!pending||pending.payload.draft_id!==form.dataset.draftId)return false;
    const prior=drafts.get(owner)||{},missing=(prior.attachments||[]).map(file=>file.name);
    form.dataset.draftId='draft-'+crypto.randomUUID();form.dataset.draftVersion='0';delete form.dataset.requestId;delete form.dataset.draftConflict;
    drafts.set(owner,{...prior,id:form.dataset.draftId,version:0,requestId:'',attachments:[],fileNames:missing,pending_attachment_names:missing});
    form.querySelector('[data-campus-saved-files]').innerHTML=savedAttachmentFields([]);
    if(missing.length&&!form.elements.files.files.length){
      form.dataset.missingFiles='1';$('#campus-missing-files')?.remove();
      form.querySelector('[data-campus-saved-files]').insertAdjacentHTML('beforebegin',`<p class="small" id="campus-missing-files">新草稿尚未附加原提交的附件，请重新选择：${missing.map(esc).join('、')} <button class="button small plain" type="button" data-campus-action="clear-files">不再附加</button></p>`);
    }
    return true;
  }
  async function recoverPublication(view,{renewReview=false}={}){
    const pending=await submission.load();if(!pending||!view.sameRoute())return null;
    let audienceReview;
    if(renewReview){
      const payload=pending.payload,selected={audience:payload.audience,grade:payload.grade,class_name:payload.class_name};
      const review=await api('/campus/audience-review',{method:'POST',json:selected});
      if(!view.sameRoute()||!await ask('重新核对上次发布的范围',`继续上次确认的《${payload.title}》，当前${targetText(selected)}：学生 ${review.students} 人、工作人员 ${review.staff} 人；正文和附件保持不变，下方的新输入不会发布。已经发布的仍返回同一记录。`,'核对并继续上次发布')||!view.sameRoute())return null;
      audienceReview=review.review;
    }
    return submission.replay({audienceReview,canSend:view.sameRoute});
  }
  function completePublication(recovered,view){
    if(!recovered?.current||!view.sameUser())return;
    const {result,intent,cleanupError}=recovered,local=drafts.get(owner),sameDraft=local?.id===intent.payload.draft_id;
    if(sameDraft)drafts.delete(owner);
    serverDrafts=serverDrafts.filter(draft=>draft.id!==intent.payload.draft_id);pubPage=1;pubQuery='';
    if(view.sameRoute()){updatePublicationRecovery();if(sameDraft)location.hash='#campus/records';}
    if(!result){toast(`上次确认的通知已经发布，本次操作没有撤回；${[403,404].includes(recovered.detailError?.status)?'当前权限无法查看原发布详情。':'暂时无法读取发布详情，可稍后在发布记录核对。'}${sameDraft?'':'当前新输入仍是草稿，尚未发布。'}${cleanupError?' 核对记录清理暂未完成，请重新打开页面核对。':''}`,true);return;}
    const label=result.state==='withdrawn'?'上次发布已有结果，当前已撤回；此操作没有恢复发布。':recovered.state==='published'?'该通知已经发布，本次停止操作没有撤回；':'已确认发布：';
    toast(`${label}站内收件 ${result.delivery.delivered}/${result.delivery.total}${result.delivery.pending?'，待投递 '+result.delivery.pending:''}${sameDraft?'':'；当前新输入仍是草稿，尚未发布。'}${cleanupError?' 发布已保存，核对记录清理暂未完成；再次重试仍会返回同一发布。':''}`,!!cleanupError||!!result.delivery.failed);
  }
  function savedAttachmentFields(files){
    return files.length?`<details class="details"><summary>已保存的附件 · ${files.length} 份</summary><ul>${files.map(file=>`<li>${esc(file.name)} · ${Math.ceil(file.size/1024)} KB${file.warning?' · '+esc(file.warning):''}</li>`).join('')}</ul><label class="check"><input type="checkbox" name="keep_attachments" checked><span>保留这些附件；取消并保存后移除</span></label></details>`:'<input type="hidden" name="keep_attachments" value="true">';
  }
  function publicationList(){
    const rows=publications.map(p=>`<article class="campus-row" data-campus-publication="${esc(p.id)}"><div><strong>${esc(p.title)}</strong>
      <p class="small muted">${esc(targetText(p))} · ${esc(p.publisher_name)} · ${p.state==='withdrawn'?'已撤回':'已发布'} · <span data-campus-delivery>${deliveryText(p.delivery)}</span></p>
      <p class="small campus-excerpt">${esc(p.body)}</p>${p.publication_policy?`<p class="small muted">${esc(p.publication_policy.label)}${p.publication_policy.external_notifications==='suppressed'?' · 外部通知已抑制':''}</p>`:''}${p.attachments.length?`<p class="small muted">附件：${p.attachments.map(f=>esc(f.name)).join('、')}</p>`:''}</div>
      <div class="row wrap"><button class="button small plain" type="button" data-campus-action="publication-detail" data-id="${esc(p.id)}">投递与版本</button>${p.state==='withdrawn'?`<button class="button small" type="button" data-campus-action="restore" data-id="${esc(p.id)}">正式恢复</button>`:''}${p.state==='published'?`<button class="button small" type="button" data-campus-action="correct" data-id="${esc(p.id)}">更正</button><button class="button small" type="button" data-campus-action="deliver-new" data-id="${esc(p.id)}">补发给新成员</button><button class="button small plain" type="button" data-campus-action="withdraw" data-id="${esc(p.id)}">撤回</button>`:''}<button class="button small" type="button" data-campus-action="retry" data-id="${esc(p.id)}" ${p.delivery.failed?'':'hidden'}>重试未送达</button></div></article>`).join('');
    return `<section class="campus-section" id="campus-published"><h2>发布记录</h2><p class="small muted">站内收件不代表已读；这里只显示数量，不显示成员的个人办理状态。</p>
      <div class="campus-search"><label class="field">查找发布记录<input id="campus-publication-search" type="search" maxlength="80" value="${esc(pubQuery)}" placeholder="标题、发布人、年级或班级"></label><button class="button small" type="button" data-campus-action="search-publications">搜索</button>${pubQuery?'<button class="button small plain" type="button" data-campus-action="clear-publications">清除</button>':''}</div>
      ${rows?`<div class="campus-list">${rows}</div>`:`<p class="muted">${pubQuery?'没有找到匹配的发布记录。':'还没有发布过学院通知。'}</p>`}
      <div class="campus-pagination row wrap"><span class="small muted" role="status">共 ${pubTotal} 条 · 第 ${pubPage} / ${pubPages} 页</span><button class="button small" type="button" data-campus-action="publications-prev" ${pubPage<=1?'disabled':''}>上一页</button><button class="button small" type="button" data-campus-action="publications-next" ${pubPage>=pubPages?'disabled':''}>下一页</button></div></section>`;
  }
  function auditList(items){
    const labels={assign_member:'设置学院身份',remove_member:'移除学院身份',publish:'发布通知',correct:'更正通知',withdraw:'撤回通知',restore:'正式恢复通知',rollback:'从历史版发布更正',deliver_new:'补发通知'};
    return `<section class="campus-section"><h2>学院操作记录</h2><label class="field">按操作筛选<select id="campus-audit-action"><option value="">全部操作</option>${Object.entries(labels).map(([value,label])=>`<option value="${value}" ${auditAction===value?'selected':''}>${label}</option>`).join('')}</select></label><p class="small muted">从服务器按当前学院权限与操作筛选；每批最多 100 条，不把本批记录当作全部。</p>${items.length?`<ul class="campus-audit">${items.map(item=>`<li>${esc(new Date(item.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))} · ${esc(item.actor_name)} · ${esc(labels[item.action]||item.action)}${item.target_name?' · '+esc(item.target_name):''}</li>`).join('')}</ul>`:'<p class="small muted">当前筛选下暂无操作记录。</p>'}<div class="row wrap"><span class="small muted">第 ${auditPrevious.length+1} 批 · ${items.length} 条</span><button class="button small" type="button" data-campus-action="audit-prev" ${auditPrevious.length?'':'disabled'}>上一批</button><button class="button small" type="button" data-campus-action="audit-next" ${auditHasMore?'':'disabled'}>继续读取</button></div></section>`;
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
    $('[data-campus-grade]',form).closest('.form-grid').hidden=!['grade','class'].includes(target);
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
    if(changed)separateSubmittedDraft(form);
    if(changed)delete form.dataset.requestId;
    const prior=drafts.get(owner)||{},files=[...form.elements.files.files];
    const fileNames=files.length?files.map(f=>f.name):(form.dataset.missingFiles==='1'?prior.fileNames||[]:[]);
    drafts.set(owner,{...prior,id:form.dataset.draftId,version:prior.id===form.dataset.draftId?(prior.version||0):(Number(form.dataset.draftVersion)||0),
      audience:form.elements.audience.value,grade:form.elements.grade.value,class_name:form.elements.class_name.value,
      title:form.elements.title.value,body:form.elements.body.value,...readPolicy(form),requestId:form.dataset.requestId||'',fileNames});
    if(changed){
      const status=form.querySelector('[data-campus-draft-status]');if(status)status.textContent='修改尚未保存';
      clearTimeout(draftTimer);
      if(!form.dataset.draftConflict)draftTimer=setTimeout(()=>persistDraft(form).catch(error=>draftError(form,error)),900);
    }
  }
  function draftError(form,error){
    if(!form.isConnected||owner!==state.session?.user?.id)return;
    const status=form.querySelector('[data-campus-draft-status]');
    if(status){status.textContent='草稿未保存：'+error.message;status.setAttribute('role','alert');}
    if(error.status===409){
      form.dataset.draftConflict='1';
      if(!form.querySelector('[data-campus-action="inspect-draft"]'))status?.insertAdjacentHTML('afterend','<button type="button" class="button small" data-campus-action="inspect-draft">核对服务器草稿</button><button type="button" class="button small" data-campus-action="copy-draft">将当前输入另存为草稿</button>');
    }
  }
  function persistDraft(form){
    clearTimeout(draftTimer);
    const uid=owner,id=form.dataset.draftId;
    const run=async()=>{
      if(uid!==state.session?.user?.id||drafts.get(uid)?.id!==id)return null;
      if(submission.pending()?.payload.draft_id===id){
        const status=form.querySelector('[data-campus-draft-status]');if(status)status.textContent='该版本已提交，请先核对上次发布结果；修改内容会另存新草稿。';
        return null;
      }
      if(form.dataset.draftConflict)throw Error('服务器草稿已有新版本，请核对后继续，或将当前输入另存为草稿。');
      const files=[...form.elements.files.files],snapshot={version:drafts.get(uid)?.version??(Number(form.dataset.draftVersion)||0),
        title:form.elements.title.value,body:form.elements.body.value,audience:form.elements.audience.value,
        grade:form.elements.grade.value,class_name:form.elements.class_name.value,...readPolicy(form),
        pending_attachment_names:form.dataset.missingFiles==='1'&&!files.length?(drafts.get(uid)?.fileNames||[]):[],
        keep_attachments:form.elements.keep_attachments.type==='hidden'||form.elements.keep_attachments.checked};
      if(!snapshot.title&&!snapshot.body&&!files.length&&!snapshot.version)return null;
      const body=new FormData();body.append('data',JSON.stringify(snapshot));for(const file of files)body.append('files',file);
      const status=form.querySelector('[data-campus-draft-status]');if(status)status.textContent='正在保存草稿…';
      const saved=await api('/campus/drafts/'+encodeURIComponent(id),{method:'PUT',body});
      if(uid!==state.session?.user?.id||drafts.get(uid)?.id!==id)return saved;
      form.dataset.draftVersion=String(saved.version);
      const sameFiles=[...form.elements.files.files].every((file,i)=>file===files[i])&&form.elements.files.files.length===files.length;
      const missingFiles=form.dataset.missingFiles==='1'&&!files.length;
      if(sameFiles&&!missingFiles){form.elements.files.value='';form.dataset.missingFiles='';}
      drafts.set(uid,{...drafts.get(uid),version:saved.version,attachments:saved.attachments,pending_attachment_names:saved.pending_attachment_names||[],fileNames:sameFiles&&!missingFiles?[]:drafts.get(uid).fileNames});
      form.querySelector('[data-campus-saved-files]').innerHTML=savedAttachmentFields(saved.attachments);
      serverDrafts=[saved,...serverDrafts.filter(item=>item.id!==id)];
      const stillSame=['title','body','audience','grade','class_name'].every(key=>form.elements[key].value===snapshot[key])&&JSON.stringify(readPolicy(form))===JSON.stringify({valid_until:snapshot.valid_until,reference_only:snapshot.reference_only});
      if(status){status.textContent=missingFiles?'正文已保存第 '+saved.version+' 版；待重新选择的附件尚未保存，请选择附件或明确不再附加。':stillSame?'已保存第 '+saved.version+' 版 · '+saved.attachments.length+' 份附件':'较早修改已保存，正在保存新输入…';status.setAttribute('role','status');}
      return saved;
    };
    const result=draftWrites.catch(()=>{}).then(run);draftWrites=result.catch(()=>{});return result;
  }
  function deliveryText(delivery){
    return `站内收件 ${delivery.delivered}/${delivery.total}${delivery.pending?' · 待投递 '+delivery.pending:''}${delivery.failed?' · 未送达 '+delivery.failed:''}${delivery.out_of_scope?' · 已不在范围 '+delivery.out_of_scope:''}`;
  }
  function scheduleDeliveryRefresh(id,uid){
    clearTimeout(deliveryTimer);
    if(!publications.some(item=>item.delivery.pending))return;
    deliveryTimer=setTimeout(async()=>{
      if(!stillCurrent(id,uid)||!document.querySelector('#campus-published'))return;
      if(document.hidden){scheduleDeliveryRefresh(id,uid);return;}
      const results=await Promise.allSettled(publications.filter(item=>item.delivery.pending).map(item=>api('/campus/publications/'+encodeURIComponent(item.id))));
      if(!stillCurrent(id,uid))return;
      for(const result of results){if(result.status!=='fulfilled')continue;const item=result.value;
        const row=document.querySelector(`[data-campus-publication="${CSS.escape(item.id)}"]`);if(!row)continue;
        const previous=publications.find(p=>p.id===item.id);if(previous)previous.delivery=item.delivery;
        row.querySelector('[data-campus-delivery]').textContent=deliveryText(item.delivery);
        row.querySelector('[data-campus-action="retry"]').hidden=!item.delivery.failed;
      }
      scheduleDeliveryRefresh(id,uid);
    },4000);
  }
  async function publicationDetail(id){
    const view=captureUiContext(state),item=await api('/campus/publications/'+encodeURIComponent(id));if(!view.sameDialog())return;detailPublication=item;
    showDialog('投递与正式版本',`<section class="stack"><h3>${esc(item.title)}</h3>${item.publication_policy?`<p class="small">${esc(item.publication_policy.label)}${item.publication_policy.valid_until?' · '+esc(policyFieldsTime(item.publication_policy.valid_until)):''}</p>`:''}<p>${esc(deliveryText(item.delivery))}</p><p class="small muted">站内收件表示记录已进入对方账号，不代表已读、已办理或手机推送已显示。待投递记录会由后台继续处理。</p>${item.change_summary?`<p class="small muted">本版变化：${[item.change_summary.title_changed?'标题已更正':'',item.change_summary.body_changed?'正文已更正':'',...(item.change_summary.attachments_added||[]).map(name=>'新增附件 '+name),...(item.change_summary.attachments_removed||[]).map(name=>'移除附件 '+name)].filter(Boolean).map(esc).join('；')||'原文和附件保持一致'}</p>`:''}${(item.delivery.errors||[]).map(error=>`<p class="alert error">${esc(error.error)} · ${error.count} 人</p>`).join('')}${renderCampusDeliveryEvidence(item.delivery.evidence,esc)}<details class="details"><summary>正式版本记录 · ${(item.history||[]).length} 版</summary>${(item.history||[]).map(entry=>`<article><h4>第 ${entry.version} 版 · ${esc(entry.title)}</h4>${entry.reason?`<p class="small muted">本版说明：${esc(entry.reason)}</p>`:''}<p class="small campus-excerpt">${esc(entry.body)}</p>${entry.attachments?.length?`<ul>${entry.attachments.map(file=>`<li>${file.download_url?`<a href="${esc(file.download_url)}" download>${esc(file.name)}</a>`:esc(file.name)}</li>`).join('')}</ul>`:''}${item.state==='published'&&entry.version!==item.version&&entry.kind!=='withdraw'?`<button type="button" class="button small" data-campus-action="rollback-version" data-id="${esc(item.id)}" data-version="${entry.version}">以第 ${entry.version} 版更正</button>`:''}</article>`).join('')}</details></section>`);
  }
  function audience(form){
    const kind=form.elements.audience.value;
    if(!kind)throw Error('请先选择发布范围');
    return {audience:kind,grade:kind==='college'?'':form.elements.grade.value.trim(),
            class_name:kind==='class'?form.elements.class_name.value.trim():''};
  }
  function correctionDialog(item,restore=false){
    showDialog(restore?'正式恢复学院通知':'更正学院通知',`<form class="stack" data-workspace-form="${restore?'campus-restore':'campus-correct'}" data-id="${esc(item.id)}" data-version="${item.version}">
      <p class="small muted">${restore?'恢复会建立新的正式版本并重新投递。原有个人任务继续保留取消或待核对状态，须本人根据新依据处理。':'向原接收范围中仍有权限的成员发送更正；保留对方的个人办理记录。'}发布范围不能在这里扩大。</p>${restore?'<label class="field">正式恢复依据与说明<textarea name="reason" required maxlength="1000" rows="3"></textarea></label>':''}
      <label class="field">标题<input name="title" required maxlength="160" value="${esc(item.title)}"></label><label class="field">通知正文<textarea name="body" required maxlength="10000" rows="6">${esc(item.body)}</textarea></label>
      ${policyFields(item)}<label class="check"><input type="checkbox" name="keep_attachments" ${restore?'':'checked'}><span>${restore?'明确沿用撤回前一版本附件':'保留原附件'}</span></label><label class="field">增加或替换附件<input type="file" name="files" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.png,.jpg,.jpeg,.webp"></label><div class="form-footer"><button class="button primary" type="submit">${restore?'确认正式恢复':'发布更正'}</button></div></form>`);
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
    if(event.target.id==='campus-audit-action'){auditAction=event.target.value;auditCursor='';auditPrevious=[];render().catch(error=>toast(error.message,true));}
    if(event.target.id==='campus-college'){collegeId=event.target.value;editing=null;auditCursor='';auditPrevious=[];render().catch(error=>toast(error.message,true));}
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
      if(action==='roster')await roster.open(collegeId);
      else if(action==='recover-publication'||action==='review-publication'){
        const recovered=await recoverPublication(view,{renewReview:action==='review-publication'});completePublication(recovered,view);
      }
      else if(action==='cancel-publication'){
        const pending=await submission.load();if(!pending||!view.sameRoute())return;
        if(!await ask('停止尚未完成的发布',`停止《${pending.payload.title}》尚未完成的发布。已经发布的通知不会因此撤回；未发布的将停止继续发送，当前输入仍可保留为草稿。`,'确认停止未完成发布')||!view.sameRoute())return;
        const stopped=await submission.cancel({canSend:view.sameRoute});if(!stopped?.current||!view.sameUser())return;
        if(stopped.state==='published'){completePublication(stopped,view);return;}
        if(view.sameRoute()){
          const form=$('[data-workspace-form="campus-publish"]');if(form&&separateSubmittedDraft(form,stopped.intent)){saveDraft(form,false);await persistDraft(form);}
          if(view.sameRoute())updatePublicationRecovery();
        }
        toast('尚未完成的发布已停止；当前输入保留为草稿，需要重新核对后才会发布。'+(stopped.cleanupError?' 停止操作已生效，核对记录清理暂未完成；请重新打开发布页面再核对停止结果。':''),!!stopped.cleanupError);
      }
      else if(action==='save-draft'){const form=button.closest('form');await persistDraft(form);}
      else if(action==='inspect-draft'){const form=button.closest('form'),remote=await api('/campus/drafts/'+encodeURIComponent(form.dataset.draftId));if(view.sameDialog())showDialog('核对服务器草稿',`<section class="stack"><p>当前输入仍留在原表单，可关闭此窗口后另存。服务器第 ${remote.version} 版：</p><h3>${esc(remote.title||'未填写标题')}</h3><p class="campus-excerpt">${esc(remote.body)}</p><p class="small muted">${esc(targetText(remote))} · ${remote.attachments.length} 份附件</p></section>`);}
      else if(action==='copy-draft'){const form=button.closest('form');form.dataset.draftId='draft-'+crypto.randomUUID();form.dataset.draftVersion='0';delete form.dataset.draftConflict;const local=drafts.get(owner)||{};drafts.set(owner,{...local,id:form.dataset.draftId,version:0,attachments:[]});form.querySelectorAll('[data-campus-action="inspect-draft"],[data-campus-action="copy-draft"]').forEach(el=>el.remove());form.querySelector('[data-campus-saved-files]').innerHTML=savedAttachmentFields([]);await persistDraft(form);if(view.sameUser())toast('当前输入已另存；原服务器附件未复制，请按需重新选择。');}
      else if(action==='new-draft'||action==='open-draft'){
        const form=$('[data-workspace-form="campus-publish"]');if(form)await persistDraft(form);if(!view.sameRoute())return;
        const selected=action==='open-draft'?await api('/campus/drafts/'+encodeURIComponent(button.dataset.id)):{id:'draft-'+crypto.randomUUID(),version:0};
        if(view.sameRoute()){drafts.set(owner,selected);await render();}
      }
      else if(action==='delete-draft'){
        const item=serverDrafts.find(d=>d.id===button.dataset.id);if(!item)return;
        if(submission.pending()?.payload.draft_id===item.id)throw Error('这份草稿已有一次结果待核对的发布，请先核对原提交。');
        if(await ask('删除发布草稿',`删除“${item.title||'未填写标题'}”及其草稿附件；不会影响已发布通知。`,'删除草稿')){
          await api('/campus/drafts/'+encodeURIComponent(item.id)+'?version='+item.version,{method:'DELETE'});
          if(drafts.get(owner)?.id===item.id)drafts.delete(owner);if(view.sameRoute())await render();
        }
      }
      else if(action==='audit-next'||action==='audit-prev'){const previousCursor=auditCursor,previousStack=[...auditPrevious];if(action==='audit-next'){if(!auditHasMore)return;auditPrevious.push(auditCursor);auditCursor=auditNext;}else auditCursor=auditPrevious.pop()||'';try{await render();}catch(error){auditCursor=previousCursor;auditPrevious=previousStack;throw error;}}
      else if(action==='publication-detail')await publicationDetail(button.dataset.id);
      else if(action==='rollback-version'&&detailPublication?.id===button.dataset.id){
        const previous=detailPublication.history.find(entry=>entry.version===Number(button.dataset.version));if(!previous)return;
        showDialog('以历史版本发布更正',`<form class="stack" data-workspace-form="campus-rollback" data-id="${esc(detailPublication.id)}" data-version="${detailPublication.version}" data-target-version="${previous.version}"><p>将第 ${previous.version} 版的正文与附件建立为一个新的正式更正版本，原历史继续保留，成员个人任务须重新核对。</p><h3>${esc(previous.title)}</h3><details class="details"><summary>核对拟恢复正文与附件</summary><p class="campus-excerpt">${esc(previous.body)}</p><ul>${(previous.attachments||[]).map(file=>`<li>${esc(file.name)}</li>`).join('')}</ul></details><label class="field">更正依据与原因<textarea name="reason" required minlength="2" maxlength="1000" rows="3"></textarea></label><button type="submit" class="button primary">确认发布更正版本</button></form>`);
      }
      else if(action==='restore'&&item)correctionDialog(item,true);
      else if(action.startsWith('jump-'))$('#campus-'+action.slice(5))?.scrollIntoView({block:'start',behavior:'smooth'});
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
      else if(action==='retry'&&item){const review=await api('/campus/audience-review',{method:'POST',json:{audience:item.audience,grade:item.grade,class_name:item.class_name}});if(!view.sameRoute()||!await ask('核对重试接收范围',`按当前授权范围重试：学生 ${review.students} 人，工作人员 ${review.staff} 人；已成功的记录不会重复发送。`,'核对并重试'))return;const result=await api('/campus/publications/'+encodeURIComponent(item.id)+'/retry',{method:'POST',json:{audience_review:review.review}});if(view.sameRoute())await render();if(view.sameUser())toast(result.delivery.failed?`仍有 ${result.delivery.failed} 条未送达`:'投递重试已接收，请查看投递进度',!!result.delivery.failed);}
      else if(action==='deliver-new'&&item){
        const review=await api('/campus/audience-review',{method:'POST',json:{audience:item.audience,grade:item.grade,class_name:item.class_name}}),reference=!!(item.publication_policy?.reference_only||item.publication_policy?.expired);
        if(!view.sameRoute()||!await ask(reference?'核对历史参考补发':'核对新成员补发',`当前范围学生 ${review.students} 人，工作人员 ${review.staff} 人。只为尚未收件的现有成员补发并重试未送达记录。${reference?'这则通知已过期或仅作历史参考，将明确作为站内参考资料送达，不发送新的外部通知。':'不会自动修改对方个人待办。'}`,reference?'确认按参考资料补发':'确认补发'))return;
        const result=await api('/campus/publications/'+encodeURIComponent(item.id)+'/deliver-new',{method:'POST',json:{version:item.version,audience_review:review.review,reference_confirmed:reference}});if(view.sameRoute())await render();if(view.sameUser())toast(`新增 ${result.delivery.added} 名接收成员，${result.delivery.failed?'仍有 '+result.delivery.failed+' 条未送达':'请查看投递进度'}`,!!result.delivery.failed);
      }
    }catch(error){if(view.sameUser()){if(button.closest('[data-workspace-form=campus-publish]'))draftError(button.closest('form'),error);toast(error.message,true);}}finally{button.disabled=false;}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target,kind=form.dataset.workspaceForm;
    if(!['campus-member','campus-publish','campus-correct','campus-restore','campus-rollback','campus-withdraw'].includes(kind))return;
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
        const pending=await submission.load();if(!view.sameRoute())return;
        if(pending){
          const recovered=await recoverPublication(view);completePublication(recovered,view);return;
        }
        if(form.dataset.missingFiles==='1')throw Error('请重新选择附件，或点击“不再附加”');
        await persistDraft(form);
        if(!view.sameRoute()||!form.isConnected)return;
        const selected=audience(form),review=await api('/campus/audience-review',{method:'POST',json:selected});
        if(!view.sameRoute()||!form.isConnected)return;
        const summary=`《${String(values.get('title')).trim()}》将发送至${targetText(selected)}：学生 ${review.students} 人，学院工作人员 ${review.staff} 人。${review.students?'请确认接收范围。':'当前没有学生符合条件，请确认是否仍要发布。'}`;
        if(!await ask('核对接收范围',summary,'确认发布')||!view.sameRoute()||!form.isConnected)return;
        form.dataset.requestId ||= requestId();
        const payload={...selected,title:String(values.get('title')).trim(),body:String(values.get('body')).trim(),request_id:form.dataset.requestId,audience_review:review.review,draft_id:form.dataset.draftId,draft_version:Number(form.dataset.draftVersion),...readPolicy(form)};
        saveDraft(form,false);
        const prepared=await submission.prepare(payload,drafts.get(draftOwner));
        if(!prepared||!view.sameRoute())return;
        const recovered=await submission.replay({canSend:view.sameRoute});completePublication(recovered,view);return;
      }else if(['campus-correct','campus-restore'].includes(kind)){
        const payload={version:Number(form.dataset.version),title:String(values.get('title')).trim(),body:String(values.get('body')).trim(),keep_attachments:values.has('keep_attachments'),...readPolicy(form),...(kind==='campus-restore'?{reason:String(values.get('reason')).trim()}: {})};
        const body=new FormData();body.append('data',JSON.stringify(payload));for(const file of values.getAll('files'))if(file.size)body.append('files',file);
        result=await api('/campus/publications/'+encodeURIComponent(form.dataset.id)+(kind==='campus-restore'?'/restore':'/correct'),{method:'POST',body});
      }else if(kind==='campus-rollback')result=await api('/campus/publications/'+encodeURIComponent(form.dataset.id)+'/rollback',{method:'POST',json:{version:Number(form.dataset.version),target_version:Number(form.dataset.targetVersion),reason:String(values.get('reason')).trim()}});
      else result=await api('/campus/publications/'+encodeURIComponent(form.dataset.id)+'/withdraw',{method:'POST',json:{version:Number(form.dataset.version),reason:String(values.get('reason')).trim()}});
      if(kind==='campus-publish'&&drafts.get(draftOwner)?.requestId===form.dataset.requestId)drafts.delete(draftOwner);
      if(!view.sameUser())return;
      if(kind==='campus-publish'){pubPage=1;pubQuery='';}
      if(['campus-correct','campus-restore','campus-rollback','campus-withdraw'].includes(kind)&&view.sameDialog())$('#dialog').close();
      if(view.sameRoute()){editing=null;if(kind==='campus-publish')location.hash='#campus/records';else await render();}
      if(kind==='campus-member')toast('学院身份已保存');
      else toast(`已接收发布：站内收件 ${result.delivery.delivered}/${result.delivery.total}${result.delivery.pending?'，待投递 '+result.delivery.pending+'，可在发布记录查看进度':''}${result.delivery.failed?'，未送达 '+result.delivery.failed+'，可在发布记录重试':''}${result.delivery.students===0?'；当前范围没有学生':''}`,!!result.delivery.failed);
    }catch(error){if(view.sameUser()){if(kind==='campus-publish'&&view.sameRoute())updatePublicationRecovery();toast(error.message,true);}}finally{form.inert=false;finish();}
  });
  document.addEventListener('campus-roster-updated',event=>{if(event.detail?.collegeId===collegeId&&location.hash==='#campus/members')render().catch(error=>toast(error.message,true));});
  window.addEventListener('hashchange',()=>{clearTimeout(deliveryTimer);});
  return {render,clearSession(){clearTimeout(draftTimer);clearTimeout(deliveryTimer);submission.clear();drafts.clear();serverDrafts=[];owner=null;}};
}
