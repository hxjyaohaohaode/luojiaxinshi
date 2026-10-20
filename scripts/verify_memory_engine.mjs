import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const require=createRequire(import.meta.url);
const engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin=process.env.MEMORY_TEST_ORIGIN||'http://127.0.0.1:8786';
if(!/^http:\/\/127\.0\.0\.1:8786$/.test(origin))throw Error('Use the isolated memory fixture on 8786');
const output=path.resolve('artifacts/memory-engine-browser');
await mkdir(output,{recursive:true});
const report={checks:[],errors:[],toolWarnings:[]};
function check(name,passed,extra={}){
  report.checks.push({name,passed,...extra});
  if(!passed)throw Error(name);
}
for(const engine of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
  const browser=await engines[engine].launch({headless:true,executablePath:engines[engine].executablePath()});
  try{
    const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
    const login=await context.request.post(origin+'/api/auth/login',{
      headers:{Origin:origin,'X-Requested-With':'campus-notice'},
      data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
    check(engine+' fixture login',login.ok());
    const session=await (await context.request.get(origin+'/api/session')).json();
    const headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
    const api=async(url,method='GET',data)=>{
      const response=await context.request.fetch(origin+'/api'+url,{method,headers,...(data===undefined?{}:{data})});
      if(!response.ok())throw Error(method+' '+url+' '+response.status()+': '+await response.text());
      return response.json();
    };
    const page=await context.newPage();page.setDefaultTimeout(12000);
    let screenshotInProgress=false;
    page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
    page.on('console',msg=>{
      if(msg.type()!=='error'||!/Content Security Policy|Refused to/.test(msg.text()))return;
      const entry={engine,error:msg.text(),screenshotInProgress,location:msg.location()};
      // Playwright's WebKit screenshot synchronization injects <style>body {}</style>
      // before every capture (coreBundle.js: inPagePrepareForScreenshots). Our CSP
      // correctly rejects it. Preserve this specific, observed tool warning without
      // weakening the application policy; every non-capture violation still fails.
      if(engine==='webkit'&&screenshotInProgress&&msg.text()==="Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear in the style-src directive of the Content Security Policy.")
        report.toolWarnings.push({...entry,source:'Playwright WebKit screenshot synchronization'});
      else report.errors.push(entry);
    });
    const screenshot=async options=>{
      screenshotInProgress=true;
      try { await page.screenshot({...options,caret:'initial',animations:'disabled'}); }
      finally { screenshotInProgress=false; }
    };
    const go=async route=>{
      await page.goto(origin+'/?memory-verification='+Date.now()+'#'+route);
      await page.waitForFunction(()=>document.querySelector('#content')?.textContent.includes('我的记忆'));
    };
    let settings=await api('/memory/settings');
    await api('/memory/settings','PUT',{...settings,mode:'auto',auto_organize:false,learn_tasks:false});
    const tag=engine+'-'+Date.now(),initial='工程验收 '+tag+'：先核对原文，再列下一步。';
    await go('memory');
    await page.locator('[data-memory-action="new"]').first().click();
    await page.locator('form[data-workspace-form="memory-entry"] textarea[name="content"]').fill(initial);
    await page.locator('input[name="labels"]').fill('浏览器验收，重要');
    await page.getByRole('button',{name:'确认保存',exact:true}).click();
    await page.locator('#dialog').waitFor({state:'hidden'});
    let item=(await api('/memory?q='+encodeURIComponent(tag))).memories.find(item=>item.content===initial);
    check(engine+' creates editable locked memory with labels',Boolean(item?.locked&&item.labels.includes('重要')));
    await page.locator(`[data-memory-action="edit"][data-id="${item.id}"]`).click();
    const updated=initial+' 已经核对了材料清单。';
    await page.locator('form[data-workspace-form="memory-entry"] textarea[name="content"]').fill(updated);
    await page.getByRole('button',{name:'确认保存',exact:true}).click();
    await page.locator('#dialog').waitFor({state:'hidden'});
    await page.locator(`[data-memory-studio="detail"][data-id="${item.id}"]`).click();
    await page.getByText('修改历史',{exact:true}).waitFor();
    check(engine+' history displays both versions',await page.locator('.memory-detail details').count()===2);
    await page.locator('.memory-detail details').last().locator('summary').click();
    await page.locator('[data-memory-restore="1"]').click();
    await page.getByRole('button',{name:'恢复版本',exact:true}).click();
    await page.locator('#dialog').waitFor({state:'hidden'});
    item=await api('/memory/items/'+item.id);
    check(engine+' restores content as a new revision',item.content===initial&&item.version===3&&item.revisions.length===3);

    await page.locator('[data-memory-studio="settings"]').click();
    await page.locator('#memory-settings-form select[name="mode"]').selectOption('review');
    await page.locator('#memory-settings-form button[type="submit"]').click();
    await page.locator('#dialog').waitFor({state:'hidden'});
    await page.getByText('先核对再保存',{exact:true}).waitFor();
    check(engine+' settings persist', (await api('/memory/settings')).mode==='review');
    const file={format:'campus-memory-v1',memories:[{kind:'fact',content:'待核对内容 '+tag,labels:['来源待核对']}]};
    await page.locator('#memory-import-file').setInputFiles({name:'memory-import.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(file))});
    await page.getByText('待核对内容 '+tag,{exact:true}).waitFor();
    const pending=(await api('/memory?q='+encodeURIComponent('待核对内容 '+tag))).memories[0];
    check(engine+' import is inactive pending',pending.review_status==='pending'&&!pending.active);
    await page.locator(`[data-memory-studio="accept"][data-id="${pending.id}"]`).click();
    await page.waitForFunction(id=>!document.querySelector(`[data-memory-studio="accept"][data-id="${id}"]`),pending.id);
    const accepted=await api('/memory/items/'+pending.id);
    check(engine+' approves pending proposal',accepted.review_status==='accepted'&&accepted.active&&accepted.locked);

    const [download]=await Promise.all([
      page.waitForEvent('download'),
      page.locator(`[data-memory-studio="markdown"][data-id="${item.id}"]`).click()
    ]);
    check(engine+' exports Markdown as a download',download.suggestedFilename().endsWith('.md'));
    const markdown=await (await context.request.get(origin+'/api/memory/items/'+item.id+'/markdown')).text();
    await page.locator('#memory-import-file').setInputFiles({name:'memory-edit.md',mimeType:'text/markdown',
      buffer:Buffer.from(markdown.replace(initial,initial+' Markdown 编辑成功。'))});
    await page.getByText(initial+' Markdown 编辑成功。',{exact:true}).waitFor();
    check(engine+' Markdown updates same ID with revision', (await api('/memory/items/'+item.id)).version===4);

    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});
      await page.locator('#memory-search').fill(tag);
      await page.waitForTimeout(260);
      check(engine+' '+width+' no horizontal overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      if(await page.locator('#toast.visible').isVisible())
        check(engine+' '+width+' import receipt remains readable',await page.locator('#toast .toast-copy').evaluate(n=>n.getBoundingClientRect().width>=140));
      await screenshot({path:path.join(output,engine+'-'+width+'.png'),fullPage:true});
      await page.locator(`[data-memory-studio="detail"][data-id="${item.id}"]`).click();
      await page.getByText('修改历史',{exact:true}).waitFor();
      await page.waitForFunction(()=>Number(getComputedStyle(document.querySelector('#dialog')).opacity)===1);
      check(engine+' '+width+' history dialog fits',await page.locator('#dialog').evaluate(d=>{
        const box=d.getBoundingClientRect();return box.left>=-1&&box.right<=innerWidth+1&&box.top>=-1&&box.bottom<=innerHeight+1;
      }));
      await screenshot({path:path.join(output,engine+'-'+width+'-history.png')});
      await page.keyboard.press('Escape');
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('#memory-search').fill('');
    await page.locator('[data-memory-studio="organize"]').click();
    await page.getByText(/已处理 .*条记录/).last().waitFor();
    check(engine+' organizer control completes',true);
    const chat=await api('/conversations','POST',{});
    await page.goto(origin+'/#chat/'+chat.id);
    await page.locator('[data-chat-action="composer-menu"]').click();
    await page.locator('[data-chat-action="context-settings"]').click();
    await page.locator(`[data-memory-studio="working"][data-id="${chat.id}"]`).click();
    await page.locator('#memory-working-form textarea').fill('人工工作记忆：核对材料后继续。');
    await page.locator('#memory-working-form input[name="locked"]').check();
    await page.locator('#memory-working-form button[type="submit"]').click();
    await page.locator('#dialog').waitFor({state:'hidden'});
    const checkpoint=await api('/conversations/'+chat.id+'/working-memory');
    check(engine+' manually editable working checkpoint',checkpoint.locked&&checkpoint.content.includes('人工工作记忆'));
    await page.locator('#chat-input').fill('记住，我的测试称呼是 '+tag+'。');
    await page.locator('#chat-composer button[type="submit"]').click();
    await page.locator('.memory-receipt').filter({hasText:'等你核对'}).waitFor();
    check(engine+' chat shows actual server memory receipt',await page.locator('.memory-receipt a[href="#memory"]').count()>0);
    await context.close();
  }catch(error){
    report.errors.push({engine,error:error.stack});console.error(engine,error.message);
  }finally{await browser.close();}
}
await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,passed:report.checks.filter(x=>x.passed).length,errors:report.errors,toolWarnings:report.toolWarnings.length},null,2));
if(report.errors.length||report.checks.some(x=>!x.passed))process.exitCode=1;
