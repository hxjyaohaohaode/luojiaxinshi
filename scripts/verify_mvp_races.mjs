import {artifactPath} from './mvp_check_runtime.mjs';
// Delay an actual autosave request, then open a different task before releasing it.
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={checks:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()});
const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
const check=(name,ok)=>{if(!ok)throw new Error(name);report.checks.push(name);};
let release;
try{
  const login=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
  if(!login.ok())throw new Error('Fixture login failed: '+await login.text());
  const session=await (await context.request.get(origin+'/api/session')).json();
  const headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
  const request=async(path,data,form=false)=>{const r=await context.request.post(origin+'/api'+path,{headers,...(form?{form:data}:{data})});if(!r.ok())throw new Error(await r.text());return r.json();};
  let n=await request('/notices',{title:'虚构并发隔离验收 '+Date.now(),body:'虚构通知：本人需要准备与提交两个独立事项。'+Date.now(),source_label:'虚构工程测试',materials_complete:'true'},true);
  n=await request(`/notices/${n.id}/manual`,{version:n.version});
  const {task_ids:ids}=await request(`/notices/${n.id}/confirm`,{version:n.version,reviewed:true,tasks:[{title:'并发验收 A'},{title:'并发验收 B'}]});
  await page.goto(origin+'/#notice/'+n.id);await page.waitForSelector('.saved-notice-header');
  for(const mode of ['workflow','requirements']){
    const open=async id=>{await page.locator(mode==='workflow'?`.task-title[data-workflow-task="${id}"]`:`[data-action=edit-task][data-id="${id}"]`).click();await page.waitForSelector(mode==='workflow'?'#workflow-form':'#task-form');};
    await open(ids[0]);
    const key=await page.locator(mode==='workflow'?'#workflow-form':'#task-form').getAttribute('data-cache-key');
    const gate=new Promise(r=>release=r);let observed;const started=new Promise(r=>observed=r);
    const pattern='**/api/edit-cache/'+encodeURIComponent(key);
    await page.route(pattern,async route=>{if(route.request().method()==='PUT'&&route.request().postDataJSON().payload){observed();await gate;}await route.continue();});
    if(mode==='requirements'){await page.locator('#task-form [name=title]').fill('A 要求保存快照');await page.locator('#task-form [name=reason]').fill('虚构并发验收');}
    else await page.locator('#workflow-form [name=next_step]').fill('A 办理保存快照');
    await page.locator(mode==='workflow'?'#workflow-form [type=submit]':'#task-form [type=submit]').click();
    await started;await page.keyboard.press('Escape');await open(ids[1]);
    const marker='B 尚未提交 '+mode;
    await page.locator(mode==='workflow'?'#workflow-form [name=next_step]':'#task-form [name=title]').fill(marker);
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/tasks/'+ids[0]+(mode==='workflow'?'/workflow':''))&&r.request().method()==='PUT');
    release();check(mode+' 延迟保存成功',(await saved).status()===200);
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已保存'));
    check(mode+' 新弹窗不被旧请求关闭',await page.locator('#dialog').evaluate(d=>d.open));
    check(mode+' 新草稿不被旧请求覆盖',await page.locator(mode==='workflow'?'#workflow-form [name=next_step]':'#task-form [name=title]').inputValue()===marker);
    const a=await (await context.request.get(origin+'/api/tasks/'+ids[0]+'/workflow')).json(),b=await (await context.request.get(origin+'/api/tasks/'+ids[1]+'/workflow')).json();
    check(mode+' 写入原事项',mode==='workflow'?a.task.workflow.data.next_step==='A 办理保存快照':a.task.data.title==='A 要求保存快照');
    check(mode+' 未写入另一事项',mode==='workflow'?b.task.workflow.data.next_step==='':b.task.data.title==='并发验收 B');
    await page.unroute(pattern);await page.keyboard.press('Escape');
  }
  console.log(JSON.stringify(report,null,2));
}catch(e){report.failure=e.stack;console.error(e);process.exitCode=1;}
finally{release?.();await writeFile(artifactPath('race-report.json'),JSON.stringify(report,null,2));await browser.close();}
