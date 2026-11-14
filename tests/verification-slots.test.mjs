import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import {createVerificationUI} from '../static/verification.js';

function fixture(t,verify=async()=>({verification_token:'fixture-proof',expires_in:300}),challenge=async()=>({challenge_id:'fixture-challenge',retry_after:0,expires_in:300,message:'发送请求已接受，请检查你的联系方式'})){
  const previous={document:globalThis.document,setTimeout:globalThis.setTimeout};
  const doc=new EventTarget();globalThis.document=doc;globalThis.setTimeout=()=>0;
  t.after(()=>Object.assign(globalThis,previous));
  const attrs=new Map(),slots=Array.from({length:6},()=>({dataset:{},textContent:''}));
  const shell={dataset:{},querySelectorAll:()=>slots};
  const status={textContent:''},button={disabled:false,isConnected:true,textContent:'',closest:s=>s==='[data-verification]'?group:null};
  const destination={value:'student@example.invalid',reportValidity:()=>true};
  const code={value:'',selectionStart:0,selectionEnd:0,readOnly:false,disabled:false,
    matches:s=>s==='[data-otp-code]',closest:s=>s==='[data-verification]'?group:null,
    getAttribute:n=>attrs.get(n)??null,setAttribute:(n,v)=>attrs.set(n,String(v)),removeAttribute:n=>attrs.delete(n),
    setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;},focus(){doc.activeElement=this;},
    dispatchEvent(e){Object.defineProperty(e,'target',{value:this});return doc.dispatchEvent(e);}};
  const form={querySelector:s=>s==='[name=username]'?{value:'fixture.account'}:{checked:true}};
  const group={isConnected:true,dataset:{purpose:'register'},closest:()=>form,
    querySelector:s=>({'[data-otp-contact]':null,'[data-otp-destination]':destination,'[data-otp-code]':code,'[data-otp-status]':status,'[data-otp-send]':button,'[data-otp-shell]':shell}[s]??null),
    querySelectorAll:s=>s==='[data-otp-slot]'?slots:[]};
  destination.closest=code.closest;destination.matches=()=>false;
  const state={session:{user:{id:'owner-a'}}},calls=[];
  const api=async(path,options)=>{calls.push({path,...options});return path==='/auth/challenges'?challenge():verify();};
  const ui=createVerificationUI({state,api,esc:String,toast(){}});
  function event(type,target,values={}){const e=new Event(type,{cancelable:true});Object.defineProperty(e,'target',{value:target});for(const [k,v]of Object.entries(values))Object.defineProperty(e,k,{value:v});doc.dispatchEvent(e);return e;}
  const send=async()=>{event('click',{closest:s=>s==='[data-otp-send]'?button:null});await tick();};
  const enter=value=>{code.value=value;code.selectionStart=code.selectionEnd=value.length;event('input',code);};
  return {ui,send,enter,event,code,destination,group,shell,slots,status,state,calls,attrs};
}

test('OTP markup has one real autofill input and six non-interactive decorative slots',t=>{
  const h=fixture(t),html=h.ui.markup('account','register');
  assert.equal((html.match(/data-otp-code(?:\s|>)/g)||[]).length,1);
  assert.equal((html.match(/data-otp-slot(?:\s|>)/g)||[]).length,6);
  assert.match(html,/autocomplete="one-time-code"/);assert.match(html,/aria-describedby="[^"]+"/);
  assert.match(html,/class="verification-code-slots" aria-hidden="true"/);
});

test('pasting spaced full-width OTP normalizes the full clipboard before the six-character limit',t=>{
  const h=fixture(t),e=h.event('paste',h.code,{clipboardData:{getData:()=>'１２３ ４５６'}});
  assert.equal(e.defaultPrevented,true);assert.equal(h.code.value,'123456');
  assert.equal(h.code.selectionStart,6);assert.deepEqual(h.slots.map(n=>n.textContent),['1','2','3','4','5','6']);
  assert.equal(h.calls.length,0,'Entering all digits must not verify or submit automatically');
  assert.notEqual(h.shell.dataset.state,'verified');
});

