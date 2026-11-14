import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const sourceBase=process.env.LUOJIAXINSHI_SOURCE_ROOT?pathToFileURL(process.env.LUOJIAXINSHI_SOURCE_ROOT.replace(/\/$/,'')+'/'):new URL('../',import.meta.url);
import vm from 'node:vm';

// Execute the production delegated submit handler, authentication/security
// factories, form feedback, API wrapper and push teardown. This controlled DOM
// records replacement, visible errors and device effects; it makes no native
// layout, pointer-hit, provider-delivery or browser claim.
const source=await readFile(new URL('static/app.js',sourceBase),'utf8');
const between=(start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);};
const apiSource=between('async function api(', '\nfunction showDialog(');
const clearSource=between('function clearSession(', '\nasync function api(');
const backgroundSource=between('function backgroundSyncAllowed(', '\nfunction updateNoticeFocus(');
const refreshSource=between('async function refreshWorkspace(', '\ndataSync=installDataSync(');
const handlerSource=between("document.addEventListener('submit',async e=>",'\nlet searchTimer;');
const productionLine=name=>{const line=source.split('\n').find(x=>x.startsWith('function '+name+'('));assert.ok(line?.endsWith('}'));return line;};
const errorSource=productionLine('formError');
const authPageSource=productionLine('authPage');
const moduleSource=async name=>(await readFile(new URL('static/'+name,sourceBase),'utf8')).replace(/^import .*;\n/gm,'').replace(/export /g,'');
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
  const document={body:new Element('body'),documentElement:new Element('html'),hidden:false,activeElement:form.fields.username||null,
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
    projections:new Map(),workspaceMutation:0,workspacePointer:null,pendingDisplayWrites:0,pendingTaskUpdates:new Map(),dataSync:{notify(){}},toast,
    currentWorkContext:()=>state.workContext,workContexts:()=>[{id:'personal'}],updateAccount(){effects.push({kind:'account-updated'});},updateWorkNavigation(){effects.push({kind:'navigation-updated'});},
    cancelChoreography(){},applyDisplayPreferences(){},taskCollection:{clear(){}},libraryUI:{clear(){}},campusUI:{clearSession(){}},chatUI:{clearSession(){}},dialogNavigation:{clear(){}},workspaceProjection:{clear(){}},
    verification:{markup:()=>'',async prove(){return 'verified-proof';}},
    showDialog(title,body){opened.push({title,body});state.dialogRequest++;dialog.open=true;disconnect(form);},
    async route(){routes.push(location.hash);},
    async fetch(url,options){const path=url.replace(/^\/api/,'');requests.push({path,method:options.method||'GET',headers:options.headers,body:options.body,rotationFlagForwarded:Object.hasOwn(options,'rotateSession')});effects.push({kind:'request',path});const answer=request?await request(path,options):{status:200,body:{session}};return {ok:answer.status>=200&&answer.status<300,status:answer.status,headers:{get(){return null;}},async json(){if(answer.jsonError)throw answer.jsonError;return answer.body;}};},
  };
  vm.createContext(sandbox);
  vm.runInContext([requestSource,feedbackSource,authSource,securitySource,pushSource,clearSource,apiSource,errorSource,authPageSource,backgroundSource,refreshSource,
    'globalThis.push=createPushNotifications({state,api,esc,toast});',
    'globalThis.accountSecurity=createAccountSecurity({state,esc,field,api,verification,showDialog,toast});',
    'globalThis.authUI=createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,route,moveSelection,verification});',handlerSource].join('\n'),sandbox);
  const submit=(submitted=form)=>events.get('submit')[0]({target:submitted,submitter:submitted.button,preventDefault(){}});
  return {state,session,location,form,dialog,requests,effects,toasts,opened,routes,sandbox,submit,renderCount:()=>renders,currentForm:()=>currentForm,
    visibleError:()=>currentForm?.isConnected?currentForm.querySelector('.form-error')?.textContent||'':'',
    close(){dialog.open=false;},leave(){dialog.open=false;state.renderId++;location.hash='#tasks';},
    replaceDialog(){state.dialogRequest++;dialog.open=true;disconnect(form);},
  };
}
const response=(status,body)=>({status,body});

