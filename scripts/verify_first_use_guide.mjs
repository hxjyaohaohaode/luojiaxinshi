// Isolated account fixtures and the same screens, routing and source picker as the app.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {browserOverride} from './browser-runtime.mjs';

const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/first-use-guide');
const layer='[data-onboarding-guide]',anchor='[data-guide-current]',ready='#content:not([inert]):not([aria-busy])';
const receive='.home-heading a[href="#new"]',sources='.home-heading a[href="#sources"]';
const body='#notice-form textarea[name="body"]',save='#notice-form [value="save"]';
const errors=[],checks=[];
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...browserOverride(chromium)});
async function device(width){
  const context=await browser.newContext({viewport:{width,height:width<600?700:850},isMobile:width<600,hasTouch:width<600,serviceWorkers:'block',reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(10000);
  page.on('pageerror',err=>errors.push(err.message));
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
  await page.locator(receive+anchor).waitFor();
}
async function seen(context){
  const response=await context.request.get(origin+'/api/session');assert.equal(response.status(),200);
  return (await response.json()).user.profile.first_use_guide_seen;
}
function recordWrites(page){
  const writes=[];
  page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))writes.push(new URL(r.url()).pathname);});
  return writes;
}
async function pointed(page,selector){
  const target=page.locator(selector+anchor);
  await target.waitFor();
  await page.waitForFunction(selector=>{
    const target=document.querySelector(selector+'[data-guide-current]'),tip=document.querySelector('.guide-tip'),ring=document.querySelector('.guide-ring');
    if(!target||!ring||!tip)return false;
    const t=target.getBoundingClientRect(),c=tip.getBoundingClientRect(),r=ring.getBoundingClientRect();
    const hit=document.elementFromPoint(t.x+t.width/2,t.y+t.height/2);
    const apart=c.bottom<=t.top||c.top>=t.bottom||c.right<=t.left||c.left>=t.right;
    return (hit===target||target.contains(hit))&&apart&&c.width>=238&&c.left>=0&&c.right<=innerWidth+1&&c.top>=0&&c.bottom<=innerHeight+1&&Math.abs(r.left-t.left)<=5&&Math.abs(r.right-t.right)<=5&&Math.abs(r.top-t.top)<=5;
  },selector,{timeout:3500}).catch(async error=>{
    const details=await target.evaluate(n=>{
      const box=e=>e.getBoundingClientRect().toJSON(),t=box(n);
      return {target:t,tip:box(document.querySelector('.guide-tip')),ring:box(document.querySelector('.guide-ring')),hit:document.elementFromPoint(t.x+t.width/2,t.y+t.height/2)?.outerHTML.slice(0,150)};
    });
    throw Error(selector+' '+JSON.stringify(details)+' '+error.message);
  });
  return target;
}
async function finish(page){
  await page.getByRole('button',{name:'结束指引'}).click();await page.locator(layer).waitFor({state:'detached'});
  assert.equal(await page.locator(anchor).count(),0);
}
let passed=false;
try{
  const {page:p,context:desktop}=await device(1280);await login(p,'guide-first');
  const writes=recordWrites(p);
  await pointed(p,receive);assert.equal(await p.locator('dialog[open]').count(),0);
  await p.screenshot({path:path.join(out,'desktop.png')});checks.push('Desktop first visit points to the clickable home link');
  assert.equal(await p.locator('video').count(),0);
  await p.getByRole('button',{name:'看视频演示'}).click();
  const video=p.locator('dialog[open] video');await video.waitFor();
  assert.equal(await video.evaluate(v=>v.paused&&v.preload==='none'),true);
  assert.equal(await video.locator('track[kind="captions"][srclang="zh-CN"]').count(),1);
  await video.evaluate(async v=>{v.muted=true;await v.play();});
  await p.waitForFunction(()=>document.querySelector('video')?.currentTime>.12);
  assert.equal(await video.evaluate(v=>v.videoWidth===1280&&v.videoHeight===720&&v.duration>20),true);
  await video.evaluate(v=>{v.currentTime=v.duration-1;});
  await p.waitForFunction(()=>{const v=document.querySelector('video');return v&&!v.seeking&&v.duration-v.currentTime<1.5;});
  await p.getByRole('button',{name:'返回指引'}).click();await pointed(p,receive);
  checks.push('Optional film plays, seeks and returns to the original spotlight');
  await p.locator(receive).focus();await p.keyboard.press('Enter');
  const field=await pointed(p,body);assert.equal(new URL(p.url()).hash,'#new');
  await field.click();await p.getByRole('button',{name:'看保存按钮'}).click();
  await pointed(p,save);assert.equal(await p.locator(body).inputValue(),'');
  assert.equal(await p.locator('#notice-form [name=rights]').isChecked(),false);
  await p.getByRole('button',{name:'再看日程入口'}).click();
  await (await pointed(p,'.home-agenda .home-section-heading a[href="#calendar"]')).click();
  await (await pointed(p,'.calendar-toolbar [data-calendar-action="today"]')).click();
  await p.locator(layer).waitFor({state:'detached'});assert.equal(await seen(desktop),true);
  assert.equal(new URL(p.url()).hash,'#calendar');checks.push('Optional calendar walkthrough follows the actual home link and Today control');
  assert.deepEqual(writes.filter(p=>p!=='/api/profile'),[]);checks.push('Real form, untouched contents, permission and submit; no business writes');
  await p.goto(origin+'/#dashboard');await p.reload();await p.locator(ready+' .personal-home').waitFor();
  assert.equal(await p.locator(layer).count(),0);await desktop.close();

  const {page:m,context:phone}=await device(320);await login(m,'guide-first');
  assert.equal(await m.locator(layer).count(),0);checks.push('Account receipt across devices');
  await replay(m);await pointed(m,receive);await m.screenshot({path:path.join(out,'mobile.png')});
  const sourceWrites=recordWrites(m);
  await m.getByRole('button',{name:'我想订阅武大官网'}).click();await pointed(m,sources);
  await m.getByRole('button',{name:'看视频演示'}).tap();
  const mobileVideo=m.locator('dialog[open] video');await mobileVideo.waitFor();
  assert.ok(await mobileVideo.evaluate(v=>{const r=v.getBoundingClientRect();return r.width>=240&&r.left>=0&&r.right<=innerWidth+1;}));
  await m.keyboard.press('Escape');await (await pointed(m,sources)).tap();
  const open='.source-page-heading [data-source-action="school-presets"]';
  await (await pointed(m,open)).tap();
  const search='#source-preset-search';const searchInput=await pointed(m,search);
  assert.equal(await m.locator('dialog[open] '+layer).count(),1);
  await searchInput.fill('不存在的栏目abcdef');assert.equal(await m.getByRole('button',{name:'看栏目按钮'}).isDisabled(),true);
  await searchInput.fill('图书馆');await m.getByRole('button',{name:'看栏目按钮'}).click();
  const subscribe='#source-preset-list [data-source-action="preset-subscribe"]';
  const button=await pointed(m,subscribe);
  assert.match(await button.locator('xpath=ancestor::article').innerText(),/图书馆/);
  await m.screenshot({path:path.join(out,'source-result.png')});
  await finish(m);assert.equal(await m.locator('dialog[open] #source-presets').isVisible(),true);
  assert.deepEqual(sourceWrites.filter(p=>p!=='/api/profile'),[]);checks.push('Mobile native dialog, real search and correct subscription button; no subscription or AI calls');
  await m.locator('dialog[open] .dialog-head [data-action=close-dialog]').click();
  await replay(m);await m.keyboard.press('Escape');await m.locator(layer).waitFor({state:'detached'});
  await replay(m);await m.goto(origin+'/#tasks');await m.locator(ready+'[data-page=tasks]').waitFor();
  assert.equal(await m.locator(layer).count(),0);checks.push('Escape and unrelated navigation exit the tour');

  await phone.clearCookies();await m.goto('about:blank');await login(m,'guide-second','new');
  await m.locator(ready+' #notice-form').waitFor();assert.equal(await seen(phone),false);
  assert.equal(await m.locator(layer).count(),0);await m.goto(origin+'/#dashboard');await pointed(m,receive);
  await m.getByRole('button',{name:'跳过指引'}).click();await m.locator(layer).waitFor({state:'detached'});
  assert.equal(await seen(phone),true);await m.reload();await m.locator(ready+' .personal-home').waitFor();
  assert.equal(await m.locator(layer).count(),0);checks.push('Second account, deep link, skip and no second prompt');
  await replay(m);await (await pointed(m,receive)).tap();
  const savedDraft=m.waitForResponse(r=>r.url().endsWith('/api/edit-cache/new-notice')&&r.request().method()==='PUT'&&r.ok());
  const draftInput=await pointed(m,body);await draftInput.fill('这是一条尚未提交的通知。');
  await m.getByRole('button',{name:'看保存按钮'}).tap();await pointed(m,save);
  await m.getByRole('button',{name:'再看日程入口'}).tap();await savedDraft;
  await pointed(m,'.home-agenda .home-section-heading a[href="#calendar"]');
  await m.getByRole('button',{name:'跳过指引'}).click();
  await m.goto(origin+'/#new');await m.reload();await m.locator(ready+' '+body).waitFor();
  assert.equal(await m.locator(body).inputValue(),'这是一条尚未提交的通知。');checks.push('An actual user edit survives the guide and a reload');
  await phone.close();assert.deepEqual(errors,[]);passed=true;
  console.log('Guided real control interactions passed at desktop and phone widths.');
}catch(error){errors.push(error.message);throw error;}
finally{
  await browser.close();await writeFile(path.join(out,'report.json'),JSON.stringify({passed,checks,errors},null,2));
}
