import {browserOverride} from './browser-runtime.mjs';
// Isolated browser fixture: real source UI and CSS, no account, model, or external requests.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {createRequire} from 'node:module';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve(import.meta.dirname,'..'),out=path.join(root,'artifacts/source-presets-browser');
await mkdir(out,{recursive:true});
const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/styles.css"><body><main class="content" id="content"></main><dialog id="dialog"></dialog><div id="toast" role="status"></div><script type="module">
import {createSourcesUI} from '/static/sources.js';
const $=s=>document.querySelector(s),esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const presets=[{id:'whu-notices',name:'武汉大学通知公告',institution:'武汉大学',url:'https://www.whu.edu.cn/tzgg.htm',article_path_prefix:'/info/5231/',purpose:'学校通知公告当前列表中的公开原文；需要校内权限的文章会提示未能读取'},{id:'whu-journal-affairs',name:'新闻与传播学院学生事务',institution:'武汉大学新闻与传播学院',url:'https://journal.whu.edu.cn/undergraduate/affairs/index',article_path_prefix:'/undergraduate/',purpose:'学院学生事务栏目当前列表，包含该栏目实际发布的本科生和研究生通知'}];
const state={session:{user:{id:'fixture-owner'}},renderId:1,dialogRequest:0};location.hash='sources';
const fixture=window.fixture={state,calls:[],entries:[],subscriptions:[],trials:new Map(),held:new Set(),waiters:new Map(),presets};
fixture.pause=p=>fixture.held.add(p);fixture.release=p=>{fixture.held.delete(p);for(const resolve of fixture.waiters.get(p)||[])resolve();fixture.waiters.delete(p);};
const api=async(p,o={})=>{
 fixture.calls.push({path:p,method:o.method||'GET',json:o.json});
 if(fixture.held.has(p))await new Promise(resolve=>{const waiters=fixture.waiters.get(p)||[];waiters.push(resolve);fixture.waiters.set(p,waiters);});
 if(p==='/source-presets')return structuredClone(presets);
 if(p==='/source-catalog')return structuredClone(fixture.entries);
 if(p==='/integrations')return {qq:{configured:false,groups:[]},wechat_publisher:{configured:false}};
 if(p==='/source-subscriptions')return structuredClone(fixture.subscriptions);
 if(p==='/notice-automation')return {enabled:false,counts:{}};
 if(p.endsWith('/subscribe')){const id=p.split('/')[2],preset=presets.find(v=>v.id===id),existing=fixture.subscriptions.find(s=>s.config.preset_id===id);if(existing)return {source_id:existing.source_id,created:false,subscription:structuredClone(existing)};const source_id='source-'+id,subscription={source_id,enabled:true,state:'waiting',version:1,config:{preset_id:id,url:preset.url,mode:'html',article_path_prefix:preset.article_path_prefix,interval_minutes:30}};fixture.entries.push({id:source_id,version:1,data:{...preset,platform:'website'}});fixture.subscriptions.push(subscription);return {source_id,created:true,subscription:structuredClone(subscription)};}
 if(p.endsWith('/subscription/preview')){
  const source_id=p.split('/')[2],item=fixture.subscriptions.find(s=>s.source_id===source_id),{version,enabled,...config}=o.json;
  if(o.method!=='POST'||!item||version!==item.version)throw Error('Synthetic preview requires the current source version');
  const trial_id='trial-'+(fixture.trials.size+1),result={trial_id,version,config,can_apply:true,list:{count:1,empty_confirmed:false,rejected_entries:[]},articles:[{url:new URL(config.article_path_prefix+'fixture.htm',config.url).href,title:'合成试读正文',status:'ok',coverage:{review_required:false}}],errors:[]};
  fixture.trials.set(trial_id,{source_id,result:structuredClone(result)});return structuredClone(result);
 }
 if(p.endsWith('/subscription/apply')){
  const source_id=p.split('/')[2],item=fixture.subscriptions.find(s=>s.source_id===source_id),trial=fixture.trials.get(o.json.trial_id);
  if(o.method!=='POST'||!item||!trial||trial.source_id!==source_id||!trial.result.can_apply||o.json.version!==item.version||trial.result.version!==item.version)throw Error('Synthetic apply requires the successful preview for this source and version');
  Object.assign(item,{enabled:o.json.enabled,state:o.json.enabled?'waiting':'paused',version:item.version+1,config:structuredClone(trial.result.config)});return structuredClone(item);
 }
 if(p.endsWith('/subscription')){const item=fixture.subscriptions.find(s=>s.source_id===p.split('/')[2]);Object.assign(item,{enabled:o.json.enabled,state:o.json.enabled?'waiting':'paused',version:item.version+1,config:{...o.json}});return structuredClone(item);}
 throw Error('Unexpected fixture request: '+p);
};
const showDialog=(title,body)=>{state.dialogRequest++;$('#dialog').innerHTML='<header class="between"><h2>'+esc(title)+'</h2><button type="button" data-close>关闭</button></header><div class="dialog-body">'+body+'</div>';if(!$('#dialog').open)$('#dialog').showModal();};
document.addEventListener('click',e=>{if(e.target.closest('[data-close],[data-action="close-dialog"]'))$('#dialog').close();});
fixture.showDialog=showDialog;
fixture.ui=createSourcesUI({state,api,esc,icon:()=>'',field:(label,name,value,type='text',attrs='')=>'<label class="field">'+esc(label)+'<input name="'+name+'" type="'+type+'" value="'+esc(value)+'" '+attrs+'></label>',area:()=>'',showDialog,ask:async()=>true,toast:message=>$('#toast').textContent=message,route:()=>{}});
await fixture.ui.render(state.renderId);fixture.ready=true;
</script></body></html>`;
const server=createServer(async(req,res)=>{
 try{
  if(req.url==='/'||req.url.startsWith('/?')){res.writeHead(200,{'Content-Type':'text/html;charset=utf-8'});res.end(html);return;}
  const url=new URL(req.url,'http://localhost'),file=path.resolve(root,'.'+decodeURIComponent(url.pathname));
  if(!file.startsWith(path.join(root,'static')+path.sep)){res.writeHead(404);res.end();return;}
  const type={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'}[path.extname(file)]||'application/octet-stream';
  res.writeHead(200,{'Content-Type':type});res.end(await readFile(file));
 }catch{res.writeHead(404);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({headless:true,...browserOverride(chromium),...(process.platform==='win32'?{channel:'msedge'}:{})});
const page=await browser.newPage({viewport:{width:320,height:720},reducedMotion:'reduce'}),report={synthetic:true,external_requests:0,model_calls:0,checks:[],errors:[]};
page.on('pageerror',error=>report.errors.push(error.message));
await page.route('**/*',async route=>{if(new URL(route.request().url()).origin!==origin){report.external_requests++;await route.abort();}else await route.continue();});
const fresh=async()=>{await page.goto(origin);await page.waitForFunction(()=>window.fixture?.ready);};
const open=()=>page.locator('[data-source-action="school-presets"]').first().click();
const subscribe=()=>page.locator('[data-source-action="preset-subscribe"][data-id="whu-notices"]');
const check=async(name,fn)=>{await fn();report.checks.push({name,passed:true});};
try{
 await fresh();
 await check('320px: selecting two school columns is read-only until the explicit subscribe click',async()=>{
  await open();await subscribe().waitFor();assert.equal(await page.locator('#source-presets article').count(),2);
  assert.equal(await page.locator('#source-presets input').count(),0);
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.method!=='GET').length),0);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1||document.querySelector('#dialog').scrollWidth>document.querySelector('#dialog').clientWidth+1),false);
  await page.screenshot({path:path.join(out,'school-presets-320.png')});
 });
 await check('duplicate subscribe clicks send once, expose refresh, and do not enable AI',async()=>{
  await page.evaluate(()=>fixture.pause('/source-presets/whu-notices/subscribe'));
  await subscribe().evaluate(b=>{b.click();b.click();});
  await page.waitForFunction(()=>fixture.waiters.has('/source-presets/whu-notices/subscribe'));
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.path.endsWith('/subscribe')).length),1);
  assert.equal(await subscribe().isDisabled(),true);
  await page.evaluate(()=>fixture.release('/source-presets/whu-notices/subscribe'));
  await page.locator('[data-source-action="sync-refresh"]').waitFor();
  assert.equal(await page.evaluate(()=>fixture.calls.some(c=>c.path==='/notice-automation'&&c.method!=='GET')),false);
  assert.equal(await page.locator('[data-source-record="source-whu-notices"]').evaluate(n=>n.open),true);
 });
 await check('preset settings keep adapter identity and fixed source fields while allowing pause',async()=>{
  await page.locator('[data-source-action="sync-config"]').click();
  const form=page.locator('[data-workspace-form="source-sync"]');
  assert.equal(await form.locator('[name="preset_id"]').inputValue(),'whu-notices');
  for(const name of ['preset_id','url','mode','article_path_prefix'])assert.equal(await form.locator('[name="'+name+'"]').getAttribute('type'),'hidden');
  const before=await page.evaluate(()=>structuredClone(fixture.subscriptions[0]));
  await form.locator('[name="enabled"]').uncheck();await form.locator('[name="interval_minutes"]').fill('45');await form.locator('[type="submit"]').click();
  const apply=page.locator('[data-source-action="rule-apply"]');await apply.waitFor();assert.match(await apply.textContent(),/保存为暂停规则/);
  assert.deepEqual(await page.evaluate(()=>structuredClone(fixture.subscriptions[0])),before,'Preview must preserve the active subscription until the explicit apply click');
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.path.endsWith('/subscription/apply')||c.path.endsWith('/subscription')).length),0);
  const payload=await page.evaluate(()=>fixture.calls.findLast(c=>c.path.endsWith('/subscription/preview')).json);
  assert.equal(payload.preset_id,'whu-notices');assert.equal(payload.article_path_prefix,'/info/5231/');assert.equal(payload.url,'https://www.whu.edu.cn/tzgg.htm');assert.equal(payload.interval_minutes,45);assert.equal(payload.enabled,false);
  await apply.click();await page.waitForFunction(()=>!document.querySelector('#dialog').open);
  const saved=await page.evaluate(()=>({subscription:structuredClone(fixture.subscriptions[0]),apply:fixture.calls.findLast(c=>c.path.endsWith('/subscription/apply')).json,trial:structuredClone([...fixture.trials.values()][0].result)}));
  assert.deepEqual(saved.apply,{version:before.version,trial_id:saved.trial.trial_id,enabled:false});assert.deepEqual(saved.subscription.config,saved.trial.config);assert.equal(saved.subscription.version,before.version+1);assert.equal(saved.subscription.enabled,false);assert.equal(saved.subscription.config.interval_minutes,45);
  await open();await page.locator('[data-source-action="preset-view"]').waitFor();await page.locator('[data-source-action="preset-view"]').click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.path.endsWith('/subscribe')).length),1);
  assert.equal(await page.locator('[data-source-action="sync-refresh"]').count(),0);
 });
 await check('a late column list does not replace a newer dialog',async()=>{
  await fresh();await page.evaluate(()=>fixture.pause('/source-presets'));await open();
  await page.waitForFunction(()=>fixture.waiters.has('/source-presets'));
  await page.evaluate(()=>{fixture.showDialog('新的窗口','<p id="new-dialog">保留新窗口</p>');fixture.release('/source-presets');});
  await page.waitForFunction(()=>!document.querySelector('[data-source-action="school-presets"]').disabled);
  assert.equal(await page.locator('#new-dialog').textContent(),'保留新窗口');
 });
 for(const changed of ['route','account'])await check('late subscribe preserves changed '+changed,async()=>{
  await fresh();await open();await subscribe().waitFor();await page.evaluate(()=>fixture.pause('/source-presets/whu-notices/subscribe'));await subscribe().click();
  await page.waitForFunction(()=>fixture.waiters.has('/source-presets/whu-notices/subscribe'));
  await page.evaluate(changed=>{if(changed==='route'){fixture.state.renderId++;location.hash='tasks';}else fixture.state.session.user.id='another-owner';document.querySelector('#dialog').close();document.querySelector('#content').innerHTML='<p id="new-view">保留当前页面</p>';fixture.release('/source-presets/whu-notices/subscribe');},changed);
  await page.waitForFunction(()=>fixture.entries.length===1);await page.evaluate(()=>new Promise(requestAnimationFrame));
  assert.equal(await page.locator('#new-view').textContent(),'保留当前页面');assert.equal(await page.locator('#toast').textContent(),'');
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.path==='/source-catalog').length),1);
 });
 await check('a newer dialog stays open when a same-route subscribe completes',async()=>{
  await fresh();await open();await subscribe().waitFor();await page.evaluate(()=>fixture.pause('/source-presets/whu-notices/subscribe'));await subscribe().click();
  await page.waitForFunction(()=>fixture.waiters.has('/source-presets/whu-notices/subscribe'));
  await page.evaluate(()=>{fixture.showDialog('继续编辑','<input id="new-input" value="保留输入">');document.querySelector('#new-input').focus();fixture.release('/source-presets/whu-notices/subscribe');});
  await page.waitForFunction(()=>fixture.calls.filter(c=>c.path==='/source-catalog').length===2);await page.evaluate(()=>new Promise(requestAnimationFrame));
  assert.equal(await page.locator('#new-input').inputValue(),'保留输入');assert.equal(await page.evaluate(()=>document.activeElement.id),'new-input');assert.equal(await page.locator('#dialog').evaluate(n=>n.open),true);
 });
 assert.deepEqual(report.errors,[]);assert.equal(report.external_requests,0);
}catch(error){report.errors.push(error.stack);process.exitCode=1;await page.screenshot({path:path.join(out,'failure.png')});}
finally{await browser.close();await new Promise(resolve=>server.close(resolve));await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
