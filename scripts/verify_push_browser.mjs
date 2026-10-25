/* Real application APIs and Service Worker; only browser subscription/provider delivery are simulated. */
import {chromium} from 'playwright';
import {createECDH,randomBytes} from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/push-browser');await fs.mkdir(out,{recursive:true});
const report={synthetic:true,external_push_requests:0,real_device_delivery_verified:false,checks:[],errors:[]};
const ecdh=createECDH('prime256v1');ecdh.generateKeys();const keys={p256dh:ecdh.getPublicKey().toString('base64url'),auth:randomBytes(16).toString('base64url')};
const browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()}),context=await browser.newContext({permissions:['notifications'],viewport:{width:1440,height:900}});
await context.addInitScript(({keys})=>{
 const key='synthetic.push.subscription';window.__pushCalls={subscribe:0,permission:0};
 const restore=()=>{const raw=localStorage.getItem(key);if(!raw)return null;const value=JSON.parse(raw);return {...value,toJSON:()=>value,async unsubscribe(){localStorage.removeItem(key);return true;}};};
 PushManager.prototype.getSubscription=async()=>restore();
 PushManager.prototype.subscribe=async()=>{window.__pushCalls.subscribe++;localStorage.setItem(key,JSON.stringify({endpoint:'https://push.services.mozilla.com/synthetic-'+crypto.randomUUID(),keys}));return restore();};
},{keys});
let deviceId=null;let page=await context.newPage();page.setDefaultTimeout(10000);const attach=()=>page.on('pageerror',error=>report.errors.push(error.message));attach();
const check=async(title,fn)=>{try{await fn();report.checks.push({title,passed:true});}catch(error){report.checks.push({title,passed:false,error:error.message});await page.screenshot({path:path.join(out,'failure.png')});throw error;}};
const waitReady=()=>page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='dashboard'&&!document.querySelector('#content').inert);
const login=async()=>{await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await waitReady();};
const open=async()=>{await page.locator('.reminder-bell').click();await page.locator('[data-push-settings]').waitFor();await page.waitForFunction(()=>!document.querySelector('[data-push-settings]').textContent.includes('正在读取'));};
const binding=()=>page.evaluate(async()=>{const reg=await navigator.serviceWorker.getRegistration('/');if(!reg)return null;return new Promise((resolve,reject)=>{const ch=new MessageChannel(),timer=setTimeout(()=>reject(Error('Worker timeout')),5000);ch.port1.onmessage=e=>{clearTimeout(timer);ch.port1.close();resolve(e.data.binding);};reg.active.postMessage({type:'CAMPUS_PUSH_STATUS'},[ch.port2]);});});
try{
 await login();
 await page.evaluate(async()=>{const session=await fetch('/api/session').then(r=>r.json()),status=await fetch('/api/push/status').then(r=>r.json());for(const device of status.devices){const r=await fetch('/api/push/subscriptions',{method:'DELETE',headers:{'Content-Type':'application/json','X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf},body:JSON.stringify({endpoint:device.endpoint})});if(!r.ok)throw Error(await r.text());}});
 await check('initial login never subscribes or registers a worker',async()=>{await open();assert.equal(await page.evaluate(()=>window.__pushCalls.subscribe),0);assert.equal(await page.evaluate(async()=> (await navigator.serviceWorker.getRegistrations()).length),0);assert.match(await page.locator('[data-push-settings]').innerText(),/本机未开启/);});
 await check('explicit opt-in stores the real API device and the worker account binding',async()=>{await page.locator('[data-push-action=enable]').click();await page.locator('[data-push-action=test]').waitFor();assert.equal((await binding()).enabled,true);const status=await page.evaluate(()=>fetch('/api/push/status').then(r=>r.json()));assert.equal(status.devices.length,1);deviceId=status.devices[0].id;assert.equal(status.enabled,true);});
 await check('only the test button requests a test and labels it queued',async()=>{let calls=0;page.on('request',r=>{if(r.url().endsWith('/push/test'))calls++;});assert.equal(calls,0);const response=page.waitForResponse(r=>r.url().endsWith('/push/test'));await page.locator('[data-push-action=test]').click();assert.equal((await response).status(),202);await page.getByText(/测试提醒已排队/).waitFor();assert.equal(calls,1);});
 await check('account binding persists after closing and reopening the application page',async()=>{await page.close();page=await context.newPage();page.setDefaultTimeout(10000);attach();await page.goto(origin+'/#dashboard');await waitReady();await open();await page.locator('[data-push-action=test]').waitFor();assert.equal((await binding()).enabled,true);await page.screenshot({path:path.join(out,'enabled.png')});});
 await check('the real API worker records simulated provider acceptance without a device-received claim',async()=>{
   // The browser polling predicate is synchronous in this Playwright version;
   // passing an async predicate can finish on a truthy Promise before delivery.
   const deadline=Date.now()+25000;let accepted=false;
   while(Date.now()<deadline){accepted=await page.evaluate(async deviceId=>{const data=await fetch('/api/fixture/push-deliveries',{cache:'no-store'}).then(r=>r.json()),status=await fetch('/api/push/status',{cache:'no-store'}).then(r=>r.json());return data.synthetic&&data.deliveries.some(item=>item.device_id===deviceId)&&status.devices.some(item=>item.id===deviceId&&item.last_success);},deviceId);if(accepted)break;await new Promise(resolve=>setTimeout(resolve,300));}
   assert.equal(accepted,true,'the background worker must actually record the simulated provider response');
   await page.locator('[data-push-action=refresh]').click();await page.getByText(/本机最近一次已交给推送服务/).waitFor();
 });
 await check('narrow reminder settings remain reachable without horizontal overflow',async()=>{for(const [width,height] of [[390,700],[390,350]]){await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await page.locator('[data-push-action=disable]').scrollIntoViewIfNeeded();assert.equal(await page.locator('[data-push-action=disable]').isVisible(),true);}await page.setViewportSize({width:1440,height:900});});
 await check('logout revokes the local subscription and worker binding before ending the session',async()=>{await page.keyboard.press('Escape');await page.locator('[data-action=logout]').click();await page.locator('#auth-form').waitFor();assert.equal((await binding()).enabled,false);assert.equal(await page.evaluate(()=>localStorage.getItem('synthetic.push.subscription')),null);});
 await check('logging back in keeps this device off until another explicit opt-in',async()=>{await login();await open();assert.match(await page.locator('[data-push-settings]').innerText(),/本机未开启/);const status=await page.evaluate(()=>fetch('/api/push/status').then(r=>r.json()));assert.equal(status.devices.length,0);});
}catch(error){console.error(error.stack);}finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify(report,null,2));if(report.checks.some(c=>!c.passed)||report.errors.length||report.checks.length!==8)process.exitCode=1;
