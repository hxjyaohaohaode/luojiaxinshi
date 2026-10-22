import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const pw=createRequire(import.meta.url)(process.env.PLAYWRIGHT_PATH||'playwright');
const origin=process.env.MEMORY_TEST_ORIGIN||'http://127.0.0.1:8786',out=path.resolve('artifacts/memory-v7-browser');
await mkdir(out,{recursive:true});
const report={synthetic:true,externalProviderCalls:0,checks:[],errors:[]};
const until=async pred=>{for(let i=0;i<80;i++){if(await pred())return;await new Promise(r=>setTimeout(r,150));}throw Error('Condition did not settle');};
const fields=m=>Object.fromEntries(['scope','project_id','topic','kind','source_conversation_id','active','pinned','version','semantic_key','valid_from','expires_at','labels','locked'].map(k=>[k,m[k]]));
let failure;
for(const engine of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
 const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
 const ctx=await browser.newContext({viewport:{width:1600,height:1000},reducedMotion:'reduce'}),page=await ctx.newPage();page.setDefaultTimeout(15000);
 page.on('pageerror',e=>report.errors.push({engine,message:e.message}));
 const check=(name,ok)=>{report.checks.push({engine,name,passed:!!ok});if(!ok)throw Error(name);};
 try{
  const login=await ctx.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});check('login',login.ok());
  const session=await (await ctx.request.get(origin+'/api/session')).json(),headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
  const api=async(url,method='GET',data)=>{const r=await ctx.request.fetch(origin+'/api'+url,{method,headers,...(data===undefined?{}:{data})});if(!r.ok())throw Error(method+' '+url+' '+r.status()+': '+await r.text());return r.json();};
  const tag='UX-'+engine+'-'+Date.now(),pair=tag+'-pair';
  let a=await api('/memory/items','POST',{content:pair+' A 😀，原有要求保留。',kind:'fact'}),b=await api('/memory/items','POST',{content:pair+' B，独立内容。',kind:'fact'});
  const project=await api('/memory/projects','POST',{name:tag+'-研究项目',description:'合成检索验收'});
  const pm=await api('/memory/items','POST',{scope:'project',project_id:project.id,content:'作者年份引用格式。',kind:'constraint'});
  const root=(await api('/memory/tree')).root_id,parent=await api('/memory/tree/folders','POST',{parent_id:root,title:tag+'-整理'}),target=await api('/memory/tree/folders','POST',{parent_id:parent.id,title:'未展开的目标目录'});
  await page.goto(origin+'/#memory');await page.locator('#memory-search').waitFor();
  await page.locator('#content:not([inert]) #memory-search').waitFor();
  check('overview uses progressive automatic display',(await page.locator('#memory-view-type').inputValue())==='auto');
  check('unexpanded overview is not flooded with raw source fragments',await page.locator('[data-tree-record^="unit-"]').count()===0);
  const search=async text=>{
    await page.locator('#content:not([inert]) #memory-search').waitFor();
    const response=page.waitForResponse(r=>r.url().includes('/api/memory/tree/entries?')&&new URL(r.url()).searchParams.get('q')===text.trim()&&r.ok());
    if(await page.locator('#memory-search').inputValue()===text)await page.locator('[data-tree-action="refresh"]').first().click();else await page.locator('#memory-search').fill(text);
    const expected=(await (await response).json()).order.map(r=>r.id);
    await until(async()=>{
      const ids=await page.locator('[data-tree-record]').evaluateAll(nodes=>nodes.map(n=>n.dataset.treeRecord));
      return await page.locator('.memory-tree-main:not([aria-busy="true"])').count()>0&&ids.length===expected.length&&ids.every(id=>expected.includes(id));
    });
  };
  const found=async id=>page.locator(`[data-tree-record="${id}"]`).waitFor();
  await search(project.name);await found(pm.id);check('project names are searchable without appearing in the body',true);
  await search(pair);await found(a.id);await found(b.id);
  await page.locator(`[data-tree-record="${a.id}"]`).click();await page.locator('.memory-detail-more summary').click();
  await api('/memory/items','POST',{content:tag+' 后台产生的独立记录。',kind:'fact'});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.locator('#memory-update-message').filter({hasText:'已有新变化'}).waitFor();
  check('background change preserves expanded detail controls',await page.locator('.memory-detail-more').evaluate(el=>el.open)&&await page.locator('[data-tree-action="move"]').isVisible());
  await page.locator('[data-tree-action="move"]').click();
  await page.locator('[data-location-query]').fill('未展开的目标目录');await until(async()=>await page.locator('#memory-move-form [name="destination"] option[value="'+target.id+'"]').count()===1);
  await page.locator('#memory-move-form [name="destination"]').selectOption(target.id);await page.locator('#memory-move-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  a=await api('/memory/items/'+a.id);check('move finds a never-expanded nested destination',a.version===2&&a.scope==='global');
  await found(a.id);await page.locator(`[data-tree-check="${a.id}"]`).check();await page.locator(`[data-tree-check="${b.id}"]`).check();
  check('batch toolbar shows the exact selected count',(await page.locator('#memory-selected-count').textContent()).includes('2'));
  await page.locator('[data-tree-action="move-many"]').click();await page.locator('[data-location-query]').fill('未展开的目标目录');await until(async()=>await page.locator('#memory-move-form [name="destination"] option[value="'+target.id+'"]').count()>0);
  await page.locator('#memory-move-form [name="destination"]').selectOption(target.id);await page.locator('#memory-move-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  a=await api('/memory/items/'+a.id);b=await api('/memory/items/'+b.id);check('batch move retains both bodies and advances each once',a.version===3&&b.version===2);
  await found(a.id);await page.locator(`[data-tree-record="${a.id}"]`).click();await page.locator('[data-tree-action="edit-inline"]').click();const draft=a.content+' 😀尚未保存的草稿。';
  await page.locator('#memory-inline-editor [name="content"]').fill(draft);await page.reload();await page.locator('#memory-search').waitFor();await search(pair);await found(a.id);await page.locator(`[data-tree-record="${a.id}"]`).click();
  check('reload advertises the recovered draft',(await page.locator('#memory-detail-pane').textContent()).includes('未保存草稿'));
  await page.locator('[data-tree-action="edit-inline"]').click();check('reload preserves exact Unicode text and base version',(await page.locator('#memory-inline-editor [name="content"]').inputValue())===draft&&Number(await page.locator('#memory-inline-editor').getAttribute('data-version'))===a.version);
  const concurrent=a.content+' 另一标签保存的新正文。';await api('/memory/items/'+a.id,'PUT',{...fields(a),content:concurrent});
  await page.locator('#memory-inline-editor [type="submit"]').click();await page.locator('[data-use-latest-version]').waitFor();
  check('conflicting save preserves the draft and shows the latest server body',(await page.locator('#memory-inline-editor [name="content"]').inputValue())===draft&&(await page.locator('[data-edit-conflict] textarea').inputValue())===concurrent);
  check('conflict does not overwrite the concurrent edit',(await api('/memory/items/'+a.id)).content===concurrent);
  await page.locator('[data-use-latest-version]').click();await page.locator('#memory-inline-editor [type="submit"]').click();await until(async()=>await page.locator('#memory-inline-editor').count()===0);
  a=await api('/memory/items/'+a.id);check('explicit conflict resolution saves once and retains history',a.content===draft&&a.revisions.some(r=>r.snapshot.content===concurrent));
  await page.locator('[data-tree-action="edit-inline"]').click();const lost=a.content+' 回包丢失也只保存一次。';await page.locator('#memory-inline-editor [name="content"]').fill(lost);
  const lostReply=async route=>{if(route.request().method()==='PUT'){await route.fetch();await route.abort('failed');}else await route.continue();};await page.route('**/api/memory/items/'+a.id,lostReply);
  await page.locator('#memory-inline-editor [type="submit"]').click();await until(async()=>!(await page.locator('#memory-inline-editor').evaluate(el=>el.inert))&&(await api('/memory/items/'+a.id)).version===a.version+1);
  await page.unroute('**/api/memory/items/'+a.id,lostReply);await page.locator('#memory-inline-editor [type="submit"]').click();await until(async()=>await page.locator('#memory-inline-editor').count()===0);
  const retried=await api('/memory/items/'+a.id);check('lost response retry replays the durable receipt without a second edit',retried.version===a.version+1&&retried.content===lost);a=retried;
  // Requests finish in the reverse order; an older query cannot replace a newer one.
  const delayed=async route=>{if(new URL(route.request().url()).searchParams.get('q')==='older-query'){await new Promise(r=>setTimeout(r,650));try{await route.continue();}catch{}}else await route.continue();};await page.route('**/api/memory/tree/entries?*',delayed);
  const older=page.waitForRequest(r=>r.url().includes('/memory/tree/entries?')&&new URL(r.url()).searchParams.get('q')==='older-query');await page.locator('#memory-search').fill('older-query');await older;await page.locator('#memory-search').fill(pair);await found(a.id);await new Promise(r=>setTimeout(r,800));
  check('out-of-order search cannot paint stale results',await page.locator(`[data-tree-record="${a.id}"]`).count()===1);await page.unroute('**/api/memory/tree/entries?*',delayed);
  await page.locator(`[data-tree-record="${a.id}"]`).click();await page.locator('[data-tree-action="edit-inline"]').click();await page.locator('#memory-inline-editor [name="content"]').fill(a.content+' 自动同步时不打断编辑。');
  b=await api('/memory/items/'+b.id);await api('/memory/items/'+b.id,'PUT',{...fields(b),content:b.content+' 后台更新。'});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.locator('#memory-update-message').filter({hasText:'已有新变化'}).waitFor();check('background synchronization keeps the editor and its draft',(await page.locator('#memory-inline-editor [name="content"]').inputValue()).endsWith('自动同步时不打断编辑。'));
  await page.locator('[data-tree-action="cancel-edit"]').click();await page.locator('[data-tree-action="refresh"]').first().click();await found(a.id);
  const autoTag=tag+'-automatic';await search(autoTag);await until(async()=>(await page.locator('#memory-match-count').textContent()).startsWith('0 '));
  await page.locator('#memory-search-scope').focus();const auto=await api('/memory/items','POST',{content:autoTag+' 后台形成的合成记录',kind:'fact'});await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await found(auto.id);check('new records synchronize without clicking refresh',true);
  // Error states are recoverable and do not erase the search input.
  const unavailable=route=>route.abort('failed');await page.route('**/api/memory/tree',unavailable);await page.locator('[data-tree-action="refresh"]').first().click();await page.locator('#memory-update-message').waitFor();
  check('read failure retains query and provides an actionable retry',(await page.locator('#memory-search').inputValue())===autoTag&&await page.locator('#memory-update-message [data-tree-action="refresh"]').count()===1);
  await page.unroute('**/api/memory/tree',unavailable);await page.locator('#memory-update-message [data-tree-action="refresh"]').click();await until(async()=>!(await page.locator('#memory-update-message').isVisible()));
  await page.locator('.memory-tree-settings>summary').click();await page.locator('[data-memory-action="project-manage"]').click();
  await page.locator(`#dialog [data-memory-action="project-edit"][data-id="${project.id}"]`).click();
  await page.locator('[data-workspace-form="memory-project"] [name="description"]').fill('人工更新的合成项目说明。');await page.locator('[data-workspace-form="memory-project"] [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  check('optional project management edits actual project metadata',(await api('/memory?limit=1')).projects.find(p=>p.id===project.id).description==='人工更新的合成项目说明。');
  await search('');const roots=await api('/memory/tree'),resourceLayer=roots.nodes.find(n=>n.node_key==='layer:resources');
  await page.locator(`#memory-tree-nav [data-tree-node="${resourceLayer.id}"]`).click();
  const sourceGroup=(await api('/memory/tree?parent_id='+resourceLayer.id)).nodes.find(n=>n.node_key==='source-group:resource_notice');
  await page.locator(`#memory-tree-nav [data-tree-node="${sourceGroup.id}"]`).click();
  const sourceFile=(await api('/memory/tree?parent_id='+sourceGroup.id)).nodes[0];await page.locator(`#memory-tree-nav [data-tree-node="${sourceFile.id}"]`).click();
  await page.locator('[data-tree-record^="unit-"]').first().waitFor();check('opening a source file automatically reveals its complete parsed fragments',true);
  await page.locator('[data-tree-record^="unit-"]').first().click();check('source fragment keeps a distinct readonly identity',await page.locator('#memory-detail-pane [data-tree-action="edit-inline"]').count()===0&&await page.locator('#memory-detail-pane [data-tree-action="open-source"]').count()===1);
  await page.locator('#memory-tree-nav [data-tree-node]').first().click();await search(autoTag);await found(auto.id);
  // Session state has its own query and all 125 entries can be reached.
  await page.locator('[data-tree-action="sessions"]').click();await page.locator('#memory-search').fill('合成会话条件');await until(async()=>(await page.locator('#memory-match-count').textContent()).includes('125 条会话'));
  check('session search stays in session mode',(await page.locator('#memory-breadcrumbs').textContent()).includes('会话与工作记忆'));
  check('session first page has fifty entries',await page.locator('.memory-tree-rows .memory-session-entry').count()===50);
  await page.locator('[data-tree-action="next"]').click();await until(async()=>(await page.locator('#memory-pagination').textContent()).includes('2 / 3'));
  await page.locator('[data-tree-action="next"]').click();await until(async()=>(await page.locator('#memory-pagination').textContent()).includes('3 / 3'));
  check('session pagination reaches beyond one hundred entries',await page.locator('.memory-tree-rows .memory-session-entry').count()===25);
  await page.locator('#memory-search').fill('合成会话条件 000');await until(async()=>await page.locator('.memory-tree-rows .memory-session-entry').count()===1);
  await page.locator('[data-memory-life="edit-session"]').click();await page.locator('#memory-session-edit [name="content"]').fill('合成会话条件 000，人工修订保留原话。');await page.locator('#memory-session-edit [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  await until(async()=>(await page.locator('#memory-items').textContent()).includes('人工修订保留原话'));check('editing a session condition refreshes the same search and mode',(await page.locator('#memory-breadcrumbs').textContent()).includes('会话与工作记忆'));
  await page.locator('[data-tree-action="refresh"]').first().click();check('refresh preserves the session query',(await page.locator('#memory-search').inputValue())==='合成会话条件 000');
  await page.locator('#memory-tree-nav [data-tree-node]').first().click();await search(pair);await found(a.id);await page.locator(`[data-tree-record="${a.id}"]`).click();await page.locator('.memory-detail-more summary').click();await page.locator('[data-tree-action="locate"]').click();
  await until(async()=>(await page.locator('#memory-breadcrumbs [aria-current]').textContent())==='未展开的目标目录');check('record can open its real directory without traversing the tree',true);
  await page.locator('[data-tree-action="folder-edit"]').click();await page.locator('[data-remove-folder]').click();await page.locator('[data-action="accept-dialog"]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  await until(async()=>(await page.locator('#memory-breadcrumbs [aria-current]').textContent())===parent.title);check('dissolving a directory keeps every record accessible',await page.locator(`[data-tree-record="${a.id}"]`).count()===1&&await page.locator(`[data-tree-record="${b.id}"]`).count()===1);
  // Responsive detail is a modal at tablet/phone widths and a side column on desktop.
  for(const width of [320,390,820,1280]){
    await page.setViewportSize({width,height:900});await page.locator(`[data-tree-record="${a.id}"]`).click();
    check('no horizontal overflow at '+width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
    if(width<=1200){
      check('detail owns modal focus at '+width,await page.locator('#memory-detail-pane').getAttribute('aria-modal')==='true'&&await page.locator('#memory-detail-pane').evaluate(el=>el.contains(document.activeElement)));
      await page.keyboard.press('Shift+Tab');check('backward tab remains inside detail at '+width,await page.locator('#memory-detail-pane').evaluate(el=>el.contains(document.activeElement)));
      await page.keyboard.press('Tab');check('forward tab remains inside detail at '+width,await page.locator('#memory-detail-pane').evaluate(el=>el.contains(document.activeElement)));
      if(width===390&&engine==='chromium')await page.screenshot({path:path.join(out,'mobile.png'),fullPage:false});
      await page.keyboard.press('Escape');check('Escape closes detail and returns focus at '+width,!await page.locator('#memory-detail-pane').evaluate(el=>el.classList.contains('is-visible'))&&await page.locator(`[data-tree-record="${a.id}"]`).evaluate(el=>el===document.activeElement));
    }else{check('desktop detail remains a nonmodal column',await page.locator('#memory-detail-pane').getAttribute('aria-modal')===null);await page.locator('[data-tree-action="close-detail"]').click();}
  }
  await page.setViewportSize({width:1600,height:1000});await page.locator(`[data-tree-record="${a.id}"]`).click();await page.evaluate(()=>scrollTo(0,0));if(engine==='chromium')await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  await page.locator('[data-tree-action="edit-inline"]').click();await page.locator('#memory-inline-editor [name="content"]').fill(a.content+' 退出时须清除。');check('unsaved draft is present before logout',await page.evaluate(()=>Object.keys(sessionStorage).some(k=>k.startsWith('campus-memory-drafts-v1:'))));
  await api('/auth/logout','POST',{});await page.locator('[data-tree-action="refresh"]').first().click();await page.locator('#auth-form').waitFor();
  check('expired session removes the private editor and memory drafts',await page.locator('#memory-inline-editor').count()===0&&!await page.evaluate(()=>Object.keys(sessionStorage).some(k=>k.startsWith('campus-memory-drafts-v1:'))));
  check('no browser exceptions',report.errors.filter(e=>e.engine===engine).length===0);
 }catch(error){failure=error;report.failure={engine,message:error.message};await page.screenshot({path:path.join(out,'failure-'+engine+'.png'),fullPage:true}).catch(()=>{});break;}
 finally{await ctx.close();await browser.close();}
}
await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({checks:report.checks.length,passed:!failure&&report.checks.every(c=>c.passed),errors:report.errors.length,failure:report.failure}));
if(failure)throw failure;
