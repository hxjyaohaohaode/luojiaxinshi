import test from 'node:test';
import assert from 'node:assert/strict';
import {showInputError,installAuthFeedback} from '../static/auth-feedback.js';

// Exercise the real feedback functions. This controlled DOM verifies ownership
// of descriptions and errors; native layout and accessibility are checked in CI.
function fixture(t){
  const before=globalThis.document,nodes=new Map(),listeners=new Map();
  t.after(()=>globalThis.document=before);
  function node(name='',text=''){
    const attrs=new Map();
    const n={name,textContent:text,className:'',removed:false,validity:{valid:true},
      getAttribute:k=>attrs.get(k)??null,setAttribute:(k,v)=>attrs.set(k,String(v)),removeAttribute:k=>attrs.delete(k),
      remove(){this.removed=true;nodes.delete(this.id);},
      closest:s=>s==='label'?label:s==='#auth-form'?form:null};
    n.classList={contains:x=>n.className.split(/\s+/).includes(x),add:x=>{if(!n.className.split(/\s+/).includes(x))n.className+=(n.className?' ':'')+x;},remove:x=>{n.className=n.className.split(/\s+/).filter(y=>y!==x).join(' ');}};
    return n;
  }
  const label={after:n=>nodes.set(n.id,n)},inputs=[];
  const form={querySelectorAll:()=>inputs.filter(n=>n.getAttribute('aria-invalid')==='true'),querySelector:s=>inputs.find(n=>s===`[name=${n.name}]`)||null};
  globalThis.document={getElementById:id=>nodes.get(id)||null,createElement:()=>node(),addEventListener:(type,fn)=>listeners.set(type,fn)};
  const input=(name,descriptions='')=>{const n=node(name);if(descriptions)n.setAttribute('aria-describedby',descriptions);inputs.push(n);return n;};
  const description=(id,text)=>{const n=node('',text);n.id=id;nodes.set(id,n);return n;};
  const edit=n=>listeners.get('input')({target:n});
  const errors=()=>[...nodes.values()].filter(n=>n.classList.contains('auth-field-error'));
  return {input,description,edit,errors};
}

test('field errors preserve the existing OTP delivery status and add their own description',t=>{
  const h=fixture(t),status=h.description('otp-status','验证码 5 分钟内有效'),input=h.input('code','otp-status');
  showInputError(input,'请输入 6 位验证码');
  assert.equal(status.textContent,'验证码 5 分钟内有效');assert.equal(status.removed,false);
  assert.equal(h.errors().length,1);assert.equal(h.errors()[0].textContent,'请输入 6 位验证码');
  assert.deepEqual(input.getAttribute('aria-describedby').split(/\s+/),['otp-status',h.errors()[0].id]);
  assert.equal(input.getAttribute('aria-invalid'),'true');
});

test('repeated validation updates only its own error and preserves multiple help references',t=>{
  const h=fixture(t),hint=h.description('hint','可粘贴完整验证码'),status=h.description('status','发送请求已接受'),input=h.input('code','hint status');
  showInputError(input,'验证码必填');const id=h.errors()[0].id;
  showInputError(input,'验证码不正确');
  assert.equal(h.errors().length,1);assert.equal(h.errors()[0].id,id);assert.equal(h.errors()[0].textContent,'验证码不正确');
  assert.deepEqual(input.getAttribute('aria-describedby').split(/\s+/),['hint','status',id]);
  assert.equal(hint.textContent,'可粘贴完整验证码');assert.equal(status.textContent,'发送请求已接受');
});

test('correcting a field removes only its owned error and keeps help and live status connected',t=>{
  const h=fixture(t),hint=h.description('hint','保留说明'),status=h.description('status','保留发送状态'),input=h.input('code','hint status');
  installAuthFeedback();showInputError(input,'验证码不正确');h.edit(input);
  assert.equal(h.errors().length,0);assert.equal(hint.removed,false);assert.equal(status.removed,false);
  assert.equal(input.getAttribute('aria-describedby'),'hint status');assert.equal(input.getAttribute('aria-invalid'),null);
  assert.equal(input.classList.contains('auth-input-error'),false);
});

test('editing another valid field does not erase a server rejection on the password',t=>{
  const h=fixture(t),account=h.input('username'),password=h.input('password');
  installAuthFeedback();showInputError(password,'账号或密码不正确');h.edit(account);
  assert.equal(password.getAttribute('aria-invalid'),'true');assert.equal(h.errors().length,1);
  assert.equal(h.errors()[0].textContent,'账号或密码不正确');
});

test('clearing native validity never deletes an unrelated description it does not own',t=>{
  const h=fixture(t),status=h.description('status','真实验证码状态'),input=h.input('code','status');
  installAuthFeedback();input.setAttribute('aria-invalid','true');h.edit(input);
  assert.equal(status.removed,false);assert.equal(status.textContent,'真实验证码状态');
  assert.equal(input.getAttribute('aria-describedby'),'status');
});
