import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

// Run the real signup click handler, OTP challenge/proof state machine and toast
// presenter together. Only DOM, clock scheduling and HTTP are controlled here;
// the actual CI70 image separately establishes the native visual symptom.
const moduleSource=async name=>(await readFile(new URL('../static/'+name,import.meta.url),'utf8')).replace(/^import .*;\n/gm,'').replace(/export /g,'');
const [authSource,verificationSource,experienceSource]=await Promise.all(['auth.js','verification.js','experience-system.js'].map(moduleSource));
const toastSource=experienceSource.slice(experienceSource.indexOf('function createToastPresenter('));
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const rejected='验证码错误、已使用或已过期，请检查后重试';

class Node{
  constructor(){this.className='';this.innerHTML='';this.textContent='';this.style={setProperty(){}};this.attributes=new Map();this.listeners=new Map();this.children=[];this.isConnected=true;this.dataset={};}
  get classList(){return {contains:value=>this.className.split(/\s+/).includes(value),add:value=>{this.className+=' '+value;}};}
  addEventListener(name,listener){const list=this.listeners.get(name)||[];list.push(listener);this.listeners.set(name,list);}
  setAttribute(name,value){this.attributes.set(name,String(value));}
  getAttribute(name){return this.attributes.get(name)??null;}
  removeAttribute(name){this.attributes.delete(name);}
  append(child){child.parentElement=this;this.children.push(child);}
  replaceChildren(){this.innerHTML='';this.children=[];}
  contains(){return false;}
  matches(){return false;}
  closest(){return null;}
  querySelector(){return null;}
  querySelectorAll(){return [];}
  focus(){}
}

function fixture({verify}={}){
  const host=new Node(),app=new Node(),dialog=new Node(),body=new Node(),doc=new Node(),wrapper=new Node(),heading=new Node();
  const state={session:null,loginReturn:null,invite:'',registrationMode:'public'},calls=[],timers=[];
  doc.body=body;doc.hidden=false;doc.activeElement=null;doc.querySelector=selector=>({'#toast':host,'#app':app,'#dialog':dialog}[selector]||null);
  const form=new Node();form.dataset={authMode:'register',signupCurrent:'1'};const group=new Node();group.dataset={verification:'auth',purpose:'register'};group.closest=()=>form;
  const slots=Array.from({length:6},()=>({dataset:{},textContent:''})),shell=new Node(),status=new Node();shell.querySelectorAll=()=>slots;
  const code=new Node();code.value='';code.selectionStart=code.selectionEnd=0;code.readOnly=false;code.disabled=false;code.reportValidity=()=>true;code.closest=()=>group;code.matches=value=>value==='[data-otp-code]';code.setSelectionRange=(a,b)=>{code.selectionStart=a;code.selectionEnd=b;};
  const destination=new Node();destination.value='student@example.invalid';destination.reportValidity=()=>true;destination.closest=()=>group;
  const send=new Node();send.disabled=false;send.closest=value=>value==='[data-verification]'?group:null;
  group.querySelector=selector=>({'[data-otp-destination]':destination,'[data-otp-code]':code,'[data-otp-status]':status,'[data-otp-send]':send,'[data-otp-shell]':shell}[selector]||null);
  const stages=[1,2,3].map(step=>{const stage=new Node();stage.dataset.signupStep=String(step);stage.querySelectorAll=()=>step===1?[code,destination]:[];return stage;});
  wrapper.querySelector=value=>value==='h2'?heading:null;form.closest=()=>wrapper;form.querySelectorAll=value=>value==='[data-signup-step]'?stages:[];
  form.querySelector=selector=>selector==='[data-verification]'?group:selector==='[name=verification_consent]'?{checked:true}:selector==='[name=username]'?{value:'synthetic.account'}:selector.match(/^\[data-signup-step="(\d)"\]$/)?stages[Number(selector.match(/\d/)[0])-1]:selector.endsWith(' input')?code:null;
  const next=new Node();next.dataset.signupNext='1';next.disabled=false;next.closest=value=>value==='form'?form:null;
  const sandbox={document:doc,window:new Node(),innerHeight:850,performance,clearTimeout(){},setTimeout(callback,delay){timers.push({callback,delay});return timers.length;},requestAnimationFrame:()=>1,MutationObserver:class{observe(){}},motionAllowed:()=>false,
    installAuthFeedback(){},passwordEditor:()=>'',brandMotion:()=>'',showInputError(){},successTransition:()=>Promise.resolve(),location:{hash:'#register'},history:{replaceState(){}},sessionStorage:{removeItem(){}}};
  vm.createContext(sandbox);vm.runInContext(toastSource+'\n'+verificationSource+'\n'+authSource+'\nglobalThis.factories={createToastPresenter,createVerificationUI,createAuthUI};',sandbox);
  const toast=sandbox.factories.createToastPresenter({esc:String,icon:()=>'',owner:()=>state.session?.user?.id});
  const api=async(path,options)=>{calls.push({path,...options});if(path==='/auth/challenges')return {challenge_id:'synthetic-challenge',retry_after:0,expires_in:300,message:'发送请求已接受'};
    assert.equal(path,'/auth/verify');if(verify)return verify(options.json);if(options.json.code!=='123456')throw Object.assign(Error(rejected),{status:400});return {verification_token:'synthetic-proof',expires_in:300};};
  const verification=sandbox.factories.createVerificationUI({state,api,esc:String,toast});
  sandbox.factories.createAuthUI({state,esc:String,field:()=>'',api,icon:()=>'',companion:()=>'',showDialog(){},toast,route:async()=>{},moveSelection(){},verification});
  const fire=async(type,target)=>{for(const listener of doc.listeners.get(type)||[])await listener({target,preventDefault(){}});};
  const click=async(selector,target)=>fire('click',{closest:value=>value===selector?target:null});
  return {host,state,form,code,shell,status,calls,timers,toast,visible:()=>host.classList.contains('visible'),
    send:()=>click('[data-otp-send]',send),next:()=>click('[data-signup-next]',next),
    enter:async value=>{code.value=value;code.selectionStart=code.selectionEnd=value.length;await fire('input',code);}};
}

