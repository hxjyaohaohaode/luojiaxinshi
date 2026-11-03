import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import {createVerificationUI} from '../static/verification.js';

function fixture(t,challengeWait=null){
  const saved=globalThis.document,interval=globalThis.setInterval;const doc=new EventTarget();globalThis.document=doc;globalThis.setInterval=()=>0;
  t.after(()=>{globalThis.document=saved;globalThis.setInterval=interval;});
  const user={value:'initial.account'},agreed={checked:true},dest={value:'13800000000',reportValidity:()=>true},code={value:'123456'},status={},button={disabled:false,isConnected:true,textContent:'',closest:()=>group};
  const form={querySelector:selector=>selector==='[name=username]'?user:agreed};
  const group={isConnected:true,dataset:{purpose:'register'},closest:()=>form,querySelector:selector=>({'[data-otp-contact]':null,'[data-otp-destination]':dest,'[data-otp-code]':code,'[data-otp-status]':status}[selector])};
  const calls=[];const api=async(path,options)=>{calls.push({path,...options});if(path==='/auth/challenges'&&challengeWait)await challengeWait;return path==='/auth/challenges'?{challenge_id:'synthetic-challenge',retry_after:60,message:'sent'}:{verification_token:'synthetic-proof',expires_in:300};};
  const state={session:null};const ui=createVerificationUI({state,api,esc:String,toast:()=>{}});
  const send=async()=>{const e=new Event('click');Object.defineProperty(e,'target',{value:{closest:()=>button}});doc.dispatchEvent(e);await tick();};
  return {ui,send,calls,user,dest,code,group,button,status,state};
}

test('registration proof survives entering account details after the SMS arrived',async t=>{
  const h=fixture(t);await h.send();h.user.value='finished.account';
  assert.equal(await h.ui.prove(h.group),'synthetic-proof');
  assert.equal(h.calls[0].json.channel,'sms');assert.equal(h.calls[1].path,'/auth/verify');
  assert.equal(await h.ui.prove(h.group),'synthetic-proof');assert.equal(h.calls.length,2);
});

test('one contact field detects email and rejects a proof after the contact changes',async t=>{
  const h=fixture(t);h.dest.value='student@example.invalid';await h.send();
  assert.equal(h.calls[0].json.channel,'email');h.dest.value='other@example.invalid';
  await assert.rejects(h.ui.prove(h.group),/修改联系方式/);assert.equal(h.calls.length,1);
});

test('login and reset keep the verified account bound to their challenge',async t=>{
  const h=fixture(t);h.group.dataset.purpose='recover';await h.send();h.user.value='another.account';
  await assert.rejects(h.ui.prove(h.group),/修改联系方式/);assert.equal(h.calls.length,1);
});

test('unified contact entry has no channel selector and offers OTP autofill',t=>{
  const h=fixture(t),html=h.ui.markup('test','register');
  assert.doesNotMatch(html,/data-otp-channel/);assert.match(html,/one-time-code/);
});

test('editing contact while sending releases the button and discards the old challenge',async t=>{
  let release;const h=fixture(t,new Promise(resolve=>release=resolve));
  await h.send();assert.equal(h.button.disabled,true);
  h.dest.value='13900000000';release();await tick();
  assert.equal(h.button.disabled,false);assert.match(h.status.textContent,/重新发送/);
  await assert.rejects(h.ui.prove(h.group),/先向当前手机号/);
  await h.send();assert.equal(await h.ui.prove(h.group),'synthetic-proof');
  assert.equal(h.calls.filter(c=>c.path==='/auth/challenges').length,2);
});

test('switching account during a code request cannot leave a usable old challenge',async t=>{
  let release;const h=fixture(t,new Promise(resolve=>release=resolve));
  await h.send();h.state.session={user:{id:'another-owner'}};release();await tick();
  assert.equal(h.button.disabled,false);
  await assert.rejects(h.ui.prove(h.group),/先向当前手机号/);
});
