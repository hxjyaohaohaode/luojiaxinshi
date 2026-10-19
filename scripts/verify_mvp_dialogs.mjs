import {artifactPath,visibleHidden} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={views:[],checks:[],errors:[],speech:'Layout fixture only; no synthesis or real provider call.',pilot:'Policy response mocked for layout only; backend access control covered by test_pilot_access.py.'};
const browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()});
const context=await browser.newContext({reducedMotion:'reduce'}),page=await context.newPage();
page.on('pageerror',e=>report.errors.push(e.message));
async function shot(name,width,dialog=false){
  await page.evaluate(()=>document.fonts.ready);
  const state=await page.evaluate(dialog=>{const node=dialog?document.querySelector('#dialog'):document.documentElement,b=dialog?node.querySelector('.dialog-body'):node,r=node.getBoundingClientRect();return {width:innerWidth,height:innerHeight,left:r.left,right:r.right,top:r.top,bottom:r.bottom,scroll:b.scrollWidth,client:b.clientWidth};},dialog);
  const hiddenVisible=await visibleHidden(page,dialog?'#dialog':'body');report.views.push({name,width,dialog,...state,hiddenVisible});if(hiddenVisible.length)report.errors.push({name,width,hiddenVisible});
  await page.screenshot({path:artifactPath(`${name}-${width}.png`),fullPage:!dialog});
}
async function go(route){await page.goto(origin+'/#'+route);await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);}
async function close(){await page.keyboard.press('Escape');await page.waitForSelector('#dialog:not([open])',{state:'attached'});}
async function authRoute(mode){await page.goto(origin+'/?auth-check='+Date.now()+'#'+mode);}
try{
  for(const [width,height] of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});
    for(const mode of ['login','register','recover']){await authRoute(mode);await page.waitForSelector(`#auth-form[data-auth-mode="${mode}"]`);await shot('auth-'+mode,width);}
    await page.route('**/api/auth/policy',route=>route.fulfill({json:{registration_mode:'invite'}}));
    for(const mode of ['login','register','invite=synthetic-layout-only']){
      await authRoute(mode);await page.waitForSelector(`#auth-form[data-auth-mode="${mode.startsWith('invite=')?'register':'login'}"]`);
      await shot('pilot-'+mode.split('=')[0],width);
      if(mode==='register'&&await page.locator('.auth-tabs').count())throw new Error('Invited pilot exposed public signup');
    }
    await page.unroute('**/api/auth/policy');
  }
  await authRoute('login');await page.waitForSelector('#auth-form[data-auth-mode="login"]');
  await page.locator('#auth-form [name=username]').fill('workflow.demo');await page.locator('#auth-form [name=password]').fill('Mvp-Verification-Only-2026');
  await page.locator('#auth-form [type=submit]').click();await page.waitForFunction(()=>location.hash==='#dashboard'&&document.querySelector('#content')?.dataset.page==='dashboard');
  report.checks.push('Real login lands on the action dashboard');
  for(const [width,height] of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});
    await go('settings');
    for(const kind of ['profile','preferences','security','speech','genui','data']){
      if(kind==='speech')await page.route('**/api/speech/config',async route=>{const response=await route.fetch();await route.fulfill({json:{...await response.json(),configured:true}});});
      await page.locator(`[data-action="settings-${kind}"]`).click();await page.waitForSelector('#dialog[open]');
      await shot('settings-'+kind,width,true);
      if(kind==='profile')for(const section of ['contacts','goals']){await page.locator(`[data-action=profile-section][data-section=${section}]`).click();await shot('profile-'+section,width,true);}
      if(kind==='speech'){for(const mode of ['design','clone']){await page.locator('#speech-form [name=mode]').selectOption(mode);await shot('speech-'+mode,width,true);}await page.unroute('**/api/speech/config');}
      await close();
    }
    await go('sources');await page.locator('[data-source-action=add]').first().click();await page.waitForSelector('#dialog[open]');await shot('source-add',width,true);await close();
    await go('calendar');await page.locator('[data-calendar-action=new]').first().click();await page.waitForSelector('#arrangement-form');await shot('calendar-add',width,true);await close();
    await page.locator('[data-calendar-action=options]').click();await page.waitForSelector('#dialog[open]');await shot('calendar-options',width,true);await close();
    await go('tasks');await page.locator('[data-action=edit-task]').first().click();await page.waitForSelector('#task-form');await shot('task-edit',width,true);await close();
    const notices=await (await context.request.get(origin+'/api/notices')).json(),notice=notices.find(n=>n.title.includes('秋季'));
    await go('notice/'+notice.id);await page.locator('[data-change-new]').click();await page.waitForSelector('#change-form');
    await page.locator('#change-form [name=target]').first().check();await shot('change-create',width,true);await close();
  }
  report.failed=report.views.filter(v=>v.scroll>v.client+1||(v.dialog&&(v.left<0||v.right>v.width+1||v.top<0||v.bottom>v.height+1)));
  console.log(JSON.stringify({views:report.views.length,errors:report.errors,failed:report.failed},null,2));
  if(report.failed.length||report.errors.length)process.exitCode=1;
}catch(e){report.failure=e.stack;console.error(e);process.exitCode=1;}
finally{await writeFile(artifactPath('dialog-report.json'),JSON.stringify(report,null,2));await browser.close();}
