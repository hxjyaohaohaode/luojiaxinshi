/* Real routes and UI, with a synthetic source reader in push_preview_server.py. */
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/source-inbox-browser');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()}),page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
page.setDefaultTimeout(10000);
const report={synthetic:true,external_source_requests:0,live_model_calls:0,checks:[],errors:[]};page.on('pageerror',e=>report.errors.push(e.message));
const api=(url,method='GET',json=null)=>page.evaluate(async({url,method,json})=>{const session=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api'+url,{method,headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf,...(json?{'Content-Type':'application/json'}:{})},...(json?{body:JSON.stringify(json)}:{})});if(!r.ok)throw Error(await r.text());return r.json();},{url,method,json});
const check=async(title,fn)=>{await fn();report.checks.push({title,passed:true});};
const go=async route=>{await page.goto(origin+'/#'+route);await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').inert,route);};
let sid,nid;
try{
 await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.waitForURL(/#dashboard/);
 const name='合成学院来源 '+Date.now();
 await check('the source form enables a persistent website subscription',async()=>{
  await go('sources');await page.locator('[data-source-action=add]').first().click();const f=page.locator('[data-workspace-form=source-catalog]');await f.locator('[name=name]').fill(name);await f.locator('[name=url]').fill('https://notice-fixture.example/notices/');await f.locator('[type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  sid=(await api('/source-catalog')).find(s=>s.data.name===name).id;await page.locator(`[data-source-record="${sid}"]>summary`).click();await page.locator(`[data-source-action=sync-config][data-id="${sid}"]`).click();await page.locator('[name=article_path_prefix]').fill('/info/');await page.locator('[data-workspace-form=source-sync] [type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});assert.equal((await api('/source-subscriptions')).find(s=>s.source_id===sid).enabled,true);
 });
 await check('refresh receives source content and routes it to needs verification without making tasks',async()=>{
  const request=page.waitForResponse(r=>r.url().endsWith('/'+sid+'/refresh'));await page.locator(`[data-source-action=sync-refresh][data-id="${sid}"]`).click();assert.equal((await request).status(),200);
  const n=(await api('/notices')).find(n=>n.source_label===name);assert.ok(n);nid=n.id;assert.equal(n.intent,'verify');assert.equal(n.task_count,0);
  await go('notices');await page.locator('[data-library-intent=verify]').click();await page.locator(`.notice-card[href="#notice/${nid}"]`).waitFor();assert.equal(await page.locator('[data-library-status=received]').isVisible(),false);await page.locator('.library-refine>summary').click();await page.locator('[data-library-status=received]').click();await page.locator(`.notice-card[href="#notice/${nid}"]`).waitFor();await page.locator('.library-refine>summary').click();await page.screenshot({path:path.join(out,'personal-inbox.png')});
 });
 await check('source correction stays on the same notice and presents a review action',async()=>{
  const before=await api('/notices/'+nid);await api('/fixture/source-version','POST',{});await api('/source-catalog/'+sid+'/refresh','POST',{});const after=await api('/notices/'+nid);assert.ok(after.version>before.version);assert.equal(after.tasks.length,0);assert.ok(after.intake_updates.some(u=>u.state==='pending'));
  await go('notice/'+nid);await page.locator('[data-action=intake-update-review]').first().waitFor();await page.screenshot({path:path.join(out,'source-update.png')});
 });
 await check('pausing the source persists and unconfigured channels stay visibly unavailable',async()=>{
  await go('sources');const card=page.locator(`[data-source-record="${sid}"]`);if(!await card.evaluate(n=>n.open))await card.locator('summary').click();await page.locator(`[data-source-action=sync-config][data-id="${sid}"]`).click();await page.locator('[data-workspace-form=source-sync] [name=enabled]').uncheck();await page.locator('[data-workspace-form=source-sync] [type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});assert.equal((await api('/source-subscriptions')).find(s=>s.source_id===sid).enabled,false);
  await page.locator('[data-source-action=platforms]').click();await page.locator('#integration-cards').waitFor();assert.equal(await page.locator('[data-source-action=qq-group]').count(),0);assert.equal(await page.locator('[data-source-action=publisher-sync]').count(),0);assert.match(await page.locator('#integration-cards').innerText(),/还没开通/);
 });
 await check('personal action filters remain usable at phone width and a short viewport',async()=>{
  await page.keyboard.press('Escape');await go('notices');for(const [width,height] of [[320,620],[390,844],[390,350]]){await page.setViewportSize({width,height});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);const filters=await page.locator('[data-library-intent]').evaluateAll(nodes=>nodes.map(n=>({height:n.getBoundingClientRect().height,clipped:n.scrollWidth>n.clientWidth+1,labelClipped:n.querySelector(':scope>span').scrollWidth>n.querySelector(':scope>span').clientWidth+1})));assert.ok(filters.every(f=>f.height>=44&&!f.clipped&&!f.labelClipped),JSON.stringify(filters));await page.locator('[data-library-intent=verify]').click();await page.locator(`.notice-card[href="#notice/${nid}"]`).waitFor();if(height===844)await page.screenshot({path:path.join(out,'personal-inbox-phone.png')});}await page.screenshot({path:path.join(out,'personal-inbox-mobile.png')});
 });
}catch(error){report.errors.push(error.stack);await page.screenshot({path:path.join(out,'failure.png')});process.exitCode=1;}
finally{await browser.close();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