const tick=()=>new Promise(resolve=>setImmediate(resolve));
const accepted=(id='owner-a',csrf='rotated-token')=>({user:{id,username:id,verified_contacts:[],profile:{}},csrf});
const outcome=promise=>promise.then(value=>({ok:true,value}),error=>({ok:false,error}));
const observations=[];
test.after(async()=>{if(process.env.ACCOUNT_ROTATION_OBSERVATIONS)await writeFile(process.env.ACCOUNT_ROTATION_OBSERVATIONS,JSON.stringify({scope:'Controlled transport using real delegated submit, API, security factory, feedback and clearSession. No native cookie, layout or CI-causality claim.',observations},null,2)+'\n');});

test('password rotation preserves the busy form across an old read 401 until its real success is delivered',async()=>{
  for(const readStartsFirst of [false,true]){
    const entered=deferred(),release=deferred(),readRelease=deferred(),next=accepted();
    const f=fixture({kind:'security',request:async path=>{
      if(path==='/auth/password'){entered.resolve();await release.promise;return response(200,{session:next});}
      if(path==='/proactive/revision'){await readRelease.promise;return response(401,{detail:'旧会话已过期'});}
      throw Error('Unexpected path '+path);
    }});
    let read;if(readStartsFirst)read=outcome(f.sandbox.api('/proactive/revision'));
    const task=f.submit();await entered.promise;if(!read)read=outcome(f.sandbox.api('/proactive/revision'));
    readRelease.resolve();const rejected=await read;
    const before={owner:f.state.session?.user?.id||null,originalSession:f.state.session===f.session,dialogOpen:f.dialog.open,formConnected:f.form.isConnected,busy:f.form.getAttribute('aria-busy'),readStatus:rejected.error?.status,responseStatus:rejected.error?.responseStatus};
    release.resolve();await task;
    observations.push({case:'held-password-success',readStartsFirst,before,after:{rotated:f.state.session===next,owner:f.state.session?.user?.id||null,requests:f.requests.map(({path,method})=>({path,method})),windowReleased:!f.state.sessionRotation}});
    assert.equal(before.originalSession,true);assert.equal(before.dialogOpen,true);assert.equal(before.formConnected,true);assert.equal(before.busy,'true');
    assert.equal(rejected.ok,false);assert.equal(before.readStatus,409);assert.equal(before.responseStatus,401);assert.equal(rejected.error.detail,'旧会话已过期');
    assert.equal(f.state.session,next);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.requests.length,2);assert.equal(f.requests.filter(x=>x.path==='/auth/password').length,1);
    assert.ok(f.requests.every(x=>x.rotationFlagForwarded===false));
  }
});

test('a late old-session 401 remains a failed read without logging out the accepted password session',async()=>{
  const release=deferred(),next=accepted();
  const f=fixture({kind:'security',request:async path=>path==='/auth/password'?response(200,{session:next}):(await release.promise,response(401,{detail:'旧会话已过期'}))});
  const read=outcome(f.sandbox.api('/proactive/revision'));await f.submit();assert.equal(f.state.session,next);
  release.resolve();const rejected=await read;
  assert.equal(rejected.ok,false);assert.equal(rejected.error.status,409);assert.equal(rejected.error.responseStatus,401);assert.equal(f.state.session,next);assert.notEqual(f.location.hash,'#login');assert.equal(f.requests.length,2);
});

test('the password request own 401 expires the session even after a concurrent read was deferred',async()=>{
  const entered=deferred(),release=deferred();
  const f=fixture({kind:'security',request:async path=>{if(path==='/auth/password'){entered.resolve();await release.promise;}return response(401,{detail:'请先登录，或登录已过期'});}});
  const task=f.submit();await entered.promise;const read=await outcome(f.sandbox.api('/proactive/revision'));
  const retained=f.state.session===f.session;release.resolve();await task;
  assert.equal(retained,true);assert.equal(read.error.status,409);assert.equal(f.state.session,null);assert.equal(f.location.hash,'#login');assert.equal(f.dialog.open,false);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.form.button.disabled,false);
});

