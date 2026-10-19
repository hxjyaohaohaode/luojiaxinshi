import {artifactPath} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';

const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={scenarios:[],errors:[]};
const sizes=JSON.parse(process.env.MVP_VIEWPORTS||'[{"width":320,"height":740},{"width":390,"height":844},{"width":600,"height":800},{"width":850,"height":800}]');
const selected=new Set((process.env.MVP_FOCUS_CASES||'').split(',').filter(Boolean));

// Hold only the application's named drawer-focus callbacks. The rest of the
// browser clock, network, autosave and route handling continues normally.
function installFocusSchedule(){
  const timers={timeout:window.setTimeout.bind(window),clear:window.clearTimeout.bind(window),frame:window.requestAnimationFrame.bind(window),cancel:window.cancelAnimationFrame.bind(window)};
  const pending=new Map();let next=-1;
  const harness=window.__focusSchedule={holdTimeout:false,holdFrame:false,events:[],release(kind){
    for(const [id,task] of [...pending]){if(task.kind!==kind)continue;pending.delete(id);this.events.push({event:'released',kind});task.fn(performance.now());}
  }};
  window.setTimeout=function(fn,delay,...args){
    if(harness.holdTimeout&&delay===260&&fn?.name==='focusMenu'){const id=next--;pending.set(id,{kind:'timeout',fn:()=>fn(...args)});harness.events.push({event:'scheduled',kind:'timeout'});return id;}
    return timers.timeout(fn,delay,...args);
  };
  window.clearTimeout=function(id){if(pending.has(id)){harness.events.push({event:'cancelled',kind:pending.get(id).kind});pending.delete(id);}else timers.clear(id);};
  window.requestAnimationFrame=function(fn){
    if(harness.holdFrame&&fn?.name==='focusMenu'){const id=next--;pending.set(id,{kind:'frame',fn});harness.events.push({event:'scheduled',kind:'frame'});return id;}
    return timers.frame(fn);
  };
  window.cancelAnimationFrame=function(id){if(pending.has(id)){harness.events.push({event:'cancelled',kind:pending.get(id).kind});pending.delete(id);}else timers.cancel(id);};
}

