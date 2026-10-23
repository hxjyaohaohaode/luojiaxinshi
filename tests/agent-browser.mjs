import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium,request} from 'playwright';

const origin='http://127.0.0.1:8793';
const out='artifacts/agent-chat-browser';await mkdir(out,{recursive:true});
const login=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await login.post('/api/auth/login',{data:{username:'agent-preview',password:'AgentPreviewFixture2026!'}})).status(),200);
const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
const context=await browser.newContext({storageState:await login.storageState(),viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
await page.addInitScript(()=>{window.__agentToasts=[];new MutationObserver(()=>{const node=document.querySelector('#toast');if(node?.textContent.includes('回复事件暂不支持')||node?.textContent.includes('工作摘要无效'))window.__agentToasts.push(node.textContent);}).observe(document,{subtree:true,childList:true,characterData:true});});
async function ask(text){await page.locator('#chat-input').fill(text);await page.locator('#chat-input').press('Enter');}
try{
  await page.goto(origin+'/#chat/new');await page.locator('#chat-input').waitFor();
  assert.equal(await page.locator('a[href="/agent"]').count(),0);checks.push('无独立智能任务页面或导航，沿用原聊天');
  await ask('请通过审批保存材料清单文件');await page.getByRole('button',{name:'批准本次',exact:true}).waitFor();
  await page.locator('.chat-agent-approval summary').click();
  assert.match(await page.locator('.chat-agent-approval pre').innerText(),/合成材料清单/);
  await page.locator('.chat-agent-approval').evaluate(async node=>{await Promise.all(node.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
  await page.screenshot({path:out+'/desktop-approval.png',animations:'disabled'});
  await page.getByRole('button',{name:'批准本次',exact:true}).click();
  await page.locator('.message-assistant:not(.is-streaming) .message-content').filter({hasText:'合成验收回复'}).waitFor();
  const link=page.locator('.chat-agent-files a');assert.equal(await link.count(),1);
  const [download]=await Promise.all([page.waitForEvent('download'),link.click()]);await download.saveAs(out+'/approved-checklist.md');
  checks.push('普通聊天完成工具循环、原有核验、原位审批及实际文件下载');
  await ask('请审批保存另一份材料清单文件');await page.getByRole('button',{name:'拒绝',exact:true}).waitFor();
  await page.reload();await page.getByRole('button',{name:'拒绝',exact:true}).waitFor();
  await page.getByRole('button',{name:'拒绝',exact:true}).click();
  await page.locator('.message-assistant').last().locator('.message-content').filter({hasText:'合成验收回复'}).waitFor();
  assert.equal(await page.locator('.message-assistant').last().locator('.chat-agent-files a').count(),0);
  checks.push('刷新原聊天可恢复待审批项，拒绝后不生成文件');
  await ask('请审批保存待取消的文件');await page.getByRole('button',{name:'拒绝',exact:true}).waitFor();
  const chatId=new URL(page.url()).hash.split('/')[1];
  const primary=page.locator('#chat-composer .send-button');
  assert.equal(await page.locator('#chat-composer .composer-stop').count(),0);
  assert.equal(await primary.getAttribute('aria-label'),'停止本次回复');
  const bounds=await primary.boundingBox();
  await page.locator('#chat-input').fill('补充草稿');
  assert.equal(await primary.getAttribute('aria-label'),'发送补充消息');
  const typed=await primary.boundingBox();assert.ok(Math.abs(typed.x-bounds.x)<1&&Math.abs(typed.y-bounds.y)<1);
  await page.locator('#chat-input').fill('  ');assert.equal(await primary.getAttribute('aria-label'),'停止本次回复');
  await page.locator('#chat-input').press('Enter');assert.equal(await page.getByRole('button',{name:'拒绝',exact:true}).count(),1);
  await page.locator('#chat-input').fill('');
  checks.push('生成时同一主按钮为停止，输入补充后为发送，清空后恢复停止；空白 Enter 不取消');

  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844],['keyboard',390,420]]){
    await page.setViewportSize({width,height});await page.locator('#chat-input').focus();
    await page.waitForFunction(()=>document.querySelector('#chat-input').getBoundingClientRect().bottom<=innerHeight+1,{},{timeout:5000});
    const sizes=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
      input:document.querySelector('#chat-input').getBoundingClientRect().bottom,viewport:innerHeight,thread:document.querySelector('#chat-thread').getBoundingClientRect().height}));
    assert.ok(sizes.scroll<=sizes.width+1,JSON.stringify(sizes));assert.ok(sizes.input<=sizes.viewport+1,JSON.stringify(sizes));assert.ok(sizes.thread>50,JSON.stringify(sizes));
    await page.screenshot({path:`${out}/${name}.png`});checks.push(`${name} ${width}×${height}: 原聊天无横向溢出，输入区可见`);
  }
  await page.locator('[data-chat-action="cancel"]').click();
  await page.getByRole('button',{name:'拒绝',exact:true}).waitFor({state:'hidden'});
  const state=await page.evaluate(async id=>(await fetch('/api/conversations/'+id)).json(),chatId);
  assert.equal(state.messages.at(-1).status,'cancelled');assert.equal(state.messages.at(-1).agent.files.length,0);
  checks.push('原聊天停止按钮取消工具执行与审批');
  await page.setViewportSize({width:1440,height:1000});
  await ask('日历待办验收：创建 2027 年 10 月 23 日 9 点到 10 点的项目讨论，以及 10 月 22 日 16 点准备报告的待办。');
  const receipt=page.locator('.message-assistant').last();
  await receipt.locator('[data-chat-action="undo-operation"]').first().waitFor({timeout:20000});
  assert.equal(await receipt.locator('.chat-operation').count(),2);
  assert.match(await receipt.innerText(),/已添加到日历/);assert.match(await receipt.innerText(),/已创建待办/);
  assert.equal(await receipt.locator('.chat-agent-approval').count(),0);
  const saved=await page.evaluate(async()=>({calendar:await (await fetch('/api/arrangements')).json(),tasks:await (await fetch('/api/tasks')).json()}));
  assert.ok(saved.calendar.some(x=>x.data.title==='工程测试：项目讨论'));
  assert.ok(saved.tasks.some(x=>x.data.title==='工程测试：准备报告'));
  await page.screenshot({path:out+'/operation-receipts.png',animations:'disabled'});
  await receipt.locator('.chat-operation').filter({hasText:'工程测试：项目讨论'}).getByRole('button',{name:'撤销',exact:true}).click();
  await receipt.locator('.chat-operation').filter({hasText:'工程测试：项目讨论'}).getByText('已撤销',{exact:true}).waitFor();
  await page.reload();await page.getByText('已撤销',{exact:true}).waitFor();
  const remaining=await page.evaluate(async()=> (await fetch('/api/arrangements')).json());
  assert.ok(!remaining.some(x=>x.data.title==='工程测试：项目讨论'));
  const fallback=await page.evaluate(async id=>{
    const chat=await (await fetch('/api/conversations/'+id)).json(),latest=chat.messages.at(-1);
    const {ConversationView}=await import('/static/genui/chat-presenter.js'),host=document.createElement('div');document.body.append(host);
    const old={id:'old',role:'assistant',status:'complete',content:'上一版回答',versions:[{id:'old',status:'complete'},{...latest,status:'failed'}]};
    const view=new ConversationView(host,{feature:{enabled:false}});view.draw([old]);
    const result={receipts:host.querySelectorAll('.chat-operation').length,text:host.textContent};view.dispose();host.remove();return result;
  },chatId);
  assert.equal(fallback.receipts,2);assert.match(fallback.text,/操作结果见下方/);assert.match(fallback.text,/已撤销/);
  checks.push('重试失败保留旧回答时，后来已提交的操作及撤销结果仍可见');
  checks.push('日历和待办直接写入原业务数据，真实回执可见，无重复审批，撤销与刷新结果一致');assert.deepEqual(errors,[]);
  assert.deepEqual(await page.evaluate(()=>window.__agentToasts),[]);
  await writeFile(out+'/results.json',JSON.stringify({synthetic:true,checks,errors},null,2));console.log(JSON.stringify({checks,errors},null,2));
}finally{
  await page.evaluate(async()=>{const cid=location.hash.split('/')[1];if(!/^[a-f0-9]{32}$/.test(cid||''))return;const chat=await (await fetch('/api/conversations/'+cid)).json();if(!chat.processing)return;const session=await (await fetch('/api/session')).json();await fetch('/api/conversations/'+cid+'/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf},body:JSON.stringify({version:chat.version})});}).catch(()=>{});
  await browser.close();await login.dispose();
}
