import {artifactPath} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={checks:[],views:[],errors:[],sample:'Isolated synthetic account only; no model calls.'};
const check=(name,value)=>{if(!value)throw Error(name);report.checks.push(name);};
for(const engine of ['chromium','firefox','webkit']){
 const browser=await pw[engine].launch({headless:true,...(engine==='chromium'?{executablePath:pw.chromium.executablePath()}:{})});
 const context=await browser.newContext({reducedMotion:'reduce'}),page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(engine+': '+e.message));
 await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
 const session=await (await context.request.get(origin+'/api/session')).json();
 const headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
 const close=async()=>{await page.locator('#dialog [data-action=close-dialog]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});};
 const go=async route=>{await page.goto(origin+'/#'+route,{waitUntil:'domcontentloaded'});await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);};
 async function shot(name,width,dialog=false){
   if(dialog)await page.waitForSelector('#dialog[open] .dialog-body');
   await page.evaluate(()=>document.fonts.ready);
   const size=await page.evaluate(dialog=>{const node=dialog?document.querySelector('#dialog'):document.documentElement,body=dialog?node.querySelector('.dialog-body'):node,r=node.getBoundingClientRect();return {viewport:innerWidth,scroll:body.scrollWidth,client:body.clientWidth,left:r.left,right:r.right,top:r.top,bottom:r.bottom,height:innerHeight};},dialog);
   check(`${engine}/${width}/${name} no overflow`,size.scroll<=size.client+2&&(!dialog||size.left>=-1&&size.right<=size.viewport+1&&size.top>=-1&&size.bottom<=size.height+1));
   report.views.push({engine,width,name,...size});
   await page.screenshot({path:artifactPath(`memory-${engine}-${width}-${name}.png`),fullPage:!dialog});
 }
 try{
   if(engine==='chromium'){
     await page.setViewportSize({width:390,height:844});await go('settings');
     await page.locator('.settings-menu a[href="#memory"]').click();await page.waitForSelector('.memory-page');
     await page.locator('[data-memory-action=project-new]').click();
     const projectName='浏览器验收项目 '+Date.now();
     let form=page.locator('[data-workspace-form=memory-project]');await form.locator('[name=name]').fill(projectName);await form.locator('[name=description]').fill('合成的课程与比赛准备项目。');await form.locator('[type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});
     const createdProject=page.locator('.memory-project').filter({hasText:projectName});await createdProject.waitFor();
     check('Create project through mobile form',await createdProject.count()===1);
     const memoryText='合成记忆：回答先给结论，再给需要本人核对的下一步。 '+Date.now();
     await page.locator('[data-memory-action=new]').click();form=page.locator('[data-workspace-form=memory-entry]');await form.locator('[name=scope]').selectOption('project');await form.locator('[name=project_id]').selectOption({index:1});await form.locator('[name=content]').fill(memoryText);await form.locator('[name=pinned]').check();await form.locator('[type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});
     const card=page.locator('.memory-card').filter({hasText:memoryText});await card.waitFor();check('Save scoped pinned memory',await card.locator('.pill').filter({hasText:'优先使用'}).count()===1);
     await card.locator('[data-memory-action=toggle]').click();await card.getByText('已停用',{exact:true}).waitFor();check('Disable memory from mobile',await card.locator('.pill').filter({hasText:'已停用'}).count()===1);
     await card.locator('[data-memory-action=edit]').click();form=page.locator('[data-workspace-form=memory-entry]');await form.locator('[name=scope]').selectOption('topic');await form.locator('[name=topic]').fill('论文写作');await form.locator('[type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});await card.getByText('论文写作',{exact:true}).waitFor();check('Move memory to explicit topic',await card.getByText('论文写作',{exact:true}).count()===1);
     await card.locator('[data-memory-action=toggle]').click();await card.getByText('已停用',{exact:true}).waitFor({state:'detached'});
     await page.locator('#memory-search').fill('不存在的特殊字串');check('Search empty state',await page.locator('.memory-card').count()===0);await page.locator('#memory-search').fill('');
     const chat=await (await context.request.post(origin+'/api/conversations',{headers,data:{title:'虚构记忆浏览器验收'}})).json();await go('chat/'+chat.id);
     await page.locator('[data-chat-action=composer-menu]').click();await page.locator('[data-chat-action=context-settings]').click();form=page.locator('[data-workspace-form=memory-context]');await form.locator('[name=project_id]').selectOption({index:1});await form.locator('[name=topics]').fill('论文写作');await form.locator('[type=submit]').click();await page.waitForSelector('#dialog:not([open])',{state:'attached'});
     const saved=await (await context.request.get(origin+`/api/conversations/${chat.id}/context`)).json();check('Conversation stores project and topic',!!saved.project_id&&saved.topics.includes('论文写作'));
     // Keep the same document alive: delayed reads must not open an old dialog
     // after SPA navigation, or replace the newly selected page.
     async function delayedDialog(pattern,open){
       let release,started;const gate=new Promise(r=>release=r),seen=new Promise(r=>started=r);
       await page.route(pattern,async route=>{started();await gate;await route.continue();});
       const response=page.waitForResponse(pattern);await open();await seen;
       await page.evaluate(()=>{location.hash='#settings';});
       await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='settings'&&!document.querySelector('#content').hasAttribute('aria-busy'));
       release();await response;await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
       check('Late '+pattern+' does not open old dialog',await page.locator('#dialog[open]').count()===0&&await page.locator('#content').getAttribute('data-page')==='settings');
       await page.unroute(pattern);
     }
     await go('memory');await delayedDialog('**/api/memory',()=>page.locator('[data-memory-action=new]').click());
     await go('chat/'+chat.id);await page.locator('[data-chat-action=composer-menu]').click();
     await delayedDialog('**/api/conversations/*/context',()=>page.locator('[data-chat-action=context-settings]').click());
     const stamp=Date.now(),factKey='浏览器互斥项 '+stamp;
     const add=async content=>{const response=await context.request.post(origin+'/api/memory/items',{headers,data:{content,semantic_key:factKey}});check('Create lifecycle fixture',response.ok());return response.json();};
     const kept=await add('保留的合成偏好 '+stamp),old=await add('停用的合成偏好 '+stamp);
     await go('memory');const conflict=page.locator('.memory-card').filter({hasText:kept.content});
     check('Conflict is visible on mobile',await conflict.getByText('冲突待处理',{exact:true}).count()===1);
     await conflict.locator('[data-memory-action=resolve]').click();await page.locator('[data-action=accept-dialog]').click();
     await page.waitForFunction(id=>!document.querySelector(`[data-memory-action=resolve][data-id="${id}"]`),kept.id);
     const resolved=await (await context.request.get(origin+'/api/memory')).json();
     check('Conflict choice persisted atomically',resolved.memories.find(m=>m.id===kept.id).active&& !resolved.memories.find(m=>m.id===old.id).active);
     await page.locator(`[data-memory-action=edit][data-id="${kept.id}"]`).click();form=page.locator('[data-workspace-form=memory-entry]');
     await form.locator('.memory-policy summary').click();await form.locator('[name=expires_at]').fill('2020-01-01T12:00');await form.locator('[type=submit]').click();
     await page.waitForSelector('#dialog:not([open])',{state:'attached'});
     await page.locator('.memory-card').filter({hasText:kept.content}).getByText('已过期',{exact:true}).waitFor();
     check('Expired memory remains visible but inactive for recall',await page.locator('.memory-card').filter({hasText:kept.content}).getByText('已过期',{exact:true}).count()===1);
   }
   const chat=await (await context.request.post(origin+'/api/conversations',{headers,data:{title:'虚构记忆布局验收'}})).json();
   for(const [width,height] of [[320,844],[390,844],[768,1024],[844,390],[1440,900],[1920,1080]]){
     await page.setViewportSize({width,height});await go('memory');await shot('page',width);
     await page.locator('[data-memory-action=new]').click();await shot('entry-global',width,true);
     const projectField=page.locator('[data-project-field]'),topicField=page.locator('[data-topic-field]');
     check(`${engine}/${width}/global hides scope-only fields`,!await projectField.isVisible()&&!await topicField.isVisible());
     await page.locator('.memory-policy summary').click();await shot('entry-lifecycle',width,true);
     await page.locator('[data-workspace-form=memory-entry] [name=scope]').selectOption('project');await shot('entry-project',width,true);
     check(`${engine}/${width}/project shows only project field`,await projectField.isVisible()&&!await topicField.isVisible());
     await page.locator('[data-workspace-form=memory-entry] [name=scope]').selectOption('topic');await shot('entry-topic',width,true);
     check(`${engine}/${width}/topic shows only topic field`,!await projectField.isVisible()&&await topicField.isVisible());await close();
     await page.locator('[data-memory-action=project-new]').click();await shot('project',width,true);await close();
     await go('chat/'+chat.id);await page.locator('[data-chat-action=composer-menu]').click();await page.locator('[data-chat-action=context-settings]').click();await shot('conversation',width,true);await close();
     await go('settings');await page.locator('[data-action=settings-model]').click();await shot('models',width,true);
     await page.locator('#open-executions').click();await page.waitForSelector('.execution-list');await shot('executions',width,true);await close();
   }
 }catch(error){report.errors.push(engine+': '+error.stack);}finally{await browser.close();}
}
await writeFile(artifactPath('memory-browser.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,views:report.views.length,errors:report.errors}));
process.exitCode=report.errors.length?1:0;
