import {patchProfile} from './profile-editor.js';
import {captureUiContext} from './ui-request.js';

export const GETTING_STARTED_HINT='workspace-capabilities-v1';
export const guideDismissed=profile=>Array.isArray(profile?.dismissed_hints)&&profile.dismissed_hints.includes(GETTING_STARTED_HINT);
export function capabilityIdentity(user){
  const member=user?.campus_membership;
  if(member?.role==='student')return {state:'verified',label:'学院身份已核实 · 学生',description:(member.college_name||'已登记学院')+'。个人通知、办理记录和材料仍只在你的个人空间中管理。'};
  if(['counselor','college_admin'].includes(member?.role))return {state:'verified',label:'学院身份已核实 · '+(member.role==='counselor'?'辅导员':'学院管理员'),description:(member.college_name||'已登记学院')+'。学院发布与协作按实际授权范围开放，个人资料与学院事务分开。'};
  return {state:'pending',label:'学院身份待核实',description:'现在可以先使用个人收件和办理功能。填写教师、员工等个人条件不会获得学院发布或管理权限。'+(user?.role==='admin'?'系统管理权限已授权，学院发布身份仍需另行确认。':'')};
}

export function createGettingStarted({state,api,esc,showDialog,toast,onPreferences}){
  const saving=new Set();
  function identityMarkup(){const identity=capabilityIdentity(state.session?.user);return `<p class="getting-started-identity" data-identity-state="${identity.state}"><strong>${esc(identity.label)}</strong> · ${esc(identity.description)}</p>`;}
  function mount(root=document.querySelector('#content')){
    const user=state.session?.user,existing=root?.querySelector('[data-getting-started]');
    if(!root||root.dataset.page!=='dashboard'||!user||guideDismissed(user.profile)){existing?.remove();return;}
    if(existing&&existing.dataset.owner===String(user.id)){existing.querySelector('[data-identity-state]')?.replaceWith(document.createRange().createContextualFragment(identityMarkup()));return;}
    existing?.remove();
    const banner=document.createElement('aside');banner.className='getting-started';banner.dataset.gettingStarted='';banner.dataset.owner=user.id;banner.setAttribute('aria-labelledby','getting-started-title');
    banner.innerHTML=`<div class="between wrap"><h2 id="getting-started-title">现在能用什么</h2><button type="button" class="button small plain" data-onboarding-dismiss>暂时跳过</button></div><p>先收好通知原文，核对后加入本人待办，再记录办理与跟进；无需等待学院身份确认。</p>${identityMarkup()}<button type="button" class="button small" data-onboarding-open>查看三步说明</button><p class="form-error" role="alert" hidden></p>`;
    root.prepend(banner);
  }
  function open(){
    const user=state.session?.user;if(!user)return;
    showDialog('现在能用什么',`<section class="stack getting-started-guide" data-onboarding-guide data-owner="${esc(user.id)}"><p>按你的实际材料和本人决定开始；这份说明可随时从“个人与账号 → 个人资料”找回。</p>${identityMarkup()}<ol><li><strong>收下原文与附件</strong><p>可以粘贴正文、链接、截图或文件，也可以选择通知来源。先保留来源和材料，再看哪些内容与你有关。</p><a class="button small" href="#new" data-onboarding-link>开始收通知</a></li><li><strong>核对后安排本人行动</strong><p>AI 整理的是待核对建议。你确认责任、时间与要求后再加入待办；未核实的日期不会自动变成正式期限。</p><a class="button small" href="#tasks" data-onboarding-link>打开我的待办</a></li><li><strong>记录办理与下一次跟进</strong><p>个人完成、校方受理与审核结果分别记录。提醒和个人安排需要明确设置；渠道接受不代表本人已读或锁屏必达。</p><a class="button small" href="#calendar" data-onboarding-link>查看个人日历</a></li></ol><p class="small muted">学院发布或成员管理仅由已授权身份进入；自填资料不会授予权限。</p><div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button type="button" class="button primary" data-onboarding-dismiss>我知道了</button></div><p class="form-error" role="alert" hidden></p></section>`);
  }
  async function dismiss(root){
    const session=state.session,uid=session?.user?.id;
    if(!uid||!root||root.dataset.owner!==String(uid)||saving.has(uid))return;
    const view=captureUiContext(state,root),buttons=[...root.querySelectorAll('[data-onboarding-dismiss]')];saving.add(uid);buttons.forEach(button=>button.disabled=true);
    try{
      const before=session.user.profile.dismissed_hints??null,values=[...new Set([...(before||[]),GETTING_STARTED_HINT])];
      if(values.length>60)throw Error('已收起的提示记录达到上限，可在显示与声音中重新显示小提示后再试。');
      const profile=await patchProfile(api,{dismissed_hints:before},{dismissed_hints:values});
      if(state.session!==session||!view.sameUser())return;
      const inline=root.matches('[data-getting-started]'),wasFocused=root.contains(document.activeElement);
      session.user.profile.dismissed_hints=profile.dismissed_hints;onPreferences?.();
      if(view.sameDialog()&&root.matches('[data-onboarding-guide]'))document.querySelector('#dialog').close();
      if(inline){root.remove();if(wasFocused&&view.sameRoute())document.querySelector('#content')?.focus({preventScroll:true});}
      toast('已收起说明，可从个人资料页再次打开');
    }catch(error){
      if(state.session!==session||!view.sameUser()||!root.isConnected)return;
      const note=root.querySelector('.form-error');note.hidden=false;note.textContent='尚未保存跳过状态：'+error.message+(error.status===409?'。当前账号的提示偏好已在另一处变化，重新打开个人页核对后再试。':'');
    }finally{saving.delete(uid);buttons.forEach(button=>button.disabled=false);}
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-onboarding-open],[data-onboarding-dismiss],[data-onboarding-link]');if(!button)return;
    if(button.hasAttribute('data-onboarding-open'))open();
    else if(button.hasAttribute('data-onboarding-link'))document.querySelector('#dialog')?.close();
    else dismiss(button.closest('[data-getting-started],[data-onboarding-guide]'));
  });
  document.addEventListener('campus:display-preferences',()=>mount());
  return {mount,open};
}
