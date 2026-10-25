/* Synthetic accounts, real API and rendered controls. No model or external delivery. */
import {chromium,firefox,webkit} from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/notice-matters-browser');await fs.mkdir(out,{recursive:true});
const report={synthetic:true,live_model_calls:0,external_messages:0,checks:[],errors:[]};
for(const [name,engine] of Object.entries({chromium,firefox,webkit})){
 const browser=await engine.launch({headless:true,executablePath:engine.executablePath()}),page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
 page.setDefaultTimeout(12000);page.on('pageerror',e=>report.errors.push({browser:name,message:e.message}));
 const check=async(title,fn)=>{await fn();report.checks.push({browser:name,title,passed:true});};
 const api=(url,method='GET',json=null)=>page.evaluate(async({url,method,json})=>{const s=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api'+url,{method,headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':s.csrf,...(json?{'Content-Type':'application/json'}:{})},...(json?{body:JSON.stringify(json)}:{})});if(!r.ok)throw Error(await r.text());return r.json();},{url,method,json});
 const go=async route=>{await page.goto(origin+'/#'+route);await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').inert,route);};
 const receive=title=>page.evaluate(async title=>{const s=await fetch('/api/session').then(r=>r.json());const data=new FormData();data.set('title',title);data.set('materials_complete','true');data.set('body',title+'，请按学院要求核对材料并办理。');const r=await fetch('/api/notices',{method:'POST',headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':s.csrf},body:data});if(!r.ok)throw Error(await r.text());return r.json();},title);
 try{
  await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.waitForURL(/#dashboard/);
  const tag=name+' '+Date.now(),a=await receive('2026年本科生综合奖学金申报通知 '+tag),b=await receive('2026年本科生综合奖学金申报补充通知 '+tag),c=await receive('2025年本科生综合奖学金申报通知 '+tag);
  for(const [n,due] of [[a,'2027-10-20'],[b,'2027-10-23']]){
   const draft=await api('/notices/'+n.id+'/manual','POST',{version:n.version});
   await api('/notices/'+n.id+'/confirm','POST',{version:draft.version,reviewed:true,tasks:[{title:'提交申请 '+name,due_date:due,due_time:'17:00',deadline_confirmed:true,deadline_text:due+' 17:00 前',resolution_note:'合成验收已核对日期与材料',materials:['申请表'],submission:'学院办公室',notes:'个人计划保留'}]});
  }
  await check('capacity screen reports effective campus limits and current usage',async()=>{
   await go('settings');await page.locator('[data-settings-category=account]').click();await page.locator('[data-action=account-usage]').click();await page.locator('#dialog-title').filter({hasText:'账号容量'}).waitFor();const text=await page.locator('#dialog').innerText();assert.match(text,/10,000/);assert.match(text,/10\.00 GB/);await page.keyboard.press('Escape');
  });
  await check('related notices are review candidates; a different year is excluded',async()=>{
   await go('notice/'+a.id);await page.locator('#notice-matters details').waitFor();await page.locator('#notice-matters summary').click();await page.locator(`[data-matter-review="${b.id}"]`).waitFor();assert.equal(await page.locator(`[data-matter-review="${c.id}"]`).count(),0);assert.equal((await api('/notices/'+a.id+'/matter')).group,null);
  });
  await check('preview shows both originals and confirms grouping through the form',async()=>{
   await page.locator(`[data-matter-review="${b.id}"]`).click();const form=page.locator('#matter-confirm-form');await form.waitFor();assert.equal(await form.locator('.matter-member').count(),2);assert.match(await form.innerText(),/2027-10-20 17:00/);assert.match(await form.innerText(),/2027-10-23 17:00/);assert.match(await form.innerText(),/申请表/);await form.locator('[name=title]').fill('奖学金申请与补充 '+tag);await form.locator('[type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelectorAll('#notice-matters .matter-member').length===2);assert.equal((await api('/notices/'+a.id+'/matter')).group.members.length,2);await page.screenshot({path:path.join(out,name+'-matter.png')});
  });
  await check('library groups related notices and can switch back to individual records',async()=>{
   await go('notices');await page.locator('#library-search').fill(tag);await page.locator('.matter-library-card').filter({hasText:'奖学金申请与补充 '+tag}).waitFor();await page.locator('[data-library-group]').click();await page.locator(`a.notice-card[href="#notice/${a.id}"]`).waitFor();await page.locator(`a.notice-card[href="#notice/${b.id}"]`).waitFor();await page.locator('[data-library-group]').click();await page.locator('.matter-library-card').filter({hasText:tag}).waitFor();
  });
  await check('an intervening task edit rejects the stale preview and offers a fresh review',async()=>{
   await go('notice/'+a.id);await page.locator('[data-matter-choose]').click();await page.locator('#matter-notice-search').fill(tag);await page.locator(`#matter-notice-options [data-id="${c.id}"]`).click();await page.locator('#matter-confirm-form').waitFor();
   const current=(await api('/notices/'+a.id)).tasks[0];await api('/tasks/'+current.id,'PUT',{version:current.version,data:{...current.data,notes:'模拟另一窗口已更新个人备注'},status:current.status,reason:'隔离夹具中的并发修改验证'});
   await page.locator('#matter-confirm-form [type=submit]').click();await page.getByRole('button',{name:'重新核对',exact:true}).waitFor();assert.equal((await api('/notices/'+a.id+'/matter')).group.members.length,2);
   const fresh=page.waitForResponse(r=>r.url().endsWith('/matter/preview'));await page.getByRole('button',{name:'重新核对',exact:true}).click();assert.equal((await fresh).status(),200);await page.getByRole('button',{name:'确认归入同一事项',exact:true}).waitFor();
   await page.keyboard.press('Escape');await page.locator('#matter-confirm-form').waitFor({state:'hidden'});await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});
  });
  await check('detail and confirmation remain usable on mobile and with keyboard-height viewport',async()=>{
   for(const [width,height] of [[320,620],[390,350]]){
    await page.setViewportSize({width,height});await go('notice/'+a.id);await page.locator('#notice-matters .matter-member').first().waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
    await page.locator('[data-matter-choose]').click();await page.locator('#matter-notice-search').fill(tag);assert.equal(await page.locator(`#matter-notice-options [data-id="${b.id}"]`).count(),0);await page.locator(`#matter-notice-options [data-id="${c.id}"]`).click();await page.locator('#matter-confirm-form').waitFor();assert.match(await page.locator('#matter-confirm-form').innerText(),/不同年份/);assert.equal(await page.evaluate(()=>document.querySelector('#dialog').scrollWidth>document.querySelector('#dialog').clientWidth+2),false);await page.screenshot({path:path.join(out,name+`-preview-${width}-${height}.png`)});await page.keyboard.press('Escape');await page.locator('#matter-confirm-form').waitFor({state:'hidden'});if(await page.locator('#dialog').isVisible()){await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});}
   }
  });
  await check('moving one notice out dissolves a two-member group and preserves both notices',async()=>{
   await page.setViewportSize({width:1440,height:900});await go('notice/'+a.id);await page.locator('[data-matter-remove]').click();await page.waitForFunction(()=>!document.querySelector('#notice-matters [data-matter-remove]')&&!!document.querySelector('#notice-matters details'));assert.equal((await api('/notices/'+a.id+'/matter')).group,null);assert.equal((await api('/notices/'+b.id+'/matter')).group,null);assert.equal((await api('/notices/'+a.id)).id,a.id);assert.equal((await api('/notices/'+b.id)).id,b.id);
  });
 }catch(error){report.errors.push({browser:name,message:error.stack});await page.screenshot({path:path.join(out,name+'-failure.png')});process.exitCode=1;}
 finally{await browser.close();}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
