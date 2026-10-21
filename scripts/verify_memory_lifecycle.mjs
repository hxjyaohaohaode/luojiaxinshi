import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
const require=createRequire(import.meta.url);
const pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786';
const output=path.resolve('artifacts/memory-v3-browser');
await mkdir(output,{recursive:true});
const report={checks:[],errors:[],toolWarnings:[]};
function check(name,value){report.checks.push({name,passed:!!value});if(!value)throw Error(name);}
for(const engine of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
 const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(14000);
 let capturing=false;
 page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
 page.on('console',message=>{
  if(message.type()!=='error'||!/Refused to|Content Security Policy/.test(message.text()))return;
  const entry={engine,message:message.text(),capturing};
  if(engine==='webkit'&&capturing&&message.text()==="Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear in the style-src directive of the Content Security Policy.")report.toolWarnings.push(entry);
  else report.errors.push(entry);
 });
 const shot=async name=>{capturing=true;try{await page.screenshot({path:path.join(output,name+'.png'),animations:'disabled',caret:'initial'});}finally{capturing=false;}};
 try{
  const login=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
  check(engine+' login',login.ok());
  const session=await (await context.request.get(origin+'/api/session')).json();
  const headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
  const api=async(url,method='GET',data)=>{
   const response=await context.request.fetch(origin+'/api'+url,{method,headers,...(data===undefined?{}:{data})});
   if(!response.ok())throw Error(method+' '+url+' '+response.status()+': '+await response.text());
   return response.json();
  };
  const tag=engine+'-'+Date.now();
  const chat=await api('/conversations','POST',{});
  const text='我计划今天核对 '+tag+' 的申请材料。';
  await api('/conversations/'+chat.id+'/messages','POST',{version:chat.version,content:text,request_id:randomUUID(),allow_external_processing:true});
  const short=(await api('/memory/session-items')).items.find(i=>i.source_message_id&&i.conversation_id===chat.id&&i.kind==='intention');
  check(engine+' temporary plan stored as session item',short&&!short.promoted_id);
  await page.goto(origin+'/?lifecycle-test='+Date.now()+'#memory');
  await page.getByRole('heading',{name:'我的记忆',exact:true}).waitFor();
  check(engine+' lifecycle entry points',await page.locator('[data-memory-life="sessions"]').count()===1);
  await page.locator('[data-memory-life="settings"]').click();
  await page.locator('#memory-lifecycle-form').waitFor();
  check(engine+' semantic reflection defaults off',!await page.locator('#memory-lifecycle-form [name="semantic_reflection"]').isChecked());
  await page.locator('#memory-lifecycle-form [name="session_days"]').fill('3');
  await page.locator('#memory-lifecycle-form button[type="submit"]').click();
  await page.locator('#dialog').waitFor({state:'hidden'});
  check(engine+' lifecycle configuration persists',(await api('/memory/lifecycle')).settings.session_days===3);
  await page.locator('[data-memory-life="sessions"]').click();
  await page.locator('[data-memory-life="promote"][data-id="'+short.id+'"]').click();
  await page.locator('#memory-promotion-form').waitFor();
  await page.locator('#memory-promotion-form button[type="submit"]').click();
  await page.locator('#dialog').waitFor({state:'hidden'});
  const promoted=(await api('/memory/session-items')).items.find(i=>i.id===short.id);
  check(engine+' UI promotes with manual confirmation',!!promoted?.promoted_id);
  const item=await api('/memory/items/'+promoted.promoted_id);
  check(engine+' promoted record locks user decision',item.locked&&item.admission==='manual');
  await page.locator('[data-memory-life="item"][data-id="'+item.id+'"]').click();
  await page.locator('#memory-item-lifecycle [name="shared"]').uncheck();
  await page.locator('#memory-item-lifecycle button[type="submit"]').click();
  await page.locator('#dialog').waitFor({state:'hidden'});
  check(engine+' per-memory sharing is editable',!(await api('/memory/items/'+item.id)).shared);
  for(const width of [1440,390,320]){
   await page.setViewportSize({width,height:1000});
   await page.locator('[data-memory-life="settings"]').click();
   await page.locator('#memory-lifecycle-form').waitFor();
   await page.waitForFunction(()=>Number(getComputedStyle(document.querySelector('#dialog')).opacity)===1);
   check(engine+' '+width+' settings dialog fits',await page.locator('#dialog').evaluate(d=>{
    const box=d.getBoundingClientRect();return box.left>=-1&&box.right<=innerWidth+1&&box.top>=-1&&box.bottom<=innerHeight+1&&d.scrollWidth<=d.clientWidth+1;
   }));
   await shot(engine+'-'+width+'-settings');
   await page.keyboard.press('Escape');
   check(engine+' '+width+' page no overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(origin+'/#chat/'+chat.id);
  const previous=(await api('/conversations/'+chat.id)).messages.filter(m=>m.role==='assistant').at(-1)?.id;
  await page.locator('#chat-input').fill('请继续核对 '+tag+' 的申请材料。');
  await page.locator('#chat-composer button[type="submit"]').click();
  let last;
  for(let i=0;i<60;i++){
   last=(await api('/conversations/'+chat.id)).messages.filter(m=>m.role==='assistant').at(-1);
   if(last?.id!==previous&&last?.status==='complete')break;
   await new Promise(resolve=>setTimeout(resolve,150));
  }
  if(last?.id===previous||last?.status!=='complete')throw Error('New answer did not complete: '+JSON.stringify({status:last?.status,error:last?.error}));
  const trace=page.locator('[data-memory-life="trace"][data-id="'+last.id+'"]');
  await trace.waitFor();
  await trace.click();
  await page.getByRole('heading',{name:'这次回答的记忆使用',exact:true}).waitFor();
  check(engine+' actual recall is inspectable',await page.locator('[data-memory-life="feedback"][data-id="'+item.id+'"]').count()===3);
  await page.locator('[data-memory-life="feedback"][data-id="'+item.id+'"][data-outcome="helpful"]').click();
  await page.locator('[data-memory-life="feedback"][data-id="'+item.id+'"][data-outcome="helpful"][aria-pressed="true"]').waitFor();
  check(engine+' helpful feedback persists',(await api('/memory/items/'+item.id)).positive===1);
  await page.locator('[data-memory-life="feedback"][data-id="'+item.id+'"][data-outcome="outdated"]').click();
  await page.locator('[data-memory-life="feedback"][data-id="'+item.id+'"][data-outcome="outdated"][aria-pressed="true"]').waitFor();
  check(engine+' outdated feedback suspends recall',(await api('/memory/items/'+item.id)).state==='needs_review');
  await page.waitForFunction(()=>Number(getComputedStyle(document.querySelector('#dialog')).opacity)===1);
  await shot(engine+'-recall-feedback');
  await page.keyboard.press('Escape');
  await page.goto(origin+'/#memory');
  await page.locator('[data-memory-life="sessions"]').click();
  await page.locator('[data-memory-life="forget-session"][data-id="'+short.id+'"]').click();
  await page.getByRole('button',{name:'确认遗忘',exact:true}).click();
  await page.locator('#dialog').waitFor({state:'hidden'});
  check(engine+' forgetting removes session and promoted derivative',!(await api('/memory/session-items')).items.some(i=>i.id===short.id)&&!(await api('/memory')).memories.some(i=>i.id===item.id));
  const project=await api('/memory/projects','POST',{name:tag+' 人工范围确认',description:'合成生命周期验证'});
  const scopedChat=await api('/conversations','POST',{});
  const scopedContext=await api('/conversations/'+scopedChat.id+'/context');
  await api('/conversations/'+scopedChat.id+'/context','PUT',{...scopedContext,topics:['原始课程专题']});
  await api('/conversations/'+scopedChat.id+'/messages','POST',{version:scopedChat.version,content:'我计划今天核对 '+tag+' 的课程材料。',request_id:randomUUID(),allow_external_processing:true});
  const scopedShort=(await api('/memory/session-items')).items.find(i=>i.conversation_id===scopedChat.id&&i.kind==='intention');
  await page.reload();await page.locator('[data-memory-life="sessions"]').click();
  await page.locator('[data-memory-life="promote"][data-id="'+scopedShort.id+'"]').click();
  await page.locator('#memory-promotion-form [name="scope"]').selectOption('project');
  check(engine+' explicit project selector is visible',await page.locator('#memory-promotion-form [name="project_id"]').isVisible());
  await page.locator('#memory-promotion-form [name="project_id"]').selectOption(project.id);
  await page.locator('#memory-promotion-form [name="content"]').fill('我偏好先核对 '+tag+' 的课程原始来源。');
  await page.locator('#memory-promotion-form button[type="submit"]').click();
  await page.locator('#dialog').waitFor({state:'hidden'});
  const explicitlyPromoted=(await api('/memory/session-items')).items.find(i=>i.id===scopedShort.id);
  const explicitItem=await api('/memory/items/'+explicitlyPromoted.promoted_id);
  check(engine+' manual promotion honors edited content and chosen project',explicitItem.project_id===project.id&&explicitItem.kind==='preference'&&explicitItem.locked);
  await page.locator('[data-memory-life="audit"]').click();
  await page.getByRole('heading',{name:'记忆形成与整理记录',exact:true}).waitFor();
  check(engine+' lifecycle audit is visible',await page.locator('#dialog').innerText().then(t=>t.includes('主动遗忘')||t.includes('会话遗忘')));
 }catch(error){report.errors.push({engine,error:error.stack});await shot(engine+'-failure').catch(()=>{});}
 finally{await context.close();await browser.close();}
}
await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,passed:report.checks.filter(c=>c.passed).length,errors:report.errors,toolWarnings:report.toolWarnings.length},null,2));
if(report.errors.length||report.checks.some(c=>!c.passed))process.exitCode=1;