try{
  for(const engine of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
    const browser=await engines[engine].launch({headless:true,executablePath:engines[engine].executablePath()});
    try{
      for(const motion of (process.env.MVP_MOTIONS||'reduce,no-preference').split(',')){
        const context=await browser.newContext({reducedMotion:motion});
        try{
          const registration=await context.request.post(origin+'/api/auth/register',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'focus.'+engine+'.'+Date.now(),password:'Focus-Verification-Only-2026',display_name:'虚构导航验收',accepted_terms:true}});
          if(!registration.ok())throw new Error('Synthetic fixture registration failed: '+registration.status());
          const page=await context.newPage();page.setDefaultTimeout(10000);await page.addInitScript(installFocusSchedule);
          page.on('pageerror',e=>report.errors.push({engine,motion,error:e.message}));
          const open=async route=>{await page.goto(origin+'/?focus-check='+Date.now()+'#'+route);await page.waitForSelector('#content[data-page="'+route+'"]');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});};
          const menu=()=>page.locator('.mobile-bottom-nav [data-action=menu]').click();
          const input=()=>page.locator('#notice-form [name=title]');
          const focusState=()=>page.evaluate(()=>({tag:document.activeElement?.tagName,name:document.activeElement?.getAttribute('name'),classes:document.activeElement?.className,events:window.__focusSchedule.events}));
          const typed=async(check,label)=>{const title='焦点验收 '+label;await input().fill(title);return title;};
          const checkTyping=async(check,title)=>{
            const actual=await focusState();check(actual.name==='title','Focus remains in the title input',actual);
            await page.keyboard.insertText(' 后续文字');check(await input().inputValue()===title+' 后续文字','Subsequent typing reaches the intended field',await input().inputValue());
          };
          for(const viewport of sizes){
            const run=async(id,work)=>{
              if(selected.size&&!selected.has(id))return;
              await page.setViewportSize(viewport);
              const result={engine,motion,...viewport,id,checks:[]},check=(passed,detail,actual)=>result.checks.push({passed:!!passed,detail,...(actual===undefined?{}:{actual})});
              try{await work(check);result.passed=result.checks.length>0&&result.checks.every(x=>x.passed);}catch(error){result.passed=false;result.error=error.stack;}
              report.scenarios.push(result);console.log(engine,motion,viewport.width,id,result.passed?'pass':'FAIL');
            };
            await run('navigate-before-delayed-focus',async check=>{
              await open('tasks');await page.evaluate(()=>window.__focusSchedule.holdTimeout=true);await menu();
              await page.locator('.sidebar-create').click();await page.waitForSelector('#notice-form');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});
              const title=await typed(check,'切页');await page.evaluate(()=>window.__focusSchedule.release('timeout'));await checkTyping(check,title);
              if(engine==='webkit'&&motion==='reduce'&&viewport.width===390)await page.screenshot({path:artifactPath('navigation-title-390.png'),animations:'disabled'});
            });
            await run('close-before-delayed-focus',async check=>{
              await open('new');await page.evaluate(()=>window.__focusSchedule.holdTimeout=true);await menu();await page.keyboard.press('Escape');
              await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
              const title=await typed(check,'关闭导航');await page.evaluate(()=>window.__focusSchedule.release('timeout'));await checkTyping(check,title);
            });
            await run('resize-before-delayed-focus',async check=>{
              await open('new');await page.evaluate(()=>window.__focusSchedule.holdTimeout=true);await menu();await page.setViewportSize({width:1024,height:800});
              await page.waitForFunction(()=>!document.querySelector('.workspace').inert);
              const title=await typed(check,'改为桌面');await page.evaluate(()=>window.__focusSchedule.release('timeout'));await checkTyping(check,title);
              check(await page.locator('.shell.menu-open').count()===0,'Desktop layout is not left in a modal drawer state');
            });
            await run('new-interaction-before-close-frame',async check=>{
              await open('new');await menu();await page.waitForFunction(()=>document.querySelector('.sidebar').contains(document.activeElement));
              await page.evaluate(()=>window.__focusSchedule.holdFrame=true);await page.keyboard.press('Escape');
              const title=await typed(check,'关闭后输入');await page.evaluate(()=>window.__focusSchedule.release('frame'));await checkTyping(check,title);
            });
            await run('keyboard-drawer-and-return-target',async check=>{
              await open('new');await menu();await page.waitForFunction(()=>document.querySelector('.sidebar').contains(document.activeElement));
              check(await page.locator('.workspace').evaluate(e=>e.inert),'Background is inert while the phone drawer is open');
              await page.evaluate(()=>[...document.querySelectorAll('.sidebar a[href],.sidebar button:not(:disabled)')].at(-1).focus());await page.keyboard.press('Tab');
              check(await page.evaluate(()=>document.activeElement===document.querySelector('.sidebar a[href],.sidebar button:not(:disabled)')),'Tab wraps from the last menu control to the first');
              await page.keyboard.press('Shift+Tab');
              check(await page.evaluate(()=>document.activeElement===[...document.querySelectorAll('.sidebar a[href],.sidebar button:not(:disabled)')].at(-1)),'Shift+Tab wraps to the last menu control');
              if(engine==='chromium'&&motion==='reduce'&&viewport.width===390)await page.screenshot({path:artifactPath('drawer-390.png'),animations:'disabled'});
              await page.keyboard.press('Escape');await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
              check(await page.evaluate(()=>document.activeElement===document.querySelector('.mobile-bottom-nav [data-action=menu]')),'Escape returns focus to the control that opened the drawer',await focusState());
              check(await page.locator('.workspace').evaluate(e=>!e.inert),'Closing restores access to the page');
            });
            await run('header-control-retains-its-return-target',async check=>{
              await open('new');await page.locator('.workspace-chrome-toggle').click();await page.waitForFunction(()=>document.querySelector('.sidebar').contains(document.activeElement));
              await page.keyboard.press('Escape');await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
              check(await page.evaluate(()=>document.activeElement===document.querySelector('.workspace-chrome-toggle')),'The header opener receives focus when it opened the drawer');
              check(await page.locator('.workspace').evaluate(e=>!e.inert),'Header drawer close restores the page');
            });
            await run('escape-only-closes-the-top-dialog',async check=>{
              await open('new');await menu();await page.waitForFunction(()=>document.querySelector('.sidebar').contains(document.activeElement));
              await page.keyboard.press('/');await page.waitForSelector('#global-search');await page.locator('#global-search').focus();
              await page.keyboard.press('Shift+Tab');
              check(await page.evaluate(()=>document.activeElement===document.querySelector('#dialog [data-action=close-dialog]')),'The drawer does not trap Tab away from the search dialog');
              // A nonempty native search input may consume Escape to clear its
              // value in Chromium. Test modal dismissal with that control empty.
              await page.locator('#global-search').fill('');
              await page.keyboard.press('Escape');await page.locator('#dialog[open]').waitFor({state:'detached'});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
              check(await page.locator('.shell.menu-open').count()===1,'Closing the search dialog preserves the underlying navigation drawer');
              check(await page.evaluate(()=>document.querySelector('.sidebar').contains(document.activeElement)),'Dialog close returns focus to the still-open navigation');
              await page.keyboard.press('Escape');await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
              check(await page.evaluate(()=>!document.querySelector('.shell.menu-open')&&document.activeElement===document.querySelector('.mobile-bottom-nav [data-action=menu]')),'A second Escape closes the drawer and returns to its opener');
            });
            await run('opening-callback-cannot-steal-dialog-focus',async check=>{
              await open('new');await page.evaluate(()=>window.__focusSchedule.holdTimeout=true);await menu();await page.keyboard.press('/');await page.waitForSelector('#global-search');
              await page.locator('#global-search').fill('虚构查询');await page.evaluate(()=>window.__focusSchedule.release('timeout'));
              check(await page.locator('#global-search').evaluate(e=>e===document.activeElement),'The later search dialog retains focus');
              await page.keyboard.insertText('继续');check(await page.locator('#global-search').inputValue()==='虚构查询继续','Typing stays inside the later search dialog');
            });
          }
        }finally{await context.close();}
      }
    }finally{await browser.close();}
  }
}catch(error){report.errors.push({error:error.stack});}
report.passed=report.scenarios.length>0&&!report.errors.length&&report.scenarios.every(x=>x.passed);
await writeFile(artifactPath('navigation-focus-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:report.passed,scenarios:report.scenarios.length,checks:report.scenarios.reduce((sum,x)=>sum+x.checks.length,0),failed:report.scenarios.filter(x=>!x.passed),errors:report.errors}));
if(!report.passed)process.exitCode=1;
