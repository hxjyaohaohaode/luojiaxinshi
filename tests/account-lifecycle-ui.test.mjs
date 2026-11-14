import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

// Execute the production delegated submit handler, authentication/security
// factories, form feedback, API wrapper and push teardown. This controlled DOM
// records replacement, visible errors and device effects; it makes no native
// layout, pointer-hit, provider-delivery or browser claim.
const source=await readFile(new URL('../static/app.js',import.meta.url),'utf8');
const between=(start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);};
const apiSource=between('async function api(', '\nfunction showDialog(');
const clearSource=between('function clearSession(', '\nasync function api(');
const handlerSource=between("document.addEventListener('submit',async e=>",'\nlet searchTimer;');
const productionLine=name=>{const line=source.split('\n').find(x=>x.startsWith('function '+name+'('));assert.ok(line?.endsWith('}'));return line;};
const errorSource=productionLine('formError');
const authPageSource=productionLine('authPage');
const moduleSource=async name=>(await readFile(new URL('../static/'+name,import.meta.url),'utf8')).replace(/^import .*;\n/gm,'').replace(/export /g,'');
const [authSource,securitySource,feedbackSource,requestSource,pushSource]=await Promise.all(['auth.js','account-security.js','auth-feedback.js','ui-request.js','push-notifications.js'].map(moduleSource));
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};

class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.dataset={};this.attributes=new Map();this.children=[];this.className='';this.textContent='';this.value='';this.disabled=false;this.isConnected=true;this.parentElement=null;}
  get classList(){return {contains:x=>this.className.split(/\s+/).includes(x),add:x=>{if(!this.className.split(/\s+/).includes(x))this.className+=(this.className?' ':'')+x;},remove:x=>{this.className=this.className.split(/\s+/).filter(y=>y!==x).join(' ');}};}
  setAttribute(k,v){this.attributes.set(k,String(v));}
  getAttribute(k){return this.attributes.get(k)??null;}
  removeAttribute(k){this.attributes.delete(k);}
  append(child){child.parentElement=this;this.children.push(child);}
  prepend(child){child.parentElement=this;this.children.unshift(child);}
  before(child){child.parentElement=this.parentElement;this.parentElement?.children.unshift(child);}
  after(child){child.parentElement=this.parentElement;this.parentElement?.children.push(child);}
  remove(){this.isConnected=false;if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);}
  replaceChildren(){for(const child of this.children)child.isConnected=false;this.children=[];}
  focus(){this.focused=true;}
  scrollIntoView(){}
  addEventListener(){}
  closest(selector){if(selector==='label'&&this.tagName==='LABEL')return this;if(selector==='dialog'&&this.tagName==='DIALOG')return this;if(selector==='form'&&this instanceof Form)return this;if(selector==='.auth-form'&&this.className==='auth-form')return this;return this.parentElement?.closest(selector)||null;}
  querySelector(selector){return this.children.find(x=>selector==='.form-error'&&x.classList.contains('form-error'))||null;}
  querySelectorAll(){return [];}
}
class Form extends Element{
  constructor(id,values={}){
    super('form');this.id=id;this.fields={};this.values={...values};this.dataset.authMode='login';
    for(const [name,value] of Object.entries(values)){const label=new Element('label'),input=new Element('input');input.name=name;input.value=value;input.type=name.includes('password')?'password':'text';label.append(input);this.append(label);this.fields[name]=input;}
    this.button=new Element('button');this.button.className='auth-submit';this.button.type='submit';this.append(this.button);
    this.group=new Element('fieldset');this.group.dataset.verification='password';this.append(this.group);
  }
  querySelector(selector){const m=selector.match(/^\[name="?([^"\]]+)"?\]$/);if(m)return this.fields[m[1]]||null;if(selector==='[type=submit]'||selector==='.auth-submit')return this.button;if(selector.startsWith('[data-verification'))return this.group;return super.querySelector(selector);}
  querySelectorAll(selector){if(selector==='[type=submit]')return [this.button];if(selector==='[aria-invalid=true]')return Object.values(this.fields).filter(x=>x.getAttribute('aria-invalid')==='true');return [];}
}

