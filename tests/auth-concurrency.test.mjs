import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

// Exercise the real delegated submit handler, authentication factory, API
// wrapper and form feedback across replaced forms. The controlled DOM and
// deferred HTTP responses verify request ordering and session ownership; they
// do not simulate browser cookies, native focus or provider delivery.
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
  querySelector(selector){return this.children.find(x=>selector==='.form-error'&&x.classList.contains('form-error')||selector==='h2'&&x.tagName==='H2')||null;}
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

function fixture({kind='login',request,proof,transition}={}){
  const logged=kind!=='login',session={user:{id:'owner-a',username:'owner-a',verified_contacts:[{channel:'email',value:'a@example.invalid'}],profile:{}},csrf:'token-a'};
  const state={session:logged?session:null,renderId:1,dialogRequest:1,invite:'',registrationMode:'public',notices:[],tasks:[],notice:null,arrangements:[{id:'old-private-arrangement'}],workOwner:logged?'owner-a':null,workContext:'personal'};
  const location={hash:logged?'#settings':'#login',origin:'http://fixture.invalid'};
  const form=new Form(kind==='login'?'auth-form':kind==='delete'?'delete-account-form':'password-form',kind==='login'?{username:'owner-a',password:'IncorrectPassword!'}:kind==='delete'?{password:'WrongPassword!',confirm:'注销账号'}:{old_password:'CurrentPassword!',new_password:'NextPassword2026!'});
  const wrapper=new Element(),dialog=new Element('dialog'),authContainer=new Element();authContainer.className='auth-form';authContainer.append(new Element('h2'));
  dialog.open=logged;dialog.close=()=>{dialog.open=false;};form.parentElement=logged?dialog:authContainer;(logged?dialog:authContainer).children.push(form);
  const events=new Map(),created=[],requests=[],effects=[],toasts=[],opened=[],routes=[];let currentForm=form,renders=0;
  const disconnect=node=>{if(!node)return;node.isConnected=false;for(const child of node.children||[])disconnect(child);};
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
    verification:{markup:()=>'',destination:()=> 'contact@example.invalid',prove:proof|| (async()=> 'verified-proof')},
    showDialog(title,body){opened.push({title,body});state.dialogRequest++;dialog.open=true;disconnect(form);},
    async route(){routes.push(location.hash);},
    async fetch(url,options){const path=url.replace(/^\/api/,'');requests.push({path,method:options.method||'GET',headers:options.headers,body:options.body});effects.push({kind:'request',path});const answer=request?await request(path,options):{status:200,body:{session}};return {ok:answer.status>=200&&answer.status<300,status:answer.status,headers:{get(){return null;}},async json(){return answer.body;}};},
  };
  vm.createContext(sandbox);
  vm.runInContext([requestSource,feedbackSource,authSource,securitySource,pushSource,clearSource,apiSource,errorSource,authPageSource,
    'globalThis.push=createPushNotifications({state,api,esc,toast});',
    'globalThis.accountSecurity=createAccountSecurity({state,esc,field,api,verification,showDialog,toast});',
    'globalThis.authUI=createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,route,moveSelection,verification});',handlerSource].join('\n'),sandbox);
  const submit=(target=form)=>events.get('submit')[0]({target,submitter:target.button,preventDefault(){}});
  if(transition)sandbox.successTransition=transition;
  const click=async (selector,control)=>{for(const listener of events.get('click')||[])await listener({target:{closest:value=>value===selector?control:null}});};
  const mount=(mode='login')=>{disconnect(currentForm);currentForm=new Form('auth-form',{username:'owner-b',display_name:'合成用户',campus_role:'student',password:'DifferentPassword2026!',confirm_password:'DifferentPassword2026!'});currentForm.dataset.authMode=mode;currentForm.dataset.signupCurrent='3';currentForm.fields.accepted_terms={checked:true};authContainer.append(currentForm);location.hash='#'+mode;return currentForm;};
  return {click,mount,state,session,location,form,dialog,requests,effects,toasts,opened,routes,sandbox,submit,renderCount:()=>renders,currentForm:()=>currentForm,
    visibleError:()=>currentForm?.isConnected?currentForm.querySelector('.form-error')?.textContent||'':'',
    close(){dialog.open=false;},leave(){dialog.open=false;state.renderId++;location.hash='#tasks';},
    replaceDialog(){state.dialogRequest++;dialog.open=true;disconnect(form);},
  };
}
const response=(status,body)=>({status,body});


const tick=()=>new Promise(resolve=>setImmediate(resolve));
const accepted=id=>({user:{id,profile:{}},csrf:'synthetic-'+id});
const authRequests=f=>f.requests.filter(item=>/^\/auth\/(?:login|verified-login|register|recover)$/.test(item.path));

for(const mode of ['login','register','recover'])test('pending password login rejects a second '+mode+' form before another session-changing request',async()=>{
  const pending=deferred();let count=0;
  const f=fixture({request:async()=>++count===1?pending.promise:response(200,{session:accepted('owner-b')})});
  const first=f.submit();await tick();const next=f.mount(mode);await f.submit(next);
  pending.resolve(response(200,{session:accepted('owner-a')}));await first;
  assert.equal(authRequests(f).length,1,'Replacing the form cannot bypass the shared authentication lock');
  assert.equal(f.state.session.user.id,'owner-a');assert.equal(f.routes.length,1);
});

test('clicking a login method while authentication is pending preserves the submitted form and shows a status',async()=>{
  const pending=deferred(),f=fixture({request:()=>pending.promise});const first=f.submit();await tick();
  await f.click('[data-login-method]',{dataset:{loginMethod:'code'}});
  const preserved=f.currentForm()===f.form&&f.form.isConnected;
  const feedback=f.toasts.some(value=>/正在|请稍候/.test(value.message));
  pending.resolve(response(200,{session:accepted('owner-a')}));await first;
  assert.equal(preserved,true);assert.equal(feedback,true);assert.equal(authRequests(f).length,1);
});