test('failed password transport and business responses honor a recorded old 401 and release the window',async()=>{
  for(const failure of ['business','network','abort']){
    const entered=deferred(),release=deferred();
    const f=fixture({kind:'security',request:async path=>{if(path==='/auth/password'){entered.resolve();await release.promise;if(failure==='business')return response(400,{detail:'原密码不正确'});const error=new Error('transport lost');if(failure==='abort')error.name='AbortError';throw error;}return response(401,{detail:'登录已过期'});}});
    const task=f.submit();await entered.promise;const read=await outcome(f.sandbox.api('/proactive/revision'));const retained=f.state.session===f.session;
    release.resolve();await task;
    observations.push({case:'password-failure-after-old401',failure,retainedUntilOutcome:retained,sessionCleared:f.state.session===null,windowReleased:!f.state.sessionRotation,requestCount:f.requests.length});
    assert.equal(retained,true);assert.equal(read.error.status,409);assert.equal(f.state.session,null);assert.equal(f.location.hash,'#login');assert.equal(f.state.sessionRotation,undefined);assert.equal(f.form.inert,false);assert.equal(f.form.button.disabled,false);assert.equal(f.requests.length,2);
  }
});

test('a password failure without an old 401 retains its form and permits one explicit corrected retry',async()=>{
  for(const failure of ['business','network']){
    let count=0;const next=accepted();
    const f=fixture({kind:'security',request:async()=>{if(++count>1)return response(200,{session:next});if(failure==='business')return response(400,{detail:'原密码不正确'});throw Error('offline');}});
    await f.submit();
    assert.equal(f.state.session,f.session);assert.equal(f.form.isConnected,true);assert.equal(f.dialog.open,true);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.form.button.disabled,false);assert.equal(f.requests.length,1);assert.ok(f.visibleError());
    f.form.fields.old_password.value='CorrectedPassword!';await f.submit();assert.equal(f.state.session,next);assert.equal(f.requests.length,2);
  }
});

test('a replaced account, newer same-owner credentials or completed local logout cannot be revived by old password outcomes',async()=>{
  for(const transition of ['other-owner','same-owner-object','same-owner-csrf','local-logout']){
    const entered=deferred(),release=deferred(),readRelease=deferred(),next=accepted();
    const f=fixture({kind:'security',request:async path=>{if(path==='/auth/password'){entered.resolve();await release.promise;return response(200,{session:next});}await readRelease.promise;return response(401,{detail:'旧请求无效'});}});
    const task=f.submit();await entered.promise;const read=outcome(f.sandbox.api('/proactive/revision'));
    let current;
    if(transition==='local-logout'){f.sandbox.clearSession();current=null;}
    else if(transition==='same-owner-csrf'){f.session.csrf='newer-accepted-csrf';current=f.session;}
    else{current=accepted(transition==='other-owner'?'owner-b':'owner-a','newer-accepted-csrf');f.state.session=current;}
    readRelease.resolve();const rejected=await read;release.resolve();await task;
    assert.equal(rejected.error.status,409);assert.equal(rejected.error.responseStatus,401);assert.equal(f.state.session,current);assert.equal(f.opened.length,0);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.requests.length,2);
    observations.push({case:'obsolete-password-outcome',transition,keptCurrentSession:f.state.session===current,successDialogs:f.opened.length,requests:f.requests.length});
  }
});

test('malformed or different-owner password 200 responses cannot be adopted as an authenticated session',async()=>{
  const bodies=[{}, {session:null}, {session:[]}, {session:'invalid'}, {session:{csrf:'value'}}, {session:{user:[],csrf:'value'}}, {session:accepted('owner-b')}, {session:{user:{id:'owner-a'},csrf:null}}, {session:{user:{id:'owner-a'},csrf:3}}, {session:{user:{id:'owner-a'},csrf:' '}}];
  for(const body of bodies){
    const f=fixture({kind:'security',request:async path=>{assert.equal(path,'/auth/password','An invalid success must not fall back to an unrelated session read');return response(200,body);}});
    await f.submit();assert.equal(f.state.session,f.session);assert.equal(f.opened.length,0);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.requests.length,1);assert.equal(f.form.button.disabled,false);assert.match(f.visibleError(),/登录信息未能确认/);
  }
});

