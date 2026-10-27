/** Regression cases for the five v9 browser comments. Mutations use a synthetic service only. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/frontend-v9-browser');await fs.mkdir(out,{recursive:true});
const report={fixture:'Synthetic UI and speech responses; no external provider calls',checks:[],errors:[]};
const wave=Buffer.alloc(44+16000*2*5);wave.write('RIFF');wave.writeUInt32LE(wave.length-8,4);wave.write('WAVEfmt ',8);wave.writeUInt32LE(16,16);wave.writeUInt16LE(1,20);wave.writeUInt16LE(1,22);wave.writeUInt32LE(16000,24);wave.writeUInt32LE(32000,28);wave.writeUInt16LE(2,32);wave.writeUInt16LE(16,34);wave.write('data',36);wave.writeUInt32LE(wave.length-44,40);
for(const engine of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',')){
 const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});const page=await browser.newPage({viewport:{width:1413,height:871}});page.setDefaultTimeout(10000);
 page.on('pageerror',e=>report.errors.push({engine,error:e.message}));
 const check=async(name,fn)=>{try{await fn();report.checks.push({engine,name,ok:true});}catch(e){report.checks.push({engine,name,ok:false,error:e.message});console.log('FAIL',engine,name,e.message.slice(0,350));await page.screenshot({path:path.join(out,engine+'-'+report.checks.length+'-failure.png')}).catch(()=>{});}};
 const nav=async route=>{await page.goto(origin+'/#'+route);await page.locator('#content:not([inert])').waitFor();};
 const api=(url,method='GET',json)=>page.evaluate(async({url,method,json})=>{const s=await(await fetch('/api/session')).json(),r=await fetch('/api'+url,{method,headers:{'X-Requested-With':'campus-notice','X-CSRF-Token':s.csrf,...(json?{'Content-Type':'application/json'}:{})},...(json?{body:JSON.stringify(json)}:{})});if(!r.ok)throw Error(await r.text());return r.json();},{url,method,json});
 try{
  await page.goto(origin+'/#login');await page.locator('[name=username]').fill('workflow.demo');await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
  await nav('memory');await page.locator('#memory-shell').waitFor();await page.waitForFunction(()=>!document.querySelector('.memory-tree-main')?.matches('[aria-busy=true]'));
  for(const [width,height] of [[1413,871],[1651,871],[1920,1080],[1280,720],[1024,768],[850,700],[768,1024],[390,844],[320,640]]){
   await page.setViewportSize({width,height});
   await page.waitForFunction(({width,height})=>innerWidth===width&&innerHeight===height&&Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--visual-height'))-height)<1,{width,height});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   for(const side of width>850?[180,234,380]:[234])await check(`memory fills container ${width}x${height} sidebar ${side}`,async()=>{
    await page.locator('.shell').evaluate((n,w)=>{localStorage.setItem('campus.sidebar.width',String(w));n.style.setProperty('--sidebar-width',w+'px');},side);
    const measure=()=>page.evaluate(()=>{const n=document.querySelector('#memory-shell'),p=n.parentElement,c=getComputedStyle(p),r=n.getBoundingClientRect(),b=p.getBoundingClientRect();return{w:r.width,available:p.clientWidth-parseFloat(c.paddingLeft)-parseFloat(c.paddingRight),right:r.right,parent:b.right,bottom:r.bottom,limit:b.bottom-parseFloat(c.paddingBottom),overflow:document.documentElement.scrollWidth>innerWidth+1};});
    await page.locator('.shell').evaluate(n=>{n.getBoundingClientRect();return Promise.all(n.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});const before=await measure();assert.ok(Math.abs(before.w-before.available)<2,JSON.stringify(before));assert.ok(Math.abs(before.bottom-before.limit)<2,JSON.stringify(before));assert.equal(before.overflow,false);
    await page.locator('#memory-search').fill('no-matches-v9-rare');await page.waitForTimeout(350);const empty=await measure();assert.ok(Math.abs(before.w-empty.w)<1,JSON.stringify({before,empty}));await page.locator('#memory-search').fill('');await page.waitForTimeout(300);
   });
   await check(`memory management usable ${width}x${height}`,async()=>{
    await page.locator('[data-tree-action=manage]').click();await page.locator('#dialog[open] .memory-management-hub').waitFor();await page.locator('#dialog').evaluate(n=>Promise.all(n.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
    const rect=await page.locator('#dialog').boundingBox();assert.ok(rect.x>=-1&&rect.y>=-1&&rect.x+rect.width<=width+1&&rect.y+rect.height<=height+1,JSON.stringify(rect));
    for(const action of ['settings','organize','backfill','jobs','export','import']){const button=page.locator(`#dialog [data-memory-studio=${action}]`);await button.scrollIntoViewIfNeeded();assert.ok(await button.isVisible());assert.ok((await button.boundingBox()).height>=36);}
    await page.locator('#dialog [data-memory-studio=settings]').click();await page.locator('#memory-settings-form').waitFor();await page.keyboard.press('Escape');await page.locator('#dialog[open] .memory-management-hub').waitFor();assert.equal(await page.locator('[data-memory-studio=settings]').evaluate(n=>n===document.activeElement),true);await page.keyboard.press('Escape');await page.locator('#dialog[open]').waitFor({state:'hidden'});await page.waitForFunction(()=>document.querySelector('[data-tree-action=manage]')===document.activeElement);
   });
  }
  await page.setViewportSize({width:1413,height:871});await page.locator('.shell').evaluate(n=>n.style.setProperty('--sidebar-width','180px'));
  await page.screenshot({path:path.join(out,engine+'-memory.png')});
  const chat=await api('/conversations','POST',{title:'v9 stability '+engine});await nav('chat/'+chat.id);await page.locator('#chat-input').fill('前端稳定性合成测试');await page.locator('#chat-composer [type=submit]').click();await page.waitForFunction(()=>[...document.querySelectorAll('[data-chat-action=speak]')].some(n=>!n.disabled));
  const tasks=await api('/tasks'),sourceId='task-'+tasks[0].id;
  await page.route('**/api/conversations/'+chat.id,async route=>{const response=await route.fetch(),data=await response.json(),m=data.messages.findLast(m=>m.role==='assistant');if(m){m.genui=null;m.content=Array.from({length:32},(_,i)=>`第 ${i+1} 段。稳定阅读内容与日期 2026-10-22 17:00，测试文字根据容器宽度自然换行。核对记录后继续处理任务。[1]`).join('\n\n');m.citations=[{source_id:sourceId,quote:'测试引用'}];m.evidence_sources=[{id:sourceId,name:'合成待办',evidence_kind:'task'}];m.grounding={memory:{selected:4},memory_operations:[]};}await route.fulfill({response,json:data});});
  await page.reload();await page.locator('.source-pill').last().waitFor();
  await check('unused memory candidates have no icon or receipt block',async()=>{assert.equal(await page.locator('.memory-use-icon:not([hidden]),.memory-receipt:not([hidden])').count(),0);});
  for(const theme of ['light','dark','auto'])for(const colorScheme of ['light','dark'])await check(`chat surface and contrast remain consistent for saved ${theme} and OS ${colorScheme}`,async()=>{
   const session=await api('/session');await api('/genui/preferences','PUT',{version:session.genui.version,enabled:session.genui.enabled,theme});
   await page.emulateMedia({colorScheme});await page.reload();await page.locator('.source-pill').last().waitFor();
   assert.equal(await page.locator('#chat-thread').getAttribute('data-genui-theme'),'light');
   const result=await page.locator('.message-assistant .message-content').first().evaluate(n=>{
    n.classList.add('gu-message');const style=getComputedStyle(n),p=n.querySelector('p')||n,fg=getComputedStyle(p).color;
    let current=p,bg;while(current){const value=getComputedStyle(current).backgroundColor;if(value!=='transparent'&&value!=='rgba(0, 0, 0, 0)'){bg=value;break;}current=current.parentElement;}
    const rgb=v=>(v.match(/[\d.]+/g)||[]).slice(0,3).map(Number),lum=v=>rgb(v).map(c=>{c/=255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((a,c,i)=>a+c*[.2126,.7152,.0722][i],0),a=lum(fg),b=lum(bg||'rgb(255,255,255)');
    return{scheme:style.colorScheme,bg:style.backgroundColor,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
   });
   assert.equal(result.scheme,'light');assert.ok(result.bg==='rgba(0, 0, 0, 0)'||result.bg==='rgb(255, 255, 255)',JSON.stringify(result));assert.ok(result.ratio>=4.5,JSON.stringify(result));
  });
  await page.emulateMedia({colorScheme:'light'});
  let synthesis=0;
  await page.route('**/api/speech/config',route=>route.fulfill({json:{configured:true,models:{default:'synthetic-voice'},voice:'synthetic'}}));
  await page.route('**/api/speech/synthesize',async route=>{synthesis++;await new Promise(r=>setTimeout(r,180));await route.fulfill({contentType:'audio/wav',body:wave});});
  await check('repeated play pause close reopen reuses generated audio',async()=>{
   const speak=page.locator('[data-chat-action=speak]').last();await speak.click();await page.waitForFunction(()=>document.querySelector('.reply-audio audio')?.src.startsWith('blob:'));assert.equal(synthesis,1);
   await speak.click();await speak.click();assert.equal(synthesis,1);await page.locator('.reply-audio [aria-label="关闭播放器"]').click();await speak.click();await page.waitForFunction(()=>document.querySelector('.reply-audio audio')?.src.startsWith('blob:'));assert.equal(synthesis,1);
   assert.ok((await page.locator('.reply-audio').boundingBox()).height<70);
  });
  for(const width of [1413,1024,1651])await check(`source reflow keeps nodes font draft audio and visible content ${width}`,async()=>{
   await page.setViewportSize({width,height:871});await page.waitForFunction(async()=>{const {chatViewportHeld}=await import('/static/chat-viewport.js');return !chatViewportHeld(document.querySelector('#chat-thread'));});await page.locator('#chat-input').fill('未发送的输入不能丢失');await page.locator('#chat-thread').evaluate(n=>n.scrollTop=n.scrollHeight*.4);
   await page.evaluate(()=>{window.__v9nodes=['#chat-workspace','.chat-main','#chat-thread','.message-assistant .message-content','#chat-input','.reply-audio audio'].map(s=>document.querySelector(s));window.__v9font=getComputedStyle(document.querySelector('.message-assistant .message-content')).fontSize;window.__v9scroll=document.querySelector('#chat-thread').scrollTop;});
   const before=await page.locator('.chat-main').boundingBox();await page.locator('.source-pill').last().evaluate(n=>n.click());await page.locator('.reply-sources-panel').waitFor();await page.locator('#chat-workspace').evaluate(node=>Promise.all(node.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
   const during=await page.locator('.chat-main').boundingBox();assert.ok(during.width<before.width-200);
   const clipped=await page.locator('.prose-flow[data-ready=true] > .prose-flow-clip').evaluateAll(nodes=>nodes.map(n=>({visible:n.clientHeight,content:n.scrollHeight})).filter(n=>n.content>n.visible+1));assert.deepEqual(clipped,[],'Reflow must retain the full intrinsic prose height');
   assert.equal(await page.evaluate(()=>['#chat-workspace','.chat-main','#chat-thread','.message-assistant .message-content','#chat-input','.reply-audio audio'].every((s,i)=>document.querySelector(s)===window.__v9nodes[i])),true);
   assert.equal(await page.locator('#chat-input').inputValue(),'未发送的输入不能丢失');assert.equal(await page.locator('.message-assistant .message-content').first().evaluate(n=>getComputedStyle(n).fontSize),await page.evaluate(()=>window.__v9font));
   const visible=await page.locator('#chat-thread').evaluate(n=>{const r=n.getBoundingClientRect();return [...n.querySelectorAll('.message-content p')].filter(p=>{const b=p.getBoundingClientRect();return b.bottom>r.top&&b.top<r.bottom;}).map(p=>p.textContent);});assert.ok(visible.length);
   await page.locator('[aria-label="关闭回答来源"]').click();await page.locator('#chat-workspace').evaluate(node=>Promise.all(node.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));assert.ok(Math.abs((await page.locator('.chat-main').boundingBox()).width-before.width)<2);const after=await page.locator('#chat-thread').evaluate(n=>n.scrollTop),initial=await page.evaluate(()=>window.__v9scroll);assert.ok(Math.abs(after-initial)<35,JSON.stringify({initial,after}));
  });
  await page.locator('.reply-audio [aria-label="关闭播放器"]').click();await page.screenshot({path:path.join(out,engine+'-chat.png')});
  await check('used memory appears as a small accessible SVG',async()=>{
   const result=await page.evaluate(async()=>{const {ConversationView}=await import('/static/genui/chat-presenter.js'),host=document.createElement('div');document.body.append(host);const view=new ConversationView(host,{feature:{enabled:false},sources:[]});view.draw([{id:'synthetic-memory-receipt',conversation_id:'test',role:'assistant',status:'complete',content:'合成测试',grounding:{memory_operations:[{status:'used',id:'m1'}]}}]);const icon=host.querySelector('.memory-use-icon'),rect=icon?.getBoundingClientRect(),answer={svg:icon?.querySelectorAll('svg').length,label:icon?.getAttribute('aria-label'),w:rect?.width,h:rect?.height};view.dispose();host.remove();return answer;});assert.equal(result.svg,1);assert.ok(result.label.includes('1 条记忆'));assert.ok(result.w<=32&&result.h<=32,JSON.stringify(result));
  });
 }catch(error){report.checks.push({engine,name:'fixture or critical flow',ok:false,error:error.message.slice(0,900)});console.log('FAIL',engine,error.message.slice(0,300));}finally{await browser.close();}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));const failed=report.checks.filter(x=>!x.ok);console.log(JSON.stringify({checks:report.checks.length,failed:failed.length,pageErrors:report.errors.length}));if(failed.length||report.errors.length)process.exitCode=1;
