import {browserOverride} from './browser-runtime.mjs';
// Synthetic end-to-end check through the original chat, provider stream and DB.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium,firefox,webkit,request} from 'playwright';

const engineName=process.env.OPENUI_BROWSER||'chromium',engine={chromium,firefox,webkit}[engineName];if(!engine)throw Error('Unknown browser');
const origin='http://127.0.0.1:8794',out=process.env.OPENUI_ARTIFACT_DIR||'artifacts/openui-browser';await mkdir(out,{recursive:true});
const login=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await login.post('/api/auth/login',{data:{username:'openui-preview',password:'OpenUIFixture2026!'}})).status(),200);
const browser=await engine.launch({headless:true,...browserOverride(engine),...(process.platform==='win32'&&engineName==='chromium'?{channel:'msedge'}:{})});
const context=await browser.newContext({storageState:await login.storageState(),viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const page=await context.newPage(),errors=[],checks=[],frameRequests=[],captureWarnings=[];let capturing=false;page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(m.type()==='error'){
  // Playwright 1.62's WebKit screenshot synchronizer injects exactly `body {}`
  // (coreBundle.js/inPagePrepareForScreenshots). Keep the host CSP strict and
  // account for this tooling-only diagnostic separately while capturing.
  const text=m.text();if(engineName==='webkit'&&capturing&&text==="Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear in the style-src directive of the Content Security Policy.")captureWarnings.push('Playwright WebKit screenshot sync stylesheet blocked by host CSP');else errors.push(text.slice(0,400));
}});
async function capture(path){capturing=true;try{await page.screenshot({path,caret:'initial'});await page.evaluate(()=>0);}finally{capturing=false;}}
page.on('request',r=>{if(r.url().endsWith('/static/genui/sandbox.html'))frameRequests.push(r.url());});
page.setDefaultTimeout(30000);
let firstAt=0,localAt=0,finishedAt=0;
try{
  await page.goto(origin+'/#chat/new');await page.locator('#chat-input').fill('生成式界面验收：每天2小时、准备7天，制作可调时间和材料清单。');
  const start=Date.now();await page.locator('#chat-input').press('Enter');
  const iframe=page.locator('.message-assistant').last().locator('iframe.openui-frame');await iframe.waitFor();
  const frame=iframe.contentFrame();await frame.locator('#total').waitFor();firstAt=Date.now()-start;
  assert.equal(await page.locator('.message-assistant').last().evaluate(n=>n.classList.contains('is-streaming')),true);
  assert.equal(await frame.locator('#openui-root').getAttribute('inert'),'');
  assert.equal(await frame.locator('#openui-root').getAttribute('inert'),'','HTML must appear before behavior is released.');
  await iframe.evaluate(node=>node.dataset.continuityProbe='same-frame');
  await capture(out+'/streaming.png');checks.push('模型尚在生成后续 HTML/JS 时，第一段组件已显示；预览保持 inert');
  await frame.locator('#openui-root:not([inert])').waitFor();localAt=Date.now()-start;
  assert.equal(await page.locator('.message-assistant').last().evaluate(n=>n.classList.contains('is-streaming')),true);
  await frame.locator('#days').fill('10');assert.equal(await frame.locator('#total').innerText(),'20');
  assert.equal(await frame.locator('#continue').isDisabled(),true);checks.push('复核期间先用本地计算，发送模型按钮保持禁用');
  await page.locator('.message-assistant').last().locator('.openui-status').waitFor({state:'hidden'});finishedAt=Date.now()-start;
  assert.ok(finishedAt>firstAt);assert.equal(await iframe.getAttribute('data-continuity-probe'),'same-frame');assert.equal(frameRequests.length,1);
  assert.equal(await frame.locator('#total').innerText(),'20');checks.push('同一 iframe 完成复核并保留先前输入，没有重载或重建');
  await page.evaluate(()=>localStorage.setItem('openui-isolation-probe','host-only'));
  const isolation=await frame.locator('body').evaluate(async()=>{
    let parentBlocked=false,storageBlocked=false,autoSendBlocked=false;
    try{void parent.document.body;}catch{parentBlocked=true;}
    try{storageBlocked=localStorage.getItem('openui-isolation-probe')===null;}catch{storageBlocked=true;}
    try{await CampusUI.sendPrompt({text:'自动请求必须被拒绝'});}catch{autoSendBlocked=true;}
    return {parentBlocked,storageBlocked,autoSendBlocked};
  });assert.deepEqual(isolation,{parentBlocked:true,storageBlocked:true,autoSendBlocked:true});checks.push('生成代码无法读取宿主 DOM/存储，加载后自动请求模型被拒绝');
  await frame.locator('#days').fill('10');assert.equal(await frame.locator('#total').innerText(),'20');
  await frame.locator('#hours').focus();await frame.locator('#hours').press('ArrowRight');assert.equal(await frame.locator('#total').innerText(),'25');
  await frame.locator('#days').fill('');assert.equal(await frame.locator('#total').innerText(),'—');assert.equal(await frame.locator('#validation').isVisible(),true);
  await frame.locator('#days').fill('10');await frame.locator('#form').check();assert.equal(await frame.locator('#progress').innerText(),'已准备 1 / 3 项');
  await frame.locator('#filter').selectOption('pending');assert.equal(await frame.locator('[data-material]').first().isVisible(),false);checks.push('原生控件即时更新计算和筛选；空数值清除过时结果；键盘可调滑块');
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__openuiCopied=text;},write:async items=>{window.__openuiCopied=await(await items[0].getType('text/plain')).text();if(items[0].types.includes('text/html'))window.__openuiCopiedHTML=await(await items[0].getType('text/html')).text();}}}));
  await page.locator('.message-assistant').last().locator('[data-chat-action=copy]').click();
  await page.waitForFunction(()=>typeof window.__openuiCopied==='string');assert.match(await page.evaluate(()=>window.__openuiCopied),/25/);assert.doesNotMatch(await page.evaluate(()=>window.__openuiCopiedHTML||''),/<iframe/i);checks.push('复制包含当前试算结果，富文本不携带隔离框架');
  await capture(out+'/desktop.png');
  await page.getByRole('button',{name:'保存互动进度',exact:true}).click();await page.getByRole('button',{name:'互动进度已保存',exact:true}).waitFor();
  const cid=new URL(page.url()).hash.split('/')[1];
  await page.reload();const restored=page.locator('.message-assistant').last().locator('iframe.openui-frame').contentFrame();await restored.locator('#total').filter({hasText:'25'}).waitFor();
  assert.equal(await restored.locator('#days').inputValue(),'10');assert.equal(await restored.locator('#form').isChecked(),true);assert.equal(await restored.locator('#filter').inputValue(),'pending');checks.push('保存调用真实 ui-state 接口；刷新恢复输入、勾选、筛选及计算');
  for(const [name,width,height]of [['mobile',390,844],['keyboard',390,420],['tablet',800,700]]){
    await page.setViewportSize({width,height});await page.locator('#chat-input').focus();
    const measured=await page.locator('iframe.openui-frame').last().evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,width:innerWidth}));
    assert.ok(measured.left>=0&&measured.right<=width+1,JSON.stringify(measured));
    const inner=await restored.locator('#openui-root').evaluate(node=>({width:node.getBoundingClientRect().width,viewport:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert.ok(inner.scroll<=inner.viewport+1,JSON.stringify(inner));
    await capture(out+'/'+name+'.png');
  }checks.push('390px 手机、键盘高度、800px 平板下无横向越界；画布按内容高度展开');
  await page.setViewportSize({width:1440,height:1000});
  await restored.locator('#continue').evaluate(node=>{window.__duplicatePromptHandler=0;node.addEventListener('click',()=>window.__duplicatePromptHandler++);});
  await restored.getByRole('button',{name:'按当前条件继续安排',exact:true}).click();
  await page.locator('.message-assistant').last().filter({hasText:'已收到当前准备时间与材料进度'}).waitFor();
  const api=await context.request.get(origin+'/api/conversations/'+cid),chat=await api.json();
  const submitted=chat.messages.filter(m=>m.role==='user').at(-1);assert.match(submitted.content,/准备时间|界面选择/);
  const choices=submitted.interaction.selections;assert.equal(choices.find(c=>c.path==='controls.days').value,'10');assert.equal(choices.find(c=>c.path==='controls.form').value,true);
  assert.equal(await page.locator('iframe.openui-frame').first().contentFrame().locator('body').evaluate(()=>window.__duplicatePromptHandler),0);assert.equal(chat.messages.filter(m=>m.role==='user').length,2);
  checks.push('用户点击后携带实际控件快照发起下一轮，并保存 interaction 与原界面进度');
  const seed=chat.messages.find(m=>m.role==='assistant'&&m.parts?.some(p=>p.kind==='ui'))?.parts.find(p=>p.kind==='ui').spec.sandbox;
  await page.evaluate(async ui=>{const {SandboxRenderer}=await import('/static/genui/openui.js');const mount=document.createElement('div');mount.id='openui-repair-probe';mount.hidden=true;document.body.append(mount);window.__openuiRepair=new SandboxRenderer(mount,{v:1,roots:[],nodes:{},state:{controls:{}},data:{},complete:false,errors:[],sandbox:{...ui,revision:1,localReady:true,cssComplete:true,htmlComplete:true}});},seed);
  await page.waitForFunction(()=>window.__openuiRepair?.localInteractive);
  const probe=page.locator('#openui-repair-probe iframe').contentFrame();await probe.locator('#days').evaluate(node=>{node.value='10';node.dispatchEvent(new Event('input',{bubbles:true}));});
  await page.waitForFunction(()=>window.__openuiRepair.controls.days==='10');
  await page.evaluate(()=>{const r=window.__openuiRepair;r.update({...r.spec,sandbox:{...r.spec.sandbox,revision:2,html:r.spec.sandbox.html.map(s=>s.replace('value="2"','value="3"'))}});});
  await page.waitForFunction(()=>window.__openuiRepair.localInteractive&&window.__openuiRepair.controls.days==='10'&&window.__openuiRepair.controls.hours==='3');
  assert.equal(await probe.locator('#total').textContent(),'30');await page.evaluate(()=>{window.__openuiRepair.dispose();document.getElementById('openui-repair-probe').remove();delete window.__openuiRepair;});
  checks.push('修正重建只保留实际改过且字段契约一致的输入，未改初值使用新稿；共享按钮阻止重复监听');
  // Stream content first, then an unexpectedly wide authored grid. This is independent of the chat fixture's CSS-first reply.
  const flowPage=await context.newPage();
  await flowPage.setViewportSize({width:320,height:640});await flowPage.goto(origin+'/privacy');
  await flowPage.evaluate(async()=>{
    const {SandboxRenderer}=await import('/static/genui/openui.js');
    const mount=document.createElement('main');document.body.replaceChildren(mount);
    mount.style.cssText='width:100%;min-width:0';document.body.style.cssText='margin:0;display:block';
    const spec={complete:false,errors:[],sandbox:{title:'合成路程比较',preferredWidth:880,initialHeight:1400,revision:1,
      html:['<article><h2>步行路线</h2><div class="paths"><section>沿湖路线</section><section>林荫路线</section></div><figure><svg viewBox="0 0 800 120" style="display:block;width:100%"><text x="100" y="80" font-size="12">入口</text><text x="650" y="80" font-size="12">终点</text></svg></figure></article>'],
      htmlComplete:false,css:'',cssComplete:false,jsFunctions:[],jsExpressions:[]}};
    window.flowRenderer=new SandboxRenderer(mount,spec);
    window.flowRenderer.frame.style.cssText='display:block;width:100%;margin:0;border:0';
  });
  const flowFrame=flowPage.locator('iframe.openui-frame'),inside=flowFrame.contentFrame();
  await inside.getByText('沿湖路线').waitFor();
  await flowPage.waitForFunction(()=>{const h=document.querySelector('iframe').getBoundingClientRect().height;return h>2&&h<300;});
  assert.equal(await inside.locator('#openui-root').evaluate(node=>node.inert),true);
  await flowPage.evaluate(()=>{const r=window.flowRenderer;r.update({...r.spec,sandbox:{...r.spec.sandbox,htmlComplete:true,cssComplete:true,
    css:'.paths{display:grid;grid-template-columns:370px 370px;gap:14px}.paths section{padding:10px}'}});});
  for(const width of [320,390,844,768,1440,320]){
    await flowPage.setViewportSize({width,height:670});
    await flowPage.waitForFunction(w=>Math.abs(document.querySelector('iframe').getBoundingClientRect().width-w)<3,width);
    await inside.locator('.paths').evaluate(async(node,targetWidth)=>{
      const label=document.querySelector('figure svg text');
      const readable=()=>{
        const m=label.getScreenCTM();
        return m&&parseFloat(getComputedStyle(label).fontSize)*Math.hypot(m.c,m.d)>=10.9;
      };
      const ready=()=>innerWidth===targetWidth&&readable()&&node.scrollWidth<=node.clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1;
      const deadline=performance.now()+2500;
      while(!ready()&&performance.now()<deadline)await new Promise(resolve=>requestAnimationFrame(resolve));
      if(!ready())throw Error('生成列或示意图未完成重排 '+JSON.stringify([targetWidth,innerWidth,label.outerHTML,readable()]));
    },width);
  }
  await flowPage.close();
  checks.push('自由 HTML 在 CSS 完成前可读，1400px 建议高度不会撑开首屏；固定双列随六次视口变化重新排版');
  assert.deepEqual(errors,[]);
  const report={passed:true,browser:engineName,source:'synthetic agent arguments, real application API/database/browser',checks,errors,captureWarnings,firstHtmlMs:firstAt,localControlsMs:localAt,interactiveMs:finishedAt};
  await writeFile(out+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}catch(error){await capture(out+'/failure.png').catch(()=>{});await writeFile(out+'/report.json',JSON.stringify({passed:false,error:String(error),checks,errors,captureWarnings,firstHtmlMs:firstAt,interactiveMs:finishedAt},null,2));throw error;}
finally{await context.close();await browser.close();await login.dispose();}
