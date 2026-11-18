// Replay two separately generated, reviewed answers through the signed-in application.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium,firefox,webkit,request} from 'playwright';
import {browserOverride} from './browser-runtime.mjs';

const name=process.env.OPENUI_BROWSER||'chromium',engine={chromium,firefox,webkit}[name];
const out=process.env.OPENUI_ARTIFACT_DIR||'artifacts/canvas-browser/'+name,origin='http://127.0.0.1:8794';
await mkdir(out,{recursive:true});
const api=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await api.post('/api/auth/login',{data:{username:'openui-preview',password:'OpenUIFixture2026!'}})).status(),200);
const session=await api.storageState();
const browser=await engine.launch({headless:true,...browserOverride(engine),...(process.platform==='win32'&&name==='chromium'?{channel:'msedge'}:{})});
const contexts=[],checks=[],sizes=[],errors=[];
async function fresh(){
  const c=await browser.newContext({storageState:session,viewport:{width:1440,height:1000},reducedMotion:'reduce'});contexts.push(c);
  const p=await c.newPage();p.setDefaultTimeout(12000);p.on('pageerror',e=>errors.push(String(e)));return p;
}
const page=await fresh();
async function canvas(p){
  const host=p.locator('.message-assistant').last(),element=host.locator('iframe.openui-frame');
  await element.waitFor();await host.locator('.openui-status').waitFor({state:'hidden'});
  return {host,element,frame:element.contentFrame()};
}
async function open(p,id){await p.goto(origin+'/#chat/'+id);return canvas(p);}
async function save(p){
  const target=p.getByRole('button',{name:'保存互动进度',exact:true});
  // Scroll as a reader would, before pressing a control below a long, expanded reply.
  const area=await p.locator('#chat-thread').boundingBox();
  await p.mouse.move(area.x+area.width-24,area.y+area.height*.6);await p.mouse.wheel(0,2500);
  await target.focus();
  await target.scrollIntoViewIfNeeded();await p.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const [response]=await Promise.all([p.waitForResponse(r=>r.url().endsWith('/ui-state')&&r.request().method()==='PUT'),target.click()]);
  assert.equal(response.status(),200,await response.text());
  await p.locator('.gu-save-feedback').filter({hasText:'互动进度已保存'}).waitFor();
}
async function captureCanvas(p,id,width,path){
  const saved=await (await api.get('/api/conversations/'+id)).json();
  const msg=saved.messages.findLast(m=>m.role==='assistant'),index=msg.parts.findIndex(part=>part.kind==='ui');
  const isolated=await p.context().newPage();
  try{
    await isolated.setViewportSize({width,height:1800});await isolated.goto(origin+'/privacy');
    await isolated.evaluate(async({spec,snapshot})=>{
      const {SandboxRenderer}=await import('/static/genui/openui.js');
      const container=document.createElement('div');
      document.body.replaceChildren(container);document.body.style.cssText='margin:0;padding:0;display:block;width:100%';
      const renderer=new SandboxRenderer(container,spec,{snapshot,readOnly:true});
      container.style.cssText='width:100%;margin:0';renderer.frame.style.cssText='display:block;width:100%;border:0;margin:0';
    },{spec:msg.parts[index].spec,snapshot:msg.genui.snapshots[index]});
    const frame=isolated.locator('iframe.openui-frame');await frame.waitFor();await isolated.locator('.openui-status').waitFor({state:'hidden'});
    await frame.screenshot({path,caret:'initial'});
  }finally{await isolated.close();}
}
async function layouts(p,id,label,width){
  const {element,frame}=await canvas(p);
  for(const [device,w,h] of [['desktop',1440,1000],['tablet',820,960],['phone',390,844],['narrow',320,650],['keyboard',390,420]]){
    await p.setViewportSize({width:w,height:h});await element.scrollIntoViewIfNeeded();
    const box=await element.boundingBox();
    const shell=await p.evaluate(()=>({page:document.documentElement.scrollWidth,viewport:innerWidth}));
    const inner=await frame.locator('#openui-root').evaluate(n=>({page:document.documentElement.scrollWidth,viewport:innerWidth,content:n.scrollHeight}));
    assert.ok(shell.page<=shell.viewport+1 && inner.page<=inner.viewport+1,JSON.stringify({shell,inner,w,label}));
    assert.ok(box.x>=-1 && box.x+box.width<=w+1 && box.width<=width+1 && box.width>=Math.min(w*.55,520),JSON.stringify({box,w,label}));
    assert.ok(box.height+2>=inner.content,JSON.stringify({box,inner,label}));
    if(label==='timeline'){
      const contained=await frame.locator('#blk-tidy').evaluate(n=>n.offsetTop+n.offsetHeight<=n.offsetParent.clientHeight+1&&[...n.children].every(c=>c.getBoundingClientRect().bottom<=n.getBoundingClientRect().bottom+1));
      assert.ok(contained,'last task and its wrapped text must fit the track');
    }
    sizes.push({label,device,screen:w,canvas:Math.round(box.width),height:Math.round(box.height),x:Math.round(box.x)});
    if(['desktop','phone'].includes(device)){
      await captureCanvas(p,id,Math.round(box.width),out+'/'+label+'-'+device+'.png');
      await p.screenshot({path:out+'/'+label+'-'+device+'-page.png',caret:'initial'});
    }
  }
  await p.setViewportSize({width:1440,height:1000});
  checks.push(label+' responsive document and host bounds at five viewport sizes');
}
try{
  const result=await (await api.get('/api/conversations')).json();
  const chats=Array.isArray(result)?result:result.items||result.conversations;
  const notice=chats.find(x=>x.title.includes('更正')),timeline=chats.find(x=>x.title.includes('时间轴'));assert.ok(notice&&timeline);
  let {frame}=await open(page,notice.id);
  await frame.locator('label[for=view-changed]').click();
  assert.equal(await frame.locator('#list .row-head').count(),2);
  await frame.locator('label[for=view-all]').click();
  assert.equal(await frame.locator('#list .row-head').count(),3);
  await frame.locator('#list .row-head').first().click();
  const text=await frame.locator('#list').innerText();
  for(const value of ['17:00','12:00','二年级','201','305'])assert.ok(text.includes(value),value);
  assert.ok(await frame.locator('#list [data-citation]').count()>0);
  checks.push('notice filters two changes or all three fields, expands real source text and produces source buttons');
  await save(page);await page.reload();frame=(await canvas(page)).frame;assert.equal(await frame.locator('#list .row-head').count(),3);
  await layouts(page,notice.id,'notice',860);
  ({frame}=await open(page,timeline.id));
  const reset=frame.locator('#btn-reset'),draft=frame.locator('#blk-draft'),value=draft.locator('.b-time');
  await reset.click();assert.equal(await value.innerText(),'09:00–09:30');
  await draft.press('ArrowRight');assert.equal(await value.innerText(),'09:15–09:45');
  const pos=await draft.boundingBox(),track=await frame.locator('#tl-track').boundingBox();
  const x=pos.x+pos.width/2,y=pos.y+pos.height/2;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+track.width/6,y,{steps:12});await page.mouse.up();
  assert.equal(await value.innerText(),'09:45–10:15');assert.match(await frame.locator('#warn').innerText(),/重叠/);
  await page.reload();frame=(await canvas(page)).frame;
  assert.equal(await frame.locator('#blk-draft .b-time').innerText(),'09:45–10:15');
  checks.push('timeline keyboard and real pointer drag snap in 15-minute steps; overlap warning and per-reply tab refresh work');
  await save(page);
  const other=await fresh();const restored=await open(other,timeline.id);
  assert.equal(await restored.frame.locator('#blk-draft .b-time').innerText(),'09:45–10:15');
  await restored.frame.locator('#blk-draft').press('End');assert.equal(await restored.frame.locator('#blk-draft .b-time').innerText(),'11:30–12:00');
  await restored.frame.locator('#btn-reset').click();assert.equal(await restored.frame.locator('#blk-draft .b-time').innerText(),'09:00–09:30');
  checks.push('saved timeline restores in independent browser storage; keyboard bounds and author-provided reset work');
  await layouts(page,timeline.id,'timeline',880);
  assert.deepEqual(errors,[]);await writeFile(out+'/report.json',JSON.stringify({passed:true,name,checks,sizes,errors},null,2));console.log(JSON.stringify({name,checks,sizes}));
}catch(error){
  await page.screenshot({path:out+'/failure.png',caret:'initial'}).catch(()=>{});
  await writeFile(out+'/report.json',JSON.stringify({passed:false,error:String(error),checks,sizes,errors},null,2));throw error;
}finally{await Promise.all(contexts.map(c=>c.close()));await browser.close();await api.dispose();}
