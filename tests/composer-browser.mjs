import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {chromium,request} from 'playwright';

const origin='http://127.0.0.1:8793',out='artifacts/composer-browser';await mkdir(out,{recursive:true});
const login=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await login.post('/api/auth/login',{data:{username:'agent-preview',password:'AgentPreviewFixture2026!'}})).status(),200);
const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{}),args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+resolve('artifacts/composer-fixtures/tone.wav')]});
const context=await browser.newContext({storageState:await login.storageState(),viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
let concurrent=0,peak=0;
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
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844],['keyboard',390,420]]){
    await page.setViewportSize({width,height});await page.locator('#chat-input').focus();
    await page.waitForFunction(()=>document.querySelector('#chat-input').getBoundingClientRect().bottom<=innerHeight+1);
    const sizes=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,composer:document.querySelector('#chat-composer').getBoundingClientRect().bottom,thread:document.querySelector('#chat-thread').getBoundingClientRect().height}));
    assert.ok(sizes.scroll<=sizes.width+1&&sizes.composer<=height+1&&sizes.thread>50,JSON.stringify(sizes));
    await page.screenshot({path:`${out}/${name}.png`,animations:'disabled'});checks.push(`${name}: 无横向溢出，输入区与对话区可用`);
  }
  await page.setViewportSize({width:1100,height:850});
  await page.evaluate(async()=>{
    const {dictate}=await import('/static/dictation.js');window.__speechCalls=[];window.__speechErrors=[];
    await dictate(document.querySelector('#chat-input'),document.querySelector('.composer-voice'),{
      ask:async()=>true,toast:x=>window.__speechErrors.push(x),api:async(path,options)=>{
        if(path==='/speech/config')return {configured:true,max_recording_seconds:60};
        const blob=options.body.get('audio'),header=new Uint8Array(await blob.arrayBuffer());
        window.__speechCalls.push({size:blob.size,header:String.fromCharCode(...header.slice(0,4))});
        await new Promise(r=>setTimeout(r,180));return {text:window.__speechCalls.length===1?'':'第 '+window.__speechCalls.length+' 段合成转写'};
      }});
  });
  await page.waitForFunction(()=>document.querySelector('#chat-input').value.includes('合成转写'),{},{timeout:18000});
  assert.equal(await page.locator('.dictation-panel').count(),1);
  assert.equal(await page.locator('.dictation-panel button').count(),1);
  assert.equal(await page.locator('#chat-composer .composer-voice').count(),1);
  assert.equal(await page.locator('.composer-voice').getAttribute('aria-pressed'),'true');
  await page.locator('#chat-input').fill('我在录音中手工补充的内容');
  await page.waitForFunction(()=>document.querySelector('#chat-input').value.includes('合成转写'),{},{timeout:12000});
  assert.match(await page.locator('#chat-input').inputValue(),/^我在录音中手工补充/);
  await page.screenshot({path:out+'/recording.png',animations:'disabled'});
  await page.getByRole('button',{name:'结束录音',exact:true}).last().click();
  await page.locator('.dictation-panel').waitFor({state:'hidden',timeout:12000});
  assert.equal(await page.locator('.composer-entry .composer-voice').count(),1);
  const audio=await page.evaluate(()=>({calls:window.__speechCalls,errors:window.__speechErrors}));
  assert.ok(audio.calls.length>=2&&audio.calls.every(x=>x.header==='RIFF'&&x.size>100));assert.deepEqual(audio.errors,[]);
  checks.push('真实 AudioWorklet 采集模拟麦克风：录音未结束即出现多段转写，保留手工输入，结束后释放录音界面（转写服务为合成夹具）');
  await page.locator('#chat-input').fill('重试前已经写好的内容');
  await page.evaluate(async()=>{
    const {dictate}=await import('/static/dictation.js');let attempts=0;window.__retryNotices=[];
    await dictate(document.querySelector('#chat-input'),document.querySelector('.composer-voice'),{
      ask:async()=>true,toast:text=>window.__retryNotices.push(text),api:async path=>{
        if(path==='/speech/config')return {configured:true,max_recording_seconds:60};
        if(++attempts===1)throw Error('合成转写故障');
        return {text:'重试后恢复的转写'};
      }});
  });
  await page.getByRole('button',{name:'重试转写（Esc 取消剩余录音）',exact:true}).waitFor({timeout:18000});
  assert.equal(await page.locator('.dictation-panel button').count(),1);
  assert.equal(await page.locator('#chat-input').inputValue(),'重试前已经写好的内容');
  await page.getByRole('button',{name:'重试转写（Esc 取消剩余录音）',exact:true}).click();
  await page.locator('.dictation-panel').waitFor({state:'hidden',timeout:12000});
  assert.match(await page.locator('#chat-input').inputValue(),/^重试前已经写好的内容[\s\S]*重试后恢复的转写/);
  assert.equal(await page.locator('#chat-composer .composer-voice').count(),1);
  checks.push('空分段不报整段失败；故障后保留已写文字，原位唯一录音按钮完成重试');
  assert.deepEqual(errors,[]);await writeFile(out+'/results.json',JSON.stringify({synthetic:true,checks,errors,peak},null,2));console.log(JSON.stringify({checks,errors,peak},null,2));
}finally{await browser.close();await login.dispose();}
