/** Measurable visual regressions, with screenshots for human review.
 * These assertions are bounds/alignment checks, not a claim about aesthetics.
 * Only the loopback synthetic fixture is used. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/visual-review-browser');
await fs.mkdir(out,{recursive:true});
const report={fixture:'Synthetic local data only; measurements do not replace visual review',checks:[],errors:[],measurements:[]};
for(const engine of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',')){
 console.log('Visual review: '+engine);
 const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
 const page=await browser.newPage({viewport:{width:1413,height:871},locale:'en-US',timezoneId:'America/Los_Angeles'});page.setDefaultTimeout(12000);page.setDefaultNavigationTimeout(45000);
 page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
 const settle=()=>page.evaluate(async()=>{await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));await Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
 const resize=async(width,height=871)=>{await page.setViewportSize({width,height});await page.waitForFunction(({width,height})=>innerWidth===width&&innerHeight===height&&Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--visual-height'))-height)<2,{width,height});await settle();};
 const nav=async route=>{await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});await page.locator('#content:not([inert])').waitFor();await settle();};
 const capture=async name=>{if(engine==='chromium')await page.screenshot({path:path.join(out,name+'.png')});};
 const check=async(name,fn)=>{try{await fn();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.message});console.log('FAIL',engine,name,error.message);await page.screenshot({path:path.join(out,engine+'-'+report.checks.length+'-failure.png')}).catch(()=>{});}};
 try{
  await page.goto(origin+'/#login',{waitUntil:'domcontentloaded'});await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
  await nav('dashboard');
  await check('priority card aligns status and title, keeps its deadline time and first action visible',async()=>{
   const b=await page.locator('#overview-focus').evaluate(n=>{const title=n.querySelector('h2').getBoundingClientRect(),label=n.querySelector('.focus-label').getBoundingClientRect(),card=n.getBoundingClientRect(),action=n.querySelector('[data-workflow-task]').getBoundingClientRect();return {title:title.toJSON(),label:label.toJSON(),card:card.toJSON(),action:action.toJSON(),text:n.textContent};});
   assert.ok(Math.abs(b.title.left-b.label.left)<2,JSON.stringify(b));assert.ok(b.card.height<240,JSON.stringify(b));assert.match(b.text,/17:00/);assert.ok(b.action.right<=b.card.right&&b.action.bottom<=b.card.bottom);
   report.measurements.push({engine,page:'dashboard',width:1413,focusHeight:b.card.height});await capture('dashboard-1413');
  });
  await check('priority switching does not clip a long title or lose its action',async()=>{
   for(let i=0;i<3;i++){const next=page.locator('[data-focus-step="1"]');if(!await next.isEnabled())break;await next.click();await settle();}
   const bounds=await page.locator('#overview-focus').evaluate(n=>{const c=n.getBoundingClientRect(),h=n.querySelector('h2').getBoundingClientRect(),b=n.querySelector('[data-workflow-task]').getBoundingClientRect();return {c:c.toJSON(),h:h.toJSON(),b:b.toJSON()};});
   assert.ok(bounds.h.right<=bounds.c.right&&bounds.b.left>=bounds.h.right,JSON.stringify(bounds));
  });
  for(const width of [1413,1024,768,390,320]){
   await resize(width,width<500?844:871);await nav('dashboard');
   await check('dashboard adapts its summary and keeps actions in the first screen at '+width,async()=>{
    const b=await page.evaluate(()=>{const rect=s=>document.querySelector(s).getBoundingClientRect().toJSON();return {focus:rect('#overview-focus'),metrics:rect('#action-metrics'),week:rect('#overview-week'),firstTask:rect('#overview-items .task-row'),overflow:document.documentElement.scrollWidth>innerWidth+1,metricsCount:document.querySelectorAll('.action-metric').length,focusAction:rect('#overview-focus [data-workflow-task]')};});
    assert.equal(b.overflow,false);assert.equal(b.metricsCount,4);assert.ok(b.firstTask.top<page.viewportSize().height-100,JSON.stringify(b));
    assert.ok(b.focusAction.right<=b.focus.right+1&&b.focusAction.bottom<=b.focus.bottom+1,JSON.stringify(b));
    report.measurements.push({engine,page:'dashboard-density',width,...b});await capture('dashboard-'+width);
   });
  }
  for(const width of [1413,1024,390,320]){
   await resize(width,width<500?844:871);await nav('tasks');
   await check('task controls share a row and leave the first task reachable at '+width,async()=>{
    const b=await page.evaluate(()=>{const input=document.querySelector('#task-search').getBoundingClientRect(),add=document.querySelector('.task-page-heading>a').getBoundingClientRect(),task=document.querySelector('#task-results .task-row').getBoundingClientRect();return {input:input.toJSON(),add:add.toJSON(),task:task.toJSON(),overflow:document.documentElement.scrollWidth>innerWidth+1};});
    assert.equal(b.overflow,false);assert.ok(Math.abs((b.input.top+b.input.height/2)-(b.add.top+b.add.height/2))<3,JSON.stringify(b));assert.ok(b.input.width>=150&&b.input.right<=b.add.left,JSON.stringify(b));assert.ok(b.task.top<(width<500?340:390),JSON.stringify(b));
    report.measurements.push({engine,page:'tasks',width,firstTaskTop:b.task.top});if([1413,390].includes(width))await capture('tasks-'+width);
   });
   await check('search, status and view switching preserve user input at '+width,async()=>{
    await page.locator('#task-search').fill('申请');await page.locator('[data-filter=all]').click();await page.locator('[data-task-view=list]').click();assert.equal(await page.locator('#task-search').inputValue(),'申请');assert.ok(await page.locator('#task-results .task-row').count()>0);await page.locator('#task-search').fill('');await page.locator('[data-task-view=board]').click();
   });
  }
  await check('a pending memory index refreshes automatically without acknowledging unread entries',async()=>{
   let firstStatus=true,firstEntries=true,watermarkSent=false,entryBeforeWatermark=false;
   const statusRoute='**/api/memory/tree/status',entriesRoute='**/api/memory/tree/entries?*';
   await page.route(statusRoute,async route=>{
    const response=await route.fetch(),data=await response.json();
    if(firstStatus){firstStatus=false;await route.fulfill({response,json:{...data,token:data.token+':pending-fixture',jobs:{queued:1}}});watermarkSent=true;}
    else await route.fulfill({response});
   });
   await page.route(entriesRoute,async route=>{
    const response=await route.fetch(),data=await response.json();
    if(firstEntries){firstEntries=false;entryBeforeWatermark=!watermarkSent;await route.fulfill({response,json:{...data,memories:[],passages:[],order:[],matched:0,total:0}});}
    else await route.fulfill({response});
   });
   try{
    await resize(1413);await nav('memory');
    await page.locator('[data-tree-record]').first().waitFor({timeout:4000});
    assert.equal(firstStatus,false);assert.equal(firstEntries,false);assert.equal(entryBeforeWatermark,false);
   }finally{await page.unroute(statusRoute);await page.unroute(entriesRoute);}
  });
  for(const [width,side] of [[1413,234],[1024,380],[390,234],[320,234]]){
   await resize(width,width<500?844:871);await nav('memory');await page.waitForFunction(()=>!document.querySelector('.memory-tree-main')?.matches('[aria-busy=true]'));
   if(width>850){await page.locator('.sidebar-resize').focus();await page.keyboard.press(side===380?'End':'Home');await settle();}
   else {await page.locator('[data-tree-action=toggle-nav]').click();await settle();}
   await check('directory heading remains one line with separate action targets at '+width,async()=>{
    const m=await page.locator('.memory-tree-nav-title').evaluate(n=>{const title=n.querySelector('strong'),r=title.getBoundingClientRect(),buttons=[...n.querySelectorAll('button')].map(x=>x.getBoundingClientRect().toJSON()),line=parseFloat(getComputedStyle(title).lineHeight);return {title:r.toJSON(),buttons,line};});
    assert.ok(m.title.height<m.line*1.5,JSON.stringify(m));assert.ok(m.title.right<=m.buttons[0].left&&m.buttons[0].right<=m.buttons[1].left,JSON.stringify(m));
   });
   if(width<500)await page.locator('[data-tree-action=toggle-nav]').click();
   await check('memory fills parent and opens full original content without clipped controls at '+width,async()=>{
    const b=await page.locator('#memory-shell').evaluate(n=>{const r=n.getBoundingClientRect(),p=n.parentElement,s=getComputedStyle(p);return {w:r.width,available:p.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight),overflow:document.documentElement.scrollWidth>innerWidth+1};});assert.equal(b.overflow,false);assert.ok(Math.abs(b.w-b.available)<2);
    assert.equal(await page.locator('#memory-detail-pane').isVisible(),false);const row=page.locator('[data-tree-record]').first();await row.click();await page.locator('#memory-detail-pane:not([hidden])').waitFor();await settle();assert.ok((await page.locator('.memory-detail-text').innerText()).length>0);await page.locator('[data-tree-action=close-detail]').click();await settle();assert.equal(await page.locator('#memory-detail-pane').isVisible(),false);if([1413,390].includes(width))await capture('memory-'+width);
   });
  }
  await check('memory dates stay readable in an English browser outside the campus timezone',async()=>{
   const rows=await page.locator('.memory-row-time').evaluateAll(nodes=>nodes.map(n=>({day:n.textContent,full:n.title})));
   assert.ok(rows.length>0);for(const row of rows){assert.match(row.day,/^\d{4}\/\d{2}\/\d{2}$/);assert.ok(row.full.startsWith(row.day+' '));}
  });
  await resize(1413);await nav('sources');
  await check('source actions align with search without a separate empty heading row',async()=>{
   const b=await page.locator('.source-toolbar').evaluate(n=>{const search=n.querySelector('.record-search-line').getBoundingClientRect(),add=n.querySelector('[data-source-action=add]').getBoundingClientRect();return {search:search.toJSON(),add:add.toJSON()};});assert.ok(Math.abs(b.search.top-b.add.top)<2,JSON.stringify(b));await capture('sources-1413');
  });
  await resize(390,844);await nav('sources');
  await check('source editor opens from its entry and Escape returns to its trigger',async()=>{
   const preset=page.locator('[data-source-action=preset][data-id=website]'),trigger=await preset.count()?preset:page.locator('.source-toolbar>[data-source-action=add]');
   await trigger.click();await page.locator('[data-workspace-form=source-catalog]').waitFor();assert.equal(await page.locator('[data-workspace-form=source-catalog] [name=platform]').inputValue(),'website');await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});await settle();assert.equal(await trigger.evaluate(n=>n===document.activeElement),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await capture('sources-390');
  });
 }catch(error){report.errors.push({engine,error:error.message});console.log('ERROR',engine,error.message);}
 finally{await browser.close();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,failures:report.checks.filter(x=>!x.ok),errors:report.errors},null,2));
if(report.checks.some(x=>!x.ok)||report.errors.length)process.exitCode=1;
