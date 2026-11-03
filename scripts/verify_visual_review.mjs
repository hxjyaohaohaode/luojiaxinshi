// Fault-injection routes must reach Playwright; actual workers are exercised by verify_push_browser.mjs.
/** Measurable visual regressions, with screenshots for human review.
 * These assertions are bounds/alignment checks, not a claim about aesthetics.
 * Only the loopback synthetic fixture is used. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin=process.env.VISUAL_BASE_URL||'http://127.0.0.1:8786',out=path.resolve('artifacts/visual-review-browser');
await fs.mkdir(out,{recursive:true});
const report={fixture:'Synthetic local data only; measurements do not replace visual review',checks:[],errors:[],measurements:[]};
for(const engine of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',')){
 console.log('Visual review: '+engine);
 const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
 const page=await browser.newPage({serviceWorkers:'block',viewport:{width:1413,height:871},locale:'en-US',timezoneId:'America/Los_Angeles'});page.setDefaultTimeout(12000);page.setDefaultNavigationTimeout(45000);
 page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
 const settle=async()=>{await page.waitForFunction(()=>!document.getAnimations().some(a=>a.playState==='running'&&a.effect?.getTiming().iterations!==Infinity&&a.effect?.target?.getClientRects?.().length&&a.effect?.target?.checkVisibility?.()!==false&&!a.effect?.target?.closest('#toast')));await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));};
 const resize=async(width,height=871)=>{await page.setViewportSize({width,height});await page.waitForFunction(({width,height})=>innerWidth===width&&innerHeight===height&&Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--visual-height'))-height)<2,{width,height});await settle();};
 const nav=async route=>{await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});await page.waitForFunction(route=>{const content=document.querySelector('#content'),rendered=content?.dataset.page;return content&&!content.inert&&rendered===location.hash.slice(1)&&(rendered===route||route==='chat'&&rendered?.startsWith('chat/'));},route);await settle();};
 const capture=async name=>{if(engine==='chromium')await page.screenshot({path:path.join(out,name+'.png')});};
 const check=async(name,fn)=>{try{await fn();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.message});console.log('FAIL',engine,name,error.message);await page.screenshot({path:path.join(out,engine+'-'+report.checks.length+'-failure.png')}).catch(()=>{});}};
 try{
  await page.goto(origin+'/#login',{waitUntil:'domcontentloaded'});await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
  await nav('dashboard');
  await check('compact home keeps the first real task aligned and actionable',async()=>{
   const b=await page.locator('#overview-items .task-row').first().evaluate(n=>{const row=n.getBoundingClientRect(),title=n.querySelector('.task-title').getBoundingClientRect(),action=n.querySelector('[data-workflow-task]').getBoundingClientRect();return {row:row.toJSON(),title:title.toJSON(),action:action.toJSON()};});
   assert.ok(b.row.height<180,JSON.stringify(b));assert.ok(b.title.left>=b.row.left&&b.title.right<=b.row.right+1,JSON.stringify(b));assert.ok(b.action.right<=b.row.right+1&&b.action.bottom<=b.row.bottom+1,JSON.stringify(b));
   report.measurements.push({engine,page:'dashboard',width:1413,firstTaskHeight:b.row.height});await capture('dashboard-1413');
  });
  await check('home task and notice tabs work with pointer and keyboard without duplicate workbenches',async()=>{
   await page.locator('[data-overview-section=notices]').click();assert.equal(await page.locator('[data-overview-section=notices]').getAttribute('aria-selected'),'true');
   await page.locator('[data-overview-section=notices]').focus();await page.keyboard.press('Home');assert.equal(await page.locator('[data-overview-section=tasks]').getAttribute('aria-selected'),'true');
   assert.equal(await page.locator('.personal-home').count(),1);assert.equal(await page.locator('.home-tabs [aria-selected=true]').count(),1);
  });
  for(const width of [1413,1024,768,390,320]){
   await resize(width,width<500?844:871);await nav('dashboard');
   await check('dashboard summary stays compact and real actions appear in the first screen at '+width,async()=>{
    const b=await page.evaluate(()=>{const rect=s=>document.querySelector(s).getBoundingClientRect().toJSON();return {heading:rect('.home-heading'),counts:rect('.home-counts'),firstTask:rect('#overview-items .task-row'),action:rect('#overview-items [data-workflow-task]'),overflow:document.documentElement.scrollWidth>innerWidth+1,metricsCount:document.querySelectorAll('.home-counts>a').length};});
    assert.equal(b.overflow,false);assert.equal(b.metricsCount,3);assert.ok(b.heading.height<100&&b.counts.height<80,JSON.stringify(b));assert.ok(b.firstTask.top<page.viewportSize().height-100,JSON.stringify(b));
    assert.ok(b.action.right<=b.firstTask.right+1&&b.action.bottom<=b.firstTask.bottom+1,JSON.stringify(b));
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
    await page.locator('#task-search').fill('申请');if(await page.locator('#task-status-select').isVisible())await page.locator('#task-status-select').selectOption('all');else await page.locator('[data-filter=all]').click();await page.locator('[data-task-view=list]').click();assert.equal(await page.locator('#task-search').inputValue(),'申请');assert.ok(await page.locator('#task-results .task-row').count()>0);await page.locator('#task-search').fill('');await page.locator('[data-task-view=board]').click();
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
   const trigger=page.locator('.source-toolbar [data-source-action=add]');
   await trigger.click();await page.locator('[data-workspace-form=source-catalog]').waitFor();assert.equal(await page.locator('[data-workspace-form=source-catalog] [name=platform]').inputValue(),'website');await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});await settle();assert.equal(await trigger.evaluate(n=>n===document.activeElement),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await capture('sources-390');
  });
  await check('bare chat restores the selected conversation through its canonical route',async()=>{
   const title='合成布局恢复 '+engine;
   const id=await page.evaluate(async title=>{const session=await fetch('/api/session').then(r=>r.json());const response=await fetch('/api/conversations',{method:'POST',headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf,'Content-Type':'application/json'},body:JSON.stringify({title})});if(!response.ok)throw Error(await response.text());return (await response.json()).id;},title);
   await nav('chat/'+id);await nav('sources');await nav('chat');
   assert.equal(new URL(page.url()).hash,'#chat/'+id);assert.equal(await page.locator('#conversation-title').innerText(),title);
  });
  for(const width of [390,320])for(const route of ['dashboard','tasks','notices','calendar','insights','sources','settings','new','chat','memory']){
   await resize(width,844);await nav(route);
   await check('mobile '+route+' keeps content and primary controls inside '+width,async()=>{
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    if(route==='chat'){
     const geometry=await page.locator('.chat-heading').evaluate(h=>{const clip=h.getBoundingClientRect(),title=h.querySelector('h1').getBoundingClientRect();return {clip:clip.toJSON(),title:title.toJSON(),buttons:[...h.querySelectorAll('[data-chat-action]')].map(b=>{const r=b.getBoundingClientRect(),i=b.querySelector('svg').getBoundingClientRect();return {action:b.dataset.chatAction,rect:r.toJSON(),rightEdgeReceivesPointer:b.contains(document.elementFromPoint(r.right-2,r.top+r.height/2)),iconRight:i.right};})};});
     assert.equal(geometry.buttons.length,3);
     for(const b of geometry.buttons){assert.ok(b.rect.left>=geometry.clip.left-.5&&b.rect.right<=geometry.clip.right+.5&&b.rect.width>=32,JSON.stringify({width,...geometry}));assert.equal(b.rightEdgeReceivesPointer,true,JSON.stringify(b));}
     assert.ok(geometry.title.right<=geometry.buttons[0].rect.left+.5,JSON.stringify(geometry));
     const materials=page.locator('.chat-heading [data-chat-action=toggle-materials]'),box=await materials.boundingBox();
     await materials.click({position:{x:box.width-2,y:box.height/2}});assert.equal(await materials.getAttribute('aria-expanded'),'true');
     await page.keyboard.press('Escape');assert.equal(await materials.getAttribute('aria-expanded'),'false');await settle();
    }
    if(route==='tasks'){
     const views=await page.locator('.view-toggle>button').evaluateAll(nodes=>nodes.map(b=>{const r=b.getBoundingClientRect(),i=b.querySelector('svg').getBoundingClientRect();return {action:b.dataset.taskView,button:r.toJSON(),icon:i.toJSON(),hit:b.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))};}));
     assert.equal(views.length,2);for(const view of views){assert.ok(view.icon.width>=14&&view.icon.height>=14&&view.button.width>=32&&view.button.height>=32,JSON.stringify(view));assert.ok(view.button.x>=0&&view.button.right<=width+.5,JSON.stringify(view));assert.equal(view.hit,true,JSON.stringify(view));}
     await page.locator('[data-task-view=list]').click();await settle();assert.equal(await page.locator('.task-board').count(),0);
     await page.locator('[data-task-view=board]').click();await settle();
     const lanes=await page.locator('.task-board-column').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().toJSON()));
     assert.ok(lanes.length>=3);for(let i=0;i<lanes.length;i++){assert.ok(lanes[i].x>=0&&lanes[i].right<=width+1,JSON.stringify(lanes[i]));if(i)assert.ok(lanes[i].top>=lanes[i-1].bottom-1,'Mobile lanes must stack without overlap');}

    }
    await capture(route+'-mobile-'+width);
   });
  }
  for(const width of [390,320]){
   await resize(width,844);await nav('calendar');
   for(const view of ['day','week','month','list'])await check('mobile calendar '+view+' aligns its controls at '+width,async()=>{
    await page.locator('[data-calendar-view='+view+']').click();await settle();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    const tabs=await page.locator('.calendar-view-tabs .tab').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().toJSON()));
    assert.equal(tabs.length,4);for(const b of tabs){assert.ok(b.width>=32&&b.height>=32,JSON.stringify(b));assert.ok(Math.abs(b.top-tabs[0].top)<1);}
    const previous=await page.locator('[data-calendar-action=previous]').boundingBox(),next=await page.locator('[data-calendar-action=next]').boundingBox();
    assert.ok(previous.x>=0&&previous.x+previous.width<=tabs[0].left+1&&tabs[3].right<=next.x+1&&next.x+next.width<=width+1,JSON.stringify({previous,tabs,next}));
    if(view==='week'){assert.equal(await page.locator('.time-calendar-scroll').count(),0,'Compact weekly agenda avoids sideways scrolling');for(const box of await page.locator('#calendar-body .agenda-row').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().toJSON())))assert.ok(box.x>=0&&box.right<=width+1,JSON.stringify(box));}
    await capture('calendar-'+view+'-'+width);
   });
  }
 }catch(error){report.errors.push({engine,error:error.message});console.log('ERROR',engine,error.message);}
 finally{await browser.close();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,failures:report.checks.filter(x=>!x.ok),errors:report.errors},null,2));
if(report.checks.some(x=>!x.ok)||report.errors.length)process.exitCode=1;