test('a password JSON decoding failure releases the window and applies only an already observed expiry',async()=>{
  for(const background of [false,true]){
    const entered=deferred(),release=deferred();
    const f=fixture({kind:'security',request:async path=>{if(path==='/auth/password'){entered.resolve();await release.promise;return {status:200,jsonError:new SyntaxError('invalid response JSON')};}return response(401,{detail:'登录已过期'});}});
    const task=f.submit();await entered.promise;if(background)await outcome(f.sandbox.api('/proactive/revision'));const retained=f.state.session===f.session;release.resolve();await task;
    assert.equal(retained,true);assert.equal(f.state.session,background?null:f.session);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.form.button.disabled,false);assert.equal(f.form.inert,false);assert.equal(f.requests.length,background?2:1);
  }
});

test('an ordinary authenticated GET 401 still clears the current session and closes its private dialog',async()=>{
  const f=fixture({kind:'security',request:async()=>response(401,{detail:'请重新登录'})});
  const rejected=await outcome(f.sandbox.api('/proactive/revision'));
  assert.equal(rejected.error.status,401);assert.equal(f.state.session,null);assert.equal(f.dialog.open,false);assert.equal(f.form.isConnected,false);assert.equal(f.location.hash,'#login');assert.equal(f.requests.length,1);
});

test('session rotation is restricted to an authenticated password POST and never enabled by contact binding',async()=>{
  for(const [path,method,flag,kind] of [['/account/contacts','POST',true,'security'],['/auth/password','GET',true,'security'],['/auth/password','POST','true','security'],['/auth/password','POST',true,'login']]){
    const f=fixture({kind,request:async()=>response(200,{ok:true})});const rejected=await outcome(f.sandbox.api(path,{method,rotateSession:flag,json:{}}));
    assert.equal(rejected.ok,false);assert.equal(f.requests.length,0);assert.equal(f.state.sessionRotation,undefined);
  }
  let f,windowDuringContact;f=fixture({kind:'security',request:async path=>{if(path==='/account/contacts'){windowDuringContact=f.state.sessionRotation;return response(200,{ok:true});}assert.equal(path,'/session');return response(200,accepted());}});
  f.form.id='contact-form';await f.submit();assert.equal(windowDuringContact,undefined);assert.deepEqual(f.requests.map(x=>x.path),['/account/contacts','/session']);assert.equal(f.state.session.user.id,'owner-a');
});

test('a second password form cannot start a competing rotation while the first write is pending',async()=>{
  const entered=deferred(),release=deferred(),next=accepted();
  const f=fixture({kind:'security',request:async()=>{entered.resolve();await release.promise;return response(200,{session:next});}});
  const first=f.submit();await entered.promise;
  const other=new Form('password-form',{old_password:'CurrentPassword!',new_password:'OtherPassword2026!'});other.parentElement=f.dialog;f.dialog.children.push(other);
  const second=f.submit(other);await tick();const sentWhilePending=f.requests.length,secondUnlocked=!other.button.disabled,secondError=other.querySelector('.form-error')?.textContent||'';
  release.resolve();await Promise.all([first,second]);
  assert.equal(sentWhilePending,1);assert.equal(secondUnlocked,true);assert.match(secondError,/正在更新/);assert.equal(f.requests.length,1);assert.equal(f.state.session,next);assert.equal(f.state.sessionRotation,undefined);
});

