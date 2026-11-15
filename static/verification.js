export function createVerificationUI({state,api,esc,toast}){
  const records=new WeakMap();
  const cooldowns=new WeakMap();
  const sending=new WeakSet();
  let nextStatusId=0;
  function markup(id,purpose,{contacts=[],title='身份验证'}={}){
    const statusId='verification-status-'+(++nextStatusId);
    return `<fieldset class="verification stack" data-verification="${id}" data-purpose="${purpose}"><legend>${esc(title)}</legend>
    ${contacts.length?`<label class="field">已验证的联系方式<select data-otp-contact>${contacts.map(c=>`<option value="${esc(c.value)}" data-channel="${c.channel}">${c.channel==='sms'?'手机':'邮箱'} · ${esc(c.value)}</option>`).join('')}</select></label>`:
    `<label class="field">手机号或邮箱<input data-otp-destination required maxlength="254" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="输入手机号或邮箱地址"></label>`}
    <div class="verification-code-row"><label class="field">验证码<span class="verification-code-input" data-otp-shell data-state="idle"><input data-otp-code type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" minlength="6" maxlength="6" aria-describedby="${statusId}" required><span class="verification-code-slots" aria-hidden="true">${'<span data-otp-slot></span>'.repeat(6)}</span></span></label><button type="button" class="button" data-otp-send>发送验证码</button></div><p id="${statusId}" class="small muted" data-otp-status role="status">验证码 5 分钟内有效，支持粘贴完整的 6 位数字。${purpose==='register'?'验证通过后，请保留当前页面并在 30 分钟内完成注册。':''}</p></fieldset>`;
  }
  function values(group){const saved=group.querySelector('[data-otp-contact]');if(saved)return {channel:saved.selectedOptions[0].dataset.channel,destination:saved.value};let destination=group.querySelector('[data-otp-destination]').value.trim();const channel=destination.includes('@')?'email':'sms';destination=channel==='email'?destination.toLowerCase():destination.replace(/[\s-]/g,'').replace(/^\+86/,'');return {channel,destination};}
  const identity=group=>JSON.stringify({...values(group),username:['login','recover'].includes(group.dataset.purpose)?group.closest('form')?.querySelector('[name=username]')?.value.trim()||'':'',purpose:group.dataset.purpose});
  function note(group,text){const el=group.querySelector('[data-otp-status]');if(el)el.textContent=text;}
  // One real input keeps selection, password-manager and SMS autofill semantics.
  // The six slots only mirror its value; filling them never submits a request.
  const cleanCode=value=>String(value??'').normalize('NFKC').replace(/[\s-]/g,'').slice(0,6);
  function paintCode(group,phase){
    const input=group.querySelector('[data-otp-code]'),shell=group.querySelector('[data-otp-shell]');
    if(!input||!shell)return;
    if(phase)shell.dataset.state=phase;
    const active=Math.min(input.selectionStart??input.value.length,5);
    shell.querySelectorAll('[data-otp-slot]').forEach((slot,index)=>{
      slot.textContent=input.value[index]||'';
      slot.dataset.filled=String(index<input.value.length);
      slot.dataset.active=String(index===active);
    });
  }
  function codeFeedback(group,phase,message){
    const input=group.querySelector('[data-otp-code]');
    if(input){
      input.readOnly=phase==='verified';
      if(phase==='error')input.setAttribute?.('aria-invalid','true');
      else input.removeAttribute?.('aria-invalid');
      if(phase==='checking')input.setAttribute?.('aria-busy','true');
      else input.removeAttribute?.('aria-busy');
    }
    paintCode(group,phase);if(message)note(group,message);
  }
  function editCode(input){
    const group=input.closest('[data-verification]');if(!group||input.readOnly||input.disabled)return;
    const raw=input.value,selection=input.selectionStart??raw.length,clean=cleanCode(raw);
    if(clean!==raw){input.value=clean;const next=cleanCode(raw.slice(0,selection)).length;input.setSelectionRange(next,next);}
    const shell=group.querySelector('[data-otp-shell]'),wasError=shell?.dataset.state==='error';
    codeFeedback(group,/^[0-9]{6}$/.test(input.value)?'ready':'idle',wasError?'验证码已修改，请重新核对并提交。':null);
  }
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
    codeFeedback(group,'idle','验证信息已修改，请重新发送验证码。');
  }
  async function prove(group){
    const record=records.get(group);
    if(!record||record.identity!==identity(group)||record.owner!==state.session?.user.id){records.delete(group);throw Error('请先向当前手机号或邮箱发送验证码；修改联系方式后需重新发送');}
    if(record.expires<=Date.now()){const message=record.proof?'联系方式验证已过期，请重新发送验证码':'验证码已过期，请重新发送';codeFeedback(group,'error',message);throw Error(message);}
    if(record.proof)return record.proof;
    const input=group.querySelector('[data-otp-code]'),code=input.value.normalize('NFKC').trim();
    if(!/^[0-9]{6}$/.test(code)){codeFeedback(group,'error','请输入 6 位验证码');throw Error('请输入 6 位验证码');}
    codeFeedback(group,'checking','正在核对验证码…');
    try{
      const result=await api('/auth/verify',{method:'POST',json:{challenge_id:record.challenge,code}});
      if(!group.isConnected||record!==records.get(group)||record.identity!==identity(group)||record.owner!==state.session?.user.id||input.value.normalize('NFKC').trim()!==code){
        if(record===records.get(group))records.delete(group);
        throw Error('验证信息已改变，请重新操作');
      }
      record.proof=result.verification_token;record.expires=Date.now()+result.expires_in*1000;
      codeFeedback(group,'verified',group.dataset.purpose==='register'?'联系方式已验证，请保留当前页面并在 30 分钟内完成注册。':'已验证，提交后生效');return record.proof;
    }catch(error){
      if(group.isConnected&&record===records.get(group)&&record.identity===identity(group)&&record.owner===state.session?.user.id)codeFeedback(group,'error',error.message);
      throw error;
    }
  }
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-otp-send]');if(!button||button.disabled)return;
    const group=button.closest('[data-verification]'),form=group.closest('form'),snapshot=identity(group),owner=state.session?.user.id;
    const destination=group.querySelector('[data-otp-destination]');if(destination&&!destination.reportValidity())return;
    if(group.dataset.purpose==='register'&&!(form?.querySelector('[name=verification_consent]')||form?.querySelector('[name=accepted_terms]'))?.checked){toast('请先阅读并同意隐私政策',true);return;}
    if(records.has(group))group.querySelector('[data-otp-code]').value='';
    // Retire the previous proof before releasing readonly for a resend. New
    // digits may only be proved against the replacement server challenge.
    records.delete(group);
    button.disabled=true;sending.add(button);codeFeedback(group,'idle','正在提交验证码发送请求…');
    try{
      const result=await api('/auth/challenges',{method:'POST',json:{...values(group),purpose:group.dataset.purpose,username:form?.querySelector('[name=username]')?.value||'',invite:state.invite||''}});
      if(!group.isConnected)return;
      if(snapshot!==identity(group)||owner!==state.session?.user.id){
        records.delete(group);button.disabled=false;button.textContent='发送验证码';
        note(group,'验证信息已修改，请向当前联系方式重新发送验证码');return;
      }
      records.set(group,{identity:snapshot,owner,challenge:result.challenge_id,expires:Date.now()+result.expires_in*1000});
      codeFeedback(group,'idle',result.message);
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
    if(event.target.matches('[data-otp-code]'))editCode(event.target);
    else invalidate(group);
  });
  document.addEventListener('paste',event=>{
    const input=event.target;if(!input.matches?.('[data-otp-code]')||input.readOnly||input.disabled||!event.clipboardData)return;
    const pasted=cleanCode(event.clipboardData.getData('text'));
    // Normalize the entire clipboard before native maxlength can truncate spaces
    // or full-width digits. Short pastes retain native insertion/selection behavior.
    if(!/^[0-9]{6}$/.test(pasted))return;
    event.preventDefault();input.value=pasted;input.setSelectionRange(6,6);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  for(const type of ['focusin','keyup','select'])document.addEventListener(type,event=>{
    if(event.target.matches?.('[data-otp-code]'))paintCode(event.target.closest('[data-verification]'));
  });
  document.addEventListener('click',event=>{
    const input=event.target;if(!input.matches?.('[data-otp-code]')||input.readOnly||input.disabled)return;
    const group=input.closest('[data-verification]'),shell=group.querySelector('[data-otp-shell]');
    if(event.detail>0&&shell){
      const slots=[...shell.querySelectorAll('[data-otp-slot]')],index=slots.findIndex(slot=>event.clientX<slot.getBoundingClientRect().right);
      const start=Math.min(index<0?5:index,input.value.length);input.setSelectionRange(start,Math.min(start+1,input.value.length));
    }
    paintCode(group);
  });
  document.addEventListener('change',event=>{
    const group=event.target.closest('[data-verification]');
    if(group&&!event.target.matches('[data-otp-code]'))invalidate(group);
  });
  return {markup,prove,destination:group=>values(group).destination};
}
