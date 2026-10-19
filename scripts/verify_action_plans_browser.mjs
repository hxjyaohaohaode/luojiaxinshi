// Real UI and HTTP against synthetic, isolated fixtures. No provider calls.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance'),version='1.8.0',origin='http://127.0.0.1:8781';
const fixture=JSON.parse(await readFile(path.join(root,`action-plan-preview-${version}.json`),'utf8'));
const report={version,sample:fixture.sample,views:[],checks:[],errors:[]};
const check=(name,value)=>{report.checks.push({name,passed:!!value});assert.ok(value,name);};
const sizes=[[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]];
let visit=0;
async function ready(page,route){
  await page.goto(origin+'/?plan-check='+(++visit)+'#'+route,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);
  await page.waitForFunction(()=>document.fonts.status==='loaded');
}
async function metrics(page,engine,width,height,view){
  const m=await page.evaluate(()=>{
    const dialog=document.querySelector('dialog[open]'),r=dialog?.getBoundingClientRect(),body=dialog?.querySelector('.dialog-body');
    const fields=[...document.querySelectorAll('#draft-form input,#draft-form textarea,#draft-form select,dialog[open] input,dialog[open] textarea,dialog[open] select')]
      .filter(e=>e.getBoundingClientRect().width>0&&!e.closest('.dependency-list')).map(e=>({name:e.name,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}));
    return{width:innerWidth,scroll:document.documentElement.scrollWidth,fields,dialog:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom,scroll:body.scrollWidth,client:body.clientWidth}:null};
  });report.views.push({engine,width,height,view,...m});
  check(`${engine} ${width} ${view} fits`,m.scroll<=width+1&&m.fields.every(e=>e.left>=0&&e.right<=width+1));
  if(m.dialog)check(`${engine} ${width} ${view} dialog`,m.dialog.left>=0&&m.dialog.right<=width+1&&m.dialog.top>=0&&m.dialog.bottom<=height+1&&m.dialog.scroll<=m.dialog.client+1);
}
async function saveWorkflow(page){
  const saved=page.waitForResponse(r=>r.url().endsWith('/workflow')&&r.request().method()==='PUT');
  await page.locator('#workflow-form button[type=submit]').click();const response=await saved;
  assert.ok(response.ok(),await response.text());await page.locator('#workflow-form').waitFor({state:'detached'});
}
async function openWorkflow(page,id){await page.locator(`[data-workflow-task="${id}"]`).first().click();await page.locator('#workflow-form').waitFor();}
try{
  for(const [engine,type] of Object.entries({chromium,firefox,webkit})){
    const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
    try{
      const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'});
      const login=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'plans.'+engine,password:'Action-Plans-Fixture-2026'}});assert.ok(login.ok());
      const page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',error=>report.errors.push({engine,message:error.message}));
      const route='notice/'+fixture.notices[engine];
      for(const[width,height]of sizes){
        await page.setViewportSize({width,height});await ready(page,route);
        check(`${engine} ${width} optional and unit unselected`,!await page.locator('[data-editor="2"] [name=include]').isChecked()&&!await page.locator('[data-editor="3"] [name=include]').isChecked());
        check(`${engine} ${width} dependency and condition displayed`,await page.locator('[data-editor="1"] [name=plan_dependency]:checked').count()===1&&(await page.locator('[data-editor="1"] [name=plan_conditions]').inputValue()).includes('立项'));
        await metrics(page,engine,width,height,'draft');
        await page.locator('[data-editor="1"] .draft-plan').evaluate(e=>{e.scrollIntoView({block:'start'});window.scrollBy(0,-64);});
        if(engine==='chromium'&&[320,390,1440].includes(width))await page.screenshot({path:path.join(root,`plans-${engine}-${width}-draft.png`)});
      }
      await page.setViewportSize({width:390,height:844});await ready(page,route);
      await page.locator('[data-editor="0"] [name=include]').uncheck();await page.locator('#draft-form [name=reviewed]').check();
      await page.getByRole('button',{name:'确认并保存待办',exact:true}).click();
      await page.getByText(/前置步骤.*未选中/).waitFor();
      check(`${engine} missing predecessor did not create tasks`,(await(await context.request.get(origin+'/api/tasks')).json()).length===0);
      await page.locator('[data-editor="0"] [name=include]').check();
      await page.locator('[data-editor="2"] [name=include]').check();
      await page.locator('[data-editor="2"] [name=plan_participation]').selectOption('declined');
      await page.locator('[data-editor="1"] [name=plan_conditions]').fill('已收到正式立项通知\n团队名单已经本人核实');
      // UI navigation flushes the existing edit cache, then reload must restore plan identity.
      await page.getByRole('link',{name:'待办',exact:true}).first().click();
      await ready(page,route);
      check(`${engine} draft plan restored`,(await page.locator('[data-editor="1"] [name=plan_conditions]').inputValue()).includes('团队名单')&&await page.locator('[data-editor="2"] [name=plan_participation]').inputValue()==='declined');
      await page.locator('#draft-form [name=reviewed]').check();
      const confirmed=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'确认并保存待办',exact:true}).click();assert.ok((await confirmed).ok());
      await page.getByText('已经转为个人待办',{exact:true}).waitFor();
      const tasks=await(await context.request.get(origin+'/api/tasks')).json();
      const first=tasks.find(t=>t.data.title==='取得签章申请表'),child=tasks.find(t=>t.data.title==='上传并记录提交回执'),optional=tasks.find(t=>t.data.title==='可选咨询');
      check(`${engine} atomic plans saved`,tasks.length===3&&child.workflow.data.dependencies[0]===first.id&&child.workflow.data.conditions.every(c=>c.state==='unknown')&&optional.action_excluded);
      for(const[width,height]of sizes){
        await page.setViewportSize({width,height});await ready(page,route);await openWorkflow(page,child.id);
        check(`${engine} ${width} unknown conditions shown`,await page.locator('[data-condition-id]').count()===2&&await page.locator('[name=condition_state]').first().inputValue()==='unknown');
        await metrics(page,engine,width,height,'conditions');
        if((engine==='chromium'&&[320,390,1440].includes(width))||(engine==='webkit'&&width===320))await page.screenshot({path:path.join(root,`plans-${engine}-${width}-conditions.png`)});
        await page.keyboard.press('Escape');
      }
      await page.setViewportSize({width:390,height:844});await ready(page,route);
      const blocked=page.waitForResponse(r=>r.url().endsWith('/tasks/'+child.id)&&r.request().method()==='PUT');
      await page.locator(`[data-action=toggle-task][data-id="${child.id}"]`).click();check(`${engine} unknown conditions block completion`,(await blocked).status()===422);
      await openWorkflow(page,child.id);
      const rows=page.locator('[data-condition-id]');
      for(const row of await rows.all()){await row.locator('[name=condition_state]').selectOption('met');await row.locator('[name=condition_note]').fill('合成验收：已核对本批次正式名单与通知');}
      await saveWorkflow(page);
      const depBlocked=page.waitForResponse(r=>r.url().endsWith('/tasks/'+child.id)&&r.request().method()==='PUT');
      await page.locator(`[data-action=toggle-task][data-id="${child.id}"]`).click();check(`${engine} unfinished prerequisite still blocks`,(await depBlocked).status()===422);
      let done=page.waitForResponse(r=>r.url().endsWith('/tasks/'+first.id)&&r.request().method()==='PUT');
      await page.locator(`[data-action=toggle-task][data-id="${first.id}"]`).click();assert.ok((await done).ok());
      await ready(page,route);await openWorkflow(page,child.id);
      await page.locator('[name=stage]').selectOption('submitted');await page.locator('[name=receipt]').fill('合成回执 PLAN-2026');await saveWorkflow(page);
      await ready(page,route);await openWorkflow(page,child.id);
      await page.locator('[name=condition_state]').first().selectOption('not_met');await page.locator('[name=condition_note]').first().fill('合成变更：已核实本批次资格被撤回');await saveWorkflow(page);
      const current=await(await context.request.get(origin+'/api/tasks/'+child.id+'/workflow')).json();
      check(`${engine} changed conditions retain history and require review`,current.task.workflow.data.receipt==='合成回执 PLAN-2026'&&current.task.workflow.data.stage==='submitted'&&current.task.change_review.state==='pending');
      await ready(page,route);await openWorkflow(page,child.id);await metrics(page,engine,390,844,'condition-changed');
      await page.screenshot({path:path.join(root,`plans-${engine}-390-changed.png`)});
      await page.keyboard.press('Escape');await ready(page,'tasks');
      check(`${engine} declined optional excluded from pending`,await page.locator(`[data-workflow-task="${optional.id}"]`).count()===0);
    }finally{await browser.close();}
  }
  check('no browser exceptions',report.errors.length===0);
}catch(error){report.failure={message:error.message,stack:error.stack};process.exitCode=1;}
finally{await writeFile(path.join(root,`action-plans-browser-${version}.json`),JSON.stringify(report,null,2));console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors,failure:report.failure||null}));}
