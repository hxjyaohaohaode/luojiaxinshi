// Original SSE, persisted checkpoints and browser reloads; isolated synthetic data.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium,firefox,webkit,request} from 'playwright';
const name=process.env.OPENUI_BROWSER||'chromium',engine={chromium,firefox,webkit}[name],origin='http://127.0.0.1:8794',out=process.env.OPENUI_ARTIFACT_DIR||'artifacts/chat-recovery/'+name;
await mkdir(out,{recursive:true});const checks=[],errors=[];
const api=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await api.post('/api/auth/login',{data:{username:'openui-preview',password:'OpenUIFixture2026!'}})).status(),200);
const csrf=(await(await api.get('/api/session')).json()).csrf,headers={'X-CSRF-Token':csrf};
let chat=await(await api.post('/api/conversations',{headers,data:{title:'刷新与版本恢复验收'}})).json();
const url='/api/conversations/'+chat.id;
const send=data=>api.post(url+'/messages/stream',{headers,data:{version:chat.version,request_id:crypto.randomUUID(),allow_external_processing:true,...data}});
assert.equal((await send({content:'合成验收：生成可交互的准备计划界面。'})).status(),200);
chat=await(await api.get(url)).json();const old=chat.messages.at(-1).id;
const browser=await engine.launch({headless:true,...(name==='chromium'&&process.platform==='win32'?{channel:'msedge'}:{})}),context=await browser.newContext({storageState:await api.storageState(),viewport:{width:1651,height:871}}),page=await context.newPage();
page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(String(e)));
let pending;
try{
  await page.goto(origin+'/#chat/'+chat.id);await page.locator('iframe.openui-frame').waitFor();
  pending=send({content:'',regenerate_message_id:old});let live;
  for(let i=0;i<100;i++){
    live=await(await api.get(url)).json();
    if(live.messages.at(-1).preview?.ui?.localReady&&live.messages.at(-1).grounding?.steps?.at(-1)?.stage==='verifying')break;
    await new Promise(r=>setTimeout(r,80));
  }
  const current=live.messages.at(-1);assert.notEqual(current.id,old);assert.equal(current.status,'processing');assert.ok(current.preview.ui.localReady);
  await page.reload();const reply=page.locator('.message-assistant').last();await page.waitForFunction(id=>document.querySelector('.message-assistant:last-child')?.dataset.messageId===id,current.id);
  const frame=page.frameLocator('iframe.openui-frame');await frame.locator('input').first().waitFor();
  assert.equal(await reply.locator('[data-chat-action=regenerate]').count(),0);assert.match(await reply.locator('.message-state').innerText().catch(()=>reply.locator('.message-label').innerText()),/核验中|处理/);
  await page.screenshot({path:out+'/review-restored.png'});checks.push('核验期间刷新，恢复最新版本的文字和互动界面，未退回上一版；生成状态与动作权限正确');
  assert.equal((await pending).status(),200);pending=null;
  await page.waitForFunction(()=>!document.querySelector('.message-assistant:last-child')?.classList.contains('is-streaming'));
  live=await(await api.get(url)).json();const final=live.messages.at(-1);assert.equal(final.id,current.id);assert.equal(final.status,'complete');assert.ok(final.genui.validated);assert.equal(final.preview,undefined);
  await page.reload();await page.waitForFunction(id=>document.querySelector('.message-assistant:last-child')?.dataset.messageId===id,current.id);await page.frameLocator('iframe.openui-frame').locator('input').first().waitFor();
  assert.equal((await(await api.get(url)).json()).messages.at(-1).genui.raw,final.genui.raw);checks.push('完成后刷新，最终正文与界面原文完全一致，预览检查点清除');
  await page.locator('.message-assistant').last().getByRole('button',{name:'上一版回复',exact:true}).click();await page.waitForFunction(id=>document.querySelector('.message-assistant:last-child')?.dataset.messageId===id,old);await page.reload();await page.waitForFunction(id=>document.querySelector('.message-assistant:last-child')?.dataset.messageId===id,old);
  await page.locator('.message-assistant').last().getByRole('button',{name:'下一版回复',exact:true}).click();await page.waitForFunction(id=>document.querySelector('.message-assistant:last-child')?.dataset.messageId===id,current.id);await page.reload();await page.waitForFunction(id=>document.querySelector('.message-assistant:last-child')?.dataset.messageId===id,current.id);checks.push('主动切换旧版和最新版都持久化，刷新后保持所选版本');
  await page.screenshot({path:out+'/latest-restored.png'});assert.deepEqual(errors,[]);await writeFile(out+'/report.json',JSON.stringify({passed:true,browser:name,checks,errors},null,2));console.log(JSON.stringify({passed:true,browser:name,checks},null,2));
}catch(error){await page.screenshot({path:out+'/failure.png'}).catch(()=>{});await writeFile(out+'/report.json',JSON.stringify({passed:false,error:String(error),checks,errors},null,2));throw error;}
finally{if(pending)await pending.catch(()=>{});await context.close();await browser.close();await api.dispose();}
