import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance'),version='1.9.0',origin='http://127.0.0.1:8781';
const fixture=JSON.parse(await readFile(path.join(root,`quality-preview-sources-${version}.json`),'utf8'));
const report={version,sample:fixture.sample,source_report:fixture.source_report,review_report:fixture.review_report,views:[],checks:[],errors:[]};
function check(name,passed){report.checks.push({name,passed});assert.ok(passed,name);}
try{
 for(const[engine,type]of Object.entries({chromium,firefox,webkit})){
  const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
  try{
   const ctx=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
   assert.ok((await ctx.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'business.notice.fixture',password:'Isolated-Notice-Fixture-2026'}})).ok());
   const page=await ctx.newPage();page.on('pageerror',e=>report.errors.push({engine,message:e.message}));let generated=0;
   page.on('request',r=>{if(r.url().endsWith('/generate'))generated++;});
   await page.goto(origin+'/#notice/'+fixture.notice_id,{waitUntil:'domcontentloaded'});await page.locator('#draft-form').waitFor();
   check(`${engine} every source record visible`,await page.locator('.quality-source').count()===fixture.quality.source_checks.length);
   await page.locator('.quality-source-checks').evaluate(e=>e.open=true);
   const attachment=page.locator('.quality-source').filter({hasText:'校园通知智能转办助手_项目需求.md'});
   check(`${engine} attachment deliverables kept`,['智能体','工作台','数据看板'].every(word=>fixture.quality.source_checks.some(c=>c.requirements_summary.includes(word))));
   await attachment.locator('details').evaluate(e=>e.open=true);
   for(const[width,height]of [[320,740],[390,844],[844,390],[1440,900]]){
    await page.setViewportSize({width,height});await attachment.evaluate(e=>e.scrollIntoView({block:'start'}));
    const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
    report.views.push({engine,width,height,...size});check(`${engine} ${width} no overflow`,size.scroll<=width+1);
    if((engine==='webkit'&&width===320)||(engine==='chromium'&&width===1440))await page.screenshot({path:path.join(root,`quality-sources-${version}-${engine}-${width}.png`)});
   }
   const link=attachment.locator('[data-action=evidence]').first(),sourceId=await link.getAttribute('data-source'),locator=await link.getAttribute('data-locator');
   await link.click();
   check(`${engine} exact source opens from attachment review`,await page.evaluate(({sourceId,locator})=>{
    const card=[...document.querySelectorAll('[data-source-card]')].find(e=>e.dataset.sourceCard===sourceId);
    return !!card?.open&&card.closest('.notice-originals').open&&[...card.querySelectorAll('.source-section')].some(e=>e.dataset.locator===locator);
   },{sourceId,locator}));
   check(`${engine} no paid generation`,generated===0);await ctx.close();
  }finally{await browser.close();}
 }
 check('no page errors',report.errors.length===0);
}finally{await writeFile(path.join(root,`notice-source-review-browser-${version}.json`),JSON.stringify(report,null,2));}
console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors}));