function fixture({kind='login',request}={}){
  const logged=kind!=='login',session={user:{id:'owner-a',username:'owner-a',verified_contacts:[{channel:'email',value:'a@example.invalid'}],profile:{}},csrf:'token-a'};
  const state={session:logged?session:null,renderId:1,dialogRequest:1,invite:'',registrationMode:'public',notices:[],tasks:[],notice:null,arrangements:[{id:'old-private-arrangement'}],workOwner:logged?'owner-a':null,workContext:'personal'};
  const location={hash:logged?'#settings':'#login',origin:'http://fixture.invalid'};
  const form=new Form(kind==='login'?'auth-form':kind==='delete'?'delete-account-form':'password-form',kind==='login'?{username:'owner-a',password:'IncorrectPassword!'}:kind==='delete'?{password:'WrongPassword!',confirm:'注销账号'}:{old_password:'CurrentPassword!',new_password:'NextPassword2026!'});
  const wrapper=new Element(),dialog=new Element('dialog'),authContainer=new Element();authContainer.className='auth-form';
  dialog.open=logged;dialog.close=()=>{dialog.open=false;};form.parentElement=logged?dialog:authContainer;(logged?dialog:authContainer).children.push(form);
  const events=new Map(),created=[],requests=[],effects=[],toasts=[],opened=[],routes=[];let currentForm=form,renders=0;
  const disconnect=node=>{node.isConnected=false;for(const child of node.children||[])disconnect(child);};
  Object.defineProperty(wrapper,'innerHTML',{set(html){renders++;disconnect(currentForm);currentForm=null;this.html=html;},get(){return this.html||'';}});
  const document={body:new Element('body'),hidden:false,activeElement:form.fields.username||null,
    addEventListener(type,listener){const list=events.get(type)||[];list.push(listener);events.set(type,list);},dispatchEvent(){},
    createElement(tag){const node=new Element(tag);created.push(node);return node;},
    getElementById(id){return created.find(n=>n.id===id&&n.isConnected)||null;},
    querySelector(selector){if(selector==='#dialog'||selector==='dialog[open]'&&dialog.open)return dialog;if(selector==='.auth-form-wrap')return wrapper;if(selector==='#auth-form')return currentForm;if(selector==='#auth-form [name=username]')return currentForm?.fields.username||null;return null;},querySelectorAll(){return [];}};
  const toast=(message,error=false)=>toasts.push({message,error});toast.clear=()=>toasts.splice(0);
  const worker={scriptURL:location.origin+'/notification-worker.js',state:'activated',postMessage(message,[port]){effects.push({kind:'worker',type:message.type});queueMicrotask(()=>port.partner.onmessage?.({data:{ok:true,binding:{enabled:false,user_id:'owner-a'}}}));}};
  const subscription={endpoint:'https://push.example.invalid/own-device',async unsubscribe(){effects.push({kind:'unsubscribe'});return true;}};
  const registration={active:worker,pushManager:{async getSubscription(){return subscription;}},async unregister(){effects.push({kind:'unregister'});return true;}};
  class Channel{constructor(){this.port1={close(){}};this.port2={close(){}};this.port1.partner=this.port2;this.port2.partner=this.port1;}}
  const sandbox={document,state,location,URL,AbortController,Map,WeakMap,WeakSet,HTMLFormElement:Form,
    FormData:class extends Map{constructor(node){super(Object.entries(node.fields).map(([k,v])=>[k,v.value]));}},
    setTimeout,clearTimeout,queueMicrotask,requestAnimationFrame:fn=>{queueMicrotask(fn);return 1;},matchMedia:()=>({matches:true}),
    history:{replaceState(_state,_title,hash){location.hash=hash;}},sessionStorage:{removeItem(){}},
    isSecureContext:true,PushManager:class{},Notification:{permission:'granted'},MessageChannel:Channel,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},navigator:{serviceWorker:{async getRegistration(){return registration;}}},
    installationAdvice:()=>'',structuredClone,esc:String,icon:()=>'',companion:()=>'',brandMotion:()=>'',moveSelection(){},
    field:(label,name,value)=>'<label>'+label+'<input name="'+name+'" value="'+value+'"></label>',
    $:(selector,root)=>root?.querySelector?.(selector)||document.querySelector(selector),
    noticeUI:{},reviewObserver:{},persistCurrentForms(){},noticeFiles:[],memoryUI:{clearPrivate(){}},
    drafts:{checkpoint(){},async flush(){},clear(){effects.push({kind:'drafts-clear'});}},reminders:{stop(){effects.push({kind:'reminders-stop'});}},
    projections:new Map(),workspaceMutation:0,dataSync:{notify(){}},toast,
    cancelChoreography(){},applyDisplayPreferences(){},taskCollection:{clear(){}},libraryUI:{clear(){}},campusUI:{clearSession(){}},chatUI:{clearSession(){}},dialogNavigation:{clear(){}},workspaceProjection:{clear(){}},
    verification:{markup:()=>'',async prove(){return 'verified-proof';}},
    showDialog(title,body){opened.push({title,body});state.dialogRequest++;dialog.open=true;disconnect(form);},
    async route(){routes.push(location.hash);},
    async fetch(url,options){const path=url.replace(/^\/api/,'');requests.push({path,method:options.method||'GET',headers:options.headers,body:options.body});effects.push({kind:'request',path});const answer=request?await request(path,options):{status:200,body:{session}};return {ok:answer.status>=200&&answer.status<300,status:answer.status,headers:{get(){return null;}},async json(){return answer.body;}};},
  };
  vm.createContext(sandbox);
  vm.runInContext([requestSource,feedbackSource,authSource,securitySource,pushSource,clearSource,apiSource,errorSource,authPageSource,
    'globalThis.push=createPushNotifications({state,api,esc,toast});',
    'globalThis.accountSecurity=createAccountSecurity({state,esc,field,api,verification,showDialog,toast});',
    'globalThis.authUI=createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,route,moveSelection,verification});',handlerSource].join('\n'),sandbox);
  const submit=()=>events.get('submit')[0]({target:form,submitter:form.button,preventDefault(){}});
  return {state,session,location,form,dialog,requests,effects,toasts,opened,routes,sandbox,submit,renderCount:()=>renders,currentForm:()=>currentForm,
    visibleError:()=>currentForm?.isConnected?currentForm.querySelector('.form-error')?.textContent||'':'',
    close(){dialog.open=false;},leave(){dialog.open=false;state.renderId++;location.hash='#tasks';},
    replaceDialog(){state.dialogRequest++;dialog.open=true;disconnect(form);},
  };
}
const response=(status,body)=>({status,body});

