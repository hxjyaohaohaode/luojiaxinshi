// Run with scripts/run_browser_checks.py --suite verify_first_use_guide.mjs (isolated, real app).
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {browserOverride} from './browser-runtime.mjs';

const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/first-use-guide');
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...browserOverride(chromium)});
const guide='dialog[open] [data-onboarding-guide]',ready='#content:not([inert]):not([aria-busy])';
const errors=[],checks=[];
let passed=false;
async function openDevice(width){
  const context=await browser.newContext({viewport:{width,height:width<600?700:850},serviceWorkers:'block',reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(10000);
  page.on('pageerror',error=>errors.push(error.message));
  await context.route(/^https?:/,route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  return {page,context};
}
async function login(page,user,hash='login'){
  await page.goto(origin+'/#'+hash);
  await page.locator('[data-login-method=password]').click();
  await page.locator('#auth-form [name=username]').fill(user);
  await page.locator('#auth-form [name=password]').fill('PilotFixtureOnly2026!');
  await page.locator('#auth-form [type=submit]').click();
  await page.locator(ready).waitFor();
}
async function replay(page){
  await page.goto(origin+'/#settings');
  await page.getByRole('button',{name:/新手指引/}).click();
  return page.locator(guide);
}
async function inBounds(page){
  const bounds=await page.locator(guide).evaluate(node=>{
    const box=node.getBoundingClientRect(),dialog=node.closest('dialog').getBoundingClientRect();
    return {width:box.width,blankBelow:Math.max(0,dialog.bottom-box.bottom),fits:box.left>=0&&box.right<=innerWidth+1&&node.scrollWidth<=node.clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1};
  });
  assert.ok(bounds.width>=240&&bounds.fits&&bounds.blankBelow<50,JSON.stringify(bounds));
}
async function assertSeen(context){
  const r=await context.request.get(origin+'/api/session');assert.equal(r.status(),200);
  assert.equal((await r.json()).user.profile.first_use_guide_seen,true);
}
try{
  const desktop=await openDevice(1280),p=desktop.page;
  await login(p,'guide-first');
  const tour=p.locator(guide);
  await tour.getByRole('heading',{name:'从哪里收通知？'}).waitFor();
  await inBounds(p);
  checks.push('first visit on desktop');
  const writes=[];p.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push(new URL(r.url()).pathname);});
  await tour.getByRole('button',{name:'武大官网的'}).click();
  assert.equal(await tour.locator('[data-guide-route]').getAttribute('href'),'#sources');
  assert.match(await tour.locator('[data-guide-path-note]').innerText(),/自动收件/);
  await p.screenshot({path:path.join(out,'desktop.png')});
  await tour.getByRole('button',{name:'下一步'}).click();
  await tour.getByRole('heading',{name:'这条通知里，我要做什么？'}).waitFor();
  assert.equal(await tour.locator('[data-guide-step="2"] h3').evaluate(n=>n===document.activeElement),true);
  await tour.getByRole('button',{name:'上一步'}).click();
  assert.equal(await tour.getByRole('button',{name:'武大官网的'}).getAttribute('aria-pressed'),'true');
  await tour.getByRole('button',{name:'下一步'}).click();
  await tour.getByRole('button',{name:'下一步'}).click();
  await tour.getByRole('button',{name:'我要申请'}).click();
  assert.match(await tour.locator('[data-guide-result]').innerText(),/12 月 4 日 17:00/);
  await tour.getByRole('button',{name:'仅存资料'}).click();
  assert.match(await tour.locator('[data-guide-result]').innerText(),/都不会增加事项/);
  await tour.getByRole('button',{name:'开始使用'}).click();
  await tour.waitFor({state:'hidden'});await assertSeen(desktop.context);
  checks.push('next, back, both outcomes and finish');
  assert.deepEqual(writes.filter(path=>path!=='/api/profile'),[],'Tour must not write notices, subscriptions, AI jobs, or calendars');
  checks.push('no domain writes');
  await p.reload();await p.locator(ready+' .personal-home').waitFor();assert.equal(await tour.count(),0);
  await desktop.context.close();

  // Fresh browser storage proves persistence comes from the account, not just the first device.
  const phone=await openDevice(320),m=phone.page;
  await login(m,'guide-first');assert.equal(await m.locator(guide).count(),0);
  checks.push('account persistence across devices');
  const again=await replay(m);
  await again.getByRole('link',{name:'去收通知'}).click();
  await m.locator(ready+' #notice-form').waitFor();
  await replay(m);await again.getByRole('button',{name:'武大官网的'}).click();
  await again.getByRole('link',{name:'去选武大来源'}).click();
  await m.getByRole('button',{name:'选择武汉大学来源'}).waitFor();
  checks.push('replay and both intake links');
  // Same browser, different account: a direct link opens first and does not consume its tour.
  await phone.context.clearCookies();await m.goto('about:blank');await login(m,'guide-second','new');
  await m.locator(ready+' #notice-form').waitFor();
  assert.equal(await m.locator(guide).count(),0);
  assert.equal((await (await phone.context.request.get(origin+'/api/session')).json()).user.profile.first_use_guide_seen,false);
  await m.goto(origin+'/#dashboard');await again.waitFor();
  checks.push('second account, deep link then first home');
  await inBounds(m);
  await again.getByRole('button',{name:'下一步'}).click();await inBounds(m);
  await m.screenshot({path:path.join(out,'mobile.png')});
  checks.push('mobile layout');
  await again.getByRole('button',{name:'跳过指引'}).click();
  await assertSeen(phone.context);
  await m.reload();await m.locator(ready+' .personal-home').waitFor();assert.equal(await m.locator(guide).count(),0);
  checks.push('skip without a second prompt');
  await replay(m);await m.keyboard.press('Escape');await m.locator('dialog[open]').waitFor({state:'hidden'});
  await phone.context.close();assert.deepEqual(errors,[]);checks.push('replay and keyboard close');passed=true;
  console.log('First visit, skip, replay, both outcomes and cross-device/account checks passed.');
}catch(error){errors.push(error.message);throw error;}
finally{
  await browser.close();
  await writeFile(path.join(out,'report.json'),JSON.stringify({passed,viewports:[1280,320],checks,errors},null,2));
}
