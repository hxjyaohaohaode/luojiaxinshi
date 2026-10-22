import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {chromium,request} from 'playwright';

const origin='http://127.0.0.1:8793',out='artifacts/reference-fusion/browser';
await mkdir(out,{recursive:true});
const api=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await api.post('/api/auth/login',{data:{username:'agent-preview',password:'AgentPreviewFixture2026!'}})).status(),200);
const csrf=(await (await api.get('/api/session')).json()).csrf;
const headers={'X-CSRF-Token':csrf};
let chat=await (await api.post('/api/conversations',{headers,data:{title:'媒体融合验收'}})).json();
const upload=await api.post(`/api/conversations/${chat.id}/sources`,{headers,multipart:{version:String(chat.version),files:{name:'合成演示.webm',mimeType:'video/webm',buffer:await readFile('static/assets/genui-demo.webm')}}});
assert.equal(upload.status(),200,await upload.text());chat=await upload.json();
const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
const context=await browser.newContext({storageState:await api.storageState(),viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];
page.on('pageerror',e=>errors.push(String(e)));
try{
  await page.goto(`${origin}/#chat/${chat.id}`);
  await page.locator('#chat-input').fill('融合媒体验收：在回复中播放我上传的视频，无需分析视频内容。');
  await page.locator('#chat-input').press('Enter');
  const reply=page.locator('.message-assistant').last(),video=reply.locator('.genui video');
  await reply.locator('.genui[data-complete=true]').waitFor({timeout:30000});
  assert.equal(await reply.locator('.gu-error').count(),0);
  await video.waitFor();
  await video.evaluate(v=>new Promise((resolve,reject)=>{
    if(v.readyState>=1)return resolve();
    v.addEventListener('loadedmetadata',resolve,{once:true});
    v.addEventListener('error',()=>reject(new Error(v.error?.message||'media failed')),{once:true});v.load();
  }));
  const src=await video.getAttribute('src');
  assert.ok(src.includes(`/api/conversations/${chat.id}/sources/${chat.sources[0].id}/download`),src);
  assert.ok(await video.evaluate(v=>v.videoWidth>0 && Number.isFinite(v.duration)));
  await video.evaluate(async v=>{v.muted=true;await v.play();});
  await page.waitForFunction(()=>document.querySelector('.message-assistant .genui video')?.currentTime>0);
  await video.evaluate(v=>v.pause());
  checks.push('真实上传 → Agent 宿主资源 → 原消息视频组件：私有资源实际解码并播放');
  const range=await api.get(src,{headers:{Range:'bytes=0-31'}});
  assert.equal(range.status(),206);assert.equal((await range.body()).length,32);
  checks.push('已鉴权媒体 Range 请求返回 206 和准确字节段');
  await page.reload();await video.waitFor();assert.equal(await video.getAttribute('src'),src);
  await video.evaluate(async v=>{v.muted=true;await v.play();});
  await page.waitForFunction(()=>document.querySelector('.message-assistant .genui video')?.currentTime>0.15);
  await video.evaluate(v=>v.pause());
  assert.equal(await reply.locator('div.gu-video').evaluate(n=>getComputedStyle(n).backgroundColor),'rgba(0, 0, 0, 0)');
  checks.push('刷新原对话后媒体引用保持一致');
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844],['narrow',320,720],['keyboard',390,420]]){
    await page.setViewportSize({width,height});
    await page.waitForFunction(()=>document.querySelector('#chat-input').getBoundingClientRect().bottom<=innerHeight+1);
    await page.locator('#chat-thread').evaluate(n=>n.scrollTop=n.scrollHeight);
    const state=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,input:document.querySelector('#chat-input').getBoundingClientRect().bottom,nested:[...document.querySelectorAll('#chat-thread .genui *')].filter(n=>/auto|scroll/.test(getComputedStyle(n).overflowY)&&n.scrollHeight>n.clientHeight+2).length}));
    assert.ok(state.scroll<=state.width+1,JSON.stringify(state));assert.ok(state.input<=height+1);assert.equal(state.nested,0);
    await page.screenshot({path:`${out}/${name}.png`,animations:'disabled'});
    checks.push(`${name} ${width}×${height}：输入可见、无横向溢出或内容嵌套滚动`);
  }
  assert.deepEqual(errors,[]);
  await writeFile(out+'/results.json',JSON.stringify({synthetic_provider:true,real_local_media:true,checks,errors},null,2));
  console.log(JSON.stringify({checks,errors},null,2));
}finally{await browser.close();await api.dispose();}
