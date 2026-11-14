import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

// Run the production authentication factory and toast presenter together. The
// small DOM below records their visible output; it is not a layout/browser test.
const authSource=(await readFile(new URL('../static/auth.js',import.meta.url),'utf8'))
  .replace(/^import .*;\n/gm,'').replace('export function createAuthUI','function createAuthUI');
const feedbackSource=await readFile(new URL('../static/experience-system.js',import.meta.url),'utf8');
const toastStart=feedbackSource.indexOf('export function createToastPresenter(');
assert.ok(toastStart>=0);
const toastSource=feedbackSource.slice(toastStart).replace('export function createToastPresenter','function createToastPresenter');
const expired='请先登录，或登录已过期';
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};

class Node {
  constructor(){this.className='';this.innerHTML='';this.style={setProperty(){}};this.attributes=new Map();this.listeners=new Map();this.children=[];}
  get classList(){return {contains:value=>this.className.split(/\s+/).includes(value),add:value=>{this.className+=' '+value;}};}
  addEventListener(name,listener){const list=this.listeners.get(name)||[];list.push(listener);this.listeners.set(name,list);}
  setAttribute(name,value){this.attributes.set(name,String(value));}
  append(child){child.parentElement=this;this.children.push(child);}
  replaceChildren(){this.innerHTML='';this.children=[];}
  contains(){return false;}
  matches(){return false;}
  querySelector(){return null;}
}

function fixture({mode='login',method='password',request,transition,onRoute,proof}={}){
  const host=new Node(),app=new Node(),dialog=new Node(),body=new Node(),doc=new Node(),state={session:null,loginReturn:null,invite:'',registrationMode:'public'};
  doc.body=body;doc.hidden=false;doc.activeElement=null;
  doc.querySelector=selector=>({'#toast':host,'#app':app,'#dialog':dialog}[selector]||null);
  doc.querySelectorAll=()=>[];
  const location={hash:mode==='recover'?'#recover':mode==='register'?'#register':'#login'},calls=[],routes=[];
  const session={user:{id:'signed-in-user',profile:{}},csrf:'synthetic-csrf'};
  const sandbox={document:doc,window:new Node(),innerHeight:850,performance,setTimeout,clearTimeout,requestAnimationFrame:()=>1,MutationObserver:class{observe(){}},motionAllowed:()=>false,
    installAuthFeedback(){},passwordEditor:()=>'',brandMotion:()=>'',showInputError(node,message){node.error=message;},successTransition:transition||(()=>Promise.resolve()),location,
    history:{replaceState(_state,_title,hash){location.hash=hash;}},sessionStorage:{removeItem(){}}};
  vm.createContext(sandbox);vm.runInContext(toastSource+'\n'+authSource+'\nglobalThis.factories={createToastPresenter,createAuthUI};',sandbox);
  const toast=sandbox.factories.createToastPresenter({esc:String,icon:()=>'',owner:()=>state.session?.user?.id});
  const api=async(path,options)=>{calls.push({path,options});return request?request(path,options,session):{session};};
  const verification={markup:()=>'',destination:()=>'+8613800000000',prove:proof||(()=>Promise.resolve('synthetic-proof'))};
  const ui=sandbox.factories.createAuthUI({state,esc:String,field:()=>'',api,icon:()=>'',companion:()=>'',showDialog(){},toast,
    route:async()=>{routes.push(location.hash);if(onRoute)await onRoute(toast);},moveSelection(){},verification});
  if(method==='code'){
    const button={dataset:{loginMethod:'code'}};
    for(const listener of doc.listeners.get('click')||[])listener({target:{closest:selector=>selector==='[data-login-method]'?button:null}});
  }
  const values={display_name:'合成账号',username:'synthetic-user',campus_role:'student',password:'ValidFixturePassword1!',confirm_password:'ValidFixturePassword1!'};
  const fields=Object.fromEntries(Object.entries(values).map(([name,value])=>[name,{value}]));fields.accepted_terms={checked:true};
  const form={dataset:{authMode:mode,signupCurrent:'3'},querySelector(selector){if(selector==='[data-verification]')return {};return fields[selector.match(/^\[name="?([^"\]]+)"?\]$/)?.[1]]||null;}};
  const data=mode==='login'?new Map([['username',values.username],['password',values.password]]):new Map(Object.entries(values));
  toast(expired,true);
  const visible=()=>host.classList.contains('visible');
  return {host,state,session,calls,routes,toast,visible,form,fields,submit:()=>ui.submit(form,data)};
}

for(const scenario of [{name:'password login',mode:'login'},{name:'verified-contact login',mode:'login',method:'code'},{name:'registration',mode:'register'},{name:'password recovery',mode:'recover'}]){
  test('successful '+scenario.name+' removes the stale authentication error from the real toast presenter',async()=>{
    const f=fixture(scenario);assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/登录已过期/);
    await f.submit();assert.equal(f.state.session,f.session);assert.equal(f.routes.length,1);
    assert.equal(f.visible(),false,'A valid accepted session must not still show the expired-login alert');assert.equal(f.host.innerHTML,'');
  });
}

test('failed credentials keep the authentication error visible and do not adopt a session',async()=>{
  const error=Object.assign(Error('账号或密码不正确'),{status:401});const f=fixture({request:()=>Promise.reject(error)});
  await assert.rejects(f.submit(),cause=>cause===error);assert.equal(f.state.session,null);assert.equal(f.routes.length,0);
  assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/登录已过期/);assert.equal(f.fields.password.error,'账号或密码不正确');
});

test('pending authentication and its unfinished success transition do not clear the prior error early',async()=>{
  const request=deferred(),transition=deferred(),transitionStarted=deferred();
  const f=fixture({request:()=>request.promise,transition:()=>{transitionStarted.resolve();return transition.promise;}});
  const pending=f.submit();assert.equal(f.visible(),true);assert.equal(f.state.session,null);
  request.resolve({session:f.session});await transitionStarted.promise;
  assert.equal(f.visible(),true);assert.equal(f.state.session,null);assert.equal(f.routes.length,0);
  transition.resolve();await pending;assert.equal(f.state.session,f.session);assert.equal(f.visible(),false);
});

test('an unsuccessful session read after an auth response preserves the existing error and unauthenticated state',async()=>{
  const error=Error('读取登录结果失败');const f=fixture({request:path=>path==='/auth/login'?{}:Promise.reject(error)});
  await assert.rejects(f.submit(),cause=>cause===error);assert.deepEqual(f.calls.map(c=>c.path),['/auth/login','/session']);
  assert.equal(f.state.session,null);assert.equal(f.routes.length,0);assert.equal(f.visible(),true);assert.match(f.host.innerHTML,/登录已过期/);
});

test('failed contact verification does not clear the alert or send a recovery request',async()=>{
  const error=Error('验证码尚未验证');const f=fixture({mode:'recover',proof:()=>Promise.reject(error)});
  await assert.rejects(f.submit(),cause=>cause===error);assert.equal(f.calls.length,0);assert.equal(f.state.session,null);assert.equal(f.visible(),true);
});

test('a new workspace error after successful authentication remains visible through route failure',async()=>{
  const error=Error('新工作台资料暂时无法读取');const f=fixture({onRoute:async toast=>{toast(error.message,true);throw error;}});
  await assert.rejects(f.submit(),cause=>cause===error);assert.equal(f.state.session,f.session);assert.equal(f.visible(),true);
  assert.match(f.host.innerHTML,/新工作台资料暂时无法读取/);assert.doesNotMatch(f.host.innerHTML,/登录已过期/);
});
