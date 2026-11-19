import {patchProfile} from './profile-editor.js';

export const GETTING_STARTED_HINT='workspace-capabilities-v1';
export const guideDismissed=profile=>profile?.first_use_guide_seen===true||!!profile?.dismissed_hints?.includes(GETTING_STARTED_HINT);
export const needsFirstUseGuide=profile=>profile?.first_use_guide_seen===false&&!guideDismissed(profile);
export function capabilityIdentity(user){
  const member=user?.campus_membership;
  if(member?.role==='student')return {state:'verified',label:'学院身份已核实 · 学生',description:(member.college_name||'已登记学院')+'。个人通知、办理记录和材料仍只在你的个人空间中管理。'};
  if(['counselor','college_admin'].includes(member?.role))return {state:'verified',label:'学院身份已核实 · '+(member.role==='counselor'?'辅导员':'学院管理员'),description:(member.college_name||'已登记学院')+'。学院发布与协作按实际授权范围开放，个人资料与学院事务分开。'};
  return {state:'pending',label:'学院身份待核实',description:'现在可以先使用个人收件和办理功能。填写教师、员工等个人条件不会获得学院发布或管理权限。'+(user?.role==='admin'?'系统管理权限已授权，学院发布身份仍需另行确认。':'')};
}

const intakePaths={
  manual:{text:'群里收到的通知，可以粘贴正文、原文链接，也可以添加截图或附件。',label:'去收通知',href:'#new'},
  school:{text:'在「订阅与来源」点「选择武汉大学来源」，选好常看的学院或栏目。之后会自动收件，不用逐条粘贴。官网采集不调用 AI。',label:'去选武大来源',href:'#sources'}
};
const outcomes={
  apply:'站内待办增加「交申请表」，日程显示 12 月 4 日 17:00 的截止时间。学院复核不会占用你的日程。',
  keep:'通知原文和附件留在「通知」里，随时可以回看。待办和日程都不会增加事项。'
};

