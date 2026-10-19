import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance'),version='1.9.0',origin='http://127.0.0.1:8781';
const fixture=JSON.parse(await readFile(path.join(root,`quality-preview-${version}.json`),'utf8'));
const report={version,sample:fixture.sample,views:[],checks:[],errors:[]};
const check=(name,value)=>{report.checks.push({name,passed:!!value});assert.ok(value,name);};
const route='notice/'+fixture.notice_id;
const explanation='已逐项对照原文：培训暂不保存，奖金申请未规定故不保存；交付材料补齐智能体、工作台、数据看板，提交方式和时间仍待核实。';
async function ready(page){await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});await page.locator('#draft-form').waitFor();await page.waitForFunction(()=>document.fonts.status==='loaded');}
async function fit(page,engine,width,height,view){
 await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,fields:[...document.querySelectorAll('.notice-quality textarea,.notice-quality button')].filter(e=>e.getBoundingClientRect().width).map(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,font:parseFloat(getComputedStyle(e).fontSize),tag:e.tagName}))}));
 report.views.push({engine,width,height,view,...size});check(`${engine} ${width} ${view}`,size.scroll<=width+1&&size.fields.every(f=>f.left>=0&&f.right<=width+1));
 if(width<=390)check(`${engine} ${width} mobile input size`,size.fields.filter(f=>f.tag==='TEXTAREA').every(f=>f.font>=16));
}
try{
 for(const[engine,type]of Object.entries({chromium,firefox,webkit})){
  const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
  try{
   const ctx=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
   assert.ok((await ctx.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'business.notice.fixture',password:'Isolated-Notice-Fixture-2026'}})).ok());
   const page=await ctx.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>report.errors.push({engine,message:e.message}));let generated=0;page.on('request',r=>{if(r.url().endsWith('/generate'))generated++;});
   await ready(page);check(`${engine} all findings visible`,await page.locator('.quality-issue').count()===fixture.quality.issues.length);
   check(`${engine} findings use student wording`,!(await page.locator('.quality-issue').first().locator(':scope > p').textContent()).includes('plan.action_kind'));
   for(const[width,height]of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});await page.locator('.notice-quality').evaluate(e=>e.scrollIntoView({block:'start'}));await fit(page,engine,width,height,'review');
    await page.locator('.quality-issue').first().evaluate(e=>e.open=true);await page.locator('.quality-issue').first().locator('details').evaluate(e=>e.open=true);
    await fit(page,engine,width,height,'evidence');
    if((engine==='chromium'&&[390,1440].includes(width))||(engine==='webkit'&&width===320))await page.screenshot({path:path.join(root,`quality-${version}-${engine}-${width}.png`)});
   }
   await page.setViewportSize({width:390,height:844});
   const first=fixture.quality.issues.find(i=>i.task_index!==null),idx=first.task_index;
   await page.locator(`[data-action=quality-step][data-source-index="${idx}"]`).first().click();
   check(`${engine} jumps to actual task`,await page.locator(`[data-editor="${idx}"] [name=title]`).evaluate(e=>e===document.activeElement));
   if(engine==='chromium'){
    await page.locator('[name=quality_resolution]').fill('暂存的核对说明，稍后继续逐项处理。');
    await page.locator(`[data-editor="${idx}"] [data-action=move-step][data-direction="-1"]`).click();
    await page.locator('.quality-issue').first().evaluate(e=>e.open=true);await page.locator(`[data-action=quality-step][data-source-index="${idx}"]`).first().click();
    check('finding survives task reorder',await page.locator(`[data-editor="${idx-1}"] [name=title]`).evaluate(e=>e===document.activeElement));
    await page.locator(`[data-editor="${idx-1}"] [data-action=move-step][data-direction="1"]`).click();
    await page.locator('#draft-form .autosave-status').filter({hasText:'已'}).waitFor();
    await ready(page);check('review explanation survives reload',(await page.locator('[name=quality_resolution]').inputValue()).includes('暂存的核对说明'));
   }
   if(engine==='webkit'){
    await page.locator('[name=quality_resolution]').fill('');await page.locator('[name=reviewed]').check();
    await page.locator('#draft-form [type=submit]').click();
    check('browser requires explicit explanation',await page.locator('[name=quality_resolution]').evaluate(e=>!e.validity.valid));
    check('no tasks before resolution',(await (await ctx.request.get(origin+'/api/tasks')).json()).length===0);
    const training=page.locator('[data-editor="10"]');await training.locator('[name=include]').uncheck();
    const deliver=page.locator('[data-editor="13"]');await deliver.locator('[name=materials]').evaluate(e=>e.closest('details').open=true);
    await deliver.locator('[name=materials]').fill('智能体\n工作台\n数据看板');
    await deliver.locator('[name=details]').fill('按榜题要求交付智能体、工作台、数据看板，配合验收；具体提交方式与验收时间仍待原单位说明。');
    check('invented optional application stays unselected',!await page.locator('[data-editor="19"] [name=include]').isChecked());
    await page.locator('[name=quality_resolution]').fill(explanation);
    const confirmed=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');await page.locator('#draft-form [type=submit]').click();
    const response=await confirmed;assert.ok(response.ok(),await response.text());await page.locator('#draft-form').waitFor({state:'detached'});
    const tasks=await (await ctx.request.get(origin+'/api/tasks')).json();check('saves nine selected corrected steps',tasks.length===9);
    check('explicit deliverables persisted',tasks.some(t=>['智能体','工作台','数据看板'].every(m=>t.data.materials.includes(m))));
    const history=await (await ctx.request.get(origin+'/api/notices/'+fixture.notice_id+'/history')).json(),confirmation=history.find(h=>h.action==='confirm_draft');
    check('original findings and decision preserved',JSON.parse(confirmation.before_json).quality.issues.length===4&&JSON.parse(confirmation.after_json).quality_resolution===explanation);
   }
   check(`${engine} no paid regeneration`,generated===0);await ctx.close();
  }finally{await browser.close();}
 }
 check('no page errors',report.errors.length===0);
}finally{await writeFile(path.join(root,`notice-quality-browser-${version}.json`),JSON.stringify(report,null,2));}
console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors}));
