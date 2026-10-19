import {artifactPath,visibleHidden} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8782',report={checks:[],views:[],errors:[],modelRequests:0,sample:'Isolated synthetic account, browser timing only; not human trial or full handling time.'};
const check=(name,value)=>{if(!value)throw Error(name);report.checks.push(name);};
let receiptId;
for(const engine of ['chromium','firefox','webkit']){
 const browser=await pw[engine].launch({headless:true,...(engine==='chromium'?{executablePath:pw.chromium.executablePath()}:{})});
 const context=await browser.newContext({reducedMotion:'reduce'}),page=await context.newPage();page.setDefaultTimeout(15000);
 page.on('pageerror',e=>report.errors.push(engine+': '+e.message));
 page.on('request',r=>{if(r.url().endsWith('/generate'))report.modelRequests++;});
 try{
  const headers={Origin:origin,'X-Requested-With':'campus-notice'};
  check(engine+' synthetic login',(await context.request.post(origin+'/api/auth/login',{headers,data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}})).ok());
  headers['X-CSRF-Token']=(await (await context.request.get(origin+'/api/session')).json()).csrf;
  const post=async(path,data,form=false)=>{const r=await context.request.post(origin+'/api'+path,{headers,...(form?{form:data}:{data})});if(!r.ok())throw Error(await r.text());return r.json();};
  let n=await post('/notices',{title:'虚构核对用时 '+engine+' '+Date.now(),body:'虚构通知：本人核对要求后提交申请表。仅验证页面计时。 '+Date.now(),materials_complete:'true'},true);
  n=await post('/notices/'+n.id+'/manual',{version:n.version});
  const go=async id=>{await page.goto(origin+'/#notice/'+id,{waitUntil:'domcontentloaded'});await page.waitForFunction(id=>document.querySelector('#content')?.dataset.page==='notice/'+id&&!document.querySelector('#content').hasAttribute('aria-busy'),id);await page.waitForSelector('#draft-form,.saved-notice-header');};
  await page.setViewportSize({width:390,height:844});await go(n.id);
  await page.locator('[data-action=add-task]').click();await page.locator('[data-editor] [name=title]').fill('核对并提交本人材料');
  // A controlled active interval proves the real event hooks, not fake submitted values.
  await page.waitForFunction(()=>document.querySelector('[data-review-time]')?.textContent!=='0 秒');
  for(const [width,height] of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
   await page.setViewportSize({width,height});await page.locator('.review-observation summary').click();
   if(!(await page.locator('.review-observation').evaluate(el=>el.open)))await page.locator('.review-observation summary').click();
   await page.locator('.review-observation').scrollIntoViewIfNeeded();
   const bounds=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));
   const hidden=await visibleHidden(page);check(`${engine}/${width} no hidden control or overflow`,!hidden.length&&bounds.scroll<=bounds.client+1);
   check(`${engine}/${width} timing scope is visible`,(await page.locator('.review-observation').innerText()).includes('关闭、刷新或重新打开分别计时'));
   if(width<=390)check(`${engine}/${width} touch target`,(await page.locator('.review-observation summary').boundingBox()).height>=44);
   report.views.push({engine,width,height,...bounds});
   if([320,1440].includes(width)){await page.evaluate(async()=>{await document.fonts.ready;window.scrollTo(0,0);});await page.screenshot({path:artifactPath(`review-time-${engine}-${width}.png`),fullPage:true});}
  }
  if(engine==='chromium'){
   const pattern='**/api/notices/'+n.id+'/confirm';let rejectedPayload;
   await page.route(pattern,async route=>{rejectedPayload=route.request().postDataJSON();await route.fulfill({status:422,json:{detail:'合成拒绝：检查重试和独立计时快照'}});},{times:1});
   await page.locator('[name=reviewed]').check();await page.locator('#draft-form [type=submit]').click();await page.locator('#draft-form .form-error').waitFor();
   check('failed request preserves active observation',rejectedPayload.review_observation.active_ms>0&&rejectedPayload.review_observation.editing_ms>0);
   const response=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.ok());await page.locator('#draft-form [type=submit]').click();await response;
   await page.waitForSelector('.saved-notice-header');receiptId=n.id;
   const saved=await (await context.request.get(origin+'/api/notices/'+n.id)).json();const value=saved.quality_receipt.observation;
   check('confirmation persists only bounded scalar observation',Object.keys(value).sort().join(',')==='active_ms,editing_ms,method'&&value.editing_ms<=value.active_ms&&value.active_ms>=rejectedPayload.review_observation.active_ms);
   check('manual draft has timing receipt despite no model issues',(await page.locator('.review-observation').innerText()).includes('本次页面核对用时'));
   const exported=await (await context.request.get(origin+'/api/export')).json();check('timing is in portable export',exported.notices.find(x=>x.id===n.id).quality_receipt.observation.active_ms===value.active_ms);
   await page.setViewportSize({width:320,height:740});await page.screenshot({path:artifactPath('review-time-receipt-320.png'),fullPage:true});
  }else{
   // Reload intentionally starts a new measured opening; no pre-refresh totals are fabricated.
   await page.reload({waitUntil:'domcontentloaded'});await page.locator('[data-review-time]').waitFor();
   check(engine+' reload starts a new opening',(await page.locator('[data-review-time]').innerText())==='0 秒');
   await go(receiptId);await page.locator('.review-observation summary').click();check(engine+' stored timing renders',(await page.locator('.review-observation').innerText()).includes('页面活跃'));
  }
 }catch(error){report.errors.push(engine+': '+error.stack);await page.screenshot({path:artifactPath(`review-time-failure-${engine}.png`)});}
 finally{await browser.close();}
}
check('no model generation requests',report.modelRequests===0);
await writeFile(artifactPath('review-observation-browser.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,views:report.views.length,errors:report.errors,modelRequests:report.modelRequests},null,2));
if(report.errors.length)process.exitCode=1;
