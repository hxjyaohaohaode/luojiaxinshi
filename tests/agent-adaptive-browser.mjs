import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {chromium,request} from 'playwright';

const liveReplay=process.env.AGENT_LIVE_UI==='1';
const replayDir=process.env.AGENT_UI_REPLAY_DIR||'artifacts/agent-adaptive-live-ui';
const origin='http://127.0.0.1:8793',out=process.env.AGENT_BROWSER_OUTPUT||(liveReplay?'artifacts/agent-adaptive-live-browser':'artifacts/agent-adaptive-browser');
await mkdir(out,{recursive:true});
const login=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await login.post('/api/auth/login',{data:{username:'agent-preview',password:'AgentPreviewFixture2026!'}})).status(),200);
const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
const context=await browser.newContext({storageState:await login.storageState(),viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
try{
  const prompt=liveReplay?'真实生成回放验收：'+JSON.parse(await readFile(replayDir+'/synthetic-transcript.json','utf8'))[0].content:'排版验收：演示活动在2026年11月3日18:00截止，需要报名表和课程截图，请生成可勾选清单和按需展开的原文。';
  await page.goto(origin+'/#chat/new');await page.locator('#chat-input').fill(prompt);await page.locator('#chat-input').press('Enter');
  const reply=page.locator('.message-assistant').last();
  await reply.locator('.genui[data-complete=true]').waitFor({timeout:30000});
  assert.equal(await reply.locator('.gu-error').count(),0);
  assert.equal(await reply.locator('.gu-check input').count(),2);
  assert.equal(await reply.locator('details.gu-accordion').getAttribute('open'),null);
  assert.equal(await reply.locator('.work-summary-toggle').getAttribute('aria-expanded'),'false');
  assert.equal(await reply.locator('.work-body li').count(),0,'Collapsed work history must be lazy');
  checks.push('原聊天由 Agent 自由组合清单和折叠原文，默认不展开工作记录或详情');
  await reply.locator('.gu-check input').first().check();
  await reply.getByRole('button',{name:'保存互动进度',exact:true}).click();
  await reply.getByRole('button',{name:'互动进度已保存',exact:true}).waitFor();
  await page.reload();await reply.locator('.gu-check input').first().waitFor();
  assert.equal(await reply.locator('.gu-check input').first().isChecked(),true);
  assert.equal(await reply.locator('.gu-check input').nth(1).isChecked(),false);
  checks.push('勾选与原有互动保存接口连通，刷新后恢复真实状态');
  await reply.locator('.work-summary-toggle').click();
  await reply.locator('.work-trace-link').waitFor();
  assert.equal(await reply.locator('.execution-trace').count(),0,'The summary must not contain the full execution log');
  assert.equal(await reply.locator('.work-body').evaluate(n=>getComputedStyle(n).maxHeight),'none');
  assert.equal(await reply.locator('.work-body').evaluate(n=>getComputedStyle(n).overflowY),'visible');
  await reply.locator('.work-trace-link').click();
  await page.locator('#dialog .trace-record').first().waitFor();
  await page.locator('#dialog .trace-record').filter({hasText:'读取所需界面组件协议'}).click();
  assert.match(await page.locator('#dialog .trace-detail').innerText(),/读取组件协议/);
  await page.keyboard.press('Escape');
  await reply.locator('.work-summary-toggle').click();
  await reply.locator('.gu-accordion>summary').click();
  assert.match(await reply.locator('details.gu-accordion').innerText(),liveReplay?/演示活动/:/提交入口和资格条件尚未提供/);
  await reply.locator('.gu-accordion>summary').click();
  checks.push('工作摘要来自本轮组件调用，原文展开显示本轮实际内容');
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844],['narrow',320,720],['keyboard',390,420]]){
    await page.setViewportSize({width,height});
    await page.waitForFunction(()=>document.querySelector('#chat-input').getBoundingClientRect().bottom<=innerHeight+1);
    await page.locator('#chat-thread').evaluate(n=>n.scrollTop=0);
    await reply.evaluate(async n=>Promise.all(n.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
    const sizes=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,input:document.querySelector('#chat-input').getBoundingClientRect().bottom,viewport:innerHeight,
      nested:[...document.querySelectorAll('#chat-thread .genui *')].filter(n=>/auto|scroll/.test(getComputedStyle(n).overflowY)&&n.scrollHeight>n.clientHeight+2).length}));
    assert.ok(sizes.scroll<=sizes.width+1,JSON.stringify(sizes));assert.ok(sizes.input<=height+1,JSON.stringify(sizes));assert.equal(sizes.nested,0);
    await page.screenshot({path:`${out}/${name}.png`,animations:'disabled'});
    checks.push(`${name} ${width}×${height} 无横向溢出或内容嵌套滚动，输入区可见`);
  }
  assert.deepEqual(errors,[]);
  const typography=await page.evaluate(()=>Object.fromEntries(['body','#chat-thread','.message-content','.gu-markdown','.work-title'].map(selector=>[selector,getComputedStyle(document.querySelector(selector)).fontFamily])));
  await writeFile(out+'/results.json',JSON.stringify({synthetic:true,live_output_replay:liveReplay,checks,errors,typography},null,2));
  console.log(JSON.stringify({checks,errors},null,2));
}finally{await browser.close();await login.dispose();}
