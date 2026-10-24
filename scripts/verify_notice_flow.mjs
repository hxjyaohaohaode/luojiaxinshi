/** Existing inputs through persisted actions; synthetic data and real local APIs. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/notice-flow-browser');
await fs.mkdir(out,{recursive:true});
const report={fixture:'Synthetic local data, real application storage and routes; link provider is a declared fixture',checks:[],errors:[]};
for(const engine of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',')){
  console.log('Notice flow: '+engine);
  const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
  const page=await browser.newPage({viewport:{width:1440,height:900},locale:'zh-CN',timezoneId:'America/Los_Angeles'});
  page.setDefaultTimeout(12000);page.setDefaultNavigationTimeout(45000);
  page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
  const api=(url,method='GET',data=null,form=false)=>page.evaluate(async({url,method,data,form})=>{
    const session=await fetch('/api/session').then(r=>r.json());
    const headers={'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
    let body;if(data){if(form){body=new FormData();for(const [key,value] of Object.entries(data))body.set(key,value);}else{headers['Content-Type']='application/json';body=JSON.stringify(data);}}
    const r=await fetch('/api'+url,{method,headers,body});const result=await r.json();if(!r.ok)throw new Error(JSON.stringify(result));return result;
  },{url,method,data,form});
  const settle=()=>page.evaluate(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
  const nav=async route=>{if(page.url()===origin+'/#'+route)await page.reload({waitUntil:'domcontentloaded'});else await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});await page.locator('#content:not([inert])').waitFor();await settle();};
  const close=async()=>{if(await page.locator('#dialog').evaluate(n=>n.open)){await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});}};
  const check=async(name,fn)=>{try{await fn();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.message});console.log('FAIL',engine,name,error.message);await page.screenshot({path:path.join(out,engine+'-'+report.checks.length+'-failure.png')}).catch(()=>{});await close();}};
  let noticeId,taskId,linkId;
  try{
    await page.goto(origin+'/#login',{waitUntil:'domcontentloaded'});
    await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
    const unique=engine+'-'+Date.now();
    for(const key of ['new-notice','intake-batch']){const cache=await api('/edit-cache/'+key);await api('/edit-cache/'+key,'PUT',{revision:cache.revision,payload:null});}
    await check('paste and upload preserve two originals and create one notice',async()=>{
      await nav('new');await page.locator('#notice-form [name=title]').fill('工程通知 '+unique);
      await page.locator('#notice-form [name=body]').fill('【合成材料】2027年10月20日14:00至16:00参加讲座。'+unique);
      await page.locator('#notice-form [name=files]').setInputFiles({name:'讲座附件.txt',mimeType:'text/plain',buffer:Buffer.from('【合成附件】参加者请在讲座开始前到场。'+unique)});
      await page.locator('[data-notice-step-to=review]').click();await page.locator('[name=rights]').check();await page.locator('[name=materials_complete]').check();
      await page.locator('#notice-form [type=submit]').click();await page.waitForURL(/#notice\//);await page.locator('.notice-handling').waitFor();
      noticeId=new URL(page.url()).hash.split('/')[1];const n=await api('/notices/'+noticeId);
      assert.equal(n.sources.length,2);assert.ok(n.sources.some(s=>s.name==='讲座附件.txt'));assert.equal(n.tasks.length,0);
    });
    await check('informational disposition persists without creating a task and can reopen',async()=>{
      await page.locator('[data-notice-disposition=reference]').click();await page.locator('#dialog [name=note]').fill('阅读后保留原文');await page.locator('#dialog [type=submit]').click();await page.locator('[data-notice-disposition=inbox]').waitFor();
      await nav('notice/'+noticeId);assert.equal(await page.locator('#draft-pane').isVisible(),false);
      const n=await api('/notices/'+noticeId);assert.equal(n.handling.disposition,'reference');assert.equal(n.tasks.length,0);
      await page.locator('[data-notice-disposition=inbox]').click();await page.locator('#dialog [type=submit]').click();await page.locator('[data-action=manual]').waitFor();
    });
    await check('an activity can be confirmed through the editor with an interval and no deadline',async()=>{
      await settle();
      const manualBox=await page.locator('[data-action=manual]').boundingBox();
      await page.mouse.move(manualBox.x+manualBox.width/2,manualBox.y+manualBox.height-.25);
      const positions=await page.locator('[data-action=manual]').evaluate(async node=>{const ys=[];for(let i=0;i<24;i++){await new Promise(requestAnimationFrame);ys.push(node.getBoundingClientRect().y);}return ys;});
      assert.ok(Math.max(...positions)-Math.min(...positions)<.1,'Hovering an action edge must not make its target oscillate');
      await page.locator('[data-action=manual]').click();await page.locator('[data-action=add-task]').click();
      const editor=page.locator('[data-editor]').first();await editor.locator('[name=title]').fill('工程讲座 '+unique);
      await editor.locator('.task-scheduled>summary').click();await editor.locator('[name=use_scheduled]').check();
      await editor.locator('[name=scheduled_start_date]').fill('2027-10-20');await editor.locator('[name=scheduled_start_time]').fill('14:00');
      await editor.locator('[name=scheduled_end_date]').fill('2027-10-20');await editor.locator('[name=scheduled_end_time]').fill('16:00');await editor.locator('[name=scheduled_confirmed]').check();
      await editor.locator('.draft-plan>summary').click();await editor.locator('[name=plan_execution_mode]').selectOption('attendance');
      await page.locator('#draft-form [name=reviewed]').check();await page.locator('#draft-form [type=submit]').click();await page.locator('#draft-pane [data-workflow-task]').first().waitFor();
      const n=await api('/notices/'+noticeId);assert.equal(n.tasks.length,1);const task=n.tasks[0];taskId=task.id;
      assert.equal(task.data.due_date,null);assert.equal(task.data.scheduled.start_time,'14:00');assert.equal(task.data.scheduled.confirmed,true);assert.equal(task.workflow.data.execution_mode,'attendance');
    });
    await check('task body opens handling while source and edit controls retain separate actions',async()=>{
      await nav('tasks');
      const primary=page.locator(`.task-primary[data-workflow-task="${taskId}"]`),row=primary.locator('xpath=ancestor::div[contains(@class,"task-row")][1]');
      const box=await primary.boundingBox();assert.ok(box.width>100&&box.height>=44);
      await primary.click({position:{x:box.width-8,y:box.height-6}});await page.locator('#workflow-form').waitFor();await close();
      await primary.focus();await page.keyboard.press('Enter');await page.locator('#workflow-form').waitFor();await close();
      await row.locator('[data-action=edit-task]').click();await page.locator('#task-form').waitFor();assert.equal(await page.locator('#workflow-form').count(),0);await close();
      await row.locator('.task-source-link').click();await page.waitForURL('**/#notice/'+noticeId);assert.equal(await page.locator('#dialog').evaluate(n=>n.open),false);await settle();
    });
    await check('activity calendar export uses its actual two-hour interval',async()=>{
      const t=(await api('/tasks/'+taskId+'/workflow')).task;
      const text=await page.evaluate(async({tid,version})=>{const s=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api/calendar/export',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'campus-notice','X-CSRF-Token':s.csrf},body:JSON.stringify({task_ids:[tid],versions:{[tid]:version}})});if(!r.ok)throw new Error(await r.text());return r.text();},{tid:taskId,version:t.version});
      assert.match(text,/DTSTART:20271020T060000Z/);assert.match(text,/DTEND:20271020T080000Z/);assert.equal((text.match(/BEGIN:VEVENT/g)||[]).length,1);
    });
    await check('custom steps persist; incomplete steps block completion; reading needs no submission receipt',async()=>{
      await page.locator(`[data-workflow-task="${taskId}"]`).first().click();await page.locator('#workflow-form [name=execution_mode]').selectOption('custom');
      await page.locator('[name=phase_label]').fill('准备交流');await page.locator('.handling-editor details>summary').click();await page.locator('[data-add-milestone]').click();await page.locator('[data-milestone-title]').fill('整理提问');
      await page.locator('#workflow-form [name=complete]').click();await page.locator('#workflow-form .form-error').waitFor();assert.equal((await api('/tasks/'+taskId+'/workflow')).task.status,'pending');
      await page.locator('[data-milestone-done]').check();await page.locator('[name=execution_mode]').selectOption('reading');await page.locator('[name=stage]').selectOption('recorded');
      await settle();if(!await page.locator('.workflow-receipt').evaluate(n=>n.open))await page.locator('.workflow-receipt>summary').click();await settle();await page.locator('#workflow-form [name=outcome]').fill('已阅读通知与附件，并记录提问');assert.equal(await page.locator('#workflow-form [name=receipt]').isVisible(),false);
      await page.locator('#workflow-form [name=complete]').click();await page.locator('#dialog').waitFor({state:'hidden'});
      const t=(await api('/tasks/'+taskId+'/workflow')).task;assert.equal(t.status,'done');assert.equal(t.workflow.data.milestones[0].done,true);assert.equal(t.workflow.data.receipt,'');
    });
    await check('public link preview is reviewed, stored and keeps its exact source URL',async()=>{
      await nav('new');await page.locator('[data-read-url]').fill('https://notice-fixture.example/'+unique);await page.locator('[data-read-link]').click();await page.locator('[data-use-link]').click();
      assert.ok(await page.locator('[name=link_preview]').inputValue());await page.locator('[data-notice-step-to=review]').click();await page.locator('[name=rights]').check();await page.locator('[name=materials_complete]').check();await page.locator('#notice-form [type=submit]').click();await page.waitForURL(/#notice\//);
      linkId=new URL(page.url()).hash.split('/')[1];const n=await api('/notices/'+linkId);assert.equal(n.sources.length,1);assert.equal(n.sources[0].origin.url,'https://notice-fixture.example/'+unique);
      await page.locator('.source-content a').first().waitFor();assert.ok(await page.locator('.source-content a').count());
    });
    await check('unreadable links leave pasted content intact for fallback',async()=>{
      await nav('new');await page.locator('[name=body]').fill('失败后保留的正文 '+unique);await page.locator('[data-read-url]').fill('https://notice-fixture.example/failure');await page.locator('[data-read-link]').click();await page.getByText('示例链接暂时不可读取，请粘贴正文或上传原件',{exact:true}).waitFor();
      assert.equal(await page.locator('[name=body]').inputValue(),'失败后保留的正文 '+unique);assert.equal(await page.locator('[name=link_preview]').inputValue(),'');
    });
    await check('batch partial success is retained; duplicates are explicitly reused or saved as another batch',async()=>{
      await nav('intake');let cards=page.locator('[data-intake-entry]');await cards.nth(0).locator('[name=title]').fill('批量通知 A '+unique);await cards.nth(0).locator('[name=body]').fill('独立的批量正文 '+unique);
      await page.locator('#intake-add').click();cards=page.locator('[data-intake-entry]');await cards.nth(1).locator('[name=title]').fill('批量通知重复 '+unique);await cards.nth(1).locator('[name=body]').fill('独立的批量正文 '+unique);
      await page.locator('#intake-save').click();await page.locator('[data-intake-retry]').waitFor();assert.equal(await page.locator('.intake-saved').count(),1);assert.equal(await page.locator('[data-intake-entry]').count(),1);
      await page.locator('[data-intake-retry]').click();await page.locator('#intake-save').click();await page.waitForFunction(()=>document.querySelectorAll('.intake-saved').length===2);
      await nav('intake');assert.equal(await page.locator('.intake-saved').count(),2);assert.equal(await page.locator('#intake-save').isDisabled(),true);
      const notices=await api('/notices');assert.equal(notices.filter(n=>n.title==='批量通知 A '+unique).length,1);assert.equal(notices.filter(n=>n.title==='批量通知重复 '+unique).length,1);
    });
    await check('batch can supplement an existing notice, reopening it and preserving originals',async()=>{
      let n=await api('/notices/'+linkId);await api('/notices/'+linkId+'/disposition','PUT',{version:n.version,disposition:'reference',note:''});
      await nav('intake');await page.locator('#intake-add').click();const card=page.locator('[data-intake-entry]');await card.locator('[name=target]').selectOption(linkId);await card.locator('[name=title]').fill('补充 '+unique);await card.locator('[name=body]').fill('补充的后续说明 '+unique);await card.locator('[name=materials_complete]').check();await page.locator('#intake-save').click();await page.waitForFunction(()=>document.querySelectorAll('.intake-saved').length===3);
      n=await api('/notices/'+linkId);assert.equal(n.handling.disposition,'inbox');assert.equal(n.sources.length,2);assert.equal(Boolean(n.materials_complete),true);
    });
    for(const [width,height] of [[1440,900],[390,844],[320,620],[844,390]]){
      await check('intake and flexible workflow remain reachable at '+width+'x'+height,async()=>{
        await page.setViewportSize({width,height});await nav('intake');await page.locator('#intake-add').click();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
        const card=page.locator('[data-intake-entry]').last();await card.locator('[name=body]').fill('窄屏临时输入');await card.locator('[data-intake-remove]').click();
        await nav('notice/'+noticeId);await page.locator(`[data-workflow-task="${taskId}"]`).first().click();await page.locator('#workflow-form').waitFor();await settle();
        const bounds=await page.locator('#dialog').evaluate(n=>({width:n.getBoundingClientRect().width,view:innerWidth,overflow:n.scrollWidth>n.clientWidth+2}));assert.ok(bounds.width<=bounds.view);assert.equal(bounds.overflow,false);
        const save=page.locator('#workflow-form [type=submit]').first();await save.scrollIntoViewIfNeeded();assert.equal(await save.isVisible(),true);
        if(engine==='chromium')await page.screenshot({path:path.join(out,'workflow-'+width+'x'+height+'.png')});await close();
      });
    }
  }catch(error){report.errors.push({engine,error:error.message});console.log('ERROR',engine,error.message);}
  finally{await browser.close();}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,failed:report.checks.filter(c=>!c.ok).length,errors:report.errors.length}));
if(report.errors.length||report.checks.some(c=>!c.ok))process.exitCode=1;
