import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance'),version='1.11.0',origin='http://127.0.0.1:8781';
const fixture=JSON.parse(await readFile(path.join(root,`notice-resolution-preview-${version}.json`),'utf8'));
const report={version,sample:fixture.sample,views:[],checks:[],errors:[]};
const check=(name,passed)=>{report.checks.push({name,passed:!!passed});assert.ok(passed,name);};
const notes={1:'已对照原文核对参赛纪律，团队办理全程遵守，不另造申请手续。',2:'同一立项名额限制已在意见四对应步骤中补充，不重复增加个人手续。'};
try{
 for(const[engine,type]of Object.entries({chromium,firefox,webkit})){
  const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
  try{
   const ctx=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
   assert.ok((await ctx.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'business.notice.fixture',password:'Isolated-Notice-Fixture-2026'}})).ok());
   const page=await ctx.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>report.errors.push({engine,message:e.message}));let generated=0;
   page.on('request',r=>{if(r.url().endsWith('/generate'))generated++;});
   const row=i=>page.locator(`[data-quality-decision="${i}"]`);
   async function ready(id=fixture.notice_id){await page.goto(origin+'/#notice/'+id,{waitUntil:'domcontentloaded'});await page.locator('#draft-form').waitFor();}
   await ready();check(`${engine} all four original findings`,await page.locator('.quality-issue').count()===4);
   check(`${engine} previous blanket note preserved`,(await page.locator('.quality-legacy-note').textContent()).includes(fixture.legacy_note));
   check(`${engine} excluded reward requires no typing`,await row(0).locator('[name=quality_action]').isDisabled());
   await page.locator('[data-editor="12"] [name=include]').check();check(`${engine} reselecting problematic step restores pending choice`,!await row(0).locator('[name=quality_action]').isDisabled());
   await page.locator('[data-editor="12"] [name=include]').uncheck();
   await row(1).locator('[name=quality_action]').selectOption('changed');await row(1).locator('[name=quality_task_key]').selectOption({index:1});
   check(`${engine} omission can point to selected content`,(await row(1).locator('[name=quality_task_key]').inputValue()).length>0);
   await row(1).locator('[name=quality_action]').selectOption('acknowledged');await row(1).locator('[name=quality_note]').fill(notes[1]);
   await row(2).locator('[name=quality_action]').selectOption('disagreed');await row(2).locator('[name=quality_note]').fill(notes[2]);
   await row(3).locator('[name=quality_action]').selectOption('changed');
   check(`${engine} irrelevant target controls are hidden`,!await row(1).locator('[data-quality-target]').isVisible()&&!await row(3).locator('[data-quality-target]').isVisible());
   await page.locator('#draft-form .autosave-status').filter({hasText:'已'}).waitFor();await ready();
   check(`${engine} per-issue choices survive reload`,await row(1).locator('[name=quality_note]').inputValue()===notes[1]&&await row(2).locator('[name=quality_action]').inputValue()==='disagreed');
   for(const[width,height]of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});await row(1).evaluate(e=>e.scrollIntoView({block:'start'}));
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
    const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,fields:[...document.querySelectorAll('.quality-decision select,.quality-decision textarea')].filter(e=>e.getBoundingClientRect().width).map(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,font:parseFloat(getComputedStyle(e).fontSize)}))}));
    report.views.push({engine,width,height,...size});check(`${engine} ${width} decisions fit`,size.scroll<=width+1&&size.fields.every(f=>f.left>=0&&f.right<=width+1));
    if(width<=390)check(`${engine} ${width} input font`,size.fields.every(f=>f.font>=16));
    check(`${engine} ${width} notes adapt after resize`,await row(1).locator('[name=quality_note]').evaluate(e=>e.clientHeight+2>=e.scrollHeight||e.clientHeight>=210));
    if((engine==='webkit'&&width===320)||(engine==='chromium'&&width===1440))await page.screenshot({path:path.join(root,`notice-resolution-${version}-${engine}-${width}.png`)});
   }
   await page.setViewportSize({width:390,height:844});
   if(engine==='chromium'){
    await page.locator('[data-editor="0"] [data-action=move-step][data-direction="1"]').click();
    await page.locator('.quality-issue').nth(3).evaluate(e=>e.open=true);await page.locator('[data-action=quality-step][data-source-index="0"]').click();
    check('finding still locates original after reorder',await page.locator('[data-editor="1"] [name=title]').evaluate(e=>e===document.activeElement));
    await page.locator('[data-editor="1"] [data-action=move-step][data-direction="-1"]').click();
    await page.locator('[name=reviewed]').check();const rejectedPromise=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');
    await page.locator('#draft-form [type=submit]').click();const rejected=await rejectedPromise;
    check('unchanged steps cannot be claimed corrected',rejected.status()===422&&(await rejected.text()).includes('尚无实际改动'));
    const tasks=await (await ctx.request.get(origin+'/api/tasks')).json();check('rejected confirmation is atomic',tasks.every(t=>t.notice_id!==fixture.notice_id));
   }
   if(engine==='webkit'){
    await page.locator('[data-editor="0"] [name=details]').fill('核对团队人数与指导教师资格；本人知悉，本榜题原则上最终立项不超过三个团队，符合参赛条件不等于已经获准立项。');
    await page.locator('[name=reviewed]').check();const promise=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');
    await page.locator('#draft-form [type=submit]').click();const response=await promise;assert.ok(response.ok(),await response.text());
    await page.locator('.quality-receipt').waitFor();await page.reload({waitUntil:'domcontentloaded'});await page.locator('.quality-receipt').waitFor();
    await page.locator('.quality-receipt').evaluate(e=>e.open=true);await page.locator('.quality-receipt-item').nth(1).evaluate(e=>e.open=true);
    check('readable receipt retains human basis after reload',(await page.locator('.quality-receipt').textContent()).includes(notes[1]));
    const saved=await (await ctx.request.get(origin+'/api/notices/'+fixture.notice_id)).json();
    check('all four decisions and original opinions retained',saved.quality_receipt.issues.length===4&&saved.quality_receipt.issues.map(i=>i.action).join(',')==='excluded,acknowledged,disagreed,changed');
    check('invented application never becomes a saved task',saved.tasks.every(t=>!t.data.title.includes('奖励申报')));
    await page.setViewportSize({width:320,height:740});await page.locator('.quality-receipt').evaluate(e=>e.scrollIntoView({block:'start'}));
    check('receipt fits narrow mobile',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,`notice-resolution-receipt-${version}-320.png`)});
   }
   await ready(fixture.manual_notices[engine]);await page.locator('[name=quality_resolution]').fill('已经逐份人工核对该合成通知，材料、责任人和未知期限保持原样。');await page.locator('[name=reviewed]').check();
   await page.locator('#draft-form [type=submit]').click();check(`${engine} incomplete review requires explicit attestation`,await page.locator('[name=manual_quality_reviewed]').evaluate(e=>!e.validity.valid));
   await page.locator('[name=manual_quality_reviewed]').check();await page.locator('[name=reviewed]').check();
   const promise=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');await page.locator('#draft-form [type=submit]').click();const result=await promise;assert.ok(result.ok(),await result.text());
   await page.locator('.quality-receipt').waitFor();check(`${engine} human fallback receipt explicit`,(await page.locator('.quality-receipt').textContent()).includes('逐份人工核对'));
   check(`${engine} no paid regeneration`,generated===0);await ctx.close();
  }finally{await browser.close();}
 }
 check('no page errors',report.errors.length===0);
}finally{await writeFile(path.join(root,`notice-resolution-browser-${version}.json`),JSON.stringify(report,null,2));}
console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors}));