test('an incorrect password keeps the current login inputs and its reachable inline error through the real delegated catch',async()=>{
  const f=fixture({request:async()=>response(401,{detail:'账号或密码错误'})});await f.submit();
  assert.equal(f.currentForm(),f.form,'The error must not be erased by replacing the login form');
  assert.equal(f.form.fields.username.value,'owner-a');assert.equal(f.form.fields.password.value,'IncorrectPassword!');
  assert.equal(f.form.fields.password.getAttribute('aria-invalid'),'true');assert.match(f.visibleError(),/账号或密码/);assert.equal(f.state.session,null);assert.equal(f.form.button.disabled,false);
});
test('a corrected login can retry the same form after a credential failure',async()=>{
  let n=0;const accepted={user:{id:'accepted-owner',profile:{}},csrf:'new-token'};
  const f=fixture({request:async()=>++n===1?response(401,{detail:'账号或密码错误'}):response(200,{session:accepted})});
  await f.submit();assert.equal(f.currentForm(),f.form);f.form.fields.password.value='CorrectPassword2026!';await f.submit();
  assert.equal(f.state.session.user.id,'accepted-owner');assert.equal(f.requests.length,2);assert.equal(f.routes.length,1);
});
test('an expired authenticated session still transitions to login rather than retaining an authorized form',async()=>{
  const f=fixture({kind:'security',request:async()=>response(401,{detail:'请先登录，或登录已过期'})});await f.submit();
  assert.equal(f.state.session,null);assert.equal(f.location.hash,'#login');assert.ok(f.renderCount()>0);assert.match(f.toasts.at(-1).message,/登录已过期/);
});
for(const exit of ['close','leave','replaceDialog'])test('a completed security save updates its owner without reopening the abandoned '+exit+' view',async()=>{
  const pending=deferred(),changed={user:{id:'owner-a',username:'owner-a',verified_contacts:[],profile:{saved:true}},csrf:'next'};
  const f=fixture({kind:'security',request:async()=>{await pending.promise;return response(200,{session:changed});}});
  const task=f.submit();await new Promise(resolve=>setImmediate(resolve));f[exit]();pending.resolve();await task;
  assert.equal(f.state.session,changed);assert.equal(f.opened.length,0,'A successful old save must not replace or reopen the current dialog');
});
test('a security save in its original dialog still refreshes the current security information',async()=>{
  const f=fixture({kind:'security'});await f.submit();assert.equal(f.opened.length,1);assert.equal(f.opened[0].title,'账号安全');assert.match(f.toasts.at(-1).message,/已更新/);
});
test('a late rejected security save has an accessible error after its dialog closes',async()=>{
  const pending=deferred();const f=fixture({kind:'security',request:async()=>{await pending.promise;return response(400,{detail:'原密码不正确'});}});
  const task=f.submit();await new Promise(resolve=>setImmediate(resolve));f.close();pending.resolve();await task;
  assert.equal(f.opened.length,0);assert.ok(f.toasts.some(x=>x.error&&x.message==='原密码不正确'),'The error cannot remain only inside a closed dialog');
});
test('repeated submission while the same security request is pending sends only one mutation',async()=>{
  const pending=deferred();const f=fixture({kind:'security',request:async()=>{await pending.promise;return response(200,{session:{...f.session}});}});
  const first=f.submit();await new Promise(resolve=>setImmediate(resolve));await f.submit();assert.equal(f.requests.length,1);pending.resolve();await first;
  assert.equal(f.requests.length,1);assert.equal(f.form.button.disabled,false);
});
test('a rejected account deletion preserves the existing device subscription and account form',async()=>{
  const f=fixture({kind:'delete',request:async path=>path==='/account/delete'?response(400,{detail:'密码不正确，账号没有注销'}):response(200,{ok:true})});await f.submit();
  assert.equal(f.state.session,f.session);assert.match(f.visibleError(),/账号没有注销/);
  assert.equal(f.effects.filter(x=>x.kind==='unsubscribe'||x.kind==='worker').length,0,'Failed deletion must not disable the existing device');
  assert.deepEqual(f.requests.map(x=>x.path),['/account/delete']);
});
test('a confirmed account deletion revokes the local device after success without an unauthenticated remote teardown',async()=>{
  const f=fixture({kind:'delete',request:async()=>response(200,{ok:true})});await f.submit();
  assert.deepEqual(f.requests.map(x=>x.path),['/account/delete']);
  assert.equal(f.effects.filter(x=>x.kind==='unsubscribe').length,1);assert.equal(f.effects.filter(x=>x.kind==='worker'&&x.type==='CAMPUS_PUSH_DISABLE').length,1);
  assert.equal(f.effects[0].path,'/account/delete');assert.equal(f.state.session,null);assert.equal(f.location.hash.replace(/^#/,''),'login');
});
test('confirmed deletion resets the previous account workspace before a new registration can start',async()=>{
  const f=fixture({kind:'delete',request:async()=>response(200,{ok:true})});await f.submit();
  assert.deepEqual(Array.from(f.state.arrangements),[]);assert.equal(f.state.workOwner,null);assert.equal(f.state.workContext,null);
});
test('a local device cleanup error cannot disguise an already confirmed account deletion as a failed deletion',async()=>{
  const f=fixture({kind:'delete',request:async()=>response(200,{ok:true})});
  f.sandbox.push.detachForLogout=async()=>{throw Error('无法确认本机提醒关闭');};await f.submit();
  assert.deepEqual(f.requests.map(x=>x.path),['/account/delete']);assert.equal(f.state.session,null);
  assert.ok(f.toasts.some(x=>x.error&&x.message.includes('账号已经注销')&&x.message.includes('无法确认本机提醒关闭')));
});
test('a new account accepted during deletion device cleanup is not deleted or logged out by the old completion',async()=>{
  const entered=deferred(),release=deferred(),f=fixture({kind:'delete',request:async()=>response(200,{ok:true})});
  f.sandbox.push.detachForLogout=async()=>{entered.resolve();await release.promise;};
  const task=f.submit();await entered.promise;const pathsBeforeCleanup=f.requests.map(x=>x.path);
  const other={user:{id:'owner-b',profile:{}},csrf:'other'};f.state.session=other;release.resolve();await task;
  assert.deepEqual(pathsBeforeCleanup,['/account/delete'],'The owner-bound deletion must precede local teardown');
  assert.equal(f.state.session,other);assert.equal(f.opened.length,0);assert.equal(f.requests.length,1);
});
test('ordinary logout continues to revoke both the local binding and its authenticated remote subscription',async()=>{
  const f=fixture({kind:'security',request:async()=>response(200,{ok:true})});await f.sandbox.push.detachForLogout();
  assert.deepEqual(f.requests.map(x=>x.path),['/push/subscriptions']);assert.equal(f.requests[0].method,'DELETE');assert.equal(f.effects.filter(x=>x.kind==='unsubscribe').length,1);
});
test('an account change rejects a late security response without opening or editing another account view',async()=>{
  const pending=deferred();const f=fixture({kind:'security',request:async()=>{await pending.promise;return response(200,{session:f.session});}});
  const task=f.submit();await new Promise(resolve=>setImmediate(resolve));const other={user:{id:'owner-b',profile:{}},csrf:'other'};f.state.session=other;pending.resolve();await task;
  assert.equal(f.state.session,other);assert.equal(f.opened.length,0);assert.equal(f.toasts.length,0);
});
