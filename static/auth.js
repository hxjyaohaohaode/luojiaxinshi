import {brandMotion} from './motion.js';
// GetUrUI's eye toggle, adapted to native inputs and the existing form flow.
const eye=()=>`<svg class="password-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path class="password-eye-slash" d="m3 3 18 18"/></svg>`;
async function successTransition(form){
  const button=form.querySelector('.auth-submit');if(!button||!form.isConnected)return;
  button.classList.remove('request-pending');button.classList.add('is-success');
  if(form.previousElementSibling?.classList.contains('form-request-status'))form.previousElementSibling.textContent='登录成功';
  button.setAttribute('aria-label','登录成功');button.removeAttribute('aria-busy');
  button.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';
  // A real successful session drives the check; failed authentication never does.
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches)await new Promise(resolve=>setTimeout(resolve,420));
}
export function createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,download,route,moveSelection}) {
  function render(){
    const canRegister=state.registrationMode==='public'||!!state.invite;
    const gated=location.hash==='#register'&&!canRegister;
    const policyNote=state.registrationMode==='invite'?'现在还在小范围试用，用管理员发给你的邀请链接就能注册。':'暂时没读到注册方式，刷新一下试试；已有账号的话可以直接登录。';
    const mode=state.invite?'register':location.hash==='#register'&&canRegister?'register':location.hash==='#recover'?'recover':'login',signup=mode==='register',recover=mode==='recover';
    const username=document.querySelector('#auth-form [name=username]')?.value||'';
    const oldNav=document.querySelector('.auth-tabs');
    const form=`<div class="auth-form" data-reveal><div class="auth-mobile-brand"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="44" height="44">珞珈信使</div>${!recover&&!state.invite&&canRegister?`<nav class="auth-tabs" aria-label="账号入口"><a href="#login" class="${signup?'':'selected'}" ${signup?'':'aria-current="page"'}>登录</a><a href="#register" class="${signup?'selected':''}" ${signup?'aria-current="page"':''}>创建账号</a></nav>`:''}<h2>${signup?'创建你的校园空间':recover?'找回账号':'欢迎回来'}</h2>${recover?'<p>输入注册时保存的恢复码就行。</p>':''}${gated?`<div class="alert info">${esc(policyNote)}</div>`:''}<form id="auth-form" data-auth-mode="${mode}" class="stack">
    ${signup?`<div class="auth-stage stack" data-auth-step="account"><div class="form-grid">${field('怎么称呼你','display_name','','text','required maxlength="40" autocomplete="nickname" placeholder="不用真实姓名也可以"')}<label class="field">校园角色<select name="campus_role" aria-label="校园角色"><option value="student">学生</option><option value="teacher">教师</option><option value="staff">教职工</option><option value="other">其他使用者</option></select></label></div><label class="field">用什么当账号名<select name="account_kind" aria-label="账号类型"><option value="username">自定义账号</option><option value="student_id">学号</option><option value="employee_id">工号</option><option value="phone">手机号</option></select></label>`:''}
    ${field(signup?'账号名':'账号名 / 学号 / 工号 / 手机号','username',username,'text','required minlength="3" maxlength="40" pattern="[a-zA-Z0-9_.@+\\-]+" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="填写注册时使用的账号"')}
    ${signup?'<p class="field-note" id="account-kind-hint">3—40 位字母、数字或 _ . @ + -，是你在这里专属的账号。</p><button type="button" class="button primary" data-auth-next>下一步 · 设置密码</button><span class="auth-step-note">1 / 2</span></div><div class="auth-stage stack" data-auth-step="password" hidden><button type="button" class="link-button auth-back" data-auth-back>← 返回账号信息</button>':''}
    ${recover?field('账号恢复码（只能用一次）','recovery_code','','text','required minlength="20" maxlength="100" autocomplete="off" spellcheck="false" placeholder="注册时保存的恢复码"'):''}
    <div class="password-field">${field(signup||recover?'设置密码 · 至少 12 个字符':'密码','password','','password',`required ${signup||recover?'minlength="12"':''} maxlength="128" autocomplete="${signup||recover?'new-password':'current-password'}"`)}<button type="button" data-auth-show aria-label="显示密码" aria-pressed="false">${eye()}</button></div>
    ${signup||recover?field('再输入一次密码','confirm_password','','password','required minlength="12" maxlength="128" autocomplete="new-password"'):''}
    ${signup?'<label class="check auth-agreement"><input type="checkbox" name="accepted_terms" required><span>我已阅读并同意<a href="#privacy" target="_blank" rel="noopener">《隐私政策》</a>和<a href="#terms" target="_blank" rel="noopener">《用户协议》</a>，愿意按说明保存我主动提交的资料。</span></label>':''}
    <button class="button primary auth-submit" type="submit">${signup?'创建账号':recover?'重设密码并登录':'登录我的空间'} ${icon('arrow')}</button>${signup?'<span class="auth-step-note">2 / 2</span></div>':''}
    </form><div class="auth-links">${signup?'<a href="#login">已有账号？去登录</a>':recover?'<a href="#login">返回登录</a>':`<a href="#recover">忘记密码</a>${canRegister?'<a href="#register">第一次来？创建账号</a>':''}`}</div>${!canRegister&&!gated?`<p class="footnote">${esc(policyNote)}</p>`:''}<button type="button" class="link-button auth-connection" data-auth-platform>学号、手机号与微信 / QQ 如何使用？</button><p class="auth-legal-links"><a href="#privacy">隐私政策</a><span aria-hidden="true">·</span><a href="#terms">用户协议</a><span aria-hidden="true">·</span><span>非武汉大学官方系统</span></p>${state.invite?'<p class="footnote">你正在用邀请链接注册。</p>':''}</div>`;
    const current=document.querySelector('.auth-form-wrap');
    if(current){current.innerHTML=form;const next=document.querySelector('.auth-tabs');if(oldNav&&next){next.replaceWith(oldNav);oldNav.querySelectorAll('a').forEach(a=>{const active=a.getAttribute('href')==='#'+mode;a.classList.toggle('selected',active);active?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current');});}}
    else document.querySelector('#app').innerHTML=`<main class="auth"><section class="auth-story"><a href="#login" class="brand">${brandMotion('greeting','',{once:true})}<span><strong>珞珈信使</strong></span></a><h1 class="sr-only">珞珈信使</h1><div class="auth-scene" data-orbit><div class="auth-orbit" aria-hidden="true"><span class="orbit-dot"></span></div><div class="auth-letter" aria-hidden="true"><i></i><i></i><i></i></div>${companion('welcome','auth-companion')}</div></section><section class="auth-form-wrap">${form}</section></main>`;
    moveSelection(document.querySelector('.auth-tabs'),'a.selected');
  }
  function step(name){document.querySelectorAll('[data-auth-step]').forEach(node=>node.hidden=node.dataset.authStep!==name);const field=document.querySelector(`[data-auth-step="${name}"] input`);field?.focus();}
  async function submit(form,fd){
    const payload=Object.fromEntries(fd),mode=form.dataset.authMode;
    if(mode!=='login'&&payload.password!==payload.confirm_password)throw new Error('两次密码不一致，再检查一下就好。');
    delete payload.confirm_password;
    if(mode==='register'){payload.accepted_terms=payload.accepted_terms==='on';payload.invite=state.invite||'';}
    const result=await api('/auth/'+({login:'login',register:'register',recover:'recover'}[mode]),{method:'POST',json:payload});
    const session=await api('/session');await successTransition(form);
    state.invite='';state.session=session;history.replaceState(null,'','#dashboard');await route();
    if(result.recovery_code){
      showDialog(mode==='register'?'空间准备好了，收好这把备用钥匙':'密码改好了，记得存好新的恢复码',`<div class="recovery-note">${companion('reading','recovery-companion')}<div><p>这串恢复码只显示这一次。忘了密码就靠它找回账号，存在你自己放心的地方吧。</p><p class="small muted">旧恢复码已经失效了。恢复码就像账号钥匙，别分享给别人。</p></div></div><code class="recovery-code">${esc(result.recovery_code)}</code><div class="row wrap"><button type="button" class="button primary" data-save-recovery>下载恢复信息</button><button type="button" class="button" data-copy-recovery>复制恢复码</button></div><div class="form-footer"><button class="button" type="button" data-action="close-dialog">已收好，开始使用</button></div>`);
      const code=result.recovery_code,username=state.session.user.username;
      document.querySelector('[data-save-recovery]').onclick=()=>download(new Blob([`珞珈信使 · 私人账号恢复信息\n账号：${username}\n服务地址：${location.origin}\n恢复码：${code}\n\n请妥善保管，不要分享。使用一次后会生成新的恢复码。\n`],{type:'text/plain;charset=utf-8'}),'校园助手-账号恢复信息.txt');
      document.querySelector('[data-copy-recovery]').onclick=async()=>{try{await navigator.clipboard.writeText(code);toast('恢复码复制好了，存到自己放心的地方吧。');}catch{toast('浏览器没让复制，选中恢复码手动复制一下吧。',true);}};
    }
  }
  document.addEventListener('change',e=>{if(e.target.name==='account_kind'){const kind=e.target.value,input=document.querySelector('#auth-form [name=username]'),hint=document.querySelector('#account-kind-hint');input.inputMode=kind==='phone'?'tel':kind==='student_id'||kind==='employee_id'?'numeric':'text';hint.textContent=kind==='phone'?'手机号只当作账号名，暂时不用短信验证。':kind==='student_id'||kind==='employee_id'?'用你的学号或工号当账号名就行，这和学校统一认证不是一回事。':'3—40 位字母、数字或 _ . @ + -，是你在这里专属的账号。';}});
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-auth-next]')){const controls=[...document.querySelectorAll('[data-auth-step="account"] input,[data-auth-step="account"] select')],invalid=controls.find(el=>!el.checkValidity());if(invalid)invalid.reportValidity();else step('password');}
    if(e.target.closest('[data-auth-back]'))step('account');

    if(e.target.closest('[data-auth-show]')){const b=e.target.closest('[data-auth-show]'),input=b.parentElement.querySelector('input');const show=input.type==='password';input.type=show?'text':'password';b.setAttribute('aria-label',show?'隐藏密码':'显示密码');b.setAttribute('aria-pressed',String(show));if(!matchMedia('(prefers-reduced-motion: reduce)').matches)b.querySelector('svg')?.animate([{transform:'scaleY(1)'},{transform:'scaleY(.12)'},{transform:'scaleY(1)'}],{duration:220});}
    if(e.target.closest('[data-auth-platform]'))showDialog('校园身份与平台账号','<div class="stack"><h3>学号、工号、手机号</h3><p>可以直接当账号名，用自己设的密码登录。短信验证和学校统一认证还没开通，所以不会显示成“已认证”。</p><h3>微信与 QQ</h3><p>微信号和 QQ 号可以在个人资料里登记。微信登录、小程序登录和 QQ 机器人收消息，都需要管理员另外开通。</p><p>现在你可以从任何地方复制通知、存截图和附件，再交给小信使。在“通知来源”里可以记下常看的公众号、群和官网。</p></div>');
  });
  return {render,submit};
}