test('a newer same-owner session accepted between atomic rotation and security continuation is never overwritten',async()=>{
  const next=accepted(),newer=accepted('owner-a','newer-after-rotation');let adoptedBeforeNotify=false;
  const f=fixture({kind:'security',request:async()=>response(200,{session:next})});
  f.sandbox.dataSync.notify=()=>{adoptedBeforeNotify=f.state.session===next;queueMicrotask(()=>{f.state.session=newer;});};
  await f.submit();
  observations.push({case:'same-owner-microtask',adoptedBeforeNotify,newerRetained:f.state.session===newer,dialogs:f.opened.length,toasts:f.toasts.length});
  assert.equal(adoptedBeforeNotify,true);assert.equal(f.state.session,newer);assert.equal(f.opened.length,0);assert.equal(f.toasts.length,0);assert.equal(f.state.sessionRotation,undefined);assert.equal(f.requests.length,1);
});

test('a real account refresh of the exact password credentials preserves its newer profile and confirms that rotation only',async()=>{
  const repetitions=[];
  for(const variant of ['same-object','new-object','different-csrf','different-owner']){
    const entered=deferred(),release=deferred(),next=accepted(),fresh=accepted(variant==='different-owner'?'owner-b':'owner-a',variant==='different-csrf'?'unrelated-current-csrf':next.csrf);
    next.user.profile={college:'profile at password commit'};fresh.user.profile={college:'newer profile from account refresh'};
    const f=fixture({kind:'security',request:async path=>{if(path==='/auth/password'){entered.resolve();await release.promise;return response(200,{session:next});}assert.equal(path,'/session');return response(200,fresh);}});
    const task=f.submit();await entered.promise;
    const refreshApplied=await f.sandbox.refreshWorkspace(new Set(['account']),{account:2});
    assert.equal(refreshApplied,false,'The real dialog guard prevents a background repaint after the account refresh');
    assert.equal(f.state.session,f.session,'refreshWorkspace actually updates the captured session object in place');
    assert.equal(f.state.session.csrf,fresh.csrf);assert.equal(f.state.session.user.profile,fresh.user.profile);
    assert.ok(f.effects.some(x=>x.kind==='account-updated'));assert.ok(f.effects.some(x=>x.kind==='navigation-updated'));
    if(variant==='new-object')f.state.session={...f.state.session};
    const current=f.state.session,profile=current.user.profile;
    let second=null,attempt=null;
    if(variant==='same-object'||variant==='new-object'){
      const form=new Form('password-form',{old_password:'NextPassword2026!',new_password:'AnotherPassword2026!'});form.parentElement=f.dialog;f.dialog.children.push(form);
      let settled=false;second=f.submit(form).finally(()=>{settled=true;});await tick();
      attempt={variant,requestsWhilePending:f.requests.length,secondSettled:settled,secondUnlocked:!form.button.disabled,error:form.querySelector('.form-error')?.textContent||''};
      repetitions.push(attempt);
    }
    release.resolve();await Promise.all([task,...(second?[second]:[])]);
    const confirmed=f.toasts.some(x=>!x.error&&x.message.includes('账号安全信息已更新'));
    observations.push({case:'account-refresh-during-password',variant,refreshApplied,currentObjectPreserved:f.state.session===current,newerProfilePreserved:f.state.session?.user?.profile===profile,confirmed,duplicateAttempt:attempt,requests:f.requests.map(x=>({path:x.path,method:x.method}))});
    assert.equal(f.state.session,current);assert.equal(f.state.session.user.profile,profile);assert.equal(profile.college,'newer profile from account refresh');
    assert.equal(confirmed,variant==='same-object'||variant==='new-object');assert.equal(f.opened.length,confirmed?1:0);assert.equal(f.state.sessionRotation,undefined);
    if(attempt)attempt.completedPaths=f.requests.map(x=>x.path);else assert.deepEqual(f.requests.map(x=>x.path),['/auth/password','/session']);
    assert.equal(next.user.profile.college,'profile at password commit','The original response body is not rewritten');
  }
  for(const attempt of repetitions){
    assert.equal(attempt.requestsWhilePending,2,attempt.variant+' must keep one password POST pending alongside its account read');
    assert.equal(attempt.secondSettled,true);assert.equal(attempt.secondUnlocked,true);assert.match(attempt.error,/正在更新/);
    assert.deepEqual(attempt.completedPaths,['/auth/password','/session']);
  }
});
