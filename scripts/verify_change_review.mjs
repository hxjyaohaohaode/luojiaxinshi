// Real HTTP and browser interactions against the isolated synthetic preview only.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',out='artifacts/mvp-acceptance';
await mkdir(out,{recursive:true});
const report={checks:[],views:[],errors:[],sample:'Synthetic local fixtures; no model calls or production data.'};
const check=(name,value)=>{if(!value)throw Error(name);report.checks.push(name);};
let auth;
for(const engine of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
 const browser=await pw[engine].launch({headless:true,...(engine==='chromium'?{executablePath:pw.chromium.executablePath()}:{})});
 const context=await browser.newContext({reducedMotion:'reduce',...(auth?{storageState:auth}:{})});
 const page=await context.newPage();page.setDefaultTimeout(15000);
 page.on('pageerror',e=>report.errors.push(engine+': '+e.message));
 try{
  if(!auth){
   const login=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
   check('Synthetic fixture login',login.ok());auth=await context.storageState();
  }
  const session=await (await context.request.get(origin+'/api/session')).json();
  const headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
  async function api(path,data,method='POST',form=false){
   const r=await context.request.fetch(origin+'/api'+path,{method,headers,...(data?{[form?'form':'data']:data}:{})});
   if(!r.ok())throw Error(`${method} ${path} ${r.status()} ${await r.text()}`);return r.json();
  }
  const getTask=async tid=>(await api('/tasks/'+tid+'/workflow',null,'GET')).task;
  async function flow(tid,fields){const t=await getTask(tid);return api('/tasks/'+tid+'/workflow',{version:t.workflow.version,task_version:t.version,data:{...t.workflow.data,...fields}},'PUT');}
  async function done(tid){const t=await getTask(tid);return api('/tasks/'+tid,{version:t.version,data:t.data,status:'done',reason:'本人已完成旧版要求'},'PUT');}
  const stamp=engine+' '+Date.now();
  let n=await api('/notices',{title:'虚构变更复核验收 '+stamp,body:'虚构通知：2027年10月20日17:00前准备申请表、核对签字，再提交。工程验收，不代表校园安排。样本 '+stamp,source_label:'虚构验收办公室',materials_complete:'true'},'POST',true);
  n=await api('/notices/'+n.id+'/manual',{version:n.version});
  const titles=['准备申请表与个人说明，核对原始签字记录及后续补充要求','核对资格及已提交材料是否仍然适用','向指定窗口提交并保存本人回执'];
  const made=await api('/notices/'+n.id+'/confirm',{version:n.version,reviewed:true,tasks:titles.map(title=>({title:title+' · '+stamp,due_date:'2027-10-20',due_time:'17:00',deadline_confirmed:true,deadline_text:'2027年10月20日17:00前',materials:['申请表'],submission:'虚构学院办公室',notes:'保留原有个人备注与提交历史'}))});
  const [root,child,last]=made.task_ids;
  await flow(root,{stage:'accepted',prepared_materials:['申请表'],receipt:'虚构旧版回执 ABC-001',outcome:'本人记录已核实旧版受理'});await done(root);
  await flow(child,{dependencies:[root]});await done(child);await flow(last,{dependencies:[child]});
  async function proposal(patch){
   const notice=await api('/notices/'+n.id,null,'GET'),t=await getTask(root);
   return api('/notices/'+n.id+'/changes',{notice_version:notice.version,kind:'supplement',text:'虚构正式补充：材料清单新增本人签字的确认页，并需核对之后所有提交步骤。',source_label:'虚构学院正式更正',targets:[{task_id:root,version:t.version,action:'revise',patch}]});
  }
  const change=await proposal({materials:['申请表','新增本人签字确认页']});
  check(engine+' transitive preview includes two subsequent steps',change.impact[0].affected_steps.length===2);
  const go=async route=>{await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);};
  const close=async()=>{await page.locator('#dialog [data-action=close-dialog]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});};
  async function openTask(tid){await page.locator(`[data-workflow-task="${tid}"]`).first().click();await page.locator('#workflow-form').waitFor();}
  async function openReview(tid){await openTask(tid);await page.locator('[data-action-review]').click();await page.locator('#action-review-form').waitFor();}
  async function view(name,width,dialog=true){
   await page.evaluate(()=>document.fonts.ready);
   const m=await page.evaluate(dialog=>{const d=dialog?document.querySelector('#dialog'):document.documentElement,b=dialog?d.querySelector('.dialog-body'):d,r=d.getBoundingClientRect();return {scroll:b.scrollWidth,client:b.clientWidth,left:r.left,right:r.right,top:r.top,bottom:r.bottom,viewport:innerWidth,height:innerHeight};},dialog);
   check(`${engine}/${width}/${name} fits viewport`,m.scroll<=m.client+2&&(!dialog||m.left>=-1&&m.right<=m.viewport+1&&m.top>=-1&&m.bottom<=m.height+1));
   report.views.push({engine,width,name,...m});
   if([320,390,1440].includes(width))await page.screenshot({path:`${out}/review-${engine}-${width}-${name}.png`,fullPage:!dialog});
  }
  const sizes=[[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]];
  for(const [width,height] of sizes){
   await page.setViewportSize({width,height});await go('notice/'+n.id);
   await page.locator(`[data-change-open="${change.id}"]`).click();await page.locator('#change-decision-form').waitFor();
   check(`${engine}/${width} preview shows downstream impact`,await page.locator('.action-review-downstream').count()===1);
   await view('impact',width);await close();
  }
  await page.setViewportSize({width:390,height:844});await page.locator(`[data-change-open="${change.id}"]`).click();
  await page.locator('#change-decision-form [name=note]').fill('已核实虚构更正内容和本人适用范围');await page.locator('#change-decision-form [name=verified]').check();
  await page.locator('#change-decision-form [type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});
  check(engine+' original completion and receipt preserved',(await getTask(root)).status==='done'&&(await getTask(root)).workflow.data.receipt==='虚构旧版回执 ABC-001');
  for(const [width,height] of sizes){
   await page.setViewportSize({width,height});await go('notice/'+n.id);await openTask(root);
   check(`${engine}/${width} completed work has actionable banner`,await page.locator('.action-review-banner [data-action-review]').count()===1);
   await view('workflow',width);await page.locator('[data-action-review]').click();await page.locator('#action-review-form').waitFor();
   check(`${engine}/${width} review never preselects conclusion`,await page.locator('#action-review-form [name=decision]:checked').count()===0);
   const radio=await page.locator('#action-review-form [value=keep]').boundingBox(),label=await page.locator('.action-review-options label span').first().boundingBox();
   check(`${engine}/${width} radio aligns with its label`,radio.height<=20&&Math.abs(radio.y-label.y)<=5);
   await view('root-review',width);await page.locator('#action-review-form [type=submit]').scrollIntoViewIfNeeded();
   check(`${engine}/${width} review save is touch sized`,(await page.locator('#action-review-form [type=submit]').boundingBox()).height>=44);
   await close();await openReview(last);await view('dependent-review',width);await close();
  }
  await page.setViewportSize({width:390,height:844});await go('notice/'+n.id);await openReview(last);
  await page.locator('#action-review-form [value=keep]').check();await page.locator('#action-review-form [name=note]').fill('先尝试后续步骤，应提示先核对前置事项');
  await page.locator('#action-review-form [type=submit]').click();await page.locator('#action-review-form .form-error').waitFor();
  check(engine+' review order is enforced visibly',(await page.locator('.form-error').innerText()).includes('前置'));await close();
  await openReview(root);const draft='已向发布方核实，新增要求仅适用于未提交者，本人原记录仍有效。';
  await page.locator('#action-review-form [value=keep]').check();
  const cached=page.waitForResponse(r=>r.url().includes('/api/edit-cache/')&&r.request().method()==='PUT'&&r.ok());
  await page.locator('#action-review-form [name=note]').fill(draft);await cached;await close();await go('notice/'+n.id);await openReview(root);
  check(engine+' review draft survives refresh',await page.locator('#action-review-form [name=note]').inputValue()===draft&&await page.locator('#action-review-form [value=keep]').isChecked());
  let release,started;const gate=new Promise(r=>release=r),seen=new Promise(r=>started=r);const pattern='**/api/tasks/'+root+'/change-review';
  await page.route(pattern,async route=>{started();await gate;await route.continue();});
  const response=page.waitForResponse(pattern);await page.locator('#action-review-form [type=submit]').click();await seen;
  await close();await openTask(child);release();await response;await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  check(engine+' late save preserves newly opened dialog',await page.locator('#workflow-form').count()===1&&(await page.locator('.workflow-task-head h3').innerText()).includes(titles[1]));
  await page.unroute(pattern);await close();
  const saved=await getTask(root);check(engine+' keep conclusion persisted',saved.status==='done'&&saved.change_review.state==='reviewed'&&saved.change_review.note===draft);
  for(const tid of [child,last]){
   await openReview(tid);await page.locator('#action-review-form [value=keep]').check();await page.locator('#action-review-form [name=note]').fill('已根据最新前置办理结论核对，本步骤继续有效');await page.locator('#action-review-form [type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});
  }
  const second=await proposal({location:'虚构新窗口'});await api(`/notices/${n.id}/changes/${second.id}/decision`,{version:second.version,decision:'apply',verified:true,note:'已核实新窗口适用于本人，需要补办'});
  await go('notice/'+n.id);await openReview(root);await page.locator('#action-review-form [value=reopen]').check();await page.locator('#action-review-form [name=note]').fill('需向新窗口补交本人说明，保留原有回执供核对');await page.locator('#action-review-form [type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});
  const reopened=await getTask(root);check(engine+' reopen retains receipt and enters supplement',reopened.status==='pending'&&reopened.workflow.data.stage==='supplement'&&reopened.workflow.data.receipt==='虚构旧版回执 ABC-001');
  await go('tasks');await page.locator('[data-action=filter][data-filter=changes]').click();await page.locator('#task-search').fill(stamp);
  check(engine+' completed dependent is in review filter',await page.locator(`[data-workflow-task="${child}"]`).count()>0);
  await view('review-list',390,false);
 }catch(error){report.errors.push(engine+': '+error.stack);}finally{await browser.close();}
 await writeFile(`${out}/change-review-browser-1.6.0.json`,JSON.stringify(report,null,2));
}
console.log(JSON.stringify({checks:report.checks.length,views:report.views.length,errors:report.errors}));
process.exitCode=report.errors.length?1:0;
