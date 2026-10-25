/* No offline cache. A persisted account binding prevents shared-device leakage. */
const DB_NAME='campus-push-binding',STORE='settings';
let serial=Promise.resolve();
function enqueue(work){const next=serial.catch(()=>{}).then(work);serial=next;return next;}
function database(){return new Promise((resolve,reject)=>{const request=indexedDB.open(DB_NAME,1);request.onupgradeneeded=()=>request.result.createObjectStore(STORE);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});}
async function readBinding(){const db=await database();try{return await new Promise((resolve,reject)=>{const tx=db.transaction(STORE,'readonly'),req=tx.objectStore(STORE).get('binding');req.onsuccess=()=>resolve(req.result||{enabled:false,user_id:null});req.onerror=()=>reject(req.error);});}finally{db.close();}}
async function writeBinding(binding){const db=await database();try{await new Promise((resolve,reject)=>{const tx=db.transaction(STORE,'readwrite');tx.objectStore(STORE).put(binding,'binding');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('推送状态未保存'));});}finally{db.close();}}
function safeUrl(value){try{const url=new URL(value||'/#dashboard',self.location.origin);return url.origin===self.location.origin&&url.pathname==='/'?url.href:self.location.origin+'/#dashboard';}catch{return self.location.origin+'/#dashboard';}}
async function closeNotifications(){for(const notice of await self.registration.getNotifications())notice.close();}
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('message',event=>{
  if(!event.data?.type?.startsWith('CAMPUS_PUSH_'))return;
  event.waitUntil(enqueue(async()=>{
    const source=event.source;if(!source?.url||new URL(source.url).origin!==self.location.origin)throw Error('来源不匹配');
    let binding=await readBinding();
    if(event.data.type==='CAMPUS_PUSH_ENABLE'){
      if(typeof event.data.user_id!=='string'||!event.data.user_id)throw Error('账号缺失');
      // The cookie-backed endpoint verifies the binding, including after a tab switches account.
      const response=await fetch('/api/session',{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('请重新登录');const session=await response.json();if(session.user?.id!==event.data.user_id)throw Error('账号已变化');
      binding={enabled:true,user_id:event.data.user_id};await writeBinding(binding);
    }else if(event.data.type==='CAMPUS_PUSH_DISABLE'){
      if(!event.data.user_id||binding.user_id===event.data.user_id){binding={enabled:false,user_id:null};await writeBinding(binding);await closeNotifications();}
    }
    event.ports[0]?.postMessage({ok:true,binding});
  }).catch(error=>event.ports[0]?.postMessage({ok:false,error:error.message})));
});
self.addEventListener('push',event=>event.waitUntil(enqueue(async()=>{
  let payload;try{payload=event.data?.json();}catch{return;}
  const binding=await readBinding();if(!binding.enabled||!payload||payload.user_id!==binding.user_id)return;
  await self.registration.showNotification(String(payload.title||'珞珈信使').slice(0,100),{body:String(payload.body||'').slice(0,300),tag:String(payload.tag||'campus-notice').slice(0,200),icon:'/static/assets/campus-notice-icon-v4-64.png',data:{url:safeUrl(payload.url),user_id:binding.user_id}});
}).catch(()=>{})));
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(enqueue(async()=>{
  const binding=await readBinding();if(!binding.enabled||event.notification.data?.user_id!==binding.user_id)return;
  const url=safeUrl(event.notification.data?.url),windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  const client=windows.find(client=>new URL(client.url).origin===self.location.origin);
  if(client){await client.navigate(url);await client.focus();}else await self.clients.openWindow(url);
}).catch(()=>{}));});
