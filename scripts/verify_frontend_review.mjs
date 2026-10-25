/** The 20 browser comments, exercised against the isolated synthetic fixture. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin=process.env.UI_ORIGIN||'http://127.0.0.1:8786';
assert.equal(new URL(origin).hostname,'127.0.0.1');assert.equal(new URL(origin).port,'8786','Never run mutations on the real experience service');
const output=path.resolve('artifacts/frontend-v8-browser');await fs.mkdir(output,{recursive:true});
const report={fixture:'synthetic, no external model calls',checks:[],errors:[]};
const sizes=[[1651,871],[1280,720],[1024,768],[768,1024],[390,844],[320,640],[844,390]];
for(const engine of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',')){
 const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
 const page=await browser.newPage({viewport:{width:1651,height:871}});page.setDefaultTimeout(12000);
 let activeCheck='startup';
 page.on('pageerror',e=>report.errors.push({engine,check:activeCheck,url:page.url(),error:e.message,stack:e.stack}));
 page.on('response',async r=>{if(r.status()>=400&&/branch|edit-cache/.test(r.url()))console.log('HTTP',engine,r.status(),new URL(r.url()).pathname,(await r.text()).slice(0,220));});
 const check=async(name,fn)=>{activeCheck=name;try{await fn();report.checks.push({engine,name,ok:true});}catch(e){report.checks.push({engine,name,ok:false,error:e.message.slice(0,1800)});console.log('FAIL',engine,name,e.message.slice(0,400));await page.screenshot({path:path.join(output,engine+'-failure-'+name.replace(/[^a-zA-Z0-9]/g,'_').slice(0,70)+'.png')}).catch(()=>{});}};
 // Follow the application's hash navigation. A repeated page.goto reloads the
 // document and can abort the draft save started by closing the previous editor.
 const nav=async(hash)=>{await page.evaluate(hash=>{location.hash='#'+hash;},hash);await page.waitForFunction(hash=>document.querySelector('#content')?.dataset.page===hash&&!document.querySelector('#content').inert,hash);};
 const api=async(url,method='GET',json)=>await page.evaluate(async({url,method,json})=>{
  const session=await(await fetch('/api/session')).json();
  const headers={'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};if(json!==undefined)headers['Content-Type']='application/json';
  const r=await fetch('/api'+url,{method,headers,...(json!==undefined?{body:JSON.stringify(json)}:{})});const value=await r.json();if(!r.ok)throw Error(`${method} ${url}: ${r.status} ${JSON.stringify(value).slice(0,200)}`);return value;
 },{url,method,json});
 try{
  await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');
  await check('01 password eye changes visibility without losing the password',async()=>{
   const eye=page.locator('[data-auth-show]');assert.equal(await eye.locator('svg').count(),1);assert.equal(await eye.innerText(),'');
   await eye.click();assert.equal(await page.locator('[name=password]').getAttribute('type'),'text');assert.equal(await eye.getAttribute('aria-pressed'),'true');
   await eye.click();assert.equal(await page.locator('[name=password]').getAttribute('type'),'password');assert.equal(await page.locator('[name=password]').inputValue(),'Mvp-Verification-Only-2026');
  });
  await check('02 rejected password never displays a success check',async()=>{
   await page.locator('[name=password]').fill('Wrong-Engineering-Password');
   const response=page.waitForResponse(r=>r.url().endsWith('/api/auth/login')&&r.request().method()==='POST');await page.locator('#auth-form [type=submit]').click();assert.equal((await response).status(),401);
   await page.locator('#auth-form:not([inert])').waitFor();assert.equal(await page.locator('.auth-submit.is-success').count(),0);await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');
  });
  await check('02 login shrinks to a real success check before navigating',async()=>{
   await page.evaluate(()=>{
    const el=document.querySelector('.auth-submit');window.__authMorph={success:false,widths:[]};
    new MutationObserver(()=>{if(el.classList.contains('is-success'))window.__authMorph.success=true;}).observe(el,{attributes:true,attributeFilter:['class']});
    new ResizeObserver(()=>{if(el.classList.contains('is-success'))window.__authMorph.widths.push(el.getBoundingClientRect().width);}).observe(el);
   });
   await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
   const morph=await page.evaluate(()=>window.__authMorph);assert.equal(morph.success,true);assert.ok(morph.widths.some(w=>w>0&&w<60),JSON.stringify(morph));
  });  await page.locator('#content:not([inert])').waitFor();
  const tasks=await api('/tasks'),arrangements=await api('/arrangements');assert.ok(tasks.length);
  if(!arrangements.length){const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());arrangements.push(await api('/arrangements','POST',{data:{title:'【合成验收】日程标题跳转',category:'course',start_date:day,end_date:day,start_time:'10:00',end_time:'11:00'},request_id:crypto.randomUUID()}));}
  if(!(await api('/source-catalog')).length)for(const [name,platform] of [['合成学院网站','website'],['合成班级群','qq_group']])await api('/source-catalog','POST',{name,platform,followed:true,semester:'工程测试学期'});
  await api('/memory/items','POST',{content:'前端验收：回答先给结论，界面随屏幕和容器变化。',kind:'preference'});
  const chat=await api('/conversations','POST',{title:'前端交互验收 '+engine});
  await nav('chat/'+chat.id);await page.locator('#chat-input').fill('记住，我的测试称呼是前端验收同学');await page.locator('#chat-composer [type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#chat-thread .message-assistant')&&!document.querySelector('#chat-composer')?.classList.contains('is-processing'));
  await page.waitForFunction(()=>[...document.querySelectorAll('[data-chat-action=branch]')].some(b=>!b.disabled));
  const initial=await api('/conversations/'+chat.id);assert.equal(initial.messages.at(-1).status,'complete');
  for(const [width,height] of sizes){
   await page.setViewportSize({width,height});
   for(const route of ['memory','sources','tasks','calendar','chat/'+chat.id])await check(`layout ${width}x${height} ${route.split('/')[0]}`,async()=>{
    await nav(route);
    const geometry=await page.evaluate(()=>{
     const rect=selector=>{const e=document.querySelector(selector);if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom,scroll:e.scrollHeight,client:e.clientHeight};};
     return {vw:innerWidth,vh:visualViewport?.height||innerHeight,documentWidth:document.documentElement.scrollWidth,body:rect('body'),content:rect('#content'),sidebar:rect('.sidebar'),memory:rect('.memory-tree-layout'),detailHidden:document.querySelector('#memory-detail-pane')?.hidden,reader:rect('.chat-reading-area'),chat:rect('.chat-main'),composer:rect('.chat-composer')};
    });
    assert.ok(geometry.documentWidth<=width+1,JSON.stringify(geometry));assert.ok(geometry.body.h<=height+1,JSON.stringify(geometry));
    assert.ok(geometry.content.bottom<=height+1,JSON.stringify(geometry));assert.ok(geometry.content.w>width*.5);
    if(width>850)assert.ok(Math.abs(geometry.sidebar.h-height)<2);
    if(geometry.memory){assert.equal(geometry.detailHidden,true);assert.ok(geometry.memory.h>geometry.content.h*.55,JSON.stringify(geometry));assert.ok(geometry.memory.bottom<=height+1);}
    if(geometry.reader){assert.ok(geometry.reader.w>=geometry.chat.w-70,JSON.stringify(geometry));assert.ok(geometry.reader.h>height*.42,JSON.stringify(geometry));assert.ok(geometry.composer.bottom<=height+1);}
    if(width===1651||width===390||(width===844&&route.startsWith('chat/')))await page.screenshot({path:path.join(output,`${engine}-${width}-${route.split('/')[0]}.png`)});
   });
  }
  await check('chat composer adapts to a shorter container without a window resize',async()=>{
   await page.setViewportSize({width:1024,height:768});await nav('chat/'+chat.id);
   await page.waitForFunction(()=>innerHeight===768&&parseFloat(document.documentElement.style.getPropertyValue('--visual-height'))===768);
   await page.locator('#chat-composer:not(.is-compact)').waitFor();
   const workspace=page.locator('#chat-workspace'),original=await workspace.evaluate(node=>node.style.height);
   try{
    // Constrain the container itself. The viewport variable belongs to chrome.js
    // and a pending browser resize event may legitimately refresh it.
    await workspace.evaluate(node=>node.style.height='350px');
    await page.waitForFunction(()=>document.querySelector('.chat-main').clientHeight===350&&document.querySelector('#chat-composer').classList.contains('is-compact'));
    await page.locator('#chat-input').fill('保留可阅读的对话区域。\n'.repeat(12));
    // A running translateY entry animation rounds a 44px box to 43.999984px in
    // Chromium/WebKit. Check settled geometry, retaining the actual 44px minimum.
    await page.locator('#chat-composer').evaluate(node=>Promise.all(node.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
    const bounds=await page.evaluate(()=>{
     const box=s=>document.querySelector(s).getBoundingClientRect().toJSON();
     return {chat:box('.chat-main'),reader:box('.chat-reading-area'),composer:box('#chat-composer'),input:box('#chat-input'),buttons:[...document.querySelectorAll('#chat-composer .composer-plus,#chat-composer .composer-entry button')].filter(e=>e.getClientRects().length).map(e=>e.getBoundingClientRect().toJSON())};
    });
    assert.equal(bounds.chat.height,350,JSON.stringify(bounds));
    assert.equal(await page.evaluate(()=>innerHeight),768);
    assert.ok(bounds.reader.height>bounds.chat.height*.42,JSON.stringify(bounds));
    assert.ok(bounds.composer.bottom<=bounds.chat.bottom&&bounds.composer.height<90,JSON.stringify(bounds));
    for(const b of bounds.buttons){assert.ok(b.width>=44&&b.height>=44,JSON.stringify(bounds));assert.ok(b.right<=bounds.composer.right&&b.bottom<=bounds.composer.bottom,JSON.stringify(bounds));assert.ok(b.right<=bounds.input.x||b.x>=bounds.input.right,JSON.stringify(bounds));}
    await page.screenshot({path:path.join(output,`${engine}-chat-short-container.png`)});
   }finally{
    await page.locator('#chat-input').fill('');
    await workspace.evaluate((node,value)=>node.style.height=value,original);
   }
   await page.locator('#chat-composer:not(.is-compact)').waitFor();
  });
  await page.setViewportSize({width:1651,height:871});
  for(const [width,height] of [[1651,871],[390,844]]){
   await page.setViewportSize({width,height});
   for(const route of ['dashboard','notices','new','settings'])await check(`other page ${width} ${route}`,async()=>{
    await nav(route);const bounds=await page.locator('#content').boundingBox();assert.ok(bounds.y+bounds.height<=height+1);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    const text=await page.locator('#content').innerText();for(const copy of ['留住原文，核对要求。把该做的事','有出处，有进展，也有下一步','把消息放在一起，把下一步留给清楚的自己','原文多留一点，判断稳妥一点'])assert.ok(!text.includes(copy));
    if(width===1651)await page.screenshot({path:path.join(output,`${engine}-${width}-${route}.png`)});
   });
  }
  await page.setViewportSize({width:1651,height:871});
  await check('03 09 13 decorative page copy is absent',async()=>{
   for(const route of ['memory','sources','tasks']){await nav(route);const text=await page.locator('#content').innerText();for(const copy of ['你的个人知识与上下文','自动积累、按需想起','知道消息从哪里来','把官网、公众号和群整理在一起','已核对的个人行动，按你的节奏'])assert.ok(!text.includes(copy),copy);}
  });
  await check('06 memory details occupy space only after selection and close cleanly',async()=>{
   await nav('memory');const layout=page.locator('.memory-tree-layout'),before=await page.locator('.memory-tree-main').boundingBox();assert.equal(await page.locator('#memory-detail-pane').isVisible(),false);
   await page.locator('[data-tree-record]').first().click();assert.equal(await page.locator('#memory-detail-pane').isVisible(),true);assert.ok((await page.locator('.memory-tree-main').boundingBox()).width<before.width);assert.ok((await layout.getAttribute('class')).includes('has-detail'));
   await page.locator('[data-tree-action=close-detail]').click();assert.equal(await page.locator('#memory-detail-pane').isVisible(),false);assert.ok(Math.abs((await page.locator('.memory-tree-main').boundingBox()).width-before.width)<2);
  });
  await check('08 15 record search starts compact and discloses working filters',async()=>{
   await nav('sources');const host=page.locator('[data-search-host=source]');assert.equal(await host.locator('.search-filters').isVisible(),false);
   assert.ok((await host.boundingBox()).height<60);await host.locator('[data-search-mode=filter]').click();assert.equal(await host.locator('.search-filters').isVisible(),true);
   await host.locator('[data-search-period]').selectOption('week');await host.locator('[data-filter-count]').waitFor({state:'visible'});
   await nav('chat/'+chat.id);await page.locator('[data-chat-action=history]').click();assert.equal(await page.locator('.history-workspace .search-filters').isVisible(),false);assert.ok((await page.locator('.history-workspace .record-search').boundingBox()).height<60);
   await page.locator('.history-workspace [data-search-mode=filter]').click();assert.equal(await page.locator('.history-workspace .search-filters').isVisible(),true);await page.locator('#dialog .dialog-head [data-action=close-dialog]').click();
  });
  await check('10 calendar weekday and date fit and align with their day columns',async()=>{
   await nav('calendar');await page.locator('[data-calendar-view=week]').click();
   const boxes=await page.evaluate(()=>[...document.querySelectorAll('.time-grid-header>button')].map(e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,date:e.querySelector('strong').getBoundingClientRect().toJSON(),day:e.querySelector('small').getBoundingClientRect().toJSON()};}));assert.equal(boxes.length,7);
   for(const b of boxes){assert.ok(b.date.y>=b.top&&b.date.bottom<=b.bottom+1,JSON.stringify(b));assert.ok(b.day.y>=b.top&&b.day.bottom<=b.bottom+1,JSON.stringify(b));assert.equal(b.top,boxes[0].top);}
   await page.screenshot({path:path.join(output,engine+'-calendar-week.png')});
  });
  await check('11 simple task completion changes immediately and rolls back a failed save',async()=>{
   let item=(await api('/tasks')).find(t=>t.status!=='cancelled');const personal=await api('/tasks/'+item.id+'/workflow');
   await api('/tasks/'+item.id+'/workflow','PUT',{version:personal.task.workflow.version,task_version:personal.task.version,data:{...personal.task.workflow.data,execution_mode:'task',stage:'active'},complete:false});
   item=(await api('/tasks')).find(t=>t.id===item.id);await nav('notice/'+item.notice_id);
   const selector=`[data-action=toggle-task][data-id="${item.id}"]`,control=page.locator(selector).first(),old=item.status==='done';
   let release;const responseGate=new Promise(resolve=>release=resolve),attempt=page.waitForRequest(r=>r.url().endsWith('/api/tasks/'+item.id)&&r.method()==='PUT');
   await page.route('**/api/tasks/'+item.id,async route=>{await responseGate;await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'合成冲突验收'})});},{times:1});
   try{await control.click();await attempt;assert.equal((await control.getAttribute('class')).includes('checked'),!old);assert.equal(await control.getAttribute('aria-busy'),'true');}finally{release();}
   await page.waitForFunction(({selector,old})=>{const e=document.querySelector(selector);return e&&!e.hasAttribute('aria-busy')&&e.classList.contains('checked')===old;},{selector,old});
   await control.click();await page.waitForFunction(selector=>{const e=document.querySelector(selector);return e&&!e.disabled&&!e.hasAttribute('aria-busy');},selector);
   const fresh=(await api('/tasks')).find(t=>t.id===item.id);assert.notEqual(fresh.status,item.status);
   if(fresh.status==='done'){const color=await page.locator(selector).first().evaluate(e=>getComputedStyle(e,'::before').backgroundColor);assert.notEqual(color,'rgb(255, 255, 255)');}
  });
  await check('12 operation pane takes most of the workflow dialog and actions remain reachable',async()=>{
   await nav('tasks');await page.locator('[data-workflow-task]').first().click();await page.locator('#dialog[open] #workflow-form').waitFor();await page.locator('#dialog').evaluate(el=>Promise.all(el.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
   const d=await page.locator('#dialog').boundingBox(),pane=await page.locator('.workflow-page:not([hidden])').boundingBox(),head=await page.locator('.workflow-task-head').boundingBox(),save=await page.locator('.workflow-save').boundingBox();
   assert.ok(d&&pane&&head&&save,JSON.stringify({d,pane,head,save}));assert.ok(pane.height>d.height*.5,JSON.stringify({d,pane,head,save}));assert.ok(head.height<140);assert.ok(save.y+save.height<=d.y+d.height+1);
   await page.screenshot({path:path.join(output,engine+'-workflow.png')});await page.locator('#dialog .dialog-head [data-action=close-dialog]').click();
  });
  await check('14 task state filters form a compact single row',async()=>{await nav('tasks');const tabs=await page.locator('[aria-label="待办状态"]').boundingBox();assert.ok(tabs.height<=46);});
  await check('18 19 record evidence is readable and its title opens the exact record',async()=>{
   for(const [kind,item,prefix]of [['task',tasks[0],'task'],['arrangement',arrangements[0],'arra']]){
    await nav('chat/'+chat.id);
    await page.evaluate(async({kind,item,prefix})=>{
     const {CitationView}=await import('/static/genui/citations.js'),content=document.createElement('div'),footer=document.createElement('div');document.querySelector('#chat-thread').append(content,footer);
     const id=prefix+'-'+item.id,source={id,name:item.data.title,evidence_kind:kind,href:kind==='task'?'#tasks':'#calendar'};
     const view=new CitationView(content,footer,{sources:[],preview:()=>{}});view.update({id:'fixture-cite',citations:[{source_id:id,locator:'记录快照',quote:JSON.stringify({record_type:'internal',values:item.data,version:item.version,status:item.status})}],evidence_sources:[source]},{sources:[],preview:()=>{}});view.open(1);
    },{kind,item,prefix});
    const quote=await page.locator('.source-quote').innerText();for(const field of ['record_type','deadline_confirmed','updated_at','"values"'])assert.ok(!quote.includes(field));
    assert.equal(await page.locator('.source-result-title').getAttribute('href'),(kind==='task'?'#tasks/':'#calendar/')+item.id);
    await page.locator('.source-result-title').click();await page.locator('#dialog[open]').waitFor();assert.ok((await page.locator('#dialog').innerText()).includes(item.data.title));
    await page.locator('#dialog .dialog-head [data-action=close-dialog]').click();
   }
  });
  for(const [width,height] of [[1651,871],[390,844]]){
   await page.setViewportSize({width,height});
   for(const kind of ['workflow','memory','source','upload','arrangement'])await check(`operation ${width} ${kind}`,async()=>{
    if(kind==='workflow'){await nav('tasks');await page.locator('[data-workflow-task]').first().click();}
    else if(kind==='memory'){await nav('memory');await page.locator('[data-memory-action=new]').click();}
    else if(kind==='source'){await nav('sources');await page.locator('[data-source-action=add]').click();}
    else if(kind==='upload'){await nav('chat/'+chat.id);await page.locator('.composer-plus').click();await page.locator('#composer-menu [data-chat-action=upload]').click();}
    else {await nav('calendar');await page.locator('[data-calendar-action=new]').first().click();}
    await page.locator('#dialog[open] form').waitFor();
    await page.locator('#dialog').evaluate(el=>Promise.all(el.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
    const box=await page.locator('#dialog').boundingBox();assert.ok(box&&box.width<=width+1&&box.height<=height+1);
    for(const field of await page.locator('#dialog textarea:visible').all()){const b=await field.boundingBox();assert.ok(b.width>width*.4&&b.height>=80,JSON.stringify(b));}
    const submit=page.locator('#dialog [type=submit]:visible').last();await submit.scrollIntoViewIfNeeded();const b=await submit.boundingBox();assert.ok(b.y+b.height<=height+1&&b.height>=36,JSON.stringify(b));
    if(kind==='workflow'&&width===390){await page.evaluate(()=>document.documentElement.style.setProperty('--visual-height','500px'));const small=await page.locator('#dialog').boundingBox(),save=await page.locator('.workflow-save').boundingBox();assert.ok(small.height<=500&&save.y+save.height<=501);await page.evaluate(()=>document.documentElement.style.setProperty('--visual-height',visualViewport.height+'px'));}
    await page.locator('#dialog .dialog-head [data-action=close-dialog]').click();
   });
  }
  await page.setViewportSize({width:1651,height:871});
  await check('07 mobile directory closes after selection without opening a keyboard',async()=>{
   await page.setViewportSize({width:390,height:844});await nav('memory');const toggle=page.locator('[data-tree-action=toggle-nav]');await toggle.click();assert.equal(await page.locator('#memory-tree-sidebar').isVisible(),true);
   await page.locator('[data-tree-action=sessions]').click();await page.locator('#memory-tree-sidebar').waitFor({state:'hidden'});assert.equal(await toggle.getAttribute('aria-expanded'),'false');assert.ok((await page.locator('#memory-breadcrumbs').innerText()).includes('会话与工作记忆'));
   assert.ok(await page.locator('.memory-tree-main').evaluate(e=>e===document.activeElement));await toggle.click();await page.locator('[data-tree-node]').first().click();await page.locator('#memory-tree-sidebar').waitFor({state:'hidden'});await page.setViewportSize({width:1651,height:871});
  });
  await check('20 leaving an unused branch never creates a conversation; sending creates one',async()=>{
   await nav('chat/'+chat.id);let writes=0,emptyDraftWrites=0;const count=()=>api('/conversations');
   const listener=req=>{if(req.method()==='PUT'&&decodeURIComponent(new URL(req.url()).pathname).includes('/edit-cache/branch:'))emptyDraftWrites++;if(req.method()==='POST'&&/\/messages\/[^/]+\/branch$/.test(new URL(req.url()).pathname))writes++;};page.on('request',listener);
   const before=(await count()).length;await page.locator('[data-chat-action=branch]').last().click();await page.waitForURL(/#chat\/[a-f0-9]+\/branch\/[a-f0-9]+$/);await page.locator('#content:not([inert])').waitFor();assert.equal(writes,0);assert.equal((await count()).length,before);
   await nav('tasks');assert.equal((await count()).length,before);assert.equal(emptyDraftWrites,0);await nav('chat/'+chat.id);await page.locator('[data-chat-action=branch]').last().click();await page.waitForURL(/#chat\/[a-f0-9]+\/branch\/[a-f0-9]+$/);await page.locator('#content:not([inert])').waitFor();await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page.includes('/branch/')&&!document.querySelector('#content').inert);await page.locator('#chat-input').fill('从这个分支继续前端工程验收');await page.locator('#chat-composer [type=submit]').click();
   await page.waitForFunction(()=>/^#chat\/[a-f0-9]{32}$/.test(location.hash));await page.waitForFunction(()=>[...document.querySelectorAll('.message-user')].some(e=>e.textContent.includes('从这个分支继续前端工程验收')));assert.equal(writes,1);assert.equal((await count()).length,before+1);page.off('request',listener);
  });
 }catch(error){report.checks.push({engine,name:'fixture or critical flow',ok:false,error:error.message.slice(0,900)});console.log('FAIL',engine,error.message.slice(0,300));}
 finally{await browser.close();}
}
await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
const failed=report.checks.filter(c=>!c.ok);console.log(JSON.stringify({checks:report.checks.length,passed:report.checks.length-failed.length,failed:failed.length,pageErrors:report.errors.length,report:path.join(output,'report.json')}));
if(failed.length||report.errors.length)process.exitCode=1;
