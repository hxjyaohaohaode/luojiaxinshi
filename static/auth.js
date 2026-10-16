import {brandMotion} from './motion.js';
export function createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,download,route,moveSelection}) {
  function render(){
    const mode=state.invite?'register':location.hash==='#register'?'register':location.hash==='#recover'?'recover':'login',signup=mode==='register',recover=mode==='recover';
    const username=document.querySelector('#auth-form [name=username]')?.value||'';
    const oldNav=document.querySelector('.auth-tabs');
    const form=`<div class="auth-form"><div class="auth-mobile-brand"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="44" height="44">珞珈 · 校园助手</div>${!recover&&!state.invite?`<nav class="auth-tabs" aria-label="账号入口"><a href="#login" class="${signup?'':'selected'}" ${signup?'':'aria-current="page"'}>登录</a><a href="#register" class="${signup?'selected':''}" ${signup?'aria-current="page"':''}>创建账号</a></nav>`:''}<h2>${signup?'创建你的校园空间':recover?'找回账号':'欢迎回来'}</h2><p>${signup?'先认识一下。选填信息以后再补。':recover?'用注册时保存的恢复码重设密码。':'上次的事情，我们接着来。'}</p><form id="auth-form" data-auth-mode="${mode}" class="stack">
    ${signup?`<div class="auth-stage stack" data-auth-step="account"><div class="form-grid">${field('怎么称呼你','display_name','','text','required maxlength="40" autocomplete="nickname" placeholder="不用真实姓名也可以"')}<label class="field">校园角色<select name="campus_role" aria-label="校园角色"><option value="student">学生</option><option value="teacher">教师</option><option value="staff">教职工</option><option value="other">其他使用者</option></select></label></div><label class="field">用什么作为账号名<select name="account_kind" aria-label="账号类型"><option value="username">自定义账号</option><option value="student_id">学号</option><option value="employee_id">工号</option><option value="phone">手机号</option></select></label>`:''}
    ${field(signup?'账号名':'账号名 / 学号 / 工号 / 手机号','username',username,'text','required minlength="3" maxlength="40" pattern="[a-zA-Z0-9_.@+\\-]+" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="填写注册时使用的账号"')}
    ${signup?'<p class="field-note" id="account-kind-hint">3—40 位字母、数字或 _ . @ + -。这是独立的个人账号。</p><button type="button" class="button primary" data-auth-next>下一步 · 设置密码</button><span class="auth-step-note">1 / 2</span></div><div class="auth-stage stack" data-auth-step="password" hidden><button type="button" class="link-button auth-back" data-auth-back>← 返回账号信息</button>':''}
    ${recover?field('一次性账号恢复码','recovery_code','','text','required minlength="20" maxlength="100" autocomplete="off" spellcheck="false" placeholder="注册时保存的恢复码"'):''}
    <div class="password-field">${field(signup||recover?'设置密码 · 至少 12 个字符':'密码','password','','password',`required ${signup||recover?'minlength="12"':''} maxlength="128" autocomplete="${signup||recover?'new-password':'current-password'}"`)}<button type="button" data-auth-show aria-label="显示密码" aria-pressed="false">显示</button></div>
    ${signup||recover?field('再输入一次密码','confirm_password','','password','required minlength="12" maxlength="128" autocomplete="new-password"'):''}
    ${signup?'<label class="check auth-agreement"><input type="checkbox" name="accepted_terms" required><span>我已阅读<a href="#" data-auth-privacy>账号与数据说明</a>，同意按说明保存本人主动提交的资料。</span></label>':''}
    <button class="button primary auth-submit" type="submit">${signup?'创建账号':recover?'重设密码并登录':'登录我的空间'} ${icon('arrow')}</button>${signup?'<span class="auth-step-note">2 / 2</span></div>':''}
    </form><div class="auth-links">${signup?'<a href="#login">已有账号？去登录</a>':recover?'<a href="#login">返回登录</a>':'<a href="#recover">忘记密码</a><a href="#register">第一次来？创建账号</a>'}</div><button type="button" class="link-button auth-connection" data-auth-platform>学号、手机号与微信 / QQ 如何使用？</button>${state.invite?'<p class="footnote">正在使用一次性成员邀请。</p>':''}</div>`;
    const current=document.querySelector('.auth-form-wrap');
    if(current){current.innerHTML=form;const next=document.querySelector('.auth-tabs');if(oldNav&&next){next.replaceWith(oldNav);oldNav.querySelectorAll('a').forEach(a=>{const active=a.getAttribute('href')==='#'+mode;a.classList.toggle('selected',active);active?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current');});}}
    else document.querySelector('#app').innerHTML=`<main class="auth"><section class="auth-story"><a href="#login" class="brand">${brandMotion('greeting','',{once:true})}<span><strong>珞珈 · 校园助手</strong><small>让校园生活，从容一点</small></span></a><div class="auth-intro"><h1>通知有点多，<br>下一步可以很清楚。</h1><p>带上原文，理清要求。把时间留给热爱。</p></div><div class="auth-scene">${companion('welcome','auth-companion')}</div><div class="auth-foot"><span>材料自己掌握</span><span>重要事项亲自确认</span></div></section><section class="auth-form-wrap">${form}</section></main>`;
    moveSelection(document.querySelector('.auth-tabs'),'a.selected');
  }
  function step(name){document.querySelectorAll('[data-auth-step]').forEach(node=>node.hidden=node.dataset.authStep!==name);const field=document.querySelector(`[data-auth-step="${name}"] input`);field?.focus();}
  async function submit(form,fd){
    const payload=Object.fromEntries(fd),mode=form.dataset.authMode;
    if(mode!=='login'&&payload.password!==payload.confirm_password)throw new Error('两次密码不一致，再检查一下就好。');
    delete payload.confirm_password;
    if(mode==='register'){payload.accepted_terms=payload.accepted_terms==='on';payload.invite=state.invite||'';}
    const result=await api('/auth/'+({login:'login',register:'register',recover:'recover'}[mode]),{method:'POST',json:payload});
    state.invite='';state.session=await api('/session');history.replaceState(null,'','#chat');await route();
    if(result.recovery_code){
      showDialog(mode==='register'?'空间准备好了，收好这把备用钥匙':'密码已更新，请保存新的恢复码',`<div class="recovery-note">${companion('reading','recovery-companion')}<div><p>这串恢复码只显示这一次。忘记密码时，用它找回账号；请保存在你自己的安全位置。</p><p class="small muted">旧恢复码已失效。恢复码相当于账号钥匙，不要分享给别人。</p></div></div><code class="recovery-code">${esc(result.recovery_code)}</code><div class="row wrap"><button type="button" class="button primary" data-save-recovery>下载恢复信息</button><button type="button" class="button" data-copy-recovery>复制恢复码</button></div><div class="form-footer"><button class="button" type="button" data-action="close-dialog">已收好，开始使用</button></div>`);
      const code=result.recovery_code,username=state.session.user.username;
      document.querySelector('[data-save-recovery]').onclick=()=>download(new Blob([`珞珈信使 · 私人账号恢复信息\n账号：${username}\n服务地址：${location.origin}\n恢复码：${code}\n\n请妥善保管，不要分享。使用一次后会生成新的恢复码。\n`],{type:'text/plain;charset=utf-8'}),'校园助手-账号恢复信息.txt');
      document.querySelector('[data-copy-recovery]').onclick=async()=>{try{await navigator.clipboard.writeText(code);toast('恢复码已复制，请保存在自己的安全位置。');}catch{toast('复制未获浏览器允许，请选中恢复码手动复制。',true);}};
    }
  }
  document.addEventListener('change',e=>{if(e.target.name==='account_kind'){const kind=e.target.value,input=document.querySelector('#auth-form [name=username]'),hint=document.querySelector('#account-kind-hint');input.inputMode=kind==='phone'?'tel':kind==='student_id'||kind==='employee_id'?'numeric':'text';hint.textContent=kind==='phone'?'手机号作为独立账号名，目前无需短信验证。':kind==='student_id'||kind==='employee_id'?'使用本人学号或工号作为账号名；不等同于学校统一认证。':'3—40 位字母、数字或 _ . @ + -。这是独立的个人账号。';}});
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-auth-next]')){const controls=[...document.querySelectorAll('[data-auth-step="account"] input,[data-auth-step="account"] select')],invalid=controls.find(el=>!el.checkValidity());if(invalid)invalid.reportValidity();else step('password');}
    if(e.target.closest('[data-auth-back]'))step('account');

    if(e.target.closest('[data-auth-show]')){const b=e.target.closest('[data-auth-show]'),input=b.parentElement.querySelector('input');const show=input.type==='password';input.type=show?'text':'password';b.textContent=show?'隐藏':'显示';b.setAttribute('aria-label',show?'隐藏密码':'显示密码');b.setAttribute('aria-pressed',String(show));}
    if(e.target.closest('[data-auth-privacy]')){e.preventDefault();showDialog('账号与数据说明','<div class="stack"><p>你主动提交的身份条件、对话、通知和附件，保存在当前部署的服务端。每个账号只能访问自己的个人材料。</p><p>自填学号、工号、手机号或微信、QQ 号不代表经过学校或平台验证。请为本产品单独设置密码。</p><p>调用 AI 前，需要另行确认向已配置的模型服务发送本会话材料、历史消息与必要个人条件。联系方式与登录密码不加入模型上下文。</p><p>可导出个人数据并删除通知或对话；备份按保留期限清理。转为通知时会创建一份你选定材料的独立副本，删除对话不会同时删除已建立的通知。</p></div>');}
    if(e.target.closest('[data-auth-platform]'))showDialog('校园身份与平台账号','<div class="stack"><h3>学号、工号、手机号</h3><p>可直接作为本产品账号名，使用自己设置的密码登录。手机号短信验证和校内统一认证需要相应服务授权，目前不会冒充已验证身份。</p><h3>微信与 QQ</h3><p>普通微信和 QQ 联系号可在个人资料中登记。网页登录、微信小程序登录、QQ 机器人消息接入是不同的应用能力，分别需要已审核应用和平台凭证。</p><p>目前可从任意渠道复制通知、保存截图和附件，再交给助手。来源管理会记录公众号、群、官网的用途与手工接入状态。</p></div>');
  });
  return {render,submit};
}
