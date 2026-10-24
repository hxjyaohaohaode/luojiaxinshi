/** Real pointer movement with isolated synthetic tasks, never the user's data. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const pw=createRequire(import.meta.url)(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/task-board-browser');
await fs.mkdir(out,{recursive:true});
const report={fixture:'Synthetic tasks; real pointer events, storage, conflict guards and undo',checks:[],errors:[]};
for(const engine of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',')){
  const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
  const page=await browser.newPage({viewport:{width:1440,height:950},locale:'zh-CN'});page.setDefaultTimeout(12000);
  page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
  const api=(url,method='GET',data=null,form=false)=>page.evaluate(async({url,method,data,form})=>{
    const session=await fetch('/api/session').then(r=>r.json()),headers={'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
    let body;if(data){if(form){body=new FormData();for(const [key,value] of Object.entries(data))body.set(key,value);}else{headers['Content-Type']='application/json';body=JSON.stringify(data);}}
    const response=await fetch('/api'+url,{method,headers,body});const result=await response.json();if(!response.ok)throw Error(JSON.stringify(result));return result;
  },{url,method,data,form});
  const settle=async()=>{await page.waitForTimeout(300);await page.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity&&!a.effect?.target?.closest?.('#toast')).map(a=>a.finished.catch(()=>{}))));};
  const check=async(name,fn)=>{try{await fn();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.message});console.log('FAIL',engine,name,error.message);await page.screenshot({path:path.join(out,engine+'-failure-'+report.checks.length+'.png')});}};
  const row=id=>page.locator(`#task-results [data-task-id="${id}"]`);
  const ids=lane=>page.locator(`[data-task-lane="${lane}"] .task-row`).evaluateAll(nodes=>nodes.map(n=>n.dataset.taskId));
  const drag=async(id,x,y,{cancel=false}={})=>{
    const box=await row(id).locator('.task-primary').boundingBox();
    await page.mouse.move(box.x+12,box.y+12);await page.mouse.down();
    for(let i=1;i<=14;i++){await page.mouse.move(box.x+12+(x-box.x-12)*i/14,box.y+12+(y-box.y-12)*i/14);await page.waitForTimeout(16);}
    await page.locator('.task-drag-ghost').waitFor();
    if(cancel)await page.keyboard.press('Escape');
    await page.mouse.up();await page.locator('.task-drag-ghost').waitFor({state:'detached'});await settle();
  };
  try{
    await page.goto(origin);await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
    const prefix='拖动验收 '+engine+' '+Date.now();
    const notice=await api('/notices','POST',{title:prefix,body:prefix+'：仅用于测试个人安排，不包含真实办理要求。',source_label:'工程夹具',materials_complete:'true'},true);
    const manual=await api('/notices/'+notice.id+'/manual','POST',{version:notice.version});
    const saved=await api('/notices/'+notice.id+'/confirm','POST',{version:manual.version,reviewed:true,tasks:['A','B','C'].map(letter=>({title:prefix+' '+letter,origin:'manual',scope:'personal'}))});
    const [a,b,c]=saved.task_ids;
    await page.goto(origin+'/#tasks');await page.locator('#task-search').fill(prefix);await page.locator('[data-filter=all]').click();await page.waitForFunction(()=>document.querySelectorAll('#task-results .task-row').length===3);await settle();
    const initial=await ids('action');
    await check('whole-card drag reorders, persists after reload, and does not open the task',async()=>{
      const target=await row(initial[0]).boundingBox();await drag(initial[2],target.x+target.width/2,target.y+12);
      assert.deepEqual(await ids('action'),[initial[2],initial[0],initial[1]]);assert.equal(await page.locator('#dialog').evaluate(n=>n.open),false);
      await page.reload();await page.locator('#task-search').fill(prefix);await page.locator('[data-filter=all]').click();await page.waitForFunction(()=>document.querySelectorAll('#task-results .task-row').length===3);await settle();
      assert.deepEqual(await ids('action'),[initial[2],initial[0],initial[1]]);
    });
    await check('cross-lane move changes personal progress while preserving formal evidence',async()=>{
      const target=await page.locator('[data-task-lane=followup] .task-lane-items').boundingBox();await drag(a,target.x+target.width/2,target.y+50);
      assert.ok((await ids('followup')).includes(a));const task=(await api('/tasks/'+a+'/workflow')).task;assert.equal(task.status,'pending');assert.equal(task.workflow.data.stage,'preparing');
      await page.screenshot({path:path.join(out,engine+'-desktop.png')});
    });
    await check('completion and undo update the real task without a confirmation modal',async()=>{
      const target=await page.locator('[data-task-lane=closed] .task-lane-items').boundingBox();await drag(a,target.x+target.width/2,target.y+50);
      assert.equal((await api('/tasks/'+a+'/workflow')).task.status,'done');assert.ok((await ids('closed')).includes(a));
      await page.locator('#toast .toast-action').click();await settle();assert.equal((await api('/tasks/'+a+'/workflow')).task.status,'pending');assert.ok((await ids('followup')).includes(a));
    });
    await check('escape and outside drops cancel cleanly without requests or accidental navigation',async()=>{
      const before=await ids('action');let moves=0;const count=r=>{if(r.url().endsWith('/move'))moves++;};page.on('request',count);
      const target=await page.locator('[data-task-lane=closed]').boundingBox();await drag(b,target.x+20,target.y+60,{cancel:true});await drag(b,80,200);
      page.off('request',count);assert.equal(moves,0);assert.deepEqual(await ids('action'),before);assert.equal(await page.locator('#dialog').evaluate(n=>n.open),false);assert.equal(await page.locator('.task-drop-placeholder').count(),0);
    });
    await check('failed save restores the current server position and offers recovery',async()=>{
      await page.route('**/api/tasks/*/move',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'这项待办刚有更新，已恢复最新位置，请重试'})}));
      const before=await ids('action'),target=await page.locator('[data-task-lane=followup] .task-lane-items').boundingBox();await drag(b,target.x+30,target.y+30);
      await page.unroute('**/api/tasks/*/move');assert.deepEqual(await ids('action'),before);assert.match(await page.locator('#toast').innerText(),/更新|重试|重拖/);
    });
    await check('keyboard move menu works with reduced motion',async()=>{
      await page.emulateMedia({reducedMotion:'reduce'});await row(b).locator('[data-task-drag-handle]').focus();await page.keyboard.press('Enter');
      await page.getByRole('button',{name:'移到留意反馈',exact:true}).click();await settle();assert.ok((await ids('followup')).includes(b));assert.equal(await page.locator('.task-drag-ghost').count(),0);
    });
    if(engine==='chromium')await check('native touch long-press reorders cards while ordinary swipes remain scrollable',async()=>{
      const mobileContext=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true,storageState:await page.context().storageState()});
      const mobile=await mobileContext.newPage();
      try{
        await mobile.goto(origin+'/#tasks');await mobile.locator('#task-search').fill(prefix);await mobile.locator('[data-filter=all]').click();
        await mobile.waitForFunction(()=>document.querySelectorAll('#task-results .task-row').length===3);await mobile.waitForTimeout(350);
        const follow=mobile.locator('[data-task-lane=followup] .task-row'),before=await follow.evaluateAll(nodes=>nodes.map(n=>n.dataset.taskId));assert.equal(before.length,2);
        await follow.last().scrollIntoViewIfNeeded();await mobile.waitForTimeout(250);
        const handle=await follow.last().locator('[data-task-drag-handle]').boundingBox(),target=await follow.first().boundingBox();
        const session=await mobileContext.newCDPSession(mobile),x=handle.x+22,y=handle.y+22;
        await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1}]});await mobile.waitForTimeout(220);
        await mobile.locator('.task-drag-ghost').waitFor();
        for(let i=1;i<=12;i++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+(target.x+80-x)*i/12,y:y+(target.y+12-y)*i/12,id:1}]});await mobile.waitForTimeout(16);}
        await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await mobile.locator('.task-drag-ghost').waitFor({state:'detached'});await mobile.waitForTimeout(350);
        assert.deepEqual(await follow.evaluateAll(nodes=>nodes.map(n=>n.dataset.taskId)),[before[1],before[0]]);
        assert.equal(await mobile.locator('#dialog').evaluate(n=>n.open),false);
        await mobile.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity&&!a.effect?.target?.closest?.('#toast')).map(a=>a.finished.catch(()=>{}))));
        // Start away from the lower scroll boundary to exercise a real page swipe.
        await mobile.locator('#content').evaluate(el=>{el.scrollTop=0;});await mobile.waitForTimeout(100);
        await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:180,y:650,id:2}]});
        for(let i=1;i<=10;i++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:180,y:650-i*25,id:2}]});await mobile.waitForTimeout(16);}
        await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await mobile.waitForTimeout(250);
        assert.equal(await mobile.locator('.task-drag-ghost').count(),0);
        assert.ok(await mobile.locator('#content').evaluate(el=>el.scrollTop)>0,'A normal card swipe must scroll the page');
        await mobile.screenshot({path:path.join(out,'chromium-touch.png')});
      }finally{await mobileContext.close();}
    });
    for(const width of [390,320])await check('compact '+width+'px layout retains large move targets and no horizontal overflow',async()=>{
      await page.setViewportSize({width,height:844});await settle();const handle=row(c).locator('[data-task-drag-handle]');await handle.scrollIntoViewIfNeeded();
      const box=await handle.boundingBox();assert.ok(box.width>=44&&box.height>=44);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await handle.click();await page.getByRole('button',{name:'移到留意反馈',exact:true}).waitFor();await page.keyboard.press('Escape');
      await page.screenshot({path:path.join(out,engine+'-'+width+'.png')});
    });
  }catch(error){report.errors.push({engine,error:error.message});console.log('ERROR',engine,error.message);}
  finally{await browser.close();}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,failed:report.checks.filter(c=>!c.ok).length,errors:report.errors.length}));
if(report.errors.length||report.checks.some(c=>!c.ok))process.exitCode=1;
