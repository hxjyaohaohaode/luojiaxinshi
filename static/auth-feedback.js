export function passwordAssessment(password,confirmation=''){
  const length=Array.from(password).length,min=length>=12,max=length>0&&length<=256,match=length>0&&password===confirmation;
  const classes=[/[a-z]/,/[A-Z]/,/[0-9]/,/[^a-zA-Z0-9]/].filter(rule=>rule.test(password)).length;
  const strength=!length?0:!min?1:length>=20&&classes>=3?4:length>=16&&classes>=2?3:2;
  return {min,max,match,strength,label:['未输入','较弱','中等','较强','强'][strength]};
}
const eye='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
const circle='<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8"/><path d="m6 10 3 3 5-6"/></svg>';
export async function successTransition(form){
  const button=form.querySelector('.auth-submit');if(!button||!form.isConnected)return;
  button.classList.remove('request-pending');button.classList.add('is-success');
  if(form.previousElementSibling?.classList.contains('form-request-status'))form.previousElementSibling.textContent='登录成功';
  button.setAttribute('aria-label','登录成功');button.removeAttribute('aria-busy');
  button.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';
  // This feedback follows a successful session response, never a submitted form.
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches)await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
}
export function passwordEditor(field,{creating=false,confirm=false}={}){
  return `<div class="auth-password-control">${field(creating?'设置密码':'密码','password','','password',`required ${creating?'minlength="12"':''} maxlength="256" autocomplete="${creating?'new-password':'current-password'}"`)}<button type="button" class="auth-eye" data-auth-show aria-label="显示密码" aria-pressed="false">${eye}</button></div>${confirm?field('确认密码','confirm_password','','password','required minlength="12" maxlength="256" autocomplete="new-password"'):''}${creating?`<div class="password-strength" data-password-strength><div class="password-strength-bars" aria-hidden="true">${'<i></i>'.repeat(4)}</div><span data-password-strength-label>强度：未输入</span></div><ul class="password-rules">${[['min','至少 12 个字符'],['max','不超过 256 个字符'],['match','两次输入一致']].map(([key,label])=>`<li data-password-rule="${key}">${circle}<span>${label}</span></li>`).join('')}</ul>`:''}`;
}
export function updatePasswordFeedback(form){
  const password=form.querySelector('[name=password]'),confirmation=form.querySelector('[name=confirm_password]');if(!password)return;
  const result=passwordAssessment(password.value,confirmation?.value||'');
  if(confirmation)confirmation.setCustomValidity(confirmation.value&&!result.match?'两次输入的密码不一致':'');
  form.querySelectorAll('[data-password-rule]').forEach(item=>item.dataset.valid=String(result[item.dataset.passwordRule]));
  const strength=form.querySelector('[data-password-strength]');if(strength){strength.dataset.strength=String(result.strength);strength.querySelectorAll('i').forEach((bar,i)=>bar.dataset.filled=String(i<result.strength));strength.querySelector('[data-password-strength-label]').textContent='强度：'+result.label;}
}
function validationText(input){
  if(input.validity.valueMissing)return input.type==='checkbox'?'请先阅读并同意协议':input.matches('[data-otp-code]')?'请输入验证码':input.matches('[data-otp-destination]')?'请输入手机号或邮箱':input.name==='username'?'请输入邮箱或手机号':input.name==='display_name'?'请输入昵称':input.name==='confirm_password'?'请再次输入密码':'请输入密码';
  if(input.validity.tooShort)return input.name==='username'?'账号名至少 3 个字符':'密码至少 12 个字符';
  if(input.validity.patternMismatch)return input.matches('[data-otp-code]')?'请输入 6 位数字验证码':'请使用字母、数字或 _ . @ + -';
  return input.validationMessage||'请检查此项内容';
}
export function showInputError(input,message){
  if(!input)return;input.setAttribute('aria-invalid','true');input.classList.add('auth-input-error');
  const field=input.closest('label');if(!field)return;
  let error=document.getElementById(input.getAttribute('aria-describedby'));if(!error){error=document.createElement('small');error.className='auth-field-error';error.setAttribute('role','alert');error.id='auth-error-'+(input.name||'code')+'-'+Math.random().toString(36).slice(2,7);field.after(error);}
  error.textContent=message;input.setAttribute('aria-describedby',error.id);
}
export function installAuthFeedback(){
  let focusPending=false;
  document.addEventListener('invalid',event=>{const form=event.target.closest?.('#auth-form');if(!form)return;event.preventDefault();showInputError(event.target,validationText(event.target));if(!focusPending){focusPending=true;queueMicrotask(()=>{form.querySelector('[aria-invalid=true]')?.focus();focusPending=false;});}},true);
  document.addEventListener('input',event=>{
    const form=event.target.closest?.('#auth-form');if(!form)return;
    if(['password','confirm_password'].includes(event.target.name))updatePasswordFeedback(form);
    for(const input of form.querySelectorAll('[aria-invalid=true]')){
      if(input.validity.valid){document.getElementById(input.getAttribute('aria-describedby'))?.remove();input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby');input.classList.remove('auth-input-error');}
    }
  });
}
