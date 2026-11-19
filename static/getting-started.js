import {startGuideTour} from './guide-tour.js';
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

export function createGettingStarted({state,api,esc,toast,onPreferences,renderHome,showDialog}){
  let tour=null;
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
    banner.innerHTML=`<div><h2 id="getting-started-title">新手指引</h2>${identityMarkup(true)}</div><div class="getting-started-actions"><button type="button" class="button small plain" data-onboarding-open>打开新手指引</button><button type="button" class="button small plain" data-onboarding-dismiss>收起</button></div>`;
    root.append(banner);
  }
  // Record only the first visible highlight, and retry a failed receipt when online.
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
      }).catch(()=>{/* The local pending receipt remains until the account write succeeds. */}).finally(()=>writes.delete(session));
    writes.set(session,save);
  }
  function showVideo(resume){
    const base='/static/assets/onboarding/first-steps';
    const revision='2',film=base+'.mp4?v='+revision;
    showDialog('新手操作演示',`<div class="guide-player">
      <video controls playsinline preload="none" poster="${base}.webp" aria-label="收通知、查看日程和订阅武汉大学官网的操作演示">
        <source src="${film}" type="video/mp4"><track kind="captions" src="${base}.zh.vtt?v=${revision}" srclang="zh-CN" label="中文">
      </video>
      <div class="guide-player-footer"><a href="${film}" download="珞珈信使新手操作演示.mp4">下载视频</a><button type="button" class="button small" data-action="close-dialog">返回指引</button></div>
    </div>`,{dismissFooter:false});
    const dialog=document.querySelector('#dialog'),video=dialog.querySelector('video');
    dialog.addEventListener('close',()=>{video.pause();resume();},{once:true});
  }
  function open(){
    const session=state.session;
    if(!session?.user)return;
    tour?.stop();
    tour=startGuideTour({
      sameUser:()=>state.session===session,
      showVideo,
      onShown:()=>remember(session),
      onEnd:()=>{tour=null;}
    });
    if((location.hash.slice(1)||'dashboard')!=='dashboard'||state.workContext&&state.workContext!=='personal'){
      state.workContext='personal';
      if((location.hash.slice(1)||'dashboard')==='dashboard')renderHome?.();
      else location.hash='#dashboard';
    }
  }
  function onHomeReady(){
    const session=state.session,root=document.querySelector('#content');
    if(tour||!session?.user||!root||root.inert||root.dataset.page!=='dashboard'||!root.querySelector('.personal-home')||!['','#dashboard'].includes(location.hash)||document.visibilityState==='hidden'||document.querySelector('dialog[open]'))return;
    const user=session.user;
    if(guideDismissed(user.profile))return;
    if(locallySeen(user.id)){remember(session);return;}
    if(needsFirstUseGuide(user.profile))open();
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
  });
  document.addEventListener('campus:display-preferences',()=>{mount();if(!state.session)tour?.stop();});
  document.addEventListener('visibilitychange',onHomeReady);
  window.addEventListener?.('online',()=>{
    const session=state.session;if(session?.user&&locallySeen(session.user.id))remember(session);
  });
  return {mount,open,onHomeReady,onRouteReady:()=>tour?.sync(true),identityMarkup};
}
