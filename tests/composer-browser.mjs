import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {chromium,request} from 'playwright';

const origin='http://127.0.0.1:8793',out='artifacts/composer-browser';await mkdir(out,{recursive:true});
const login=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await login.post('/api/auth/login',{data:{username:'agent-preview',password:'AgentPreviewFixture2026!'}})).status(),200);
const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{}),args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+resolve('artifacts/composer-fixtures/tone.wav')]});
const context=await browser.newContext({serviceWorkers:'block',storageState:await login.storageState(),viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
let concurrent=0,peak=0;
const observations={geometry:[],events:[],dropped_events:0};
async function recordGeometry(phase){
  const data=await page.evaluate(phase=>window.__composerGeometry?.capture(phase)??null,phase);
  if(!data)return null;
  observations.geometry.push(data.snapshot);observations.events=data.events;observations.dropped_events=data.dropped_events;
  // Keep the pre-assertion state even when a later geometry assertion fails.
  await writeFile(out+'/geometry.json',JSON.stringify({synthetic:true,observations},null,2));
  return data.snapshot;
}
function assertRecordingGeometry(snapshot){
  assert.ok(snapshot,'Recording geometry was captured');
  assert.equal(snapshot.viewport.width,1100,'Use the original recording viewport');
  assert.equal(snapshot.viewport.height,850,'Use the original recording viewport');
  const context=JSON.stringify({phase:snapshot.phase,viewport:snapshot.viewport,shell:snapshot.shell});
  assert.ok(Math.abs(snapshot.viewport.scrollX)<=1,`Recording must not shift the document horizontally: ${context}`);
  for(const node of snapshot.ancestors.filter(node=>node.structural)){
    assert.ok(Math.abs(node.scrollLeft)<=1,`Recording must not shift a structural scroll ancestor: ${JSON.stringify({phase:snapshot.phase,node})}`);
  }
  const workspace=snapshot.targets['.workspace'],sidebar=snapshot.targets['.sidebar'];
  assert.ok(workspace&&workspace.rect.width>0,`Workspace exists: ${context}`);
  if(sidebar&&sidebar.visibility!=='hidden'&&sidebar.display!=='none'&&sidebar.rect.width>0){
    assert.ok(workspace.rect.left>=sidebar.rect.right-1,`Workspace must remain beside the visible sidebar: ${JSON.stringify({phase:snapshot.phase,workspace,sidebar})}`);
  }
  for(const selector of ['.chat-heading','#chat-composer','#chat-input','#chat-composer .composer-plus','.dictation-panel','.dictation-time','.dictation-panel > button']){
    const target=snapshot.targets[selector];
    assert.ok(target&&target.rect.width>0,`Recording control exists: ${selector}`);
    assert.ok(target.rect.left>=workspace.rect.left-1&&target.rect.right<=workspace.rect.right+1,`Recording control must stay inside the workspace: ${JSON.stringify({phase:snapshot.phase,selector,target,workspace})}`);
    assert.ok(target.visible_width>=target.rect.width-1,`Recording control must not be clipped by an ancestor: ${JSON.stringify({phase:snapshot.phase,selector,target})}`);
  }
}
await page.route('**/api/conversations/*/sources',async route=>{
  if(route.request().method()!=='POST')return route.continue();
  concurrent++;peak=Math.max(peak,concurrent);
  try{await new Promise(r=>setTimeout(r,200));const response=await route.fetch();await route.fulfill({response});}finally{concurrent--;}
});
try{
  await page.goto(origin+'/#chat/new');await page.locator('#chat-input').waitFor();
  const files=[];
  for(let i=0;i<6;i++)files.push({name:`工程图片-${i}.png`,mimeType:'image/png',buffer:await readFile(`artifacts/composer-fixtures/image-${i}.png`)});
  files.push({name:'准备说明.txt',mimeType:'text/plain',buffer:Buffer.from('工程样例：先建立项目，再准备报告提纲。')});
  files.push({name:'声音.wav',mimeType:'audio/wav',buffer:await readFile('artifacts/composer-fixtures/tone.wav')});
  files.push({name:'短片.mp4',mimeType:'video/mp4',buffer:await readFile('artifacts/composer-fixtures/clip.mp4')});
  await page.locator('#composer-file-input').setInputFiles(files);
  await page.waitForFunction(()=>document.querySelectorAll('.composer-attachment.ready').length===9,{},{timeout:60000});
  assert.equal(peak,3);assert.equal(await page.locator('.composer-attachment.error').count(),0);
  await page.waitForFunction(()=>[...document.querySelectorAll('.composer-attachment img')].every(img=>img.complete&&img.naturalWidth>0));
  checks.push('9 份图片、文字、音频和视频同时加入，实际上传峰值 3，全部就绪');
  await page.locator('#chat-input').fill('请核对这批工程材料');
  await page.screenshot({path:out+'/attachments-desktop.png',animations:'disabled'});
  await page.locator('#chat-input').press('Enter');
  await page.locator('.message-assistant:not(.is-streaming) .message-content').filter({hasText:'合成验收回复'}).waitFor({timeout:30000});
  assert.equal(await page.locator('.message-user .message-attachment').count(),9);
  await page.waitForFunction(()=>[...document.querySelectorAll('.message-user img')].every(img=>img.complete&&img.naturalWidth>0));
  await page.reload();await page.locator('.message-user .message-attachment').first().waitFor();
  assert.equal(await page.locator('.message-user .message-attachment').count(),9);
  checks.push('附件跟随发送的用户消息保存，刷新后保留全部 9 份关联');
  for(const action of ['toggle-materials','toggle-materials']){
    await page.locator('.chat-heading [data-chat-action="'+action+'"]').click();
    await page.waitForTimeout(220);
    const alignment=await page.evaluate(()=>{const area=document.querySelector('#chat-thread').getBoundingClientRect(),user=document.querySelector('.message-user').getBoundingClientRect();return {area:area.right,user:user.right,gap:area.right-user.right};});
    assert.ok(alignment.gap<42&&alignment.gap>=0,JSON.stringify(alignment));
  }
  checks.push('材料面板开合后用户消息随容器右侧移动');
  const stable=await page.evaluate(async()=>{
    const {ConversationView}=await import('/static/genui/chat-presenter.js');const host=document.createElement('div');document.body.append(host);
    const view=new ConversationView(host,{feature:{enabled:true},sources:[],arrangements:[],tasks:[]});
    const message={id:'preview',role:'assistant',status:'processing',content:'',_preview:'已经展示的完整预览，不能倒退。'};
    view.draw([message]);const before=host.querySelector('.message-content').textContent;
    message._liveParts=[{kind:'text',text:'已'}];view.draw([message]);const after=host.querySelector('.message-content').textContent;
    message.status='complete';delete message._preview;message._liveParts=[{kind:'text',text:'经过核验的最终内容。'}];view.draw([message]);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
    const final=host.querySelector('.message-content').textContent;view.dispose();host.remove();return {before,after,final};
  });assert.equal(stable.before,stable.after);assert.match(stable.final,/最终内容/);checks.push('最终流的首段到达时不清空或倒退预览，完成后切换核验结果');
  await page.evaluate(()=>{
    const started=performance.now(),events=[];let dropped=0;
    const structuralSelector='html,body,#app,.shell,.workspace,#content,#chat-workspace,.chat-main,.chat-reading-area';
    const selectors=['html','body','#app','.shell','.sidebar','.workspace','#content','#chat-workspace','#chat-materials','.reply-sources-panel','.chat-main','.chat-reading-area','#chat-thread','.chat-heading','#chat-composer','#chat-input','#chat-composer .composer-plus','#composer-menu','.dictation-panel','.dictation-time','.dictation-panel > button'];
    const identity=node=>node instanceof Element?node.tagName.toLowerCase()+(node.id?'#'+node.id:'')+(node.classList.length?'.'+[...node.classList].join('.'):''):String(node?.nodeName||'window');
    const rectangle=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
    const describe=node=>{
      const style=getComputedStyle(node);
      return {identity:identity(node),structural:node.matches(structuralSelector),rect:rectangle(node),scrollLeft:node.scrollLeft,scrollTop:node.scrollTop,scrollWidth:node.scrollWidth,scrollHeight:node.scrollHeight,clientLeft:node.clientLeft,clientWidth:node.clientWidth,clientHeight:node.clientHeight,overflowX:style.overflowX,overflowY:style.overflowY,paddingLeft:style.paddingLeft,paddingRight:style.paddingRight,borderLeftWidth:style.borderLeftWidth,borderRightWidth:style.borderRightWidth,position:style.position,transform:style.transform,display:style.display,visibility:style.visibility,hidden:node.hidden,ariaExpanded:node.getAttribute('aria-expanded'),gridTemplateColumns:style.gridTemplateColumns};
    };
    const capture=phase=>{
      const targets={},ancestors=new Set(),visual=window.visualViewport;
      for(const selector of selectors){
        const node=document.querySelector(selector);if(!node)continue;
        const target=describe(node),clip=[];let left=Math.max(0,target.rect.left),right=Math.min(innerWidth,target.rect.right);
        for(let parent=node.parentElement;parent;parent=parent.parentElement){
          ancestors.add(parent);const style=getComputedStyle(parent);
          if(['auto','scroll','hidden','clip'].includes(style.overflowX)){
            const r=rectangle(parent),edge=r.left+parent.clientLeft,limit=edge+parent.clientWidth;
            left=Math.max(left,edge);right=Math.min(right,limit);clip.push({identity:identity(parent),left:edge,right:limit,scrollLeft:parent.scrollLeft,overflowX:style.overflowX});
          }
        }
        ancestors.add(node);targets[selector]={...target,visible_left:left,visible_right:right,visible_width:Math.max(0,right-left),clipping_ancestors:clip};
      }
      const shell=document.querySelector('.shell'),input=document.querySelector('#chat-input');
      const snapshot={phase,elapsed_ms:performance.now()-started,viewport:{width:innerWidth,height:innerHeight,scrollX,scrollY,devicePixelRatio,scrollingElement:identity(document.scrollingElement),visualViewport:visual?{width:visual.width,height:visual.height,offsetLeft:visual.offsetLeft,offsetTop:visual.offsetTop,pageLeft:visual.pageLeft,pageTop:visual.pageTop,scale:visual.scale}:null},shell:{classes:shell?.className,sidebarWidth:shell?getComputedStyle(shell).getPropertyValue('--sidebar-width'):null,sidebarOpenWidth:shell?getComputedStyle(shell).getPropertyValue('--sidebar-open-width'):null,htmlClasses:document.documentElement.className,bodyClasses:document.body.className},activeElement:identity(document.activeElement),input:input?{length:input.value.length,selectionStart:input.selectionStart,selectionEnd:input.selectionEnd,scrollLeft:input.scrollLeft,scrollTop:input.scrollTop}:null,targets,ancestors:[...ancestors].map(describe)};
      return {snapshot,events:[...events],dropped_events:dropped};
    };
    const event=event=>{
      const node=event.target===document?document.scrollingElement:event.target;
      if(event.type==='scroll'&&(!(node instanceof Element)||!node.matches(structuralSelector+',#chat-thread,#chat-input')))return;
      if(['input','pointerdown','click'].includes(event.type)&&!node.closest?.('#chat-composer'))return;
      const value={type:event.type,elapsed_ms:performance.now()-started,target:identity(node),activeElement:identity(document.activeElement),viewport:{width:innerWidth,height:innerHeight,scrollX,scrollY},scrollOffsets:[...document.querySelectorAll(structuralSelector+',#chat-thread,#chat-input')].map(el=>({identity:identity(el),left:el.scrollLeft,top:el.scrollTop}))};
      if(events.length<256)events.push(value);else dropped++;
    };
    for(const name of ['scroll','focusin','input','pointerdown','click'])document.addEventListener(name,event,true);
    window.addEventListener('resize',event);window.visualViewport?.addEventListener('resize',event);
    window.__composerGeometry={capture};
  });
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844],['keyboard',390,420]]){
    await page.setViewportSize({width,height});await page.locator('#chat-input').focus();
    await page.waitForFunction(()=>document.querySelector('#chat-input').getBoundingClientRect().bottom<=innerHeight+1);
    const sizes=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,composer:document.querySelector('#chat-composer').getBoundingClientRect().bottom,thread:document.querySelector('#chat-thread').getBoundingClientRect().height}));
    assert.ok(sizes.scroll<=sizes.width+1&&sizes.composer<=height+1&&sizes.thread>50,JSON.stringify(sizes));
    await recordGeometry(name+'-after-focus');
    await page.screenshot({path:`${out}/${name}.png`,animations:'disabled'});checks.push(`${name}: 无横向溢出，输入区与对话区可用`);
  }
  await page.setViewportSize({width:1100,height:850});
  // Intercept the public speech endpoints while the real composer owns the
  // recording session. Importing source dictate() here creates a second active
  // session when the production UI is bundled, so it cannot test this button.
  const speechCalls=[];
  await page.route('**/api/speech/config',route=>route.fulfill({json:{configured:true,max_recording_seconds:60}}));
  const transcribe=async route=>{
    const request=route.request(),form=await new Response(request.postDataBuffer(),{headers:{'Content-Type':request.headers()['content-type']}}).formData();
    const blob=form.get('audio');assert.ok(blob&&typeof blob.arrayBuffer==='function');
    const header=new Uint8Array(await blob.arrayBuffer());
    speechCalls.push({size:blob.size,header:String.fromCharCode(...header.slice(0,4))});
    assert.equal(form.get('allow_external_processing'),'true');
    await new Promise(r=>setTimeout(r,180));
    await route.fulfill({json:{text:speechCalls.length===1?'':'第 '+speechCalls.length+' 段合成转写'}});
  };
  await page.route('**/api/speech/transcribe',transcribe);
  await page.evaluate(()=>{
    window.__speechErrors=[];
    window.__speechToastObserver=new MutationObserver(()=>{const toast=document.querySelector('#toast');if(toast?.matches('.visible.error'))window.__speechErrors.push(toast.textContent);});
    window.__speechToastObserver.observe(document.querySelector('#toast'),{subtree:true,childList:true,attributes:true});
  });
  await recordGeometry('before-open-composer-menu');
  await page.getByRole('button',{name:'添加附件与更多选项',exact:true}).click();
  await recordGeometry('before-start-recording');
  await page.locator('#composer-menu .composer-voice').click();
  await recordGeometry('after-start-recording-click');
  await page.waitForFunction(()=>document.querySelector('#chat-input').value.includes('合成转写'),{},{timeout:18000});
  await recordGeometry('after-first-transcript');
  assert.equal(await page.locator('#dialog').evaluate(node=>node.open),false,'Recording starts from its button without an extra application confirmation');
  assert.equal(await page.locator('.dictation-panel').count(),1);
  assert.equal(await page.locator('.dictation-panel button').count(),1);
  assert.equal(await page.locator('#chat-composer .composer-voice').count(),1);
  assert.equal(await page.locator('.composer-voice').getAttribute('aria-pressed'),'true');
  await recordGeometry('before-manual-fill');
  await page.locator('#chat-input').fill('我在录音中手工补充的内容');
  await recordGeometry('after-manual-fill');
  await page.waitForFunction(()=>document.querySelector('#chat-input').value.includes('合成转写'),{},{timeout:12000});
  assert.match(await page.locator('#chat-input').inputValue(),/^我在录音中手工补充/);
  const beforeRecordingScreenshot=await recordGeometry('before-recording-screenshot');
  await page.screenshot({path:out+'/recording.png',animations:'disabled'});
  const afterRecordingScreenshot=await recordGeometry('after-recording-screenshot');
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const recordingAfterFrames=await recordGeometry('recording-two-frames-after-screenshot');
  for(const snapshot of [beforeRecordingScreenshot,afterRecordingScreenshot,recordingAfterFrames])assertRecordingGeometry(snapshot);
  await page.getByRole('button',{name:'结束录音',exact:true}).last().click();
  await page.locator('.dictation-panel').waitFor({state:'hidden',timeout:12000});
  assert.equal(await page.locator('#composer-menu .composer-voice').count(),1);
  assert.equal(await page.locator('#chat-composer .composer-voice').count(),1);
  const speechErrors=await page.evaluate(()=>{window.__speechToastObserver.disconnect();return window.__speechErrors;});
  assert.ok(speechCalls.length>=2&&speechCalls.every(x=>x.header==='RIFF'&&x.size>100));assert.deepEqual(speechErrors,[]);
  checks.push('真实 AudioWorklet 采集模拟麦克风：录音未结束即出现多段转写，保留手工输入，结束后释放录音界面（转写服务为合成夹具）');
  await page.locator('#chat-input').fill('重试前已经写好的内容');
  await page.unroute('**/api/speech/transcribe',transcribe);
  let attempts=0;
  await page.route('**/api/speech/transcribe',route=>++attempts===1?route.fulfill({status:503,json:{detail:'合成转写故障'}}):route.fulfill({json:{text:'重试后恢复的转写'}}));
  await page.getByRole('button',{name:'添加附件与更多选项',exact:true}).click();
  await page.locator('#composer-menu .composer-voice').click();
  await page.getByRole('button',{name:'重试转写（Esc 取消剩余录音）',exact:true}).waitFor({timeout:18000});
  assert.equal(await page.locator('.dictation-panel button').count(),1);
  assert.equal(await page.locator('#chat-input').inputValue(),'重试前已经写好的内容');
  await page.getByRole('button',{name:'重试转写（Esc 取消剩余录音）',exact:true}).click();
  await page.locator('.dictation-panel').waitFor({state:'hidden',timeout:12000});
  assert.match(await page.locator('#chat-input').inputValue(),/^重试前已经写好的内容[\s\S]*重试后恢复的转写/);
  assert.equal(await page.locator('#chat-composer .composer-voice').count(),1);
  assert.ok(attempts>=2,'The public transcription endpoint receives a real retry');
  checks.push('空分段不报整段失败；故障后保留已写文字，原位唯一录音按钮完成重试');
  await recordGeometry('after-recording-retry');
  assert.deepEqual(errors,[]);await writeFile(out+'/results.json',JSON.stringify({synthetic:true,checks,errors,peak,observations},null,2));console.log(JSON.stringify({checks,errors,peak},null,2));
}catch(error){
  await recordGeometry('failure').catch(()=>{});
  const state=await page.locator('.composer-attachment').evaluateAll(nodes=>nodes.map(node=>({name:node.querySelector('.attachment-name')?.textContent,state:node.className,message:node.querySelector('.attachment-state')?.textContent}))).catch(()=>[]);
  await writeFile(out+'/failure.json',JSON.stringify({error:String(error),url:page.url(),attachments:state,expected_checks:9,complete:false,checks,errors,peak,observations},null,2));
  await page.screenshot({path:out+'/failure.png'}).catch(()=>{});throw error;
}finally{await browser.close();await login.dispose();}
