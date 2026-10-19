// Review a copy of the stored real-provider result. No provider call or production data.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {chromium,firefox,webkit}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('artifacts/mvp-acceptance');
const version=process.env.BUSINESS_VERSION||'1.8.0',label=process.env.BUSINESS_LABEL||'normalized';
const fixture=JSON.parse(await readFile(path.join(root,`business-notice-${label}-${version}.json`),'utf8'));
const selected=fixture.draft.tasks.map((task,i)=>({task,i})).filter(({task,i})=>task.scope==='personal'&&fixture.draft.plans?.[i]?.action_kind!=='optional');
const origin='http://127.0.0.1:8781',route='notice/'+fixture.notice_id;
const report={version,sample:'Real supplied notice, real-generated draft, synthetic account; isolated copy.',views:[],checks:[],errors:[]};
const uploadIndex=fixture.draft.tasks.findIndex(t=>t.scope==='personal'&&t.due_date==='2026-10-20'&&t.due_time==='00:00');
assert.ok(uploadIndex>=0);
let sharedAuth,visit=0;
const check=(name,value)=>{report.checks.push({name,passed:!!value});assert.ok(value,name);};
async function ready(page){
  await page.goto(origin+'/?notice-verification='+(++visit)+'#'+route,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);
  await page.waitForFunction(()=>document.fonts.status==='loaded');
}
async function metrics(page,engine,width,height,view){
  const m=await page.evaluate(()=>{const nav=document.querySelector('.mobile-bottom-nav');return{scroll:document.documentElement.scrollWidth,width:innerWidth,height:innerHeight,
    navigation:{position:getComputedStyle(nav).position,bottom:nav.getBoundingClientRect().bottom,transform:getComputedStyle(nav).transform},
    fields:[...document.querySelectorAll('#draft-form input,#draft-form textarea,#draft-form select')].filter(e=>e.getBoundingClientRect().width>0).map(e=>({name:e.name,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))};});
  report.views.push({engine,width,height,view,...m});
  check(`${engine} ${width} ${view} fits`,m.scroll<=width+1&&m.fields.every(e=>e.left>=0&&e.right<=width+1));
  if(width<=850&&height>=500)check(`${engine} ${width} ${view} bottom navigation aligned`,m.navigation.position==='fixed'&&Math.abs(m.navigation.bottom-height)<=1);
}
try{
  for(const [engine,type] of Object.entries({chromium,firefox,webkit})){
    const browser=await type.launch({headless:true,...(engine==='chromium'?{executablePath:chromium.executablePath()}:{})});
    try{
      const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce',...(sharedAuth?{storageState:sharedAuth}:{})});
      if(!sharedAuth){
        const response=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'business.notice.fixture',password:'Isolated-Notice-Fixture-2026'}});
        assert.ok(response.ok());sharedAuth=await context.storageState();
      }
      const page=await context.newPage();page.setDefaultTimeout(15000);
      page.on('pageerror',error=>report.errors.push({engine,message:error.message}));
      for(const [width,height] of [[320,740],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
        await page.setViewportSize({width,height});await ready(page);
        check(`${engine} ${width} all steps visible`,await page.locator('.task-editor').count()===fixture.draft.tasks.length);
        for(let i=0;i<fixture.draft.tasks.length;i++){
          assert.equal(await page.locator(`[data-editor="${i}"] [name="include"]`).isChecked(),fixture.draft.tasks[i].scope!=='other'&&fixture.draft.plans?.[i]?.action_kind!=='optional');
        }
        const upload=page.locator(`[data-editor="${uploadIndex}"]`);
        check(`${engine} ${width} exact date/time`,await upload.locator('[name="due_date"]').inputValue()==='2026-10-20'&&await upload.locator('[name="due_time"]').inputValue()==='00:00');
        check(`${engine} ${width} human confirmation`,!await upload.locator('[name="deadline_confirmed"]').isChecked());
        await metrics(page,engine,width,height,'draft');
        const warnings=page.locator('.draft-warnings');
        if(await warnings.count()){
          if(!await warnings.evaluate(e=>e.open))await warnings.locator('summary').click();
          const content=await warnings.textContent();
          check(`${engine} ${width} all warnings retained`,fixture.draft.warnings.every(w=>content.includes(w)));
          await metrics(page,engine,width,height,'warnings-expanded');
          if(fixture.draft.warnings.length>3)await warnings.locator('summary').click();
        }
        if((engine==='chromium'&&[320,390,1440].includes(width))||(engine==='webkit'&&width===320)){
          await page.screenshot({path:path.join(root,`business-${version}-${engine}-${width}-overview.png`),animations:'disabled'});
          await upload.evaluate(e=>{e.scrollIntoView({block:'start'});window.scrollBy(0,-64);});
          await page.screenshot({path:path.join(root,`business-${version}-${engine}-${width}-deadline.png`),animations:'disabled'});
        }
        const overview=page.locator('.draft-overview');
        if(!await overview.evaluate(e=>e.open))await overview.locator('summary').click();
        check(`${engine} ${width} full overview retained`,(await overview.textContent()).includes(fixture.draft.summary));
        await metrics(page,engine,width,height,'overview-expanded');
        await overview.locator('summary').click();
        await page.getByText('查看八类事实与来源',{exact:true}).click();
        check(`${engine} ${width} eight facts`,await page.locator('.facts .fact').count()===8);
        await metrics(page,engine,width,height,'facts');
        await page.getByText('查看八类事实与来源',{exact:true}).click();
        const notes=upload.locator('details').filter({has:page.getByText('个人备注与原文依据',{exact:true})});
        if(!await notes.evaluate(e=>e.open))await notes.locator('summary').click();
        const link=upload.locator('[data-action="evidence"]').first();
        const sourceId=await link.getAttribute('data-source'),locator=await link.getAttribute('data-locator');
        await link.click();
        check(`${engine} ${width} exact source opened`,await page.evaluate(({sourceId,locator})=>{
          const card=[...document.querySelectorAll('[data-source-card]')].find(e=>e.dataset.sourceCard===sourceId);
          const section=[...card.querySelectorAll('.source-section')].find(e=>e.dataset.locator===locator);
          return card.open&&card.closest('.notice-originals').open&&section.getBoundingClientRect().height>0&&section.textContent.includes('2026年10月19日24:00');
        },{sourceId,locator}));
        await metrics(page,engine,width,height,'original');
      }
      if(engine==='webkit'){
        await page.setViewportSize({width:390,height:844});await ready(page);
        const upload=page.locator(`[data-editor="${uploadIndex}"]`);
        for(let i=0;i<fixture.draft.tasks.length;i++)await page.locator(`[data-editor="${i}"] [name="include"]`).setChecked(selected.some(s=>s.i===i));

        await upload.locator('[name="deadline_confirmed"]').check();
        const requirements=upload.locator('details').filter({has:page.getByText('办理要求、材料与联系方式',{exact:true})});
        if(!await requirements.evaluate(e=>e.open))await requirements.locator('summary').click();
        await upload.locator('[name="resolution_note"]').fill('工程复核原件明确写2026年10月19日24:00，换算为20日00:00；模拟本人确认。');
        await page.locator('#draft-form [name="reviewed"]').check();
        const saved=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');
        await page.getByRole('button',{name:'确认并保存待办',exact:true}).click();
        check('mobile explicit confirmation succeeds',(await saved).ok());
        await page.getByText('已经转为个人待办',{exact:true}).waitFor();
        const tasks=await (await context.request.get(origin+'/api/tasks')).json();
        const savedUpload=tasks.find(t=>t.data.title===fixture.draft.tasks[uploadIndex].title);
        check('only selected personal steps are created',tasks.length===selected.length&&savedUpload.data.due_date==='2026-10-20'&&savedUpload.data.due_time==='00:00'&&savedUpload.data.deadline_confirmed);
        check('model proposals do not confirm external conditions',tasks.flatMap(t=>t.workflow.data.conditions).every(c=>c.state==='unknown'));
        check('selected prerequisites bind real task IDs',savedUpload.workflow.data.dependencies.length>=2&&savedUpload.workflow.data.dependencies.every(id=>tasks.some(t=>t.id===id)));
        await page.reload({waitUntil:'domcontentloaded'});await page.getByText('已经转为个人待办',{exact:true}).waitFor();
        check('confirmed result persists after reload',await page.locator('.task-row').count()===selected.length);
        await page.screenshot({path:path.join(root,`business-${version}-webkit-390-confirmed.png`),animations:'disabled'});
      }
    }finally{await browser.close();}
  }
  check('no page exceptions',report.errors.length===0);
}catch(error){report.failure={message:error.message,stack:error.stack};process.exitCode=1;}
finally{
  await writeFile(path.join(root,`business-browser-${version}.json`),JSON.stringify(report,null,2));
  console.log(JSON.stringify({views:report.views.length,checks:report.checks.length,errors:report.errors,failure:report.failure||null}));
}
