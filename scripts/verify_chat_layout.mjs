import {browserOverride} from './browser-runtime.mjs';
// Real controls and scroll gestures in an isolated account; no paid model.
import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {chromium,firefox,webkit,request} from 'playwright';

const name=process.env.OPENUI_BROWSER||'chromium',engine={chromium,firefox,webkit}[name];
const out=process.env.OPENUI_ARTIFACT_DIR||'artifacts/chat-layout/chromium',origin='http://127.0.0.1:8794';await mkdir(out,{recursive:true});
const api=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await api.post('/api/auth/login',{data:{username:'openui-preview',password:'OpenUIFixture2026!'}})).status(),200);
const headers={'X-CSRF-Token':(await(await api.get('/api/session')).json()).csrf};
const created=await api.post('/api/conversations',{headers,data:{title:'紧凑聊天布局验收'}});assert.equal(created.status(),200);const chat=await created.json();
const response=await api.post('/api/conversations/'+chat.id+'/messages/stream',{headers,data:{version:chat.version,content:Array(18).fill('合成布局验收：检查单行输入、阅读收起标题以及向上滚动恢复。').join('\n\n'),request_id:crypto.randomUUID(),allow_external_processing:true}});assert.equal(response.status(),200);
const browser=await engine.launch({headless:true,...browserOverride(engine),...(process.platform==='win32'&&name==='chromium'?{channel:'msedge'}:{})});
const context=await browser.newContext({storageState:await api.storageState(),viewport:{width:1651,height:871},reducedMotion:'reduce'});
const page=await context.newPage(),checks=[],errors=[];page.on('pageerror',e=>errors.push(String(e)));page.setDefaultTimeout(15000);
const geometry=()=>page.evaluate(()=>{const rect=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right};};return {form:rect(document.querySelector('#chat-composer')),input:rect(document.querySelector('#chat-input')),plus:rect(document.querySelector('.composer-plus')),send:rect(document.querySelector('.send-button')),header:rect(document.querySelector('.chat-heading')),thread:rect(document.querySelector('#chat-thread')),note:rect(document.querySelector('.chat-footnote')),width:innerWidth,scroll:document.documentElement.scrollWidth};});
function assertHeaderCoversReader({header,thread}) {
  assert.ok(header.x<=thread.x+1 && header.right>=thread.right-1,
    'The transcript must stay covered at both edges of the visible header: '+JSON.stringify({header,thread}));
}
try{
  await page.goto(origin+'/#chat/'+chat.id,{waitUntil:'domcontentloaded'});const input=page.locator('#chat-input');await page.locator('#content:not([inert])').waitFor();await input.waitFor();
  const empty=await geometry();assertHeaderCoversReader(empty);assert.ok(empty.form.height<=58,JSON.stringify(empty));
  for(const value of ['输入一行内容','连续单行文字'.repeat(120)]){
    await input.fill(value);const current=await geometry();assert.ok(Math.abs(current.form.height-empty.form.height)<=1);assert.equal(await input.getAttribute('wrap'),'off');
    for(const key of ['plus','send'])assert.ok(Math.abs(current[key].y+current[key].height/2-(current.input.y+current.input.height/2))<=3,JSON.stringify(current));
  }
  await input.fill('第一行\n第二行\n第三行');const expanded=await geometry();assert.ok(expanded.input.height>=empty.input.height+35);
  await input.fill(Array(20).fill('显式换行后的输入').join('\n'));assert.ok((await geometry()).input.height<=144);
  await input.fill('');assert.ok(Math.abs((await geometry()).form.height-empty.form.height)<=1);checks.push('空白、短单行和长单行保持一行；显式换行增高，删除后收回');
  await page.getByRole('button',{name:'添加附件与更多选项',exact:true}).click();assert.ok(await page.locator('#composer-menu').isVisible());assert.ok(await page.locator('#composer-menu .composer-voice').isVisible());await page.getByRole('button',{name:'添加附件与更多选项',exact:true}).click();
  const before=await geometry();assert.ok(before.note.height<=18);await page.screenshot({path:out+'/desktop.png',caret:'initial'});
  await input.focus();await page.evaluate(()=>{document.querySelector('#chat-thread').scrollTop=100;});
  assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('reading-content')),false);
  await page.mouse.move(before.thread.x+before.thread.width/2,before.thread.y+100);await page.mouse.wheel(0,240);
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.chat-heading')).opacity==='0');
  const hidden=await geometry();assert.ok(Math.abs(hidden.thread.height-before.thread.height)<1);assert.ok(Math.abs(hidden.thread.y-before.thread.y)<1);await page.screenshot({path:out+'/reading.png',caret:'initial'});
  // Exercise the application's own scroll handler. Importing the source file
  // here would create a different WeakMap instance when the app is bundled.
  const beforeJump=await page.locator('#chat-thread').evaluate(node=>node.scrollTop);
  await page.locator('#chat-jump-latest').click();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.ok(Math.abs(await page.locator('#chat-thread').evaluate(node=>node.scrollTop)-beforeJump)>1,'The real jump control must actually move to the latest reply');
  assert.equal(await page.locator('.chat-heading').evaluate(n=>getComputedStyle(n).opacity),'0','The application scroll after a real reading gesture must not reopen the heading');
  const frameHeading=page.frameLocator('iframe.openui-frame').locator('h1,h2,h3,p').first();await frameHeading.waitFor();const readingTarget=await frameHeading.boundingBox();await page.mouse.move(readingTarget.x+Math.min(80,readingTarget.width/2),readingTarget.y+readingTarget.height/2);
  await page.mouse.wheel(0,-100);await page.waitForFunction(()=>getComputedStyle(document.querySelector('.chat-heading')).opacity==='1');
  await page.mouse.wheel(0,180);await page.waitForFunction(()=>getComputedStyle(document.querySelector('.chat-heading')).opacity==='0');
  await page.locator('#chat-thread').evaluate(n=>new Promise(resolve=>{let top=n.scrollTop,changed=performance.now();const probe=()=>{if(n.scrollTop!==top){top=n.scrollTop;changed=performance.now();}if(performance.now()-changed>=150)resolve();else requestAnimationFrame(probe);};requestAnimationFrame(probe);}));
  const stable=await page.locator('#chat-thread').evaluate(n=>({top:n.scrollTop,height:n.clientHeight,y:n.getBoundingClientRect().y}));
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.chat-heading')).opacity==='1',{}, {timeout:3500});
  assert.deepEqual(await page.locator('#chat-thread').evaluate(n=>({top:n.scrollTop,height:n.clientHeight,y:n.getBoundingClientRect().y})),stable,'Idle reveal must never move the reader or change its scroll position');
  await page.mouse.wheel(0,180);await page.waitForFunction(()=>getComputedStyle(document.querySelector('.chat-heading')).opacity==='0');
  await input.click();await page.waitForFunction(()=>getComputedStyle(document.querySelector('.chat-heading')).opacity==='1');
  checks.push('顶栏以浮层淡入淡出；显隐与空闲恢复均不改变阅读区域高度、位置或滚动锚点');
  for(const [label,width,height]of [['mobile',390,844],['keyboard',390,420],['tablet',800,700]]){
    await page.setViewportSize({width,height});
    // The visual viewport resize event can arrive after setViewportSize resolves.
    // Measure only once the app has applied that event and layout has settled.
    await page.waitForFunction(({width,height})=>innerWidth===width&&innerHeight===height&&Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--visual-height'))-height)<1,{width,height});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await input.fill('连续输入'.repeat(120));await input.focus();const size=await geometry();assertHeaderCoversReader(size);
    assert.ok(size.form.height<=60&&size.form.bottom<=height+1&&size.scroll<=width+1&&size.thread.height>90,JSON.stringify(size));
    for(const key of ['plus','send'])assert.ok(size[key].x>=0&&size[key].right<=width+1&&size[key].height>=44);
    await page.screenshot({path:out+'/'+label+'.png',caret:'initial'});
  }checks.push('手机、平板和键盘高度保持一行，触控按钮可达，无页面横向溢出');
  await input.fill('');await page.locator('#composer-file-input').setInputFiles({name:'布局验收.txt',mimeType:'text/plain',buffer:Buffer.from('用于布局检查的合成附件。')});
  await page.locator('.composer-attachment.ready').waitFor();const attached=await geometry();assert.ok(attached.form.height>empty.form.height);assert.ok(attached.form.bottom<=700+1);
  await page.locator('.attachment-remove').click();await page.locator('.composer-attachment').waitFor({state:'detached'});assert.ok((await geometry()).form.height<=60);checks.push('附件独立占用内容行，移除后收回；菜单与发送控件不受压缩影响');
  const current=await (await api.get('/api/conversations/'+chat.id)).json();
  const upload=await api.post('/api/conversations/'+chat.id+'/sources',{headers,multipart:{
    version:String(current.version),files:{name:'合成预览.png',mimeType:'image/png',buffer:await readFile('static/assets/campus-notice-icon-v4-64.png')},
  }});
  assert.equal(upload.status(),200,await upload.text());
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('#content:not([inert]) .materials-toggle').click();
  const thumbnail=page.locator('#material-list .material-thumbnail');
  await thumbnail.waitFor();
  await page.waitForFunction(()=>document.querySelector('#material-list .material-thumbnail')?.naturalWidth>0);
  await thumbnail.click();
  await page.locator('#dialog[open]').waitFor();
  await page.keyboard.press('Escape');
  checks.push('真实图片材料在列表中以缩略图显示，点击可打开原有预览');

  await page.goto(origin+'/#chat/new');
  await page.locator('#content:not([inert]) .chat-welcome-doodle').waitFor();
  await page.waitForFunction(()=>document.querySelector('.chat-welcome-doodle')?.naturalWidth>0);
  await page.locator('.recent-chats > summary').click();
  for(const width of [320,390,814,1171]){
    await page.setViewportSize({width,height:871});
    await page.waitForFunction(width=>innerWidth===width,width);
    const layout=await page.evaluate(()=>{
      const rect=selector=>document.querySelector(selector).getBoundingClientRect();
      const center=selector=>{const box=rect(selector);return box.left+box.width/2;};
      return {
        thread:center('#chat-thread'),
        welcome:['.chat-welcome-doodle','.chat-welcome h2','.scene-choices','.recent-chats'].map(center),
        visibleIcons:[...document.querySelectorAll('.scene-choice > svg')].every(svg=>svg.getBoundingClientRect().width>0),
        toggleRight:rect('.workspace-chrome-toggle').right,titleLeft:rect('#conversation-title').left,
        toggleCenter:(rect('.workspace-chrome-toggle').top+rect('.workspace-chrome-toggle').bottom)/2,
        headingCenter:(rect('.chat-heading').top+rect('.chat-heading').bottom)/2,
      };
    });
    assert.ok(layout.welcome.every(center=>Math.abs(center-layout.thread)<3),JSON.stringify({width,...layout}));
    assert.ok(layout.visibleIcons&&layout.toggleRight<=layout.titleLeft&&Math.abs(layout.toggleCenter-layout.headingCenter)<2,JSON.stringify({width,...layout}));
    if(width===390||width===1171)await page.screenshot({path:out+'/welcome-'+width+'.png',caret:'hide'});
  }
  checks.push('最近对话展开后，插画、标题、快捷入口和列表仍共用中线，顶栏图标在四种宽度下可见且无碰撞');
  await page.getByRole('button',{name:'历史对话',exact:true}).click();
  const history=page.locator('#dialog .history-workspace');
  await history.locator('.history-chat').first().waitFor();
  const compact=await history.evaluate(n=>({entries:n.querySelectorAll('.history-chat').length,height:n.closest('dialog').getBoundingClientRect().height}));
  if(compact.entries<=4)assert.ok(compact.height<360,JSON.stringify(compact));
  await history.getByRole('button',{name:'筛选',exact:true}).click();
  await history.getByLabel('关键词匹配范围').selectOption('materials');
  await history.locator('#chat-history-search').fill('合成预览');
  await history.locator('#chat-history-search').press('Enter');
  const hit=history.locator(`.history-chat[href="#chat/${chat.id}"]`).filter({hasText:'合成预览.png'});
  await hit.waitFor();
  assert.equal(await hit.getAttribute('href'),'#chat/'+chat.id);
  await history.getByLabel('搜索历史对话材料').selectOption('without-materials');
  await history.getByText('没找到匹配的对话').waitFor();
  await history.getByRole('button',{name:'移除筛选：无材料'}).click();
  await hit.waitFor();
  checks.push('历史对话可按材料名查找，并可叠加和移除有无材料筛选');
  assert.deepEqual(errors,[]);const report={passed:true,browser:name,checks,emptyComposerHeight:empty.form.height,expandedInputHeight:expanded.input.height,floatingHeaderHeight:hidden.header.height,footnoteHeight:before.note.height,errors};await writeFile(out+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}catch(error){await page.screenshot({path:out+'/failure.png',caret:'initial'}).catch(()=>{});await writeFile(out+'/report.json',JSON.stringify({passed:false,error:String(error),checks,errors},null,2));throw error;}
finally{await context.close();await browser.close();await api.dispose();}
