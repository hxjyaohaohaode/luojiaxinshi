export function createVerificationUI({state,api,esc,toast}){
  const records=new WeakMap();
  const cooldowns=new WeakMap();
  const sending=new WeakSet();
  function markup(id,purpose,{contacts=[],title='身份验证'}={}){
    return `<fieldset class="verification stack" data-verification="${id}" data-purpose="${purpose}"><legend>${esc(title)}</legend>
    ${contacts.length?`<label class="field">已验证的联系方式<select data-otp-contact>${contacts.map(c=>`<option value="${esc(c.value)}" data-channel="${c.channel}">${c.channel==='sms'?'手机':'邮箱'} · ${esc(c.value)}</option>`).join('')}</select></label>`:
    `<label class="field">手机号或邮箱<input data-otp-destination required maxlength="254" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="输入手机号或邮箱地址"></label>`}
    <div class="verification-code-row"><label class="field">验证码<input data-otp-code inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" minlength="6" maxlength="6" required></label><button type="button" class="button" data-otp-send>发送验证码</button></div><p class="small muted" data-otp-status role="status">验证码 5 分钟内有效。</p></fieldset>`;
  }
  function values(group){const saved=group.querySelector('[data-otp-contact]');if(saved)return {channel:saved.selectedOptions[0].dataset.channel,destination:saved.value};let destination=group.querySelector('[data-otp-destination]').value.trim();const channel=destination.includes('@')?'email':'sms';destination=channel==='email'?destination.toLowerCase():destination.replace(/[\s-]/g,'').replace(/^\+86/,'');return {channel,destination};}
  const identity=group=>JSON.stringify({...values(group),username:['login','recover'].includes(group.dataset.purpose)?group.closest('form')?.querySelector('[name=username]')?.value.trim()||'':'',purpose:group.dataset.purpose});
  function note(group,text){const el=group.querySelector('[data-otp-status]');if(el)el.textContent=text;}
  function stopCountdown(group){
    clearTimeout(cooldowns.get(group));
    cooldowns.delete(group);
  }
  function countdown(group,button,seconds){
    stopCountdown(group);
    const ends=Date.now()+seconds*1000;
    function tick(){
      if(!button.isConnected)return;
      const remaining=Math.max(0,Math.ceil((ends-Date.now())/1000));
      button.textContent=remaining?`${remaining} 秒后重发`:'重新发送';
      button.disabled=remaining>0;
      if(remaining)cooldowns.set(group,setTimeout(tick,1000));
    }
    tick();
  }
  function invalidate(group){
    const record=records.get(group);
    if(!record||record.identity===identity(group))return;
    records.delete(group);stopCountdown(group);
    const button=group.querySelector('[data-otp-send]');
    button.disabled=sending.has(button);button.textContent='发送验证码';
    group.querySelector('[data-otp-code]').value='';
    note(group,'验证信息已修改，请重新发送验证码。');
  }
  async function prove(group){
    const record=records.get(group);
    if(!record||record.identity!==identity(group))throw Error('请先向当前手机号或邮箱发送验证码；修改联系方式后需重新发送');
    if(record.expires<=Date.now())throw Error('验证码已过期，请重新发送');
    if(record.proof)return record.proof;
    const code=group.querySelector('[data-otp-code]').value.normalize('NFKC').trim();
    if(!/^[0-9]{6}$/.test(code))throw Error('请输入 6 位验证码');
    const result=await api('/auth/verify',{method:'POST',json:{challenge_id:record.challenge,code}});
    if(!group.isConnected||record!==records.get(group)||record.identity!==identity(group))throw Error('验证信息已改变，请重新操作');
    record.proof=result.verification_token;record.expires=Date.now()+result.expires_in*1000;note(group,'已验证，提交后生效');return record.proof;
  }
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-otp-send]');if(!button||button.disabled)return;
    const group=button.closest('[data-verification]'),form=group.closest('form'),snapshot=identity(group),owner=state.session?.user.id;
    const destination=group.querySelector('[data-otp-destination]');if(destination&&!destination.reportValidity())return;
    if(group.dataset.purpose==='register'&&!(form?.querySelector('[name=verification_consent]')||form?.querySelector('[name=accepted_terms]'))?.checked){toast('请先阅读并同意隐私政策',true);return;}
    if(records.has(group))group.querySelector('[data-otp-code]').value='';
    button.disabled=true;sending.add(button);note(group,'正在提交验证码发送请求…');
    try{
      const result=await api('/auth/challenges',{method:'POST',json:{...values(group),purpose:group.dataset.purpose,username:form?.querySelector('[name=username]')?.value||'',invite:state.invite||''}});
      if(!group.isConnected)return;
      if(snapshot!==identity(group)||owner!==state.session?.user.id){
        records.delete(group);button.disabled=false;button.textContent='发送验证码';
        note(group,'验证信息已修改，请向当前联系方式重新发送验证码');return;
      }
      records.set(group,{identity:snapshot,challenge:result.challenge_id,expires:Date.now()+result.expires_in*1000});
      note(group,result.message);
      countdown(group,button,result.retry_after);
    }catch(error){
      if(group.isConnected){
        note(group,error.message);
        countdown(group,button,error.retryAfter||0);
      }
    }finally{sending.delete(button);}
  });
  document.addEventListener('input',event=>{
    const group=event.target.closest('[data-verification]');
    if(!group)return;
    if(event.target.matches('[data-otp-code]'))event.target.value=event.target.value.normalize('NFKC').replace(/\s/g,'');
    else invalidate(group);
  });
  document.addEventListener('change',event=>{
    const group=event.target.closest('[data-verification]');
    if(group&&!event.target.matches('[data-otp-code]'))invalidate(group);
  });
  return {markup,prove,destination:group=>values(group).destination};
}
