import {browserExecutable} from './browser-runtime.mjs';
/* Synthetic accounts, real API and rendered controls. No model or external delivery. */
import {chromium,firefox,webkit} from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/notice-matters-browser');await fs.mkdir(out,{recursive:true});
const report={synthetic:true,live_model_calls:0,external_messages:0,checks:[],errors:[],observations:{grouping:[]}};
const observationJobs=new Set();
const bounded=async(promise,label)=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(label+' did not complete within 12000ms')),12000);})]);}finally{clearTimeout(timer);}};
const pageQuery=(request,query)=>{const url=new URL(request.url());return request.method()==='GET'&&url.origin===origin&&url.pathname==='/api/notices/page'&&url.searchParams.get('q')===query&&!url.searchParams.has('cursor');};
async function groupingObservation(page,engine,mode,query,ids){
 const evidence={engine,mode,query,notice_ids:ids,status:'running',requests:[],responses:[],snapshots:[],events:[],dropped_events:0,clock_domains:{network:'Node Date.now milliseconds',dom:'document performance.now milliseconds'}};
 report.observations.grouping.push(evidence);
 const keys=new WeakMap(),pending=new Set(),endings=new Map();let sequence=0,stopped=false,queryObserved;
 const queryReceipt=new Promise(resolve=>{queryObserved=resolve;});
 const relevant=request=>{const url=new URL(request.url());return url.origin===origin&&url.pathname==='/api/notices/page';};
 const key=request=>{if(!keys.has(request))keys.set(request,++sequence);return keys.get(request);};
 const onRequest=request=>{if(!relevant(request))return;const id=key(request);let finish;const promise=new Promise(resolve=>{finish=resolve;});endings.set(id,{promise,finish});evidence.requests.push({id,at:Date.now(),method:request.method(),url:request.url()});};
 const onFailure=request=>{if(!keys.has(request))return;const id=key(request);evidence.requests.push({id,at:Date.now(),event:'requestfailed',error:request.failure()?.errorText||'unknown'});endings.get(id)?.finish();};
 const onFinished=request=>{if(!keys.has(request))return;const id=key(request);evidence.requests.push({id,at:Date.now(),event:'requestfinished'});endings.get(id)?.finish();};
 const onResponse=response=>{
  const request=response.request();if(!keys.has(request))return;
  const receipt={request_id:key(request),at:Date.now(),url:response.url(),status:response.status(),body_state:'pending'};evidence.responses.push(receipt);
  const work=(async()=>{try{const raw=await response.body();receipt.body_state='complete';receipt.body_sha256=createHash('sha256').update(raw).digest('hex');try{const data=JSON.parse(raw.toString('utf8'));receipt.parse_state='json';receipt.filters=data.filters||null;receipt.total=data.total??null;receipt.items=Array.isArray(data.items)?data.items.map(n=>({id:n.id,version:n.version,matter:n.matter?{id:n.matter.id,title:n.matter.title,member_count:n.matter.member_count}:null})):null;receipt.detail=data.detail||null;}catch(error){receipt.parse_state='invalid_json';receipt.parse_error=error.message;}}catch(error){receipt.body_state='unavailable';receipt.error=error.message;}finally{if(pageQuery(request,query)&&receipt.body_state==='complete')queryObserved(receipt);}})();
  pending.add(work);observationJobs.add(work);work.finally(()=>{pending.delete(work);observationJobs.delete(work);});
 };
 page.on('request',onRequest);page.on('requestfailed',onFailure);page.on('requestfinished',onFinished);page.on('response',onResponse);
 await page.evaluate(()=>{
  const reference=document.querySelector('[data-library-group]'),events=[],limit=160;
  const rect=node=>{if(!node)return null;const r=node.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height};};
  const button=()=>{const node=document.querySelector('[data-library-group]');return node?{present:true,count:document.querySelectorAll('[data-library-group]').length,same_node:node===reference,connected:node.isConnected,hidden:node.hidden,disabled:node.disabled,pressed:node.getAttribute('aria-pressed'),display:getComputedStyle(node).display,visibility:getComputedStyle(node).visibility,rect:rect(node),ancestors:[...function*(n){for(let p=n.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')yield{open:p.open,className:p.className};}(node)]}:{present:false};};
  const snapshot=phase=>{const results=document.querySelector('#library-results'),groups=[...document.querySelectorAll('.matter-library-card')].map(n=>({title:n.querySelector('a')?.textContent||'',member_ids:[...n.querySelectorAll('li a[href^="#notice/"]')].map(a=>a.getAttribute('href').slice(8))})),individuals=[...document.querySelectorAll('a.notice-card[href^="#notice/"]')].map(a=>a.getAttribute('href').slice(8));return{phase,at:performance.now(),route:location.hash,query:document.querySelector('#library-search')?.value||'',busy:results?.getAttribute('aria-busy')??null,count:document.querySelector('#library-count')?.textContent||'',button:button(),groups,individual_ids:individuals,record_ids:[...new Set([...individuals,...groups.flatMap(g=>g.member_ids)])].sort()};};
  const state={reference,events,dropped:0,stage:'initial',snapshot,button,listener:null};
  state.listener=event=>{if(!document.querySelector('#content')?.contains(event.target))return;if(events.length>=limit){state.dropped++;return;}const target=event.target instanceof Element?event.target:null,control=target?.closest('[data-library-group]'),item={type:event.type,at:performance.now(),stage:state.stage,isTrusted:event.isTrusted,target:{tag:target?.tagName||'',id:target?.id||'',className:typeof target?.className==='string'?target.className:'',text:(target?.textContent||'').slice(0,120),connected:!!target?.isConnected,rect:rect(target)},group_target:!!control,same_reference:control===reference,x:event.clientX??null,y:event.clientY??null,pressed_at_capture:button().pressed??null};events.push(item);queueMicrotask(()=>{item.pressed_after_dispatch=button().pressed??null;item.reference_connected_after_dispatch=!!reference?.isConnected;});};
  for(const type of ['pointerdown','pointerup','click','input'])document.addEventListener(type,state.listener,true);
  window.__noticeMatterObservation=state;
 });
 evidence.service_worker_controller=await page.evaluate(()=>navigator.serviceWorker?.controller?.scriptURL||null);
 const capture=async phase=>{const value=await page.evaluate(phase=>{const state=window.__noticeMatterObservation;state.stage=phase;return state.snapshot(phase);},phase);evidence.snapshots.push(value);return value;};
 const stop=async()=>{
  if(stopped)return;stopped=true;page.off('request',onRequest);const errors=[];
  try{const observed=await page.evaluate(()=>{const state=window.__noticeMatterObservation;if(!state)return null;const final=state.snapshot('observer-final');for(const type of ['pointerdown','pointerup','click','input'])document.removeEventListener(type,state.listener,true);const result={events:state.events,dropped_events:state.dropped,final};delete window.__noticeMatterObservation;return result;});if(observed){evidence.events=observed.events;evidence.dropped_events=observed.dropped_events;evidence.snapshots.push(observed.final);}}catch(error){errors.push(error);}
  try{await bounded(Promise.allSettled([...endings.values()].map(e=>e.promise)),'Grouping request completion');await bounded(Promise.allSettled([...pending]),'Grouping response body observations');}catch(error){errors.push(error);}
  finally{page.off('requestfailed',onFailure);page.off('requestfinished',onFinished);page.off('response',onResponse);evidence.pending_response_reads=pending.size;}
  if(errors.length){evidence.cleanup_errors=errors.map(e=>e.message);throw errors[0];}
 };
 return{evidence,capture,queryReceipt,stop,requestKey:key};
}
function assertGroupControl(snapshot,pressed){const b=snapshot.button;assert.equal(b.count,1);assert.equal(b.same_node,true);assert.equal(b.connected,true);assert.equal(b.hidden,false);assert.equal(b.disabled,false);assert.equal(b.pressed,pressed);assert.notEqual(b.display,'none');assert.notEqual(b.visibility,'hidden');assert.ok(b.rect.width>0&&b.rect.height>0);assert.ok(b.ancestors.every(n=>n.open));}
async function assertSettledGrouping(page,receipt,ids,grouped){
 assert.equal(receipt.status,200);assert.equal(receipt.body_state,'complete');assert.equal(receipt.parse_state,'json');assert.equal(receipt.filters?.q,new URL(receipt.url).searchParams.get('q'));assert.deepEqual(receipt.items.map(n=>n.id).sort(),[...ids].sort());
 await page.waitForFunction(({ids,grouped})=>{const results=document.querySelector('#library-results'),button=document.querySelector('[data-library-group]');const actual=[...new Set([...document.querySelectorAll('a.notice-card[href^="#notice/"],.matter-library-card li a[href^="#notice/"]')].map(a=>a.getAttribute('href').slice(8)))].sort();return results?.getAttribute('aria-busy')==='false'&&button?.getAttribute('aria-pressed')===String(grouped)&&JSON.stringify(actual)===JSON.stringify([...ids].sort());},{ids,grouped});
}
function validateQueryReceipts(probe,ids){
 const evidence=probe.evidence,requests=evidence.requests.filter(r=>r.method==='GET'&&new URL(r.url).searchParams.get('q')===evidence.query&&!new URL(r.url).searchParams.has('cursor'));
 const wanted=new Set(requests.map(r=>r.id)),receipts=evidence.responses.filter(r=>wanted.has(r.request_id)),completed=receipts.filter(r=>r.body_state==='complete');
 const cancelled=id=>evidence.requests.some(r=>r.id===id&&r.event==='requestfailed'&&/abort|cancel/i.test(r.error));
 assert.ok(completed.length>0,'At least one actual complete query response is required');
 for(const receipt of completed){assert.equal(receipt.status,200);assert.equal(receipt.parse_state,'json');assert.equal(receipt.filters?.q,evidence.query);assert.deepEqual(receipt.items.map(n=>n.id).sort(),[...ids].sort());}
 for(const request of requests)if(!completed.some(r=>r.request_id===request.id))assert.ok(cancelled(request.id),'An incomplete query must have an actual cancellation receipt: '+request.id);
 evidence.query_receipts={completed:completed.map(r=>r.request_id),cancelled:requests.filter(r=>cancelled(r.id)).map(r=>r.id)};
 return{completed,cancelled};
}
async function controlledGrouping(browser,engine,tag,a,b,c,owner){
 const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(12000);
 const pageErrors=[];page.on('pageerror',error=>{pageErrors.push(error.message);report.errors.push({browser:engine,scope:'controlled-grouping',message:error.message});process.exitCode=1;});
 let probe,release,captured;const gate=new Promise(resolve=>{release=resolve;}),capturedResponse=new Promise(resolve=>{captured=resolve;}),jobs=new Set();
 const hold={release_requested:false,entries:[]};
 const matcher=url=>url.origin===origin&&url.pathname==='/api/notices/page'&&url.searchParams.get('q')===tag&&!url.searchParams.has('cursor');
 const handler=route=>{
  if(route.request().method()!=='GET'||hold.release_requested)return route.continue();
  const entry={request_id:probe.requestKey(route.request()),request_url:route.request().url(),request_at:Date.now(),handler_entered:true,response_captured:false,fulfillment_completed:false};hold.entries.push(entry);
  const work=(async()=>{try{const response=await route.fetch({timeout:12000}),raw=await response.body();entry.response_status=response.status();entry.body_sha256=createHash('sha256').update(raw).digest('hex');entry.response_captured=true;try{const data=JSON.parse(raw.toString('utf8'));entry.response_ids=(data.items||[]).map(n=>n.id);entry.parse_state='json';}catch(error){entry.parse_state='invalid_json';entry.parse_error=error.message;}captured(entry);await gate;entry.release_at=Date.now();try{await route.fulfill({response});entry.fulfillment_completed=true;}catch(error){entry.fulfillment_error=error.message;}}catch(error){entry.fetch_error=error.message;await route.abort().catch(()=>{});}finally{entry.finished_at=Date.now();}})();
  jobs.add(work);work.finally(()=>jobs.delete(work));return work;
 };
 let routed=false,primaryError=null;
 try{
  await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.waitForURL(/#dashboard/);
  const session=await context.request.get(origin+'/api/session');assert.equal(session.status(),200);const controlledOwner=(await session.json()).user;assert.equal(controlledOwner.username,'workflow.demo');assert.equal(controlledOwner.id,owner.id);
  await page.goto(origin+'/#notices');await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='notices'&&!document.querySelector('#content').inert);
  await page.locator('.matter-library-card').filter({hasText:'奖学金申请与补充 '+tag}).waitFor();
  const control=page.locator('[data-library-group]');while(await control.locator('xpath=ancestor::details[not(@open)]').count())await control.locator('xpath=ancestor::details[not(@open)]').first().locator(':scope>summary').click();await control.waitFor();
  probe=await groupingObservation(page,engine,'controlled-real-response-hold',tag,[a.id,b.id,c.id]);probe.evidence.hold=hold;probe.evidence.page_errors=pageErrors;probe.evidence.owner={id:controlledOwner.id,username:controlledOwner.username};assert.equal(probe.evidence.service_worker_controller,null);
  const initial=await probe.capture('before-controlled-query');assertGroupControl(initial,'true');assert.notEqual(initial.query,tag);
  await page.route(matcher,handler);routed=true;
  const [first]=await Promise.all([bounded(capturedResponse,'Real query handler capture'),page.locator('#library-search').fill(tag)]);
  assert.equal(first.response_status,200);assert.equal(first.parse_state,'json');assert.deepEqual([...first.response_ids].sort(),[a.id,b.id,c.id].sort());
  const loading=await probe.capture('held-query-before-click');assert.equal(loading.busy,'true');assert.equal(loading.record_ids.length,0);assert.equal(hold.release_requested,false);assertGroupControl(loading,'true');
  await control.click();const clicked=await probe.capture('held-query-after-single-click');assertGroupControl(clicked,'false');assert.equal(clicked.busy,'true');assert.equal(clicked.record_ids.length,0);assert.equal(hold.release_requested,false);
  hold.release_requested=true;release();
  const [receipt]=await Promise.all([bounded(probe.queryReceipt,'Controlled complete query receipt'),bounded(Promise.allSettled([...jobs]),'Held query fulfillment')]);await assertSettledGrouping(page,receipt,[a.id,b.id,c.id],false);
  await page.locator(`a.notice-card[href="#notice/${a.id}"]`).waitFor();await page.locator(`a.notice-card[href="#notice/${b.id}"]`).waitFor();
  assertGroupControl(await probe.capture('released-individuals-before-restore'),'false');await control.click();assertGroupControl(await probe.capture('after-controlled-restore'),'true');
  await page.locator('.matter-library-card').filter({hasText:tag}).waitFor();await assertSettledGrouping(page,receipt,[a.id,b.id,c.id],true);
  await probe.stop();const receipts=validateQueryReceipts(probe,[a.id,b.id,c.id]);
  for(const entry of hold.entries){
   if(entry.response_captured){assert.equal(entry.response_status,200);assert.equal(entry.parse_state,'json');assert.deepEqual([...entry.response_ids].sort(),[a.id,b.id,c.id].sort());}
   const delivered=receipts.completed.find(r=>r.request_id===entry.request_id);
   if(delivered){assert.equal(entry.fulfillment_completed,true);assert.equal(delivered.body_sha256,entry.body_sha256);entry.browser_outcome='delivered';}
   else{assert.ok(receipts.cancelled(entry.request_id),'An undelivered held response must have an actual cancellation receipt');entry.browser_outcome='cancelled';}
  }
  assert.ok(hold.entries.some(e=>e.response_captured));
  const clicks=probe.evidence.events.filter(e=>e.type==='click'&&e.group_target);probe.evidence.group_clicks=clicks.length;
  assert.equal(clicks.length,2);assert.equal(clicks.filter(e=>e.stage==='held-query-before-click').length,1);assert.equal(pageErrors.length,0);
  probe.evidence.status='passed';
 }catch(error){primaryError=error;if(probe){probe.evidence.status='failed';probe.evidence.error=error.stack;await probe.capture('controlled-failure').catch(()=>{});}await page.screenshot({path:path.join(out,engine+'-controlled-grouping-failure.png')}).catch(()=>{});throw error;}
 finally{
  hold.release_requested=true;release();const cleanup=[];
  for(const action of [()=>bounded(Promise.allSettled([...jobs]),'Controlled query handlers during cleanup'),()=>probe?.stop(),()=>routed?page.unroute(matcher,handler):null,()=>context.close()]){try{await action();}catch(error){cleanup.push(error);}}
  if(cleanup.length){if(probe){probe.evidence.cleanup_errors=cleanup.map(e=>e.message);probe.evidence.status='failed';}if(!primaryError)throw cleanup[0];}
 }
}
for(const [name,engine] of Object.entries({chromium,firefox,webkit})){
 const browser=await engine.launch({headless:true,executablePath:browserExecutable(engine)}),page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
 page.setDefaultTimeout(12000);page.on('pageerror',e=>report.errors.push({browser:name,message:e.message}));
 const check=async(title,fn)=>{await fn();report.checks.push({browser:name,title,passed:true});};
 const api=(url,method='GET',json=null)=>page.evaluate(async({url,method,json})=>{const s=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api'+url,{method,headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':s.csrf,...(json?{'Content-Type':'application/json'}:{})},...(json?{body:JSON.stringify(json)}:{})});if(!r.ok)throw Error(await r.text());return r.json();},{url,method,json});
 const go=async route=>{await page.goto(origin+'/#'+route);await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').inert,route);if(route.startsWith('notice/')){const context=page.locator('.notice-context');if(!await context.evaluate(n=>n.open))await context.locator(':scope>summary').click();}};
 const reveal=async(selector)=>{const control=page.locator(selector).first();await control.waitFor({state:'attached'});while(await control.locator('xpath=ancestor::details[not(@open)]').count())await control.locator('xpath=ancestor::details[not(@open)]').first().locator(':scope>summary').click();await control.waitFor();return control;};
 const receive=title=>page.evaluate(async title=>{const s=await fetch('/api/session').then(r=>r.json());const data=new FormData();data.set('title',title);data.set('materials_complete','true');data.set('body',title+'，请按学院要求核对材料并办理。');const r=await fetch('/api/notices',{method:'POST',headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':s.csrf},body:data});if(!r.ok)throw Error(await r.text());return r.json();},title);
 try{
  await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.waitForURL(/#dashboard/);
  const ownerResponse=await page.context().request.get(origin+'/api/session');assert.equal(ownerResponse.status(),200);const owner=(await ownerResponse.json()).user;assert.equal(owner.username,'workflow.demo');
  const tag=name+' '+Date.now(),a=await receive('2026年本科生综合奖学金申报通知 '+tag),b=await receive('2026年本科生综合奖学金申报补充通知 '+tag),c=await receive('2025年本科生综合奖学金申报通知 '+tag);
  for(const [n,due] of [[a,'2027-10-20'],[b,'2027-10-23']]){
   const draft=await api('/notices/'+n.id+'/manual','POST',{version:n.version});
   await api('/notices/'+n.id+'/confirm','POST',{version:draft.version,reviewed:true,tasks:[{title:'提交申请 '+name,due_date:due,due_time:'17:00',deadline_confirmed:true,deadline_text:due+' 17:00 前',resolution_note:'合成验收已核对日期与材料',materials:['申请表'],submission:'学院办公室',notes:'个人计划保留'}]});
  }
  await check('capacity screen reports effective campus limits and current usage',async()=>{
   await go('settings');await page.locator('[data-settings-category=account]').click();await page.locator('[data-action=account-usage]').click();await page.locator('#dialog-title').filter({hasText:'账号容量'}).waitFor();const text=await page.locator('#dialog').innerText();assert.match(text,/10,000/);assert.match(text,/10\.00 GB/);await page.keyboard.press('Escape');
  });
  await check('related notices are review candidates; a different year is excluded',async()=>{
   await go('notice/'+a.id);await page.locator('#notice-matters details').waitFor();await page.locator('#notice-matters summary').click();await page.locator(`[data-matter-review="${b.id}"]`).waitFor();assert.equal(await page.locator(`[data-matter-review="${c.id}"]`).count(),0);assert.equal((await api('/notices/'+a.id+'/matter')).group,null);
  });
  await check('preview shows both originals and confirms grouping through the form',async()=>{
   await page.locator(`[data-matter-review="${b.id}"]`).click();const form=page.locator('#matter-confirm-form');await form.waitFor();assert.equal(await form.locator('.matter-member').count(),2);assert.match(await form.innerText(),/2027-10-20 17:00/);assert.match(await form.innerText(),/2027-10-23 17:00/);assert.match(await form.innerText(),/申请表/);await form.locator('[name=title]').fill('奖学金申请与补充 '+tag);await form.locator('[type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('#notice-matters .matter-member').length===2);assert.equal((await api('/notices/'+a.id+'/matter')).group.members.length,2);await page.screenshot({path:path.join(out,name+'-matter.png')});
  });
  await check('library groups related notices and can switch back to individual records',async()=>{
   await go('notices');const probe=await groupingObservation(page,name,'normal-service-worker-environment',tag,[a.id,b.id,c.id]);probe.evidence.owner={id:owner.id,username:owner.username};let primaryError=null;
   try{
    await probe.capture('before-normal-query');await page.locator('#library-search').fill(tag);await page.locator('.matter-library-card').filter({hasText:'奖学金申请与补充 '+tag}).waitFor();
    await probe.capture('before-first-click');await (await reveal('[data-library-group]')).click();assertGroupControl(await probe.capture('after-first-click'),'false');
    await page.locator(`a.notice-card[href="#notice/${a.id}"]`).waitFor();await page.locator(`a.notice-card[href="#notice/${b.id}"]`).waitFor();
    await probe.capture('before-second-click');await (await reveal('[data-library-group]')).click();assertGroupControl(await probe.capture('after-second-click'),'true');
    await page.locator('.matter-library-card').filter({hasText:tag}).waitFor();
    const receipt=await bounded(probe.queryReceipt,'Normal query receipt after the original toggle sequence');await assertSettledGrouping(page,receipt,[a.id,b.id,c.id],true);await page.locator('.matter-library-card').filter({hasText:tag}).waitFor();await probe.capture('normal-final-query-applied');
    await probe.stop();validateQueryReceipts(probe,[a.id,b.id,c.id]);const clicks=probe.evidence.events.filter(e=>e.type==='click'&&e.group_target);probe.evidence.group_clicks=clicks.length;assert.equal(clicks.length,2);probe.evidence.status='passed';
   }catch(error){primaryError=error;probe.evidence.status='failed';probe.evidence.error=error.stack;await probe.capture('normal-failure').catch(()=>{});throw error;}
   finally{try{await probe.stop();}catch(error){probe.evidence.cleanup_errors||=[];probe.evidence.cleanup_errors.push(error.message);if(!primaryError)throw error;}}
   await controlledGrouping(browser,name,tag,a,b,c,owner);
  });
  await check('an intervening task edit rejects the stale preview and offers a fresh review',async()=>{
   await go('notice/'+a.id);await page.locator('[data-matter-choose]').click();await page.locator('#matter-notice-search').fill(tag);await page.locator(`#matter-notice-options [data-id="${c.id}"]`).click();await page.locator('#matter-confirm-form').waitFor();
   const current=(await api('/notices/'+a.id)).tasks[0];await api('/tasks/'+current.id,'PUT',{version:current.version,data:{...current.data,notes:'模拟另一窗口已更新个人备注'},status:current.status,reason:'隔离夹具中的并发修改验证'});
   await page.locator('#matter-confirm-form [type=submit]').click();await page.getByRole('button',{name:'重新核对',exact:true}).waitFor();assert.equal((await api('/notices/'+a.id+'/matter')).group.members.length,2);
   const fresh=page.waitForResponse(r=>r.url().endsWith('/matter/preview'));await page.getByRole('button',{name:'重新核对',exact:true}).click();assert.equal((await fresh).status(),200);await page.getByRole('button',{name:'确认归入同一事项',exact:true}).waitFor();
   await page.keyboard.press('Escape');await page.locator('#matter-confirm-form').waitFor({state:'hidden'});await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});
  });
  await check('detail and confirmation remain usable on mobile and with keyboard-height viewport',async()=>{
   for(const [width,height] of [[320,620],[390,350]]){
    await page.setViewportSize({width,height});await go('notice/'+a.id);await page.locator('#notice-matters .matter-member').first().waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
    await page.locator('[data-matter-choose]').click();await page.locator('#matter-notice-search').fill(tag);assert.equal(await page.locator(`#matter-notice-options [data-id="${b.id}"]`).count(),0);await page.locator(`#matter-notice-options [data-id="${c.id}"]`).click();await page.locator('#matter-confirm-form').waitFor();assert.match(await page.locator('#matter-confirm-form').innerText(),/不同年份/);assert.equal(await page.evaluate(()=>document.querySelector('#dialog').scrollWidth>document.querySelector('#dialog').clientWidth+2),false);await page.screenshot({path:path.join(out,name+`-preview-${width}-${height}.png`)});await page.keyboard.press('Escape');await page.locator('#matter-confirm-form').waitFor({state:'hidden'});if(await page.locator('#dialog').isVisible()){await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});}
   }
  });
  await check('moving one notice out dissolves a two-member group and preserves both notices',async()=>{
   await page.setViewportSize({width:1440,height:900});await go('notice/'+a.id);await page.locator('[data-matter-remove]').click();await page.waitForFunction(()=>!document.querySelector('#notice-matters [data-matter-remove]')&&!!document.querySelector('#notice-matters details'));assert.equal((await api('/notices/'+a.id+'/matter')).group,null);assert.equal((await api('/notices/'+b.id+'/matter')).group,null);assert.equal((await api('/notices/'+a.id)).id,a.id);assert.equal((await api('/notices/'+b.id)).id,b.id);
  });
 }catch(error){report.errors.push({browser:name,message:error.stack});await page.screenshot({path:path.join(out,name+'-failure.png')});process.exitCode=1;}
 finally{await browser.close();}
}
try{await bounded(Promise.allSettled([...observationJobs]),'All grouping response diagnostics');assert.equal(observationJobs.size,0);}catch(error){report.errors.push({scope:'grouping-diagnostics',message:error.stack});process.exitCode=1;}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