for(const mode of ['register','recover'])test('pending '+mode+' holds the shared lock through its contact proof and forbids a replacement login',async()=>{
  const proof=deferred(),f=fixture({proof:()=>proof.promise,request:async()=>response(200,{session:accepted('owner-b')})});
  const source=f.mount(mode),first=f.submit(source);await tick();const next=f.mount('login');await f.submit(next);
  proof.resolve('synthetic-proof');await first;
  assert.equal(authRequests(f).length,0,'An abandoned proof cannot start the old authentication request or a competing login');
  assert.equal(f.state.session,null);assert.equal(f.routes.length,0);
  await f.submit(next);assert.equal(authRequests(f).length,1);assert.equal(f.state.session.user.id,'owner-b');
});

test('verified-contact login shares the same pending lock as password login',async()=>{
  const pending=deferred(),f=fixture({proof:()=>pending.promise,request:async()=>response(200,{session:accepted('owner-b')})});
  await f.click('[data-login-method]',{dataset:{loginMethod:'code'}});const source=f.mount('login');
  const first=f.submit(source);await tick();const next=f.mount('recover'),second=f.submit(next);await tick();
  pending.resolve('synthetic-proof');await Promise.all([first,second]);
  assert.equal(authRequests(f).length,0);assert.equal(f.state.session,null);
  await f.click('[data-login-method]',{dataset:{loginMethod:'password'}});const retry=f.mount('login');
  await f.submit(retry);assert.equal(authRequests(f).length,1);assert.equal(authRequests(f)[0].path,'/auth/login');
});

test('a failed original request unlocks the replacement form without discarding its entered values',async()=>{
  const pending=deferred();let count=0;
  const f=fixture({request:async()=>++count===1?pending.promise:response(200,{session:accepted('owner-b')})});
  const first=f.submit();await tick();const next=f.mount('login');next.fields.username.value='kept-user';
  pending.resolve(response(401,{detail:'账号或密码错误'}));await first;
  assert.equal(f.currentForm(),next);assert.equal(next.fields.username.value,'kept-user');
  await f.submit(next);assert.equal(authRequests(f).length,2);assert.equal(f.state.session.user.id,'owner-b');
});

test('failed proof and failed fallback session reads release the lock for a later login',async()=>{
  let failProof=true,failSession=true;
  const f=fixture({proof:async()=>{if(failProof)throw Error('验证码不正确');return 'synthetic-proof';},request:async path=>path==='/session'&&failSession?response(503,{detail:'读取结果失败'}):path==='/auth/recover'?response(200,{}):response(200,{session:accepted('owner-b')})});
  let source=f.mount('recover');await f.submit(source);assert.equal(f.requests.length,0);
  failProof=false;source=f.mount('recover');await f.submit(source);assert.equal(f.state.session,null);assert.equal(f.requests.length,2);
  failSession=false;source=f.mount('login');await f.submit(source);assert.equal(f.state.session.user.id,'owner-b');assert.equal(authRequests(f).length,2);
});

test('the success transition remains serialized until the session is adopted',async()=>{
  const transition=deferred(),entered=deferred();
  const f=fixture({transition:()=>{entered.resolve();return transition.promise;},request:async()=>response(200,{session:accepted('owner-a')})});
  const first=f.submit();await entered.promise;const next=f.mount('login');const second=f.submit(next);await tick();
  const sentWhileTransitionPending=authRequests(f).length;transition.resolve();await Promise.all([first,second]);
  assert.equal(sentWhileTransitionPending,1);assert.equal(f.routes.length,1);assert.equal(f.state.session.user.id,'owner-a');
});

test('a late anonymous authentication response cannot overwrite a newly adopted session',async()=>{
  const pending=deferred(),f=fixture({request:()=>pending.promise});const first=f.submit();await tick();
  const newer=accepted('owner-b');f.state.session=newer;pending.resolve(response(200,{session:accepted('owner-a')}));await first;
  assert.equal(f.state.session,newer);assert.equal(f.routes.length,0);
});

test('a session change during the successful animation also prevents late session adoption',async()=>{
  const transition=deferred(),entered=deferred(),f=fixture({transition:()=>{entered.resolve();return transition.promise;},request:async()=>response(200,{session:accepted('owner-a')})});
  const first=f.submit();await entered.promise;const newer=accepted('owner-b');f.state.session=newer;transition.resolve();await first;
  assert.equal(f.state.session,newer);assert.equal(f.routes.length,0);
});

for(const legal of ['privacy','terms'])test('successful authentication preserves the '+legal+' page opened while it was pending',async()=>{
  const pending=deferred(),f=fixture({request:()=>pending.promise});f.state.loginReturn={owner:'owner-a',hash:'#tasks'};
  const first=f.submit();await tick();f.form.isConnected=false;f.location.hash='#'+legal;
  pending.resolve(response(200,{session:accepted('owner-a')}));await first;
  assert.equal(f.state.session.user.id,'owner-a');assert.equal(f.location.hash,'#'+legal);assert.deepEqual(f.routes,['#'+legal]);
});

test('an authentication form retained after an accepted session cannot start another account login',async()=>{
  const f=fixture({request:async()=>response(200,{session:accepted('owner-a')})});await f.submit();
  const next=f.mount('login');await f.submit(next);assert.equal(authRequests(f).length,1);assert.equal(f.state.session.user.id,'owner-a');
});
