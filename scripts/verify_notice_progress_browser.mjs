// Isolated fixture, real application routes, no external model calls.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance'),version='1.8.1',origin='http://127.0.0.1:8781';
const fixture=JSON.parse(await readFile(path.join(root,`action-plan-preview-${version}.json`),'utf8'));
assert.ok(path.resolve(fixture.data_dir).startsWith(root+path.sep));
const report={version,sample:'Synthetic live owner older than 240 seconds; no provider calls',views:[],checks:[],errors:[]};
const check=(name,condition)=>{report.checks.push({name,passed:!!condition});assert.ok(condition,name);};
function advance(item,phase){
  execFileSync(path.resolve('.venv/Scripts/python.exe'),['-c',`import sqlite3,sys,time,json
with sqlite3.connect(sys.argv[1]) as c:
 c.execute('UPDATE executions SET stage=? WHERE id=?',(sys.argv[4],sys.argv[3]))
 if sys.argv[4]=='complete':
  draft={'title':'处理结果验收','summary':'合成草稿，请对照核实','applicability':'needs_review','applicability_reason':'合成样本','facts':{},'tasks':[],'warnings':[]}
  c.execute("UPDATE notices SET status='draft',draft=?,processing_token=NULL,version=version+1,draft_version=version+1 WHERE id=?",(json.dumps(draft),sys.argv[2]))
  c.execute("UPDATE executions SET status='succeeded',finished_at=?,stage='verifying' WHERE id=?",(int(time.time()),sys.argv[3]))
  c.execute("INSERT INTO execution_metrics VALUES(?,?)",(sys.argv[3],json.dumps({'transport':'sse','first_answer_seconds':35.123,'provider_seconds':75.12,'validation_seconds':.018,'input_tokens':1234,'output_tokens':2345})))
`,path.join(fixture.data_dir,'campus.sqlite3'),item.id,item.execution_id,phase],{windowsHide:true});
}
async function fit(page,engine,width,height,view){
  await page.waitForFunction(()=>document.fonts.status==='loaded');
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const size=await page.evaluate(()=>{const d=document.querySelector('dialog[open]'),b=d?.querySelector('.dialog-body'),r=d?.getBoundingClientRect();return{scroll:document.documentElement.scrollWidth,width:innerWidth,dialog:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom,scroll:b.scrollWidth,client:b.clientWidth}:null};});
  report.views.push({engine,width,height,view,...size});check(`${engine} ${width} ${view}`,size.scroll<=width+1&&(!size.dialog||(size.dialog.left>=0&&size.dialog.right<=width+1&&size.dialog.top>=0&&size.dialog.bottom<=height+1&&size.dialog.scroll<=size.dialog.client+1)));
}
try{
 for(const[engine,type]of Object.entries({chromium,firefox,webkit})){
  const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
  try{
   const ctx=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),item=fixture.processing_notices[engine];
   assert.ok((await ctx.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'plans.'+engine,password:'Action-Plans-Fixture-2026'}})).ok());
   const page=await ctx.newPage();page.on('pageerror',e=>report.errors.push({engine,message:e.message}));let generated=0;page.on('request',r=>{if(r.url().endsWith('/generate'))generated++;});
   await page.goto(origin+'/#notice/'+item.id,{waitUntil:'domcontentloaded'});await page.locator('[data-notice-progress]').waitFor();
   await page.waitForFunction(()=>document.querySelector('[data-notice-elapsed]')?.textContent.includes('秒'));
   check(`${engine} long live owner remains processing`,await page.locator('[data-notice-phase]').textContent()==='正在结合原文整理');
   for(const[width,height]of [[320,740],[390,844],[844,390],[1440,900],[1920,1080]]){await page.setViewportSize({width,height});await fit(page,engine,width,height,'waiting');}
   advance(item,'receiving');await page.waitForFunction(()=>document.querySelector('[data-notice-phase]')?.textContent.includes('接收'));
   advance(item,'verifying');await page.waitForFunction(()=>document.querySelector('[data-notice-phase]')?.textContent.includes('校验'));
   await page.setViewportSize({width:390,height:844});await fit(page,engine,390,844,'verifying');
   await page.screenshot({path:path.join(root,`progress-${engine}-390.png`),fullPage:true});
   advance(item,'complete');await page.locator('#draft-form').waitFor();check(`${engine} auto refreshes validated result`,await page.locator('[data-notice-progress]').count()===0);
   await page.goto(origin+'/#settings',{waitUntil:'domcontentloaded'});await page.locator('[data-action=settings-model]').click();await page.locator('#open-executions').click();
   await page.locator('.execution-list').waitFor();check(`${engine} scalar timings visible`,(await page.locator('.execution-list').textContent()).includes('35.1 秒'));
   for(const[width,height]of [[320,740],[390,844],[844,390],[1440,900]]){await page.setViewportSize({width,height});await fit(page,engine,width,height,'record');}
   await page.setViewportSize({width:320,height:740});await page.screenshot({path:path.join(root,`progress-${engine}-320-record.png`),fullPage:true});
   check(`${engine} never regenerates`,generated===0);
   await ctx.close();
  }finally{await browser.close();}
 }
 check('no browser errors',report.errors.length===0);
}finally{await writeFile(path.join(root,`notice-progress-browser-${version}.json`),JSON.stringify(report,null,2));}
console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors}));