export function createGettingStarted({state,api,esc,showDialog,toast,onPreferences}){
  const presented=new Set(),writes=new WeakMap();
  const pendingKey=uid=>'campus.first-use-guide.pending.'+uid;
  const locallySeen=uid=>{
    if(presented.has(uid))return true;
    try{return localStorage.getItem(pendingKey(uid))==='1';}catch{return false;}
  };
  function identityMarkup(compact=false){const identity=capabilityIdentity(state.session?.user);return `<p class="getting-started-identity" data-identity-state="${identity.state}"><strong>${esc(identity.label)}</strong>${compact?'':' · '+esc(identity.description)}</p>`;}
  function mount(root=document.querySelector('#content')){
    const user=state.session?.user,existing=root?.querySelector('[data-getting-started]');
    if(!root||root.dataset.page!=='dashboard'||!user||guideDismissed(user.profile)||locallySeen(user.id)){existing?.remove();return;}
    if(existing&&existing.dataset.owner===String(user.id)){existing.querySelector('[data-identity-state]')?.replaceWith(document.createRange().createContextualFragment(identityMarkup(true)));return;}
    existing?.remove();
    const banner=document.createElement('aside');banner.className='getting-started';banner.dataset.gettingStarted='';banner.dataset.owner=user.id;banner.setAttribute('aria-labelledby','getting-started-title');
    banner.innerHTML=`<div><h2 id="getting-started-title">新手指引</h2>${identityMarkup(true)}</div><div class="getting-started-actions"><button type="button" class="button small plain" data-onboarding-open>看三步指引</button><button type="button" class="button small plain" data-onboarding-dismiss>收起</button></div>`;
    root.append(banner);
  }
  // Record the first presentation, including closing with Escape, the X or a reload.
  // This receipt never authorizes notice collection, AI processing or a calendar write.
  function remember(session){
    const user=session.user;
    if(guideDismissed(user.profile)||writes.has(session))return;
    presented.add(user.id);
    try{localStorage.setItem(pendingKey(user.id),'1');}catch{}
    const save=patchProfile(api,{first_use_guide_seen:user.profile.first_use_guide_seen??null},{first_use_guide_seen:true})
      .then(profile=>{
        try{localStorage.removeItem(pendingKey(user.id));}catch{}
        if(state.session!==session)return;
        session.user.profile.first_use_guide_seen=profile.first_use_guide_seen;
        onPreferences?.();
      }).catch(()=>{
        if(state.session!==session)return;
        const note=document.querySelector('#dialog[open] [data-guide-sync]');
        if(note)note.hidden=false;
      }).finally(()=>writes.delete(session));
    writes.set(session,save);
  }
  function open(returnFocus=null){
    const session=state.session;if(!session?.user)return;
    const first=intakePaths.manual;
    showDialog('新手指引',`<section class="getting-started-guide" data-onboarding-guide data-owner="${esc(session.user.id)}">
      <div class="guide-progress"><span data-guide-count>第 1 步，共 3 步</span><progress value="1" max="3" aria-label="新手指引进度"></progress></div>
      <ol class="guide-steps">
        <li data-guide-step="1"><h3 tabindex="-1">从哪里收通知？</h3>
          <div class="guide-choices" role="group" aria-label="选择通知来源"><button type="button" class="button small" data-guide-path="manual" aria-pressed="true">群里收到的</button><button type="button" class="button small" data-guide-path="school" aria-pressed="false">武大官网的</button></div>
          <div class="guide-sample" aria-live="polite"><p data-guide-path-note>${first.text}</p><a data-onboarding-link data-guide-route href="${first.href}">${first.label} →</a></div>
        </li>
        <li data-guide-step="2" hidden><h3 tabindex="-1">这条通知里，我要做什么？</h3>
          <div class="guide-sample"><span class="guide-caption">示例原文 · 奖学金申请</span><blockquote>请有意申请的本科生在 12 月 4 日 17:00 前交申请表。学院将于 12 月 7 日复核。</blockquote>
          <dl><dt>你要做的</dt><dd>如果要申请，12 月 4 日 17:00 前交表。</dd><dt>学院要做的</dt><dd>12 月 7 日复核，你不用再交一次。</dd></dl></div>
          <p class="guide-note">你可以手动整理，也可以同意使用 AI 生成草稿。草稿不会直接写进日历。</p>
        </li>
        <li data-guide-step="3" hidden><h3 tabindex="-1">要把它加入我的日程吗？</h3>
          <p>用刚才的奖学金通知试一下。</p>
          <div class="guide-choices" role="group" aria-label="选择示例的办理方式"><button type="button" class="button small" data-guide-outcome="apply" aria-pressed="false">我要申请</button><button type="button" class="button small" data-guide-outcome="keep" aria-pressed="false">仅存资料</button></div>
          <div class="guide-sample"><span class="guide-caption">示例结果 · 不会修改你的账号</span><p data-guide-result aria-live="polite">选一种处理方式，看看待办和日程会有什么变化。</p></div>
          <p class="guide-note">只把自己确认要办的事加入待办。有明确日期的会出现在站内日程；想在手机日历里提醒，还需导出并导入手机。</p>
          <div class="guide-links"><a href="#tasks" data-onboarding-link>打开待办 →</a><a href="#calendar" data-onboarding-link>查看日程 →</a></div>
        </li>
      </ol>
      <div class="guide-controls"><button type="button" class="button plain" data-action="close-dialog" data-guide-skip>跳过指引</button><button type="button" class="button" data-guide-prev hidden>上一步</button><button type="button" class="button primary" data-guide-next>下一步</button><button type="button" class="button primary" data-action="close-dialog" data-guide-finish hidden>开始使用</button></div>
      <div class="guide-footnote"><span>以后可在「我的 → 个人资料 → 新手指引」重看。</span><details><summary>我的学院身份</summary>${identityMarkup()}</details></div>
      <p class="small muted" data-guide-sync hidden>本次不会再提示，联网后将再次尝试保存到账号。</p>
    </section>`,{dismissFooter:false,returnFocus});
    remember(session);
  }
  function onHomeReady(){
    const session=state.session,root=document.querySelector('#content');
    if(!session?.user||!root||root.inert||root.dataset.page!=='dashboard'||!root.querySelector('.personal-home')||!['','#dashboard'].includes(location.hash)||document.visibilityState==='hidden'||document.querySelector('dialog[open]'))return;
    const user=session.user;
    if(guideDismissed(user.profile))return;
    if(locallySeen(user.id)){remember(session);return;}
    if(needsFirstUseGuide(user.profile))open(root);
  }
  function showStep(guide,number){
    const steps=[...guide.querySelectorAll('[data-guide-step]')],next=steps[number-1];
    if(!next)return;
    for(const step of steps)step.hidden=step!==next;
    guide.querySelector('[data-guide-count]').textContent=`第 ${number} 步，共 ${steps.length} 步`;
    guide.querySelector('progress').value=number;
    guide.querySelector('[data-guide-prev]').hidden=number===1;
    guide.querySelector('[data-guide-next]').hidden=number===steps.length;
    guide.querySelector('[data-guide-finish]').hidden=number!==steps.length;
    guide.querySelector('[data-guide-skip]').hidden=number===steps.length;
    next.querySelector('h3').focus();
  }
  document.addEventListener('click',event=>{
    const target=event.target.closest('button,a');
    if(!target||!state.session?.user)return;
    const banner=target.closest('[data-getting-started]');
    if(banner&&banner.dataset.owner===String(state.session.user.id)){
      if(target.hasAttribute('data-onboarding-open'))open();
      else if(target.hasAttribute('data-onboarding-dismiss')){
        remember(state.session);banner.remove();document.querySelector('#content')?.focus({preventScroll:true});toast('可以在「我的 → 个人资料」重看新手指引');
      }
      return;
    }
    const guide=target.closest('[data-onboarding-guide]');
    if(!guide||guide.dataset.owner!==String(state.session.user.id))return;
    if(target.hasAttribute('data-onboarding-link')){guide.closest('dialog')?.close();return;}
    if(target.hasAttribute('data-guide-next')||target.hasAttribute('data-guide-prev')){
      showStep(guide,Number(guide.querySelector('[data-guide-step]:not([hidden])').dataset.guideStep)+(target.hasAttribute('data-guide-next')?1:-1));return;
    }
    if(target.dataset.guidePath){
      const path=intakePaths[target.dataset.guidePath];if(!path)return;
      for(const b of guide.querySelectorAll('[data-guide-path]'))b.setAttribute('aria-pressed',String(b===target));
      guide.querySelector('[data-guide-path-note]').textContent=path.text;
      const link=guide.querySelector('[data-guide-route]');link.href=path.href;link.textContent=path.label+' →';
    }else if(target.dataset.guideOutcome){
      for(const b of guide.querySelectorAll('[data-guide-outcome]'))b.setAttribute('aria-pressed',String(b===target));
      guide.querySelector('[data-guide-result]').textContent=outcomes[target.dataset.guideOutcome];
    }
  });
  document.addEventListener('campus:display-preferences',()=>mount());
  document.addEventListener('visibilitychange',onHomeReady);
  window.addEventListener?.('online',()=>{
    const session=state.session;if(session?.user&&locallySeen(session.user.id))remember(session);
  });
  return {mount,open,onHomeReady};
}
