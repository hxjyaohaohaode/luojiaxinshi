import {passwordEditor,showInputError,installAuthFeedback,successTransition} from './auth-feedback.js';
import {brandMotion} from './motion.js';
export function createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,route,moveSelection,verification}){
  let loginMethod='password';
  installAuthFeedback();
  const agreement=()=>'<label class="check auth-agreement"><input type="checkbox" name="accepted_terms" required><span>我已阅读并同意<a href="#privacy" target="_blank" rel="noopener">《隐私政策》</a>和<a href="#terms" target="_blank" rel="noopener">《用户协议》</a>。</span></label>';
  function signupMarkup(username){return `<ol class="auth-progress" aria-label="注册进度">${['验证联系方式','填写账号','设置密码'].map((text,i)=>`<li data-progress-step="${i+1}" ${i===0?'aria-current="step"':''}><span>${i+1}</span>${text}</li>`).join('')}</ol>
    <form id="auth-form" data-auth-mode="register" data-signup-current="1" class="stack" autocomplete="on">
    <fieldset data-signup-step="1" class="auth-stage stack"><legend class="sr-only">验证联系方式</legend>${verification.markup('auth','register',{title:'验证手机号或邮箱'})}<label class="check auth-agreement"><input type="checkbox" name="verification_consent" required><span>同意按<a href="#privacy" target="_blank" rel="noopener">《隐私政策》</a>验证此联系方式</span></label><div class="form-footer"><button type="button" class="button primary" data-signup-next="1">验证并继续 ${icon('arrow')}</button></div></fieldset>
    <fieldset data-signup-step="2" class="auth-stage stack" disabled hidden><legend class="sr-only">填写账号</legend>${field('怎么称呼你','display_name','','text','required maxlength="40" autocomplete="nickname"')}${field('账号名','username',username,'text','required minlength="3" maxlength="40" pattern="[a-zA-Z0-9_.@+\\-]+" autocomplete="username" autocapitalize="none" spellcheck="false"')}<label class="field">常用身份<select name="campus_role"><option value="student">学生</option><option value="teacher">教师</option><option value="staff">教职工</option><option value="other">其他</option></select></label><p class="small muted">用于安排个人工作台，可在设置中修改。学院权限由管理员另行核对。</p><div class="form-footer"><button type="button" class="button" data-signup-back="1">上一步</button><button type="button" class="button primary" data-signup-next="2">下一步 ${icon('arrow')}</button></div></fieldset>
    <fieldset data-signup-step="3" class="auth-stage stack" disabled hidden><legend class="sr-only">设置密码</legend>${passwordEditor(field,{creating:true,confirm:true})}${agreement()}<div class="form-footer"><button type="button" class="button" data-signup-back="2">上一步</button><button type="submit" class="button primary auth-submit">注册</button></div></fieldset></form>`;}
  function signupStep(form,step){
    form.dataset.signupCurrent=String(step);
    form.closest('.auth-form').querySelector('h2').textContent=['','注册','填写账号','设置密码'][step];
    form.querySelectorAll('[data-signup-step]').forEach(group=>{const active=Number(group.dataset.signupStep)===step;group.hidden=!active;group.disabled=!active;});
    form.closest('.auth-form').querySelectorAll('[data-progress-step]').forEach(node=>{if(Number(node.dataset.progressStep)===step)node.setAttribute('aria-current','step');else node.removeAttribute('aria-current');});
    form.querySelector('[data-signup-step="'+step+'"] input')?.focus({preventScroll:true});
  }
  function render(){
    const canRegister=state.registrationMode==='public'||!!state.invite;
    const mode=state.invite?'register':location.hash==='#register'&&canRegister?'register':location.hash==='#recover'?'recover':'login';
    const signup=mode==='register',recover=mode==='recover',otp=mode!=='login'||loginMethod==='code';
    const username=document.querySelector('#auth-form [name=username]')?.value||'';
    const unavailable=state.authPolicy?.channels&&!Object.values(state.authPolicy.channels).some(Boolean);
    const form=`<div class="auth-form"><div class="auth-mobile-brand"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="44" height="44">珞珈信使</div><h2>${signup?'注册':recover?'找回密码':'欢迎回来'}</h2>
    ${mode==='login'?`<div class="auth-methods" aria-label="登录方式"><button class="${loginMethod==='password'?'selected':''}" type="button" data-login-method="password" aria-pressed="${loginMethod==='password'}">密码登录</button><button class="${loginMethod==='code'?'selected':''}" type="button" data-login-method="code" aria-pressed="${loginMethod==='code'}">验证码登录</button></div>`:''}
    ${unavailable&&otp?'<p class="alert info">验证码通道正在配置，暂时无法发送。已有账号可使用密码登录。</p>':''}
    ${signup?signupMarkup(username):`<form id="auth-form" data-auth-mode="${mode}" class="stack">
    ${otp?'':field('账号、邮箱或手机号','username',username,'text','required minlength="3" maxlength="254" autocomplete="username" autocapitalize="none" spellcheck="false"')}
    ${recover||!otp?passwordEditor(field,{creating:recover,confirm:recover}):''}
    ${otp?verification.markup('auth',mode,{title:signup?'验证手机号或邮箱':'验证已绑定的手机号或邮箱'}):''}
    <button class="button primary auth-submit" type="submit">${recover?'重设密码并登录':'登录'}</button></form>`}
    <div class="auth-links">${signup||recover?'<a href="#login">返回登录</a>':`<a href="#recover">忘记密码</a>${canRegister?'<a href="#register">创建账号</a>':''}`}</div>
    ${!canRegister?'<p class="small muted">当前使用邀请链接注册；已有账号可直接登录。</p>':''}
    <p class="auth-legal-links"><a href="#privacy">隐私政策</a><span>·</span><a href="#terms">用户协议</a><span>·</span><button type="button" class="link-button" data-auth-platform>接入说明</button></p></div>`;
    const current=document.querySelector('.auth-form-wrap');if(current)current.innerHTML=form;
    else document.querySelector('#app').innerHTML=`<main class="auth"><section class="auth-story"><a href="#login" class="brand">${brandMotion('greeting','',{once:true})}<span><strong>珞珈信使</strong></span></a><h1 class="sr-only">珞珈信使</h1><div class="auth-scene" data-orbit><div class="auth-orbit" aria-hidden="true"><span class="orbit-dot"></span></div><div class="auth-letter" aria-hidden="true"><i></i><i></i><i></i></div>${companion('welcome','auth-companion')}</div></section><section class="auth-form-wrap">${form}</section></main>`;
    moveSelection(document.querySelector('.auth-tabs'),'a.selected');
  }
  async function submit(form,fd){
    const mode=form.dataset.authMode;
    if(mode==='register'&&form.dataset.signupCurrent!=='3'){form.inert=false;form.querySelector(`[data-signup-next="${form.dataset.signupCurrent}"]`)?.click();return;}
    const payload=mode==='register'?Object.fromEntries(['display_name','username','campus_role','password','confirm_password'].map(name=>[name,form.querySelector(`[name="${name}"]`).value])):Object.fromEntries(fd),otp=mode!=='login'||loginMethod==='code';
    if(mode!=='login'&&payload.password!==payload.confirm_password)throw Error('两次输入的密码不一致');
    delete payload.confirm_password;
    if(otp){
      const group=form.querySelector('[data-verification]');
      if(mode==='recover')payload.username=verification.destination(group);
      try{payload.verification_token=await verification.prove(group);}
      catch(error){if(mode==='register')signupStep(form,1);throw error;}
    }
    if(mode==='register'){payload.accepted_terms=form.querySelector('[name=accepted_terms]').checked;payload.invite=state.invite||'';}
    if(mode==='login'&&otp)delete payload.username;
    let result;
    try{result=await api('/auth/'+(mode==='login'&&otp?'verified-login':mode),{method:'POST',json:payload});}
    catch(error){
      if(mode==='register')signupStep(form,error.status===409||error.detail?.code==='alias_proof_required'?2:error.status===400?1:3);
      else if(error.status===401)showInputError(form.querySelector('[name=password]'),'账号或密码不正确');
      throw error;
    }
    const session=result.session||await api('/session');
    await successTransition(form);
    const returnHash=state.loginReturn?.owner===session.user.id?state.loginReturn.hash:location.hash;
    const canReturn=/^#(?:dashboard|notices|notice|tasks|calendar|chat|sources|memory|settings|campus|insights|intake|new)(?:\/[A-Za-z0-9_-]+)*$/.test(returnHash);
    state.session=session;state.loginReturn=null;state.invite='';
    toast.clear();
    try{sessionStorage.removeItem('campus.registration.invite');}catch{}
    history.replaceState(null,'',canReturn?returnHash:'#dashboard');
    await route();
  }
  document.addEventListener('click',async event=>{
    const back=event.target.closest('[data-signup-back]');if(back)signupStep(back.closest('form'),Number(back.dataset.signupBack));
    const next=event.target.closest('[data-signup-next]');
    if(next&&!next.disabled){const form=next.closest('form'),step=Number(next.dataset.signupNext),stage=form.querySelector(`[data-signup-step="${step}"]`);if([...stage.querySelectorAll('input')].some(input=>!input.reportValidity()))return;next.disabled=true;try{if(step===1)await verification.prove(form.querySelector('[data-verification]'));signupStep(form,step+1);}catch(error){toast(error.message,true);}finally{next.disabled=false;}}
    const method=event.target.closest('[data-login-method]');if(method){loginMethod=method.dataset.loginMethod;render();}
    const show=event.target.closest('[data-auth-show]');if(show){const input=show.closest('form').querySelector('[name=password]'),visible=input.type==='password';input.type=visible?'text':'password';show.setAttribute('aria-label',visible?'隐藏密码':'显示密码');show.setAttribute('aria-pressed',String(visible));}
    if(event.target.closest('[data-auth-platform]'))showDialog('校园身份与平台接入','<div class="stack"><p>手机号或邮箱经过验证码验证后可用于登录和账号安全验证。学号和工号只作为你填写的账号名，学校统一认证尚未接入。</p><p>微信 / QQ 登录需要单独申请平台应用与权限。现有的群通知接入和公众号内容导入不等同于微信 / QQ 登录。</p></div>');
  });
  return {render,submit};
}