test('native edits update visible digits without announcing a successful verification',t=>{
  const h=fixture(t);h.enter('１２３４５６');assert.equal(h.code.value,'123456');
  assert.equal(h.shell.dataset.state,'ready');assert.equal(h.code.readOnly,false);assert.equal(h.calls.length,0);
  h.enter('123');assert.deepEqual(h.slots.map(n=>n.textContent),['1','2','3','','','']);
  assert.equal(h.shell.dataset.state,'idle');
});

test('a real verification rejection preserves the entered code and makes the error perceivable',async t=>{
  const h=fixture(t,async()=>{throw Object.assign(Error('验证码不正确，请核对后重试'),{status:400});});
  await h.send();h.enter('123456');await assert.rejects(h.ui.prove(h.group),/验证码不正确/);
  assert.equal(h.code.value,'123456');assert.equal(h.code.readOnly,false);
  assert.equal(h.attrs.get('aria-invalid'),'true');assert.equal(h.shell.dataset.state,'error');
  assert.match(h.status.textContent,/验证码不正确/);assert.equal(h.calls.length,2);
});

test('verified feedback waits for the real response and remains distinct from a filled input',async t=>{
  let release;const response=new Promise(resolve=>release=resolve);const h=fixture(t,()=>response);
  await h.send();h.enter('123456');const pending=h.ui.prove(h.group);await tick();
  assert.equal(h.shell.dataset.state,'checking');assert.equal(h.code.readOnly,false);
  release({verification_token:'actual-receipt',expires_in:300});assert.equal(await pending,'actual-receipt');
  assert.equal(h.shell.dataset.state,'verified');assert.equal(h.code.readOnly,true);
  assert.match(h.status.textContent,/已验证/);assert.equal(await h.ui.prove(h.group),'actual-receipt');assert.equal(h.calls.length,2);
});

test('changing the contact clears the proof, digits and verified styling together',async t=>{
  const h=fixture(t);await h.send();h.enter('123456');await h.ui.prove(h.group);
  h.destination.value='changed@example.invalid';h.event('input',h.destination);
  assert.equal(h.code.value,'');assert.equal(h.code.readOnly,false);assert.equal(h.shell.dataset.state,'idle');
  assert.deepEqual(h.slots.map(n=>n.textContent),['','','','','','']);
  await assert.rejects(h.ui.prove(h.group),/请先向当前手机号/);
});

test('a late verification response cannot install a proof after an account change',async t=>{
  let release;const response=new Promise(resolve=>release=resolve);const h=fixture(t,()=>response);
  await h.send();h.enter('123456');const pending=h.ui.prove(h.group);await tick();
  h.state.session={user:{id:'owner-b'}};release({verification_token:'old-owner-proof',expires_in:300});
  await assert.rejects(pending,/验证信息已改变/);assert.notEqual(h.shell.dataset.state,'verified');
  await assert.rejects(h.ui.prove(h.group),/请先向当前手机号/);
});

test('editing a rejected code clears its visual error and does not issue another request',async t=>{
  const h=fixture(t,async()=>{throw Error('错码');});await h.send();h.enter('123456');await assert.rejects(h.ui.prove(h.group));
  h.enter('123457');assert.equal(h.attrs.has('aria-invalid'),false);assert.equal(h.shell.dataset.state,'ready');
  assert.equal(h.calls.length,2);assert.equal(h.code.readOnly,false);
});

test('a pending resend cannot reuse the previous verified proof for newly entered digits',async t=>{
  let release,issued=0,verified=0;const pending=new Promise(resolve=>release=resolve);
  const h=fixture(t,async()=>({verification_token:'proof-'+(++verified),expires_in:300}),async()=>++issued===1?{challenge_id:'first-challenge',retry_after:0,expires_in:300}:pending);
  await h.send();h.enter('123456');assert.equal(await h.ui.prove(h.group),'proof-1');
  await h.send();assert.equal(h.code.value,'');assert.equal(h.code.readOnly,false);
  h.enter('654321');await assert.rejects(h.ui.prove(h.group),/请先向当前手机号/);
  assert.equal(verified,1,'The pending replacement cannot verify against the retired challenge');
  release({challenge_id:'second-challenge',retry_after:0,expires_in:300});await tick();
  assert.equal(await h.ui.prove(h.group),'proof-2');
  assert.equal(h.calls.at(-1).json.challenge_id,'second-challenge');
  assert.equal(h.calls.at(-1).json.code,'654321');
});
