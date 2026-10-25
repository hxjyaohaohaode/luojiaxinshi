import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {setImmediate as tick} from 'node:timers/promises';
import {createPushNotifications,pushUnavailable,decodePublicKey,localPushDevice,deliveryText} from '../static/push-notifications.js';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const settle=async()=>{for(let i=0;i<12;i++)await tick();};
test('capability, current device and delivery labels do not overstate availability or receipt',()=>{
 assert.match(pushUnavailable({isSecureContext:false}),/HTTPS/);
 assert.match(pushUnavailable({isSecureContext:true,navigator:{}}),/不支持/);
 assert.equal(pushUnavailable({isSecureContext:true,navigator:{serviceWorker:{}},PushManager(){},Notification(){}}),'');
 assert.deepEqual([...decodePublicKey('AQID-_8')],[1,2,3,251,255]);
 assert.equal(localPushDevice({enabled:true,devices:[{endpoint:'elsewhere',enabled:1}]},{endpoint:'local'}),null);
 assert.equal(localPushDevice({devices:[{endpoint:'local',enabled:0}]},{endpoint:'local'}),null);
 assert.match(deliveryText({state:'accepted'}),/尚不能确认/);
});
function harness(t,{postWait=null,deleteFails=false}={}){
 const names=['document','location','navigator','isSecureContext','Notification','PushManager','MessageChannel','CustomEvent'];const saved=names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]);
 const doc=new EventTarget();doc.querySelector=()=>null;doc.hidden=false;
 let binding={enabled:false,user_id:null},sub=null,permissionRequests=0,registrations=0,subscribes=0,unsubscribes=0;
 const posts=[],toasts=[],session={user:{id:'alice'}};const state={session};
 const subscription={endpoint:'https://push.services.mozilla.com/test',toJSON(){return {endpoint:this.endpoint,keys:{p256dh:'pub',auth:'secret'}};},async unsubscribe(){unsubscribes++;sub=null;return true;}};
 const worker={scriptURL:'https://campus.example/notification-worker.js',state:'activated',postMessage(msg,ports){if(msg.type==='CAMPUS_PUSH_ENABLE')binding={enabled:true,user_id:msg.user_id};else if(msg.type==='CAMPUS_PUSH_DISABLE'&&(!binding.user_id||binding.user_id===msg.user_id))binding={enabled:false,user_id:null};queueMicrotask(()=>ports[0].postMessage({ok:true,binding}));}};
 const reg={active:worker,pushManager:{async getSubscription(){return sub;},async subscribe(){subscribes++;sub=subscription;return sub;}},async unregister(){}};
 class Channel{constructor(){this.port1={onmessage:null,close(){}};this.port2={postMessage:data=>this.port1.onmessage?.({data})};}}
 function Notice(){}Notice.permission='granted';Notice.requestPermission=async()=>{permissionRequests++;return 'granted';};
 const values={document:doc,location:{origin:'https://campus.example'},navigator:{serviceWorker:{async getRegistration(){return registrations?reg:null;},async register(){registrations++;return reg;}}},isSecureContext:true,Notification:Notice,PushManager:function(){},MessageChannel:Channel,CustomEvent:class extends Event{constructor(type,o){super(type);this.detail=o.detail;}}};
 for(const [name,value] of Object.entries(values))Object.defineProperty(globalThis,name,{value,writable:true,configurable:true});
 const api=async(path,options)=>{if(options){posts.push({path,...options});if(options.method==='POST'&&path==='/push/subscriptions'&&postWait)await postWait.promise;if(options.method==='DELETE'&&deleteFails)throw Error('offline');return {};}
 if(path==='/push/config')return {supported:true,public_key:'AQID'};
 if(path==='/push/status')return {enabled:sub!==null,devices:sub?[{endpoint:sub.endpoint,enabled:1}]:[]};throw Error(path);};
 const push=createPushNotifications({state,api,esc:String,toast:(...x)=>toasts.push(x)});
 const click=action=>{const control={disabled:false,dataset:{pushAction:action}};const event=new Event('click');Object.defineProperty(event,'target',{value:{closest:()=>control}});doc.dispatchEvent(event);};
 t.after(async()=>{push.stop();await settle();for(const [name,descriptor] of saved)descriptor?Object.defineProperty(globalThis,name,descriptor):delete globalThis[name];});
 return {push,state,posts,click,Notice,get binding(){return binding;},counts:()=>({permissionRequests,registrations,subscribes,unsubscribes})};
}
test('starting only reads status; enabling and test delivery require explicit buttons',async t=>{
 const h=harness(t);h.push.start();await h.push.refresh();assert.deepEqual(h.counts(),{permissionRequests:0,registrations:0,subscribes:0,unsubscribes:0});assert.equal(h.posts.length,0);
 h.click('enable');await settle();assert.equal(h.push.enabled(),true);assert.equal(h.binding.user_id,'alice');assert.equal(h.posts.filter(x=>x.path==='/push/test').length,0);
 h.click('test');await settle();assert.equal(h.posts.filter(x=>x.path==='/push/test').length,1);assert.match(h.push.markup(),/排队不代表已经送达/);
});
test('logout revokes local display and subscription even if backend deletion fails',async t=>{
 const h=harness(t,{deleteFails:true});h.push.start();await h.push.refresh();h.click('enable');await settle();await h.push.detachForLogout();assert.equal(h.binding.enabled,false);assert.equal(h.push.enabled(),false);assert.equal(h.counts().unsubscribes,1);
});
test('a late subscription save cannot re-enable delivery after logout',async t=>{
 const hold=deferred(),h=harness(t,{postWait:hold});h.push.start();await h.push.refresh();h.click('enable');await settle();assert.equal(h.posts.length,1);
 await h.push.detachForLogout();hold.resolve();await settle();assert.equal(h.binding.enabled,false);assert.equal(h.push.enabled(),false);
});
test('permission refusal remains off and produces a recoverable state',async t=>{
 const h=harness(t);h.Notice.permission='default';h.Notice.requestPermission=async()=>'denied';h.push.start();await h.push.refresh();h.click('enable');await settle();assert.equal(h.push.enabled(),false);assert.equal(h.counts().subscribes,0);assert.match(h.push.markup(),/网站设置/);
});
async function workerHarness(){
 const code=await fs.readFile(new URL('../static/notification-worker.js',import.meta.url),'utf8'),handlers={},values=new Map(),shown=[],opened=[];let sessionUser='alice';
 const db={close(){},transaction(){const tx={objectStore(){return {get(key){const req={};queueMicrotask(()=>{req.result=values.get(key);req.onsuccess();});return req;},put(value,key){values.set(key,value);queueMicrotask(()=>tx.oncomplete());}};}};return tx;}};
 const ctx={URL,Promise,Error,String,queueMicrotask,indexedDB:{open(){const req={};queueMicrotask(()=>{req.result=db;req.onsuccess();});return req;}},fetch:async()=>({ok:true,json:async()=>({user:{id:sessionUser}})}),self:{location:{origin:'https://campus.example'},addEventListener:(type,handler)=>handlers[type]=handler,registration:{showNotification:async(title,options)=>shown.push({title,options}),getNotifications:async()=>shown.map(item=>({close(){item.closed=true;}}))},clients:{matchAll:async()=>[],openWindow:async url=>opened.push(url)}}};vm.createContext(ctx);vm.runInContext(code,ctx);
 const send=async(type,data={})=>{let pending;const replies=[];handlers[type]({...data,waitUntil:promise=>pending=promise});await pending;return replies;};
 const message=async(type,user_id)=>{let reply;await send('message',{source:{url:'https://campus.example/'},data:{type,user_id},ports:[{postMessage:r=>reply=r}]});return reply;};
 const push=payload=>send('push',{data:{json:()=>payload}});
 return {message,push,shown,opened,send,setUser:id=>sessionUser=id};
}
test('worker suppresses unbound and cross-account payloads, and closes existing notifications on logout',async()=>{
 const w=await workerHarness(),payload={user_id:'alice',title:'提醒',body:'办理资料',url:'/#tasks/one'};
 await w.push(payload);assert.equal(w.shown.length,0);
 assert.equal((await w.message('CAMPUS_PUSH_ENABLE','alice')).ok,true);await w.push({...payload,user_id:'bob'});assert.equal(w.shown.length,0);
 await w.push(payload);assert.equal(w.shown.length,1);await w.message('CAMPUS_PUSH_DISABLE','alice');assert.equal(w.shown[0].closed,true);await w.push(payload);assert.equal(w.shown.length,1);
});
test('worker verifies enable identity and normalizes external notification destinations',async()=>{
 const w=await workerHarness();assert.equal((await w.message('CAMPUS_PUSH_ENABLE','bob')).ok,false);await w.message('CAMPUS_PUSH_ENABLE','alice');await w.push({user_id:'alice',url:'https://evil.example/steal'});assert.equal(w.shown[0].options.data.url,'https://campus.example/#dashboard');
 let closed=false;await w.send('notificationclick',{notification:{data:w.shown[0].options.data,close(){closed=true;}}});assert.equal(closed,true);assert.deepEqual(w.opened,['https://campus.example/#dashboard']);
 await w.message('CAMPUS_PUSH_DISABLE','alice');await w.send('notificationclick',{notification:{data:w.shown[0].options.data,close(){}}});assert.equal(w.opened.length,1);
});
