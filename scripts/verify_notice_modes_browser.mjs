import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance'),version='1.10.0',origin='http://127.0.0.1:8781';
const fixture=JSON.parse(await readFile(path.join(root,`notice-modes-preview-${version}.json`),'utf8'));
const report={version,sample:fixture.sample,views:[],checks:[],errors:[]};
const check=(name,passed)=>{report.checks.push({name,passed});assert.ok(passed,name);};
try{
 for(const[engine,type]of Object.entries({chromium,firefox,webkit})){
  const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
  try{
   const ctx=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
   assert.ok((await ctx.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'notice.modes.fixture',password:'Notice-Modes-Fixture-2026'}})).ok());
   const page=await ctx.newPage();page.on('pageerror',error=>report.errors.push({engine,message:error.message}));const generated=[];
   page.on('request',request=>{if(request.url().endsWith('/generate'))generated.push(request.postDataJSON());});
   async function ready(mode){await page.goto(origin+'/#notice/'+fixture.notices[engine][mode],{waitUntil:'domcontentloaded'});await page.locator('#notice-processing-mode').waitFor();}
   await ready('fast');check(`${engine} starts with configured model`,await page.locator('#notice-processing-mode').inputValue()==='configured');
   await page.locator('#ai-consent').check();await page.locator('#notice-processing-mode').selectOption('fast');
   check(`${engine} switching price clears old consent`,!await page.locator('#ai-consent').isChecked());
   await page.locator('[data-action=generate]').click();check(`${engine} no request before renewed consent`,generated.length===0&&await page.locator('[data-notice-progress]').count()===0);
   check(`${engine} actual price is visible`,(await page.locator('[data-notice-mode-price]').textContent()).includes('10 倍'));
   await page.locator('#toast.visible').waitFor({state:'hidden'});
   for(const[width,height]of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});await page.locator('.notice-mode').evaluate(e=>e.scrollIntoView({block:'start'}));
    const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,selectFont:parseFloat(getComputedStyle(document.querySelector('#notice-processing-mode')).fontSize)}));
    report.views.push({engine,width,height,...size});check(`${engine} ${width} fits with cost expanded`,size.scroll<=width+1);
    if(width<=390){check(`${engine} ${width} mobile selection font`,size.selectFont>=16);check(`${engine} ${width} selection clears fixed header`,(await page.locator('#notice-processing-mode').boundingBox()).y>=48);}
    if((engine==='webkit'&&width===320)||(engine==='chromium'&&width===1440))await page.screenshot({path:path.join(root,`notice-mode-${version}-${engine}-${width}.png`)});
   }
   for(const mode of ['fast','configured']){
    if(mode==='configured')await ready(mode);
    check(`${engine} ${mode} selection explicit`,await page.locator('#notice-processing-mode').inputValue()===mode);
    await page.setViewportSize({width:390,height:844});await page.locator('#ai-consent').check();
    const resultPromise=page.waitForResponse(response=>response.url().endsWith('/generate')&&response.request().method()==='POST');
    await page.locator('[data-action=generate]').click();const response=await resultPromise;assert.ok(response.ok(),await response.text());await page.locator('#draft-form').waitFor();
    check(`${engine} ${mode} captured before controls disappear`,generated.at(-1).processing_mode===mode);
    const record=await response.json(),executions=await (await ctx.request.get(origin+'/api/executions')).json();
    const run=executions.items.find(item=>item.notice_id===record.id);
    assert.ok(run,'completed generation must have an execution record for the same notice');
    const expected=mode==='fast'?['mimo-v2.6-pro-ultraspeed','mimo-v2.6-pro-ultraspeed']:['mimo-v2.6-pro','mimo-v2.6-flash'];
    check(`${engine} ${mode} actually routes both stages`,JSON.stringify(run.metrics.calls.map(call=>call.model))===JSON.stringify(expected));
    check(`${engine} ${mode} complete review retained`,record.draft.quality.status==='passed'&&run.metrics.call_count===2);
    const history=await (await ctx.request.get(origin+'/api/notices/'+fixture.notices[engine][mode]+'/history')).json();
    check(`${engine} ${mode} consent recorded`,JSON.parse(history.find(item=>item.action==='ai_processing_consent').after_json).processing_mode===mode);
   }
   check(`${engine} exactly two user initiated generations`,generated.length===2);
   check(`${engine} no auto confirmed tasks`,(await (await ctx.request.get(origin+'/api/tasks')).json()).length===0);
   const session=await (await ctx.request.get(origin+'/api/session')).json();check(`${engine} configured models unchanged`,session.ai.model==='mimo-v2.6-pro'&&session.ai.notice_review_model==='mimo-v2.6-flash');
   await ctx.close();
  }finally{await browser.close();}
 }
 check('no page errors',report.errors.length===0);
}finally{await writeFile(path.join(root,`notice-modes-browser-${version}.json`),JSON.stringify(report,null,2));}
console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors}));
