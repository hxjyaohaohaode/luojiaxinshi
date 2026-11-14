/** Final detail regressions against the owned loopback fixture, using real UI and APIs. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {browserExecutable} from './browser-runtime.mjs';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/frontend-finish-browser');
const engines=(process.env.UI_ENGINES||'chromium,firefox,webkit').split(','),checksPerEngine=6,timeout=12000;
const report={fixture:'Isolated real application APIs and synthetic accounts; no external recipients or providers.',network_fixture:{service_workers:'block',reason:'The monitor regression holds real GET responses; normal worker behavior remains covered by the existing PWA suites.'},status:'running',complete:false,passed:false,expected_checks:engines.length*checksPerEngine,active:null,checks:[],errors:[],headers:[],text_enlargement:[],draft_conflicts:[],monitor_drafts:[],requests:[]};
await fs.mkdir(out,{recursive:true});
async function save(){const file=path.join(out,'report.json');await fs.writeFile(file+'.tmp',JSON.stringify(report,null,2));await fs.rename(file+'.tmp',file);}
async function bounded(promise,label){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+' exceeded '+timeout+' ms')),timeout);})]);}finally{clearTimeout(timer);}}
const sha=value=>createHash('sha256').update(value).digest('hex');
await save();

function headerGeometry(){
  const heading=document.querySelector('.library-heading'),title=heading?.querySelector('h1'),receive=heading?.querySelector('a[href="#new"]'),search=document.querySelector('#library-search'),filter=document.querySelector('.library-refine>summary'),result=document.querySelector('#library-results'),first=result?.querySelector('.notice-card,.matter-library-card');
  const box=node=>{if(!node)return null;const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
  const describe=node=>{if(!node)return null;const rect=box(node),style=getComputedStyle(node),point={x:(rect.left+rect.right)/2,y:(rect.top+rect.bottom)/2},hit=document.elementFromPoint(point.x,point.y);return {rect,font_size:parseFloat(style.fontSize),line_height:style.lineHeight,visibility:style.visibility,display:style.display,class_name:node.className,scroll_width:node.scrollWidth,client_width:node.clientWidth,receives_pointer:!!hit&&(hit===node||node.contains(hit))};};
  return {viewport:{width:innerWidth,height:innerHeight},route:location.hash,content_busy:document.querySelector('#content')?.inert,results_busy:result?.getAttribute('aria-busy'),title:describe(title),receive:describe(receive),heading:box(heading),search:describe(search),filter:describe(filter),first_record:box(first),document_width:document.documentElement.scrollWidth,content_width:document.querySelector('#content')?.scrollWidth,content_client_width:document.querySelector('#content')?.clientWidth};
}

for(const engine of engines){
  const browser=await pw[engine].launch({headless:true,executablePath:browserExecutable(pw[engine])});
  const context=await browser.newContext({viewport:{width:1280,height:850},serviceWorkers:'block'}),page=await context.newPage();
  page.setDefaultTimeout(timeout);const errors=[];
  page.on('pageerror',error=>{const item={engine,error:error.message};errors.push(item);report.errors.push(item);process.exitCode=1;});
  const network=(kind,request,extra={})=>{const url=new URL(request.url());if(url.origin!==origin)return;report.requests.push({engine,kind,at:Date.now(),method:request.method(),path:url.pathname+url.search,...extra});if(report.requests.length>180)report.requests.splice(0,report.requests.length-180);};
  page.on('request',request=>network('request',request));page.on('response',response=>network('response',response.request(),{status:response.status(),from_service_worker:response.fromServiceWorker()}));page.on('requestfailed',request=>network('failed',request,{error:request.failure()?.errorText||'unknown'}));
  const api=async(route,method='GET',data,expected=200)=>{
    const current=await context.request.get(origin+'/api/session');assert.equal(current.status(),200);const session=await current.json();
    const response=await context.request.fetch(origin+'/api'+route,{method,headers:{Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf,...(data===undefined?{}:{'Content-Type':'application/json'})},...(data===undefined?{}:{data})});
    assert.equal(response.status(),expected,await response.text());return response.json();
  };
  const nav=async target=>{await page.evaluate(target=>{location.hash='#'+target;},target);await page.waitForFunction(target=>document.querySelector('#content')?.dataset.page===target&&!document.querySelector('#content')?.inert,target);};
  const login=async(username,password)=>{await context.clearCookies();await page.goto(origin+'/#login');await page.locator('[name=username]').fill(username);await page.locator('[name=password]').fill(password);await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();assert.equal((await api('/session')).user.username,username);};
  const check=async(name,work)=>{report.active={engine,name};await save();try{await work();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.stack||String(error)});throw error;}finally{await save();}};
  const responseFor=(pathname,method='GET')=>page.waitForResponse(response=>new URL(response.url()).pathname===pathname&&response.request().method()===method);
  const draftReady=()=>page.waitForFunction(()=>{const form=document.querySelector('[data-workspace-form="campus-publish"]');return form&&!form.inert&&form.getAttribute('aria-busy')!=='true'&&!form.querySelector('[data-campus-action="save-draft"]')?.disabled;});
  const saveDraft=async(form,id)=>{
    const previous=Number(await form.getAttribute('data-draft-version'));
    const [response]=await Promise.all([responseFor('/api/campus/drafts/'+id,'PUT'),form.locator('[data-campus-action=save-draft]').click()]);assert.equal(response.status(),200);
    await page.waitForFunction(({id,previous})=>{const form=document.querySelector('[data-workspace-form="campus-publish"]');return form?.dataset.draftId===id&&Number(form.dataset.draftVersion)>previous&&!form.querySelector('[data-campus-action="save-draft"]')?.disabled;},{id,previous});
    const data=await api('/campus/drafts/'+id);assert.equal(Number(await form.getAttribute('data-draft-version')),data.version);return data;
  };
  const conflictCopy=async label=>{
    await nav('campus/publish');let form=page.locator('[data-workspace-form="campus-publish"]');await form.waitFor();
    const title='末轮冲突 '+engine+' '+label,filename='原申请表-'+engine+'-'+label+'.txt';
    await form.locator('[name=audience]').selectOption('class');await form.locator('[name=grade]').fill('2026级');await form.locator('[name=class_name]').fill('试点一班');
    await form.locator('[name=title]').fill(title);await form.locator('[name=body]').fill('独立原文 '+title+'。这份原件属于隔离验收，不发送到外部服务。');
    await form.locator('[name=files]').setInputFiles({name:filename,mimeType:'text/plain',buffer:Buffer.from('原始附件 '+title)});
    const originalId=await form.getAttribute('data-draft-id'),first=await saveDraft(form,originalId);assert.equal(first.attachments.length,1);
    const remote=await api('/campus/drafts/'+originalId,'PUT',{version:first.version,title:'另一端已保存 '+title,body:first.body,audience:first.audience,grade:first.grade,class_name:first.class_name,keep_attachments:true,pending_attachment_names:[],valid_until:first.valid_until,reference_only:first.reference_only});
    const entry={engine,label,title,filename,original_id:originalId,original:first,external_update:remote,status:'running'};report.draft_conflicts.push(entry);await save();
    const [failed]=await Promise.all([responseFor('/api/campus/drafts/'+originalId,'PUT'),(async()=>{await form.locator('[name=title]').fill(title+' 本人新输入');await form.locator('[data-campus-action=save-draft]').click();})()]);
    entry.conflict_response={status:failed.status(),body:await failed.json()};assert.equal(failed.status(),409);
    await page.waitForFunction(()=>document.querySelector('[data-workspace-form="campus-publish"]')?.dataset.draftConflict==='1');
    const copiedResponse=page.waitForResponse(response=>{const u=new URL(response.url());return u.pathname.startsWith('/api/campus/drafts/')&&u.pathname!=='/api/campus/drafts/'+originalId&&response.request().method()==='PUT';});
    const [copyResponse]=await Promise.all([copiedResponse,form.locator('[data-campus-action=copy-draft]').click()]);assert.equal(copyResponse.status(),200);const copied=await copyResponse.json();entry.copy_response=copied;
    await page.waitForFunction(id=>document.querySelector('[data-workspace-form="campus-publish"]')?.dataset.draftId===id,copied.id);await draftReady();
    assert.notEqual(copied.id,originalId);assert.deepEqual(copied.attachments,[]);assert.deepEqual(copied.pending_attachment_names,[filename]);assert.equal(await form.getAttribute('data-missing-files'),'1');assert.match(await page.locator('#campus-missing-files').innerText(),new RegExp(filename.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    entry.original_after_copy=await api('/campus/drafts/'+originalId);assert.deepEqual(entry.original_after_copy,remote);await save();return {entry,form,id:copied.id};
  };
  try{
    await login('workflow.demo','Mvp-Verification-Only-2026');await nav('notices');
    await check('notification title and receive action share a compact row with independent usable controls',async()=>{
      for(const width of [320,390,1280]){
        await page.setViewportSize({width,height:width===320?740:850});
        await page.waitForFunction(()=>{const h=document.querySelector('.library-heading h1'),a=document.querySelector('.library-heading a'),r=a?.getBoundingClientRect(),hit=r?document.elementFromPoint((r.left+r.right)/2,(r.top+r.bottom)/2):null;return h&&!h.classList.contains('sr-only')&&a&&(hit===a||a.contains(hit))&&document.querySelector('#library-results')?.getAttribute('aria-busy')==='false';});
        const value=await page.evaluate(headerGeometry);report.headers.push({engine,...value});await save();
        assert.equal(value.content_busy,false);assert.equal(value.results_busy,'false');assert.ok(value.title.rect.width>0&&value.title.rect.height>0);assert.equal(value.title.visibility,'visible');assert.ok(!value.title.class_name.includes('sr-only'));
        assert.ok(Math.abs((value.title.rect.top+value.title.rect.bottom)/2-(value.receive.rect.top+value.receive.rect.bottom)/2)<=1.5);assert.ok(value.title.rect.right<=value.receive.rect.left-2);
        assert.ok(value.receive.rect.width>=43.9&&value.receive.rect.height>=43.9);assert.equal(value.receive.receives_pointer,true);assert.ok(value.search.rect.height>=43.9&&value.filter.rect.height>=43.9);
        assert.ok(value.document_width<=width+1&&value.content_width<=value.content_client_width+1);assert.ok(value.first_record,'The header is checked with actual notice content');
        await page.screenshot({path:path.join(out,engine+'-notices-'+width+'.png')});
      }
    });
    await check('actual doubled notification text remains readable and controls remain reachable at narrow widths',async()=>{
      for(const width of [320,390]){
        await page.setViewportSize({width,height:900});
        const scaled=await page.evaluate(()=>{const nodes=[...document.querySelectorAll('.library-heading h1,.library-heading a,#library-search,.library-refine>summary,#library-summary button,#library-summary select')];const values=nodes.map(node=>({node,size:parseFloat(getComputedStyle(node).fontSize),original:node.style.fontSize}));window.__finishTextSizes=values;for(const value of values)value.node.style.fontSize=(value.size*2)+'px';return values.map(value=>({tag:value.node.tagName,id:value.node.id,class_name:value.node.className,before:value.size,after:parseFloat(getComputedStyle(value.node).fontSize)}));});
        try{
          const header=await page.evaluate(headerGeometry),entry={engine,width,method:'Actual CSS font sizes on the notification heading and primary controls are doubled; this is not a claim of native browser zoom or physical assistive-technology testing.',scaled,geometry:header};report.text_enlargement.push(entry);await save();
          for(const item of scaled)assert.ok(Math.abs(item.after-item.before*2)<.1);assert.ok(header.title.rect.width>0&&header.title.rect.height>0);assert.ok(header.title.scroll_width<=header.title.client_width+1);
          for(const value of [header.title,header.receive,header.search,header.filter])assert.ok(value.rect.left>=-1&&value.rect.right<=width+1);
          assert.ok(header.document_width<=width+1&&header.content_width<=header.content_client_width+1);assert.ok(header.receive.rect.height>=43.9);
          await page.locator('.library-heading a').click({trial:true});await page.locator('#library-search').focus();assert.equal(await page.locator('#library-search').evaluate(node=>document.activeElement===node),true);
          await page.screenshot({path:path.join(out,engine+'-notices-text-200-'+width+'.png')});
        }finally{await page.evaluate(()=>{for(const value of window.__finishTextSizes||[])value.node.style.fontSize=value.original;delete window.__finishTextSizes;});}
      }
    });
    await page.setViewportSize({width:390,height:844});await login('pilot-counselor','PilotFixtureOnly2026!');
    await check('a conflicting publication draft preserves missing originals across copying and reload until explicit removal',async()=>{
      const {entry,id}=await conflictCopy('明确不附加');let form=page.locator('[data-workspace-form="campus-publish"]');const requests=[];
      const record=request=>{if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/campus/publications')requests.push(request.url());};page.on('request',record);
      try{await form.locator('[type=submit]').click();await page.locator('#toast.visible .toast-copy').filter({hasText:'请重新选择附件'}).waitFor();entry.blocked_publish_attempts=requests.length;assert.equal(requests.length,0);}finally{page.off('request',record);}
      await page.reload();await page.locator('.campus-drafts>summary').click();await page.locator('[data-campus-action=open-draft][data-id="'+id+'"]').click();
      await page.waitForFunction(id=>document.querySelector('[data-workspace-form="campus-publish"]')?.dataset.draftId===id,id);form=page.locator('[data-workspace-form="campus-publish"]');
      entry.after_reload=await api('/campus/drafts/'+id);assert.deepEqual(entry.after_reload.pending_attachment_names,[entry.filename]);assert.equal(await form.getAttribute('data-missing-files'),'1');assert.match(await form.locator('[name=title]').inputValue(),/本人新输入/);
      await page.locator('#campus-missing-files').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,engine+'-copied-draft-missing-files.png')});
      await form.locator('[data-campus-action=clear-files]').click();entry.after_explicit_removal=await saveDraft(form,id);assert.deepEqual(entry.after_explicit_removal.pending_attachment_names,[]);assert.deepEqual(entry.after_explicit_removal.attachments,[]);assert.equal(await form.getAttribute('data-missing-files'),'');assert.deepEqual(await api('/campus/drafts/'+entry.original_id),entry.external_update);entry.status='passed';
    });
    await check('reselecting a copied draft attachment permits one new publication while leaving the conflicting original unchanged',async()=>{
      const previous=await page.locator('[data-workspace-form="campus-publish"]').getAttribute('data-draft-id');await page.locator('[data-campus-action=new-draft]').click();
      await page.waitForFunction(previous=>{const form=document.querySelector('[data-workspace-form="campus-publish"]');return form&&form.dataset.draftId!==previous&&form.dataset.draftVersion==='0';},previous);await draftReady();
      const {entry,form,id}=await conflictCopy('重新选择');const name='重新选择-'+engine+'.txt';
      await form.locator('[name=files]').setInputFiles({name,mimeType:'text/plain',buffer:Buffer.from('本次本人重新选择的合成附件 '+engine)});
      entry.after_reselection=await saveDraft(form,id);assert.deepEqual(entry.after_reselection.pending_attachment_names,[]);assert.deepEqual(entry.after_reselection.attachments.map(file=>file.name),[name]);assert.equal(await form.getAttribute('data-missing-files'),'');
      const [published]=await Promise.all([responseFor('/api/campus/publications','POST'),(async()=>{await form.locator('[type=submit]').click();await page.locator('#dialog [data-action=accept-dialog]').click();})()]);
      assert.equal(published.status(),200);entry.publication=await published.json();await page.waitForFunction(()=>location.hash==='#campus/records'&&document.querySelector('#content')?.dataset.page==='campus/records'&&!document.querySelector('#content')?.inert);
      const saved=await api('/campus/publications?q='+encodeURIComponent(entry.copy_response.title));entry.publication_ids=saved.items.map(item=>item.id);assert.deepEqual(entry.publication_ids,[entry.publication.id]);assert.deepEqual(await api('/campus/drafts/'+entry.original_id),entry.external_update);entry.status='passed';
    });
    await login('pilot-site','PilotFixtureOnly2026!');await nav('settings');
    await check('monitor refresh and independent saves preserve both editable drafts including input made during a held real response',async()=>{
      await page.locator('[data-settings-category=account]').click();await page.locator('[data-action=settings-operations]').click();await page.locator('#open-operations-monitor').click();await page.locator('#monitor-settings').waitFor({state:'attached'});
      const before=await api('/admin/monitor'),entry={engine,status:'running',before,held_responses:[]};report.monitor_drafts.push(entry);await save();
      await page.locator('#monitor-settings').locator('..').locator(':scope > summary').click();
      const settings=page.locator('#monitor-settings'),expiry=page.locator('#monitor-expiry'),label='待保存期限-'+engine,stamp='2030-01-02T09:30';
      await settings.locator('[name=queue_age_minutes]').fill('777');await expiry.locator('[name=label]').fill(label);await expiry.locator('[name=expiry]').fill(stamp);
      let release,readyResolve,readyReject,holding=true;const gate=new Promise(resolve=>{release=resolve;}),ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;}),tasks=[];
      const handler=route=>{const work=(async()=>{
        if(route.request().method()!=='GET'||!holding){await route.continue();return;}
        const response=await route.fetch(),body=await response.body(),receipt={url:route.request().url(),status:response.status(),body_sha256:sha(body),state:'held'};entry.held_responses.push(receipt);readyResolve();await gate;
        try{await route.fulfill({response,body});receipt.state='fulfilled';}catch(error){receipt.state='failed';receipt.error=String(error);throw error;}
      })().catch(error=>{readyReject(error);throw error;});work.catch(()=>{});tasks.push(work);return work;};
      let primaryError;
      await page.route(origin+'/api/admin/monitor',handler);
      try{
        await page.locator('[data-monitor-scan]').click();await bounded(ready,'The actual monitor refresh response');
        entry.while_held={queue:await settings.locator('[name=queue_age_minutes]').inputValue(),label:await expiry.locator('[name=label]').inputValue(),expiry:await expiry.locator('[name=expiry]').inputValue(),scan_disabled:await page.locator('[data-monitor-scan]').isDisabled()};
        assert.equal(entry.while_held.scan_disabled,true);assert.equal(entry.while_held.queue,'777');assert.equal(await settings.locator('[name=queue_age_minutes]').isEditable(),true);
        await settings.locator('[name=queue_age_minutes]').fill('999');holding=false;release();await bounded(Promise.all(tasks),'Delivery of the held monitor response');
        await page.waitForFunction(()=>document.querySelector('#monitor-settings [name=queue_age_minutes]')?.value==='999'&&!document.querySelector('[data-monitor-scan]')?.disabled);
      }catch(error){primaryError=error;throw error;}finally{holding=false;release();try{try{await bounded(Promise.allSettled(tasks),'Monitor route cleanup');}finally{await page.unroute(origin+'/api/admin/monitor',handler);}}catch(error){entry.cleanup_error=String(error);if(!primaryError)throw error;}await save();}
      try{
        entry.after_scan={queue:await settings.locator('[name=queue_age_minutes]').inputValue(),label:await expiry.locator('[name=label]').inputValue(),expiry:await expiry.locator('[name=expiry]').inputValue(),expanded:await settings.evaluate(node=>node.closest('details').open)};
        assert.deepEqual(entry.after_scan,{queue:'999',label,expiry:stamp,expanded:true});assert.ok(entry.held_responses.length>0);for(const receipt of entry.held_responses){assert.equal(receipt.status,200);assert.equal(receipt.state,'fulfilled');}
        const [expiryResponse]=await Promise.all([responseFor('/api/admin/monitor/settings','PUT'),expiry.locator('[type=submit]').click()]);assert.equal(expiryResponse.status(),200);
        await page.waitForFunction(()=>document.querySelector('#monitor-expiry [name=label]')?.value===''&&!document.querySelector('#monitor-expiry [type=submit]')?.disabled);
        entry.after_expiry_save=await api('/admin/monitor');entry.expected_expiry=await page.evaluate(stamp=>new Date(stamp).toISOString(),stamp);assert.equal(await settings.locator('[name=queue_age_minutes]').inputValue(),'999');assert.equal(entry.after_expiry_save.settings.queue_age_minutes,before.settings.queue_age_minutes);assert.equal(Date.parse(entry.after_expiry_save.settings.credential_expiries[label]),Date.parse(entry.expected_expiry));
        await expiry.locator('[name=label]').fill('另一份未提交期限-'+engine);await expiry.locator('[name=expiry]').fill('2031-02-03T10:20');
        const [thresholdResponse]=await Promise.all([responseFor('/api/admin/monitor/settings','PUT'),settings.locator('[type=submit]').click()]);assert.equal(thresholdResponse.status(),200);
        await page.waitForFunction(()=>document.querySelector('#monitor-settings [name=queue_age_minutes]')?.value==='999'&&!document.querySelector('#monitor-settings [type=submit]')?.disabled);
        entry.after_threshold_save=await api('/admin/monitor');assert.equal(entry.after_threshold_save.settings.queue_age_minutes,999);assert.equal(await expiry.locator('[name=label]').inputValue(),'另一份未提交期限-'+engine);assert.equal(await expiry.locator('[name=expiry]').inputValue(),'2031-02-03T10:20');
        await expiry.locator('[name=label]').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,engine+'-monitor-unsaved-draft.png')});entry.status='passed';
      }finally{const current=await api('/admin/monitor');entry.fixture_cleanup=await api('/admin/monitor/settings','PUT',{...before.settings,expected_revision:current.settings_revision});await save();}
    });
    await check('the final detail flows finish with the declared worker precondition and no uncaught page errors',async()=>{
      assert.equal(await page.evaluate(()=>navigator.serviceWorker?.controller?.scriptURL||null),null);assert.deepEqual(errors,[]);assert.equal(report.checks.filter(item=>item.engine===engine).length,checksPerEngine-1);
    });
  }catch(error){report.status='failed';report.failure={engine,active:report.active,error:error.stack||String(error)};await page.screenshot({path:path.join(out,engine+'-failure.png')}).catch(()=>{});await save();process.exitCode=1;}
  finally{await context.close();await browser.close();await save();}
}
report.active=null;report.complete=report.checks.length===report.expected_checks;report.passed=report.complete&&!report.errors.length&&report.checks.every(item=>item.ok===true);report.status=report.passed?'passed':report.complete?'failed':'incomplete';await save();
console.log(JSON.stringify({expected:report.expected_checks,recorded:report.checks.length,passed:report.checks.filter(item=>item.ok).length,errors:report.errors,complete:report.complete,status:report.status}));if(!report.passed)process.exitCode=1;
