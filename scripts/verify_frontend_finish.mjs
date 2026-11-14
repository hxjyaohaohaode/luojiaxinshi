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
const report={fixture:'Isolated real application APIs and synthetic accounts; no external recipients or providers.',network_fixture:{service_workers:'block',reason:'The monitor and draft regressions hold real responses; normal worker behavior remains covered by the existing PWA suites.'},status:'running',complete:false,passed:false,expected_checks:engines.length*(checksPerEngine+1),active:null,checks:[],errors:[],headers:[],text_enlargement:[],notice_layouts:[],draft_conflicts:[],draft_attachment_races:[],monitor_drafts:[],requests:[]};
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

// Read the actual resize/entry state. This probe does not close the drawer,
// scroll the page, finish animations or change focus to make a photo pass.
function noticeLayout({width,height,phase,measurement='observation',wait=false}){
  const one=selector=>document.querySelector(selector),box=node=>{if(!node)return null;const r=node.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
  const describe=node=>node?{tag:node.tagName,id:node.id||null,class_name:typeof node.className==='string'?node.className:null}:null;
  const shell=one('.shell'),drawer=one('.sidebar'),workspace=one('.workspace'),content=one('#content'),results=one('#library-results');
  const controls={title:one('.library-heading h1'),receive:one('.library-heading a[href="#new"]'),search:one('#library-search'),filter:one('.library-refine>summary')};
  const targets=Object.fromEntries(Object.entries(controls).map(([name,node])=>{
    const rect=box(node),style=node?getComputedStyle(node):null,point=rect?{x:(rect.left+rect.right)/2,y:(rect.top+rect.bottom)/2}:null,hit=point?document.elementFromPoint(point.x,point.y):null,ancestry=[];
    for(let parent=node;parent;parent=parent.parentElement){const s=getComputedStyle(parent);ancestry.push({element:describe(parent),display:s.display,visibility:s.visibility,opacity:Number(s.opacity)});}
    return [name,{rect,display:style?.display||null,visibility:style?.visibility||null,font_size:style?parseFloat(style.fontSize):null,point,hit:describe(hit),receives_pointer:!!node&&!!hit&&(hit===node||node.contains(hit)),ancestry}];
  }));
  const active=[];
  for(const animation of document.getAnimations()){
    const target=animation.effect?.target,timing=animation.effect?.getComputedTiming?.();
    if(!(target instanceof Element)||!(animation.pending||animation.playState==='running')||!Number.isFinite(timing?.endTime))continue;
    if(!(target===shell||target===workspace||target===content||drawer?.contains(target)||content?.contains(target)))continue;
    const rectCount=target.getClientRects().length;let closedDetails=null;
    for(let parent=target.parentElement;parent;parent=parent.parentElement){
      if(parent.tagName!=='DETAILS'||parent.open)continue;
      const summary=[...parent.children].find(child=>child.tagName==='SUMMARY');
      if(!summary?.contains(target)){closedDetails=describe(parent);break;}
    }
    // Firefox can retain unstarted transitions for the non-rendered contents
    // of closed details. Keep their evidence, but still wait for every visible
    // transition, reveal transition and motion that has actually started.
    const dormant=animation.pending&&animation.currentTime===0&&animation.startTime===null;
    const hiddenPending=dormant&&!!animation.transitionProperty&&!['display','visibility','content-visibility'].includes(animation.transitionProperty)&&rectCount===0&&!!closedDetails;
    active.push({target:describe(target),play_state:animation.playState,pending:animation.pending,current_time:animation.currentTime,start_time:animation.startTime,end_time:timing.endTime,transition:animation.transitionProperty||null,rendering:{client_rect_count:rectCount,closed_details:closedDetails},blocks_readiness:!hiddenPending});
  }
  const drawerStyle=drawer?getComputedStyle(drawer):null,mobile=matchMedia('(max-width:850px)').matches,bounds={drawer:box(drawer),workspace:box(workspace),content:box(content),results:box(results),first_record:box(results?.querySelector('.notice-card,.matter-library-card'))};
  const checks={viewport:innerWidth===width&&innerHeight===height,route_ready:location.hash==='#notices'&&content?.dataset.page==='notices'&&!content.inert&&!content.closest('[inert]')&&results?.getAttribute('aria-busy')==='false',structure_present:!!shell&&!!drawer&&!!bounds.first_record,menu_closed:!!shell&&!shell.classList.contains('menu-open'),drawer_in_place:!mobile||(drawerStyle?.visibility==='hidden'&&!!bounds.drawer&&bounds.drawer.right<=1),finite_motion_finished:active.every(item=>!item.blocks_readiness),targets_visible:Object.values(targets).every(item=>item.rect?.width>0&&item.rect?.height>0&&item.ancestry.every(parent=>parent.display!=='none'&&parent.visibility==='visible'&&parent.opacity>=.999)),targets_receive_pointer:Object.values(targets).every(item=>item.receives_pointer)};
  const scroll=Object.fromEntries([['html',document.documentElement],['body',document.body],['shell',shell],['workspace',workspace],['content',content]].map(([name,node])=>[name,node?{left:node.scrollLeft,top:node.scrollTop,width:node.scrollWidth,height:node.scrollHeight,client_width:node.clientWidth,client_height:node.clientHeight}:null]));
  const snapshot={at_ms:performance.now(),phase,measurement,route:location.hash,viewport:{width:innerWidth,height:innerHeight},mobile,drawer:{class_name:drawer?.className||null,shell_class:shell?.className||null,visibility:drawerStyle?.visibility||null,transform:drawerStyle?.transform||null},bounds,targets,active_finite_animations:active,scroll,checks,ready:Object.values(checks).every(Boolean)};
  if(!wait)return snapshot;
  const key=JSON.stringify({phase,measurement,width,height,viewport:snapshot.viewport,bounds,targets,scroll,checks}),previous=window.__finishNoticeLayout,stableFrames=snapshot.ready?(previous?.key===key?previous.stable_frames+1:1):0;
  snapshot.stable_frames=stableFrames;const samples=previous?.phase===phase?previous.samples:[];if(previous?.key!==key)samples.push(snapshot);if(samples.length>24)samples.splice(1,samples.length-24);
  window.__finishNoticeLayout={phase,key,stable_frames:stableFrames,last:snapshot,samples};return snapshot.ready&&stableFrames>=2?snapshot:false;
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
  const layoutArgs=entry=>({width:entry.width,height:entry.height,phase:entry.phase});
  const beginLayout=async(phase,width,height)=>{const entry={engine,phase,width,height,status:'resizing',before_resize:await page.evaluate(noticeLayout,{phase,width,height})};report.notice_layouts.push(entry);await save();return entry;};
  const settleLayout=async(entry,beforeField='before_wait',settledField='settled')=>{entry[beforeField]=await page.evaluate(noticeLayout,{...layoutArgs(entry),measurement:beforeField});await save();const handle=await page.waitForFunction(noticeLayout,{...layoutArgs(entry),measurement:settledField,wait:true});try{entry[settledField]=await handle.jsonValue();}finally{await handle.dispose();}assert.equal(entry[settledField].ready,true);assert.ok(entry[settledField].stable_frames>=2);await save();};
  const capturedLayout=async entry=>{entry.after_capture=await page.evaluate(noticeLayout,layoutArgs(entry));assert.equal(entry.after_capture.ready,true,JSON.stringify(entry.after_capture));entry.status='passed';};
  const finishLayout=async(entry,stage='after_capture_or_failure')=>{entry.observation=await page.evaluate(()=>{const value=window.__finishNoticeLayout;return value?{phase:value.phase,last:value.last,samples:value.samples}:null;}).catch(error=>({error:error.message}));entry.final=await page.evaluate(noticeLayout,layoutArgs(entry)).catch(error=>({error:error.message}));entry.final_observation_stage=stage;if(entry.status!=='passed')entry.status='incomplete';await save();};
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
        const layout=await beginLayout('header-'+width,width,width===320?740:850);
        try{
        await page.setViewportSize({width,height:width===320?740:850});
        layout.after_resize=await page.evaluate(noticeLayout,layoutArgs(layout));
        await settleLayout(layout);
        await page.waitForFunction(()=>{const h=document.querySelector('.library-heading h1'),a=document.querySelector('.library-heading a'),r=a?.getBoundingClientRect(),hit=r?document.elementFromPoint((r.left+r.right)/2,(r.top+r.bottom)/2):null;return h&&!h.classList.contains('sr-only')&&a&&(hit===a||a.contains(hit))&&document.querySelector('#library-results')?.getAttribute('aria-busy')==='false';});
        const value=await page.evaluate(headerGeometry);report.headers.push({engine,...value});await save();
        assert.equal(value.content_busy,false);assert.equal(value.results_busy,'false');assert.ok(value.title.rect.width>0&&value.title.rect.height>0);assert.equal(value.title.visibility,'visible');assert.ok(!value.title.class_name.includes('sr-only'));
        assert.ok(Math.abs((value.title.rect.top+value.title.rect.bottom)/2-(value.receive.rect.top+value.receive.rect.bottom)/2)<=1.5);assert.ok(value.title.rect.right<=value.receive.rect.left-2);
        assert.ok(value.receive.rect.width>=43.9&&value.receive.rect.height>=43.9);assert.equal(value.receive.receives_pointer,true);assert.ok(value.search.rect.height>=43.9&&value.filter.rect.height>=43.9);
        assert.ok(value.document_width<=width+1&&value.content_width<=value.content_client_width+1);assert.ok(value.first_record,'The header is checked with actual notice content');
        await page.screenshot({path:path.join(out,engine+'-notices-'+width+'.png')});
        await capturedLayout(layout);
        }catch(error){layout.error=error.message;throw error;}finally{await finishLayout(layout);}
      }
    });
    await check('actual doubled notification text remains readable and controls remain reachable at narrow widths',async()=>{
      for(const width of [320,390]){
        const layout=await beginLayout('text-200-'+width,width,900);
        try{
        await page.setViewportSize({width,height:900});
        layout.after_resize=await page.evaluate(noticeLayout,layoutArgs(layout));
        const scaled=await page.evaluate(()=>{const nodes=[...document.querySelectorAll('.library-heading h1,.library-heading a,#library-search,.library-refine>summary,#library-summary button,#library-summary select')];const values=nodes.map(node=>({node,size:parseFloat(getComputedStyle(node).fontSize),original:node.style.fontSize}));window.__finishTextSizes=values;for(const value of values)value.node.style.fontSize=(value.size*2)+'px';return values.map(value=>({tag:value.node.tagName,id:value.node.id,class_name:value.node.className,before:value.size,after:parseFloat(getComputedStyle(value.node).fontSize)}));});
        try{
          await settleLayout(layout);
          const header=await page.evaluate(headerGeometry),entry={engine,width,method:'Actual CSS font sizes on the notification heading and primary controls are doubled; this is not a claim of native browser zoom or physical assistive-technology testing.',scaled,geometry:header};report.text_enlargement.push(entry);await save();
          for(const item of scaled)assert.ok(Math.abs(item.after-item.before*2)<.1);assert.ok(header.title.rect.width>0&&header.title.rect.height>0);assert.ok(header.title.scroll_width<=header.title.client_width+1);
          for(const value of [header.title,header.receive,header.search,header.filter])assert.ok(value.rect.left>=-1&&value.rect.right<=width+1);
          assert.ok(header.document_width<=width+1&&header.content_width<=header.content_client_width+1);assert.ok(header.receive.rect.height>=43.9);
          await page.locator('.library-heading a').click({trial:true});await page.locator('#library-search').focus();assert.equal(await page.locator('#library-search').evaluate(node=>document.activeElement===node),true);
          await settleLayout(layout,'before_capture','capture_settled');
          await page.screenshot({path:path.join(out,engine+'-notices-text-200-'+width+'.png')});
          await capturedLayout(layout);
        }finally{await page.evaluate(()=>{for(const value of window.__finishTextSizes||[])value.node.style.fontSize=value.original;delete window.__finishTextSizes;});}
        }catch(error){layout.error=error.message;throw error;}finally{await finishLayout(layout,'after_original_font_restoration_or_failure');}
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
      const previous=await page.locator('[data-workspace-form="campus-publish"]').getAttribute('data-draft-id');
      const drafts=page.locator('.campus-drafts');if(!await drafts.evaluate(node=>node.open))await drafts.locator(':scope > summary').click();
      const newDraft=drafts.locator('[data-campus-action=new-draft]');assert.equal(await newDraft.isVisible(),true);await newDraft.click();
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
    await check('an acknowledged draft save preserves later attachment removal and text until the next real save persists them',async()=>{
      await login('pilot-counselor','PilotFixtureOnly2026!');await nav('campus/publish');await draftReady();
      const form=page.locator('[data-workspace-form=campus-publish]'),id=await form.getAttribute('data-draft-id'),title='保存期间的附件选择 '+engine,filename='待移除原件-'+engine+'.txt';
      await form.locator('[name=audience]').selectOption('class');await form.locator('[name=grade]').fill('2026级');await form.locator('[name=class_name]').fill('试点一班');
      await form.locator('[name=title]').fill(title);await form.locator('[name=body]').fill('第一份合成正文 '+engine);await form.locator('[name=files]').setInputFiles({name:filename,mimeType:'text/plain',buffer:Buffer.from('本轮自行创建并准备移除的合成附件 '+engine)});
      const initial=await saveDraft(form,id);assert.deepEqual(initial.attachments.map(item=>item.name),[filename]);
      await form.locator('[data-campus-saved-files] details > summary').click();const keep=form.locator('[name=keep_attachments]');assert.equal(await keep.isChecked(),true);
      const entry={engine,id,status:'running',initial,writes:[],late_body:'在较早保存等待时继续填写的正文 '+engine};report.draft_attachment_races.push(entry);await save();
      let releaseFirst,releaseLater,firstResolve,firstReject,laterResolve,laterReject,primary;
      const firstGate=new Promise(resolve=>{releaseFirst=resolve;}),laterGate=new Promise(resolve=>{releaseLater=resolve;}),firstEntered=new Promise((resolve,reject)=>{firstResolve=resolve;firstReject=reject;}),laterEntered=new Promise((resolve,reject)=>{laterResolve=resolve;laterReject=reject;});laterEntered.catch(()=>{});
      const tasks=[],url=origin+'/api/campus/drafts/'+id;
      const handler=route=>{
        if(route.request().method()!=='PUT')return route.continue();
        const ordinal=entry.writes.length+1,receipt={ordinal,state:'received'};entry.writes.push(receipt);
        const task=(async()=>{
          // Parse the actual outgoing multipart body locally, without changing it.
          const request=route.request(),bytes=request.postDataBuffer(),parts=await new Response(bytes,{headers:{'Content-Type':request.headers()['content-type']}}).formData(),payload=JSON.parse(parts.get('data'));
          receipt.request_sha256=sha(bytes);receipt.snapshot={version:payload.version,title:payload.title,body:payload.body,keep_attachments:payload.keep_attachments,pending_attachment_names:payload.pending_attachment_names};
          if(ordinal>1){receipt.state='transport-held';laterResolve();await laterGate;}
          const response=await route.fetch({timeout}),body=await response.body(),value=JSON.parse(body.toString());
          receipt.response={status:response.status(),bytes:body.length,body_sha256:sha(body),version:value.version,attachments:value.attachments?.map(item=>item.name)};
          if(ordinal===1){entry.first_saved=value;receipt.state='response-held';firstResolve();await firstGate;}
          await route.fulfill({response,body});receipt.state='fulfilled';
        })().catch(error=>{firstReject(error);laterReject(error);throw error;});task.catch(()=>{});tasks.push(task);return task;
      };
      await page.route(url,handler);
      try{
        await form.locator('[name=title]').fill(title+' 已修改标题');
        await Promise.all([bounded(firstEntered,'The earlier actual draft response'),form.locator('[data-campus-action=save-draft]').click()]);await save();
        assert.equal(entry.writes[0].response.status,200);assert.equal(entry.writes[0].snapshot.keep_attachments,true);assert.deepEqual(entry.first_saved.attachments.map(item=>item.name),[filename]);
        await keep.uncheck();await form.locator('[name=body]').fill(entry.late_body);assert.equal(await keep.isChecked(),false);
        const firstDelivery=responseFor('/api/campus/drafts/'+id,'PUT');releaseFirst();await bounded(tasks[0],'Delivery of the earlier draft response');const delivered=await firstDelivery;assert.equal(delivered.status(),200);assert.equal(sha(await delivered.body()),entry.writes[0].response.body_sha256);
        await page.waitForFunction(({id,version})=>{const form=document.querySelector('[data-workspace-form=campus-publish]');return form?.dataset.draftId===id&&Number(form.dataset.draftVersion)===version&&!form.querySelector('[data-campus-action=save-draft]').disabled;},{id,version:entry.first_saved.version});
        entry.after_earlier_response={keep:await keep.isChecked(),details_open:await form.locator('[data-campus-saved-files] details').evaluate(node=>node.open),body:await form.locator('[name=body]').inputValue(),status:await form.locator('[data-campus-draft-status]').innerText()};
        assert.equal(entry.after_earlier_response.keep,false);assert.equal(entry.after_earlier_response.details_open,true);assert.equal(entry.after_earlier_response.body,entry.late_body);assert.doesNotMatch(entry.after_earlier_response.status,/^已保存第/);assert.match(entry.after_earlier_response.status,/较早修改已保存|正在保存草稿/);
        // Later writes remain at the real transport boundary while this UI state
        // is inspected; automatic saving cannot hide the earlier response race.
        entry.server_before_later_save=await api('/campus/drafts/'+id);assert.equal(entry.server_before_later_save.version,entry.first_saved.version);assert.deepEqual(entry.server_before_later_save.attachments.map(item=>item.name),[filename]);
        const finalButton=await form.locator('[data-campus-action=save-draft]').elementHandle();assert.ok(finalButton);
        await Promise.all([bounded(laterEntered,'The actual subsequent draft request'),form.locator('[data-campus-action=save-draft]').click()]);
        assert.equal(entry.writes[1].snapshot.keep_attachments,false);assert.equal(entry.writes[1].snapshot.body,entry.late_body);releaseLater();
        await page.waitForFunction(node=>!node.disabled,finalButton);await bounded(Promise.all(tasks),'Completion of the actual draft saves');
        entry.final_saved=await api('/campus/drafts/'+id);assert.ok(entry.final_saved.version>entry.first_saved.version);assert.equal(entry.final_saved.body,entry.late_body);assert.deepEqual(entry.final_saved.attachments,[]);assert.deepEqual(entry.final_saved.pending_attachment_names,[]);
        assert.equal(await form.locator('[name=keep_attachments]').getAttribute('type'),'hidden');assert.equal(await form.getAttribute('data-missing-files'),'');assert.match(await form.locator('[data-campus-draft-status]').innerText(),/已保存第.*0 份附件/);
        for(const receipt of entry.writes){assert.equal(receipt.response.status,200);assert.equal(receipt.state,'fulfilled');}assert.deepEqual(errors,[]);entry.status='passed';
      }catch(error){primary=error;entry.status='failed';entry.error=error.stack||String(error);throw error;}
      finally{
        releaseFirst();releaseLater();const cleanup=await Promise.allSettled([bounded(Promise.all(tasks),'Draft race response cleanup'),bounded(page.unroute(url,handler),'Draft race routing cleanup')]);
        entry.cleanup=cleanup.map(result=>({status:result.status,...(result.status==='rejected'?{error:String(result.reason)}:{})}));await save();
        if(!primary){const failed=cleanup.find(result=>result.status==='rejected');if(failed){entry.status='failed';entry.cleanup_error=String(failed.reason);await save();throw failed.reason;}}
      }
    });
  }catch(error){report.status='failed';report.failure={engine,active:report.active,error:error.stack||String(error)};await page.screenshot({path:path.join(out,engine+'-failure.png')}).catch(()=>{});await save();process.exitCode=1;}
  finally{await context.close();await browser.close();await save();}
}
report.active=null;report.complete=report.checks.length===report.expected_checks;report.passed=report.complete&&!report.errors.length&&report.checks.every(item=>item.ok===true);report.status=report.passed?'passed':report.complete?'failed':'incomplete';await save();
console.log(JSON.stringify({expected:report.expected_checks,recorded:report.checks.length,passed:report.checks.filter(item=>item.ok).length,errors:report.errors,complete:report.complete,status:report.status}));if(!report.passed)process.exitCode=1;
