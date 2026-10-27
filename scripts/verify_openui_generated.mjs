// Replay the actual paid-model artifact; all subsequent browser work is offline.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium,firefox,webkit,request} from 'playwright';
const name=process.env.OPENUI_BROWSER||'chromium',engine={chromium,firefox,webkit}[name];
const out=process.env.OPENUI_ARTIFACT_DIR||'artifacts/openui-live/browser/chromium',origin='http://127.0.0.1:8794';await mkdir(out,{recursive:true});
const api=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await api.post('/api/auth/login',{data:{username:'openui-preview',password:'OpenUIFixture2026!'}})).status(),200);
const browser=await engine.launch({headless:true,...(process.platform==='win32'&&name==='chromium'?{channel:'msedge'}:{})});
const context=await browser.newContext({storageState:await api.storageState(),viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const page=await context.newPage(),errors=[],checks=[];page.setDefaultTimeout(30000);page.on('pageerror',e=>errors.push(String(e)));
try{
  await page.goto(origin+'/#chat/new');await page.locator('#chat-input').fill('回放真实模型生成的合成工程工具，制作生成式交互界面：每天2小时、准备7天，合计14小时。');await page.locator('#chat-input').press('Enter');
  const host=page.locator('.message-assistant').last();await host.locator('iframe.openui-frame').waitFor();const frame=host.locator('iframe.openui-frame').contentFrame();
  await host.locator('.openui-status').waitFor({state:'hidden'});const total=frame.locator('#total,[id$="-total"],[id$="_total"]').first();assert.equal(parseFloat(await total.innerText()),14);
  const number=frame.locator('input[type=number]'),slider=frame.locator('input[type=range]');
  await number.fill('10');assert.equal(parseFloat(await total.innerText()),20);
  await slider.focus();await slider.press('ArrowRight');assert.equal(parseFloat(await total.innerText()),25);
  for(const invalid of ['','1.5','31']){await number.fill(invalid);assert.equal(await total.innerText(),'—');assert.match(await frame.locator('#openui-root [role=alert],#openui-root [id*="error"],#openui-root .ui-error').first().innerText(),/空|整数|范围/);}
  await number.fill('10');assert.equal(parseFloat(await total.innerText()),25);checks.push('真实生成代码可执行：2×7、改天数、键盘调节、空值/小数/越界及恢复');
  await page.screenshot({path:out+'/desktop.png',caret:'initial'});
  await page.getByRole('button',{name:'保存互动进度',exact:true}).click();await page.getByRole('button',{name:'互动进度已保存',exact:true}).waitFor();await page.reload();
  const restored=page.locator('.message-assistant').last().locator('iframe.openui-frame').contentFrame();await restored.locator('#total,[id$="-total"],[id$="_total"]').filter({hasText:'25'}).first().waitFor();checks.push('真实生成控件通过原接口保存并在刷新后重算');
  for(const [label,width,height]of [['mobile',390,844],['keyboard',390,420]]){
    await page.setViewportSize({width,height});await page.locator('#chat-input').focus();
    const geometry=await restored.locator('#openui-root').evaluate(n=>({scroll:document.documentElement.scrollWidth,width:innerWidth,height:n.getBoundingClientRect().height}));
    assert.ok(geometry.scroll<=geometry.width+1);await page.screenshot({path:out+'/'+label+'.png',caret:'initial'});
  }checks.push('真实生成界面在手机和键盘高度下无横向越界');
  await restored.getByRole('button',{name:'按当前条件继续分析',exact:true}).click();await page.locator('.message-assistant').last().filter({hasText:'已收到当前准备时间与材料进度'}).waitFor();checks.push('真实模型生成的追问按钮连通原聊天，携带当前条件');
  assert.deepEqual(errors,[]);const result={passed:true,browser:name,source:'actual MiMo-generated UI replayed offline',checks,errors};await writeFile(out+'/report.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}catch(error){await page.screenshot({path:out+'/failure.png',caret:'initial'}).catch(()=>{});await writeFile(out+'/report.json',JSON.stringify({passed:false,error:String(error),checks,errors},null,2));throw error;}
finally{await context.close();await browser.close();await api.dispose();}
