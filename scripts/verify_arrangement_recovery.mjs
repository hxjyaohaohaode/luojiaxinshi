import {artifactPath} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={scenarios:[],errors:[]};
const sizes=JSON.parse(process.env.MVP_VIEWPORTS||'[[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]');
const fixture=title=>({title,category:'personal',start_date:'2026-10-19',end_date:'2026-10-19',start_time:'09:00',end_time:'10:00',repeat:'none',repeat_until:null,location:'虚构验收地点',notes:'工程测试，不代表真实安排。'});
try{
for(const engine of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
  const browser=await engines[engine].launch({headless:true,executablePath:engines[engine].executablePath()});
  try{
    const context=await browser.newContext({reducedMotion:'reduce'}),headers={Origin:origin,'X-Requested-With':'campus-notice'};
    const registration=await context.request.post(origin+'/api/auth/register',{headers,data:{username:'recovery.'+engine+'.'+Date.now(),password:'Recovery-Verification-Only-2026',display_name:'虚构保存恢复验收',accepted_terms:true}});
    if(!registration.ok())throw new Error('Fixture registration: '+registration.status());
    headers['X-CSRF-Token']=(await(await context.request.get(origin+'/api/session')).json()).csrf;
    const request=async(method,path,data)=>{const r=await context.request.fetch(origin+'/api'+path,{method,headers,...(data?{data}:{})});if(!r.ok())throw new Error(method+' '+path+': '+r.status());return r.json();};
    const read=path=>request('GET',path);
    const cache=async payload=>{const prior=await read('/edit-cache/arrangement-new');return request('PUT','/edit-cache/arrangement-new',{revision:prior.revision,payload});};
    const create=async data=>{const request_id=randomUUID();const saved=await request('POST','/arrangements',{request_id,data});return {request_id,data,saved};};
    const page=await context.newPage();page.setDefaultTimeout(12000);page.on('pageerror',e=>report.errors.push({engine,error:e.message}));
    const open=async()=>{await page.goto(origin+'/?recover-check='+Date.now()+'#calendar');await page.waitForSelector('.calendar-toolbar');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});};
    const newArrangement=()=>page.locator('.calendar-toolbar [data-calendar-action=new]').click();
    const recovered=()=>page.waitForSelector('#arrangement-recovery');
    const choice=name=>page.locator(`[data-arrangement-recovery=${name}]`).click();
    const geometry=async check=>{
      const g=await page.evaluate(()=>{const d=document.querySelector('dialog'),b=d.querySelector('.dialog-body'),r=d.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth,height:innerHeight,scroll:b.scrollWidth,client:b.clientWidth,targets:[...d.querySelectorAll('[data-arrangement-recovery]')].map(e=>{const r=e.getBoundingClientRect();return [r.width,r.height];})};});
      check(g.left>=0&&g.right<=g.width+1&&g.top>=0&&g.bottom<=g.height+1&&g.scroll<=g.client+1,'Recovery panel stays inside the viewport');
      check(g.targets.every(([w,h])=>w>=39&&h>=39),'Recovery choices keep usable target sizes');
    };
    for(const [width,height] of sizes){
      await page.setViewportSize({width,height});
      const run=async(label,work)=>{const result={engine,width,height,label,checks:[]},check=(passed,detail)=>result.checks.push({passed:!!passed,detail});try{await work(check);result.passed=result.checks.every(x=>x.passed);}catch(error){result.passed=false;result.error=error.stack;}report.scenarios.push(result);console.log(engine,width,height,label,result.passed?'pass':'FAIL');};
      await run('Cleanup fails, then reload and explicitly start another arrangement',async check=>{
        await cache(null);await open();await newArrangement();
        const title='虚构清理恢复 '+Date.now();await page.locator('#arrangement-form [name=title]').fill(title);
        const oldRequest=await page.locator('#arrangement-form').getAttribute('data-request-id');
        const cleanup=async route=>{if(route.request().method()==='PUT'&&route.request().postDataJSON().payload===null)await route.fulfill({status:503,json:{detail:'虚构清理失败'}});else await route.continue();};
        await page.route(origin+'/api/edit-cache/arrangement-new',cleanup);
        try{await page.locator('#arrangement-form [type=submit]').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('旧草稿清理未完成'));}finally{await page.unroute(origin+'/api/edit-cache/arrangement-new',cleanup);}
        check((await read('/arrangements')).filter(x=>x.data.title===title).length===1,'The formal save happened once');
        await open();await newArrangement();await recovered();await geometry(check);
        check((await page.locator('#arrangement-recovery').textContent()).includes('已经保存'),'Reload identifies the completed submission');
        check((await read('/edit-cache/arrangement-new')).payload.request_id===oldRequest,'Recovery preserves the original draft until a choice');
        if(engine==='chromium'&&[320,390,1440].includes(width))await page.screenshot({path:artifactPath(`recovery-${width}.png`),animations:'disabled'});
        await choice('blank');await page.waitForSelector('#arrangement-form');
        check(await page.locator('#arrangement-form [name=title]').inputValue()==='','Explicit blank choice starts an empty form');
        check(await page.locator('#arrangement-form').getAttribute('data-request-id')!==oldRequest,'The new intent has a new request key');
      });
      await run('A later edit is shown and copying requires an explicit new intent',async check=>{
        const old=await create(fixture('虚构原草稿 '+Date.now()));await cache({request_id:old.request_id,data:old.data});
        const newer=await request('PUT','/arrangements/'+old.saved.id,{version:1,data:{...old.saved.data,title:'另一页面后来修改的已保存版本'+('较长标题'.repeat(20)),location:'L'.repeat(250),notes:'虚构长备注用于滚动验收。'.repeat(100)}});
        await open();await newArrangement();await recovered();
        check((await page.locator('#arrangement-recovery').textContent()).includes(newer.data.title),'Recovery shows the current saved version');await geometry(check);
        await choice('view');await page.waitForSelector('.event-detail');
        check((await page.locator('.dialog-head').textContent()).includes(newer.data.title),'View opens the saved record, not the stale draft');
        check((await read('/edit-cache/arrangement-new')).payload.data.title===old.data.title,'Viewing does not discard draft edits');
        await page.keyboard.press('Escape');await newArrangement();await recovered();await choice('copy');await page.waitForSelector('#arrangement-form');
        check(await page.locator('#arrangement-form [name=title]').inputValue()===old.data.title,'Explicit copy preserves the draft fields');
        check(await page.locator('#arrangement-form').getAttribute('data-request-id')!==old.request_id,'Explicit copy cannot reuse the completed request');
        await page.locator('#arrangement-form [type=submit]').click();await page.locator('#arrangement-form').waitFor({state:'detached'});
        const rows=await read('/arrangements');check(rows.find(x=>x.id===old.saved.id).data.title===newer.data.title&&rows.filter(x=>x.data.title===old.data.title).length===1,'Copy adds one new arrangement and preserves the later edit');
      });
      await run('Deleted result remains deleted until explicit recreation',async check=>{
        const old=await create(fixture('虚构已删除安排 '+Date.now()));await cache({request_id:old.request_id,data:old.data});
        await request('DELETE','/arrangements/'+old.saved.id,{version:1});await open();await newArrangement();await recovered();
        check((await page.locator('#arrangement-recovery').textContent()).includes('随后已删除'),'Recovery distinguishes deletion from a missing submission');
        check(!(await read('/arrangements')).some(x=>x.id===old.saved.id),'Opening recovery does not recreate a deleted item');
        await choice('copy');await page.waitForSelector('#arrangement-form');await page.locator('#arrangement-form [type=submit]').click();await page.locator('#arrangement-form').waitFor({state:'detached'});
        const rows=(await read('/arrangements')).filter(x=>x.data.title===old.data.title);check(rows.length===1&&rows[0].id!==old.saved.id,'Explicit recreation uses a different record');
      });
      await run('A lost success response is reconciled without retrying the write',async check=>{
        await cache(null);await open();await newArrangement();const title='虚构响应丢失 '+Date.now();await page.locator('#arrangement-form [name=title]').fill(title);
        const lost=async route=>{if(route.request().method()==='POST'){const r=await route.fetch();if(!r.ok())throw new Error('Expected committed write');await route.abort('failed');}else await route.continue();};
        await page.route(origin+'/api/arrangements',lost);
        try{await page.locator('#arrangement-form [type=submit]').click();await recovered();}finally{await page.unroute(origin+'/api/arrangements',lost);}
        check((await page.locator('#arrangement-recovery').textContent()).includes('已经保存'),'A failed transport does not masquerade as a failed write');
        check((await read('/arrangements')).filter(x=>x.data.title===title).length===1,'There is exactly one committed result');
      });
      await run('Unavailable status preserves the draft and retry restores editing',async check=>{
        const draft={request_id:randomUUID(),data:fixture('虚构尚未保存 '+Date.now())};await cache(draft);await open();
        const unavailable=route=>route.fulfill({status:503,json:{detail:'虚构状态服务不可用'}});
        await page.route(origin+'/api/arrangements/requests/*',unavailable);
        try{await newArrangement();await recovered();await geometry(check);check((await page.locator('#arrangement-recovery').textContent()).includes('暂时无法连接'),'Unavailable status is not treated as unsaved');}finally{await page.unroute(origin+'/api/arrangements/requests/*',unavailable);}
        await choice('retry');await page.waitForSelector('#arrangement-form');
        check(await page.locator('#arrangement-form [name=title]').inputValue()===draft.data.title,'Retry restores the untouched unsaved draft');
        check(await page.locator('#arrangement-form').getAttribute('data-request-id')===draft.request_id,'Unsaved intent keeps its idempotency key');
      });
      await run('Confirmed older server keeps an unsaved draft editable',async check=>{
        const draft={request_id:randomUUID(),data:fixture('虚构旧服务草稿 '+Date.now())};await cache(draft);await open();
        const missing=route=>route.fulfill({status:404,json:{detail:'Not Found'}}),legacy=route=>route.fulfill({json:{status:'ok',version:'1.14.0'}});
        await page.route(origin+'/api/arrangements/requests/*',missing);await page.route(origin+'/api/health',legacy);
        try{await newArrangement();await page.waitForSelector('#arrangement-form');check(await page.locator('#arrangement-form [name=title]').inputValue()===draft.data.title,'Older process does not block the existing draft');check(await page.locator('#arrangement-form').getAttribute('data-request-id')===draft.request_id,'Legacy fallback preserves the original request identity');check(await page.locator('[data-creation-status=legacy]').isVisible(),'Manual verification is explained when automatic status is unavailable');}
        finally{await page.unroute(origin+'/api/arrangements/requests/*',missing);await page.unroute(origin+'/api/health',legacy);}
      });
      await run('Missing endpoint on a current server is not treated as an unsaved draft',async check=>{
        const draft={request_id:randomUUID(),data:fixture('虚构当前服务异常 '+Date.now())};await cache(draft);await open();
        const missing=route=>route.fulfill({status:404,json:{detail:'Not Found'}}),current=route=>route.fulfill({json:{status:'ok',version:'1.14.1'}});
        await page.route(origin+'/api/arrangements/requests/*',missing);await page.route(origin+'/api/health',current);
        try{await newArrangement();await recovered();check((await page.locator('#arrangement-recovery').textContent()).includes('暂时无法连接'),'A current server failure cannot use legacy fallback');check((await read('/edit-cache/arrangement-new')).payload.request_id===draft.request_id,'Unknown state preserves the original draft');}
        finally{await page.unroute(origin+'/api/arrangements/requests/*',missing);await page.unroute(origin+'/api/health',current);}
      });
      await run('A delayed status read cannot replace a later dialog',async check=>{
        const old=await create(fixture('虚构迟到核对 '+Date.now()));await cache({request_id:old.request_id,data:old.data});await open();
        let release,observed,finished;const gate=new Promise(r=>release=r),started=new Promise(r=>observed=r),done=new Promise(r=>finished=r);
        const delayed=async route=>{observed();try{await gate;await route.continue();}finally{finished();}};
        await page.route(origin+'/api/arrangements/requests/*',delayed);
        try{await newArrangement();await started;await page.locator('.calendar-toolbar [data-calendar-action=options]').click();const response=page.waitForResponse(r=>r.url().includes('/api/arrangements/requests/'));release();await done;await(await response).finished();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));check(await page.locator('#calendar-option-date').count()===1&&!await page.locator('#arrangement-recovery').count(),'The later settings dialog remains open');}finally{release();await page.unroute(origin+'/api/arrangements/requests/*',delayed);}
      });
    }
    await context.close();
  }finally{await browser.close();}
}
}catch(error){report.errors.push({error:error.stack});}
report.passed=!report.errors.length&&report.scenarios.every(x=>x.passed);
await writeFile(artifactPath('arrangement-recovery-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:report.passed,scenarios:report.scenarios.length,checks:report.scenarios.reduce((sum,x)=>sum+x.checks.length,0),failed:report.scenarios.filter(x=>!x.passed),errors:report.errors},null,2));
if(!report.passed)process.exitCode=1;
