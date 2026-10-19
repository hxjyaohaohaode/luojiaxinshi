import {artifactPath,visibleHidden} from './mvp_check_runtime.mjs';
// Synthetic local server only. PLAYWRIGHT_PATH may point to a bundled runtime.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=artifactPath();await mkdir(root,{recursive:true});
const origin='http://127.0.0.1:8780';
const engines={chromium,firefox,webkit};
const selected=(process.env.MVP_BROWSERS||'chromium').split(',');
const report={routes:[],dialogs:[],errors:[]};
let sharedAuth;
for(const name of selected){
  console.log('Checking browser:',name);
  const browser=await engines[name].launch({headless:true,...(name==='chromium'?{executablePath:chromium.executablePath()}:{})});
  try{
  const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce',...(sharedAuth?{storageState:sharedAuth}:{})});
  if(!sharedAuth){
    const login=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
    if(!login.ok())throw new Error('Fixture login failed: '+await login.text());
    sharedAuth=await context.storageState();
  }
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push({engine:name,message:e.message}));
  page.setDefaultTimeout(15000);page.setDefaultNavigationTimeout(15000);
  const notices=await (await context.request.get(origin+'/api/notices')).json();
  const notice=notices.find(n=>n.title.includes('秋季'));
  const routes=['dashboard','tasks','notices','new','chat','calendar','sources','settings','memory','notice/'+notice.id];
  const sizes=process.env.MVP_VIEWPORTS?JSON.parse(process.env.MVP_VIEWPORTS):(name==='chromium'||process.env.MVP_ALL_VIEWPORTS==='true')?[[1440,900],[390,844],[320,740],[768,1024],[844,390],[1920,1080]]:[[390,844],[1440,900]];
  for(const [width,height] of sizes){
    console.log('Checking viewport:',name,width,height);
    await page.setViewportSize({width,height});
    for(const route of routes){
      await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});
      await page.waitForFunction(route=>{const c=document.querySelector('#content');return c?.dataset.page===route&&!c.hasAttribute('aria-busy');},route,{timeout:25000});
      await page.waitForFunction(()=>document.fonts.status==='loaded',null,{timeout:5000});
      const metrics=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,
        error:document.querySelector('#content')?.textContent.includes('暂时未能打开'),
        title:document.querySelector('#content h1')?.textContent,
        overflow:[...document.querySelectorAll('#content *')].filter(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.right>innerWidth+2&&s.position!=='fixed'&&!el.closest('[hidden],.tabs,.time-grid,.calendar-scroll,.dependency-list');}).slice(0,8).map(el=>({tag:el.tagName,cls:el.className,right:Math.round(el.getBoundingClientRect().right)}))}));
      const hiddenVisible=await visibleHidden(page);report.routes.push({engine:name,route,width,height,...metrics,hiddenVisible});
      // Check component alignment, not just document overflow. A larger touch
      // target must not cover a neighboring title or drift outside its column.
      const alignment=await page.evaluate(()=>{
        const failures=[];
        for(const row of document.querySelectorAll('.task-row')){
          const check=row.querySelector('.task-check')?.getBoundingClientRect(),title=row.querySelector('.task-title')?.getBoundingClientRect();
          if(check&&title&&Math.min(check.right,title.right)-Math.max(check.left,title.left)>1&&Math.min(check.bottom,title.bottom)-Math.max(check.top,title.top)>1)failures.push('Task checkbox overlaps title');
          for(const button of row.querySelectorAll('.task-actions button')){const box=button.getBoundingClientRect();if(box.width<39||box.height<39)failures.push('Task action target is too small');}
        }
        const main=document.querySelector('.chat-main'),composer=document.querySelector('.chat-composer'),heading=document.querySelector('.chat-heading h1');
        if(main&&composer){const m=main.getBoundingClientRect(),c=composer.getBoundingClientRect();if(Math.abs((c.left-m.left)-(m.right-c.right))>2)failures.push('Chat composer is not centered');if(c.left<m.left-1||c.right>m.right+1)failures.push('Chat composer leaves its column');}
        if(heading&&heading.getBoundingClientRect().width<=1)failures.push('Chat heading is hidden');
        return [...new Set(failures)];
      });
      report.routes.at(-1).alignment=alignment;
      await writeFile(path.join(root,'browser-progress.json'),JSON.stringify(report,null,2));
      if(process.env.MVP_SCREENSHOTS!=='false'&&name==='chromium'&&[1440,390,320].includes(width))await page.screenshot({path:path.join(root,`${route.split('/')[0]}-${width}.png`),fullPage:true,animations:'disabled'});
      if(process.env.MVP_SCREENSHOTS!=='false'&&name!=='chromium'&&width===390&&['calendar','sources'].includes(route))await page.screenshot({path:path.join(root,`${name}-${route}-${width}.png`),fullPage:true,animations:'disabled'});
    }
    console.log('Checking workflow dialog:',name,width,height);
    await page.goto(origin+'/#tasks',{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='tasks'&&!document.querySelector('#content').hasAttribute('aria-busy'));
    await page.locator('.task-title[data-workflow-task]').first().click();
    await page.waitForSelector('#workflow-form');
    const dialog=await page.evaluate(()=>{const d=document.querySelector('dialog'),b=d.querySelector('.dialog-body');return {left:d.getBoundingClientRect().left,right:d.getBoundingClientRect().right,top:d.getBoundingClientRect().top,bottom:d.getBoundingClientRect().bottom,width:innerWidth,height:innerHeight,scroll:b.scrollWidth,client:b.clientWidth};});
    report.dialogs.push({engine:name,view:'workflow',width,height,...dialog});
    if(process.env.MVP_SCREENSHOTS!=='false'&&name==='chromium'&&[1440,390,320].includes(width))await page.screenshot({path:path.join(root,`workflow-${width}.png`)});
    await page.keyboard.press('Escape');
  }
  console.log('Routes and dialogs complete:',name);
  await page.close({runBeforeUnload:false});
  }catch(error){report.errors.push({engine:name,message:error.message});await writeFile(path.join(root,'browser-report.json'),JSON.stringify(report,null,2));throw error;}
  finally{await browser.close().catch(()=>{});}
}
await writeFile(path.join(root,'browser-report.json'),JSON.stringify(report,null,2));
const failed=[...report.routes.filter(r=>r.scroll>r.width+1||r.error||r.hiddenVisible.length||r.alignment?.length),...report.dialogs.filter(d=>d.left<0||d.right>d.width+1||d.top<0||d.bottom>d.height+1||d.scroll>d.client+1)];
console.log(JSON.stringify({routes:report.routes.length,dialogs:report.dialogs.length,errors:report.errors,failed,overflows:report.routes.filter(r=>r.overflow.length).map(r=>({engine:r.engine,route:r.route,width:r.width,overflow:r.overflow}))},null,2));
if(failed.length||report.errors.length)process.exitCode=1;
