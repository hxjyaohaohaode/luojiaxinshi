export function createAccountSecurity({state,esc,field,api,verification,showDialog,toast}){
  function open(){
    const user=state.session.user,contacts=user.verified_contacts||[];
    showDialog('账号安全',`<div class="stack"><p>登录账号：${esc(user.username)}</p><section class="stack"><h3>手机号与邮箱</h3>
    ${contacts.length?contacts.map(c=>`<p>${c.channel==='sms'?'手机':'邮箱'}：${esc(c.value)} <span class="pill">已验证</span></p>`).join(''):'<p class="small muted">此账号尚未验证联系方式。请先绑定，以便验证码登录和找回密码。</p>'}
    <button class="button" type="button" data-contact-bind>绑定或更换联系方式</button></section>
    ${contacts.length?`<form id="password-form" class="stack" data-no-history><h3>修改密码</h3>${field('原密码','old_password','','password','required autocomplete="current-password"')}${field('新密码 · 至少 12 个字符','new_password','','password','required minlength="12" maxlength="256" autocomplete="new-password"')}${verification.markup('password','password',{contacts})}<div class="form-footer"><button class="button primary" type="submit">更新密码并退出其他设备</button></div></form>`:''}
    <section class="account-danger"><h3>注销账号</h3><p class="small muted">账号和你保存的全部资料都会删除，无法恢复。</p><button type="button" class="button small danger" data-action="delete-account">注销账号…</button></section></div>`);
  }
  function bindDialog(){const contacts=state.session.user.verified_contacts||[];showDialog('验证联系方式',`<form id="contact-form" class="stack" data-no-history>
    ${contacts.length?verification.markup('old-contact','contact_authorize',{contacts,title:'先验证当前联系方式'}):field('当前密码','old_password','','password','required autocomplete="current-password"')}
    ${verification.markup('new-contact','contact_bind',{title:'验证新手机号或邮箱'})}<p class="small muted">绑定后可用该联系方式登录；同类联系方式将被替换，其他设备需要重新登录。</p><div class="form-footer"><button type="submit" class="button primary">确认绑定</button></div></form>`);}
  async function submit(form,fd){
    const uid=state.session?.user.id,payload=Object.fromEntries(fd);
    let result;
    if(form.id==='contact-form'){
      const old=form.querySelector('[data-verification="old-contact"]');if(old)payload.authorization_token=await verification.prove(old);
      payload.verification_token=await verification.prove(form.querySelector('[data-verification="new-contact"]'));
      if(state.session?.user.id!==uid)return;
      await api('/account/contacts',{method:'POST',json:payload});
    }else{
      payload.verification_token=await verification.prove(form.querySelector('[data-verification]'));
      if(state.session?.user.id!==uid)return;
      result=await api('/auth/password',{method:'POST',json:payload});
    }
    const session=result?.session||await api('/session');if(state.session?.user.id!==uid)return;state.session=session;open();toast('账号安全信息已更新，其他设备需要重新登录');
  }
  document.addEventListener('click',event=>{if(event.target.closest('[data-contact-bind]'))bindDialog();});
  return {open,submit};
}