async function rejectOnce(f){await f.send();await f.enter('654321');await f.next();assert.equal(f.form.dataset.signupCurrent,'1');assert.equal(f.shell.dataset.state,'error');assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/验证码错误/);}

test('a corrected signup OTP clears its own persistent failure only after real verification accepts it',async()=>{
  const f=fixture();await rejectOnce(f);await f.enter('123456');assert.equal(f.visible(),true,'Editing alone must not claim the failure is resolved');
  await f.next();assert.equal(f.form.dataset.signupCurrent,'2');assert.equal(f.shell.dataset.state,'verified');assert.equal(f.visible(),false);assert.equal(f.host.innerHTML,'');
  assert.deepEqual(f.calls.map(item=>item.path),['/auth/challenges','/auth/verify','/auth/verify']);
});

test('the original verification error remains visible throughout a corrective request still awaiting acceptance',async()=>{
  const held=deferred(),f=fixture({verify:async values=>{if(values.code!=='123456')throw Error(rejected);return held.promise;}});await rejectOnce(f);await f.enter('123456');const pending=f.next();await tick();
  assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/验证码错误/);assert.equal(f.form.dataset.signupCurrent,'1');assert.equal(f.shell.dataset.state,'checking');
  held.resolve({verification_token:'synthetic-proof',expires_in:300});await pending;assert.equal(f.visible(),false);assert.equal(f.form.dataset.signupCurrent,'2');
});

test('a newer unrelated message is not dismissed when the prior signup error is corrected',async()=>{
  const f=fixture();await rejectOnce(f);f.toast('另一项操作尚未保存，请检查',true);await f.enter('123456');await f.next();
  assert.equal(f.form.dataset.signupCurrent,'2');assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/另一项操作尚未保存/);
});

test('an unrelated message arriving during corrective verification survives its successful completion',async()=>{
  const held=deferred(),f=fixture({verify:async values=>{if(values.code!=='123456')throw Error(rejected);return held.promise;}});await rejectOnce(f);await f.enter('123456');const pending=f.next();await tick();
  f.toast('新的网络问题需要核对',true);held.resolve({verification_token:'synthetic-proof',expires_in:300});await pending;
  assert.equal(f.form.dataset.signupCurrent,'2');assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/新的网络问题/);
});

test('uncorrected or repeatedly rejected verification remains persistent and cannot advance signup',async()=>{
  const f=fixture();await rejectOnce(f);await f.enter('654322');await f.next();
  assert.equal(f.form.dataset.signupCurrent,'1');assert.equal(f.shell.dataset.state,'error');assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/验证码错误/);assert.equal(f.timers.length,0,'Persistent verification errors have no expiry timer');
});

test('a first successful verification does not clear an unrelated pre-existing message',async()=>{
  const f=fixture();f.toast('请核对另一个待处理问题',true);await f.send();await f.enter('123456');await f.next();
  assert.equal(f.form.dataset.signupCurrent,'2');assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/另一个待处理问题/);
});

test('toast tickets clear only their current message while the existing no-argument clear remains compatible',()=>{
  const f=fixture(),previous=f.toast('前一个错误',true),current=f.toast('最新错误',true);
  f.toast.clear(previous);assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/最新错误/);
  f.toast.clear(current);assert.equal(f.visible(),false);f.toast('无参清理兼容',true);f.toast.clear();assert.equal(f.visible(),false);
});
