/** Real cross-role campus UI, immutable publication versions and personal records. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
import {browserExecutable} from './browser-runtime.mjs';

const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/campus-administration-browser');
const engines=(process.env.UI_ENGINES||'chromium,firefox,webkit').split(','),timeout=12000,password='CampusAdministration2026!';
const names=[
  'the system administrator grants a college role and roster review changes only explicitly selected valid members',
  'publishing from the college workspace delivers the reviewed original and attachment without creating a personal task',
  'a recipient creates and cancels a personal task before official changes without exposing it to the publisher',
  'official correction retains the recipient notice and personal record while showing the new source revision',
  'withdrawal and formal restoration create separate official versions without reactivating the recipient task',
  'rolling back an older official version creates a new history entry with the original attachment bytes',
  'a newly authorized member receives an explicitly confirmed current-version backfill without duplicate delivery',
  'official lifecycle claims require selected source evidence and explicit personal identity verification',
  'a concurrent lifecycle update preserves the open form without overwriting the newer server record',
  'member-import audit filtering and cursor pagination show real authorized changes without repeating rows',
  'the campus administration flows retain independent owners and finish without uncaught page errors',
];
const report={fixture:'Separate synthetic owners per engine. Registration uses the real challenge/proof/register APIs and local captured codes only; role assignment, selected roster commit, publication versions, personal task editing, lifecycle and audit navigation use real UI controls. Audit pagination is prepared with 101 actual versioned membership changes, never fabricated database rows.',expected_checks:engines.length*names.length,names,status:'running',complete:false,passed:false,checks:[],errors:[],actors:[],receipts:[],roster:[],publications:[],personal_records:[],lifecycle:[],audit:[],requests:[]};
await fs.mkdir(out,{recursive:true});
const sha=value=>createHash('sha256').update(value).digest('hex');
async function save(){const file=path.join(out,'report.json');await fs.writeFile(file+'.tmp',JSON.stringify(report,null,2));await fs.rename(file+'.tmp',file);}
await save();

for(const [engineIndex,engine] of engines.entries()){
  const browser=await pw[engine].launch({headless:true,executablePath:browserExecutable(pw[engine])});
  const actors=[],pageErrors=[],tag='学院完整链 '+engine+' '+randomUUID().slice(0,8),className='独立验收班-'+engine+'-'+randomUUID().slice(0,6);
  let pid,nid,personal,initial,versionTwo;
  async function actor(label,existing=false){
    const context=await browser.newContext({viewport:{width:1280,height:850},locale:'zh-CN'}),page=await context.newPage();
    const value={label,context,page,username:existing?'pilot-site':'adm-'+engine+'-'+label+'-'+randomUUID().slice(0,6),owner:null};actors.push(value);
    page.setDefaultTimeout(timeout);page.setDefaultNavigationTimeout(45000);
    page.on('pageerror',error=>{const item={engine,actor:label,error:error.message};pageErrors.push(item);report.errors.push(item);process.exitCode=1;});
    page.on('request',request=>{const url=new URL(request.url());if(url.origin!==origin)return;report.requests.push({engine,actor:label,at:Date.now(),method:request.method(),path:url.pathname+url.search});if(report.requests.length>260)report.requests.splice(0,report.requests.length-260);});
    return value;
  }
  const site=await actor('site',true),manager=await actor('manager'),student=await actor('student'),late=await actor('late'),spare=await actor('spare');
  const api=async(who,route,{method='GET',data,expected=200}={})=>{
    const headers={Origin:origin,'X-Requested-With':'campus-notice'};
    if(method!=='GET'){
      const response=await who.context.request.get(origin+'/api/session',{timeout});
      if(response.ok()){const session=await response.json();headers['X-CSRF-Token']=session.csrf;headers['X-Workspace-Owner']=session.user.id;}
      else assert.equal(response.status(),401,await response.text());
    }
    const response=await who.context.request.fetch(origin+'/api'+route,{method,headers,timeout,...(data===undefined?{}:{data})}),text=await response.text();
    assert.equal(response.status(),expected,text);return text?JSON.parse(text):null;
  };
  const responseFor=(who,pathname,method='POST',query=null)=>who.page.waitForResponse(response=>{
    const url=new URL(response.url());return url.origin===origin&&url.pathname==='/api'+pathname&&response.request().method()===method&&(!query||query(url.searchParams));
  });
  async function auditPagination(who,direction,query,entry){
    const id=engine+'-'+direction,detail={engine,action:direction,timeout_ms:timeout,started_at:Date.now(),status:'running',native_events:[],network:[],response_wait:{status:'not_started'},click:{status:'not_started'},cleanup:null};
    (entry.pagination_actions||=[]).push(detail);
    const requests=new Map();let sequence=0,failed=false,response;
    const requestInfo=request=>{
      const url=new URL(request.url());if(url.origin!==origin||request.method()!=='GET'||!(url.pathname.startsWith('/api/campus/')||url.pathname==='/api/proactive/revision'))return null;
      if(!requests.has(request))requests.set(request,requests.size+1);
      return {request_id:requests.get(request),method:request.method(),path:url.pathname+url.search,matches_waiter:url.pathname==='/api/campus/audit'&&query(url.searchParams)};
    };
    const record=(kind,request,extra={})=>{const info=requestInfo(request);if(info)detail.network.push({sequence:++sequence,kind,at:Date.now(),...info,...extra});};
    const onRequest=request=>record('request',request),onResponse=value=>record('response',value.request(),{status:value.status(),from_service_worker:value.fromServiceWorker()}),onFailure=request=>record('requestfailed',request,{error:request.failure()?.errorText||'unknown'});
    const observe=(name,work)=>{
      const value=detail[name];value.status='pending';value.started_at=Date.now();
      let promise;try{promise=work();}catch(error){promise=Promise.reject(error);}
      return Promise.resolve(promise).then(result=>{value.status='fulfilled';value.finished_at=Date.now();if(name==='response_wait')value.response={...requestInfo(result.request()),status:result.status()};return result;},error=>{value.status='rejected';value.finished_at=Date.now();value.error=error.stack||String(error);throw error;});
    };
    who.page.on('request',onRequest);who.page.on('response',onResponse);who.page.on('requestfailed',onFailure);
    try{
      await who.page.evaluate(id=>{
        if(window.__campusAuditPagination)throw Error('Another pagination diagnostic is still active');
        const types=['pointerdown','mousedown','pointerup','mouseup','click','pointercancel'],events=[],ids=new WeakMap();let next=0,down=null;
        const key=node=>{if(!node)return null;if(!ids.has(node))ids.set(node,++next);return ids.get(node);};
        const describe=node=>node instanceof Element?{node_id:key(node),tag:node.tagName,id:node.id||null,action:node.getAttribute('data-campus-action')}:null;
        const listener=event=>{
          const target=event.target instanceof Element?event.target:null,control=target?.closest('[data-campus-action]')||null;
          if(event.type==='pointerdown'||event.type==='mousedown'&&!down)down=control;
          events.push({sequence:events.length+1,type:event.type,at:Date.now(),performance_ms:performance.now(),trusted:event.isTrusted,button:event.button??null,pointer_type:event.pointerType||null,x:event.clientX??null,y:event.clientY??null,target:describe(target),control:describe(control),down_target:describe(down),down_connected:down?down.isConnected:null,same_down_target:down?control===down:null,route:location.hash});
        };
        window.__campusAuditPagination={id,types,events,listener};
        for(const type of types)document.addEventListener(type,listener,{capture:true,passive:true});
      },id);
      const outcomes=await Promise.allSettled([observe('response_wait',()=>responseFor(who,'/campus/audit','GET',query)),observe('click',()=>who.page.locator('[data-campus-action=audit-'+direction+']').click())]);
      const failures=outcomes.map((value,index)=>value.status==='rejected'?{operation:index===0?'response_wait':'click',error:value.reason}:null).filter(Boolean);
      if(failures.length)throw new AggregateError(failures.map(value=>value.error),'Audit '+direction+' failed: '+failures.map(value=>value.operation+': '+(value.error?.message||String(value.error))).join('; '));
      response=outcomes[0].value;detail.status='observed';
    }catch(error){failed=true;detail.status='failed';detail.error=error.stack||String(error);throw error;}
    finally{
      who.page.off('request',onRequest);who.page.off('response',onResponse);who.page.off('requestfailed',onFailure);
      try{
        const captured=await who.page.evaluate(id=>{const value=window.__campusAuditPagination;if(!value||value.id!==id)return {removed:false,events:[]};try{return {removed:true,events:value.events};}finally{for(const type of value.types)document.removeEventListener(type,value.listener,true);delete window.__campusAuditPagination;}},id);
        detail.native_events=captured.events;detail.cleanup={network_listeners_removed:true,native_listeners_removed:captured.removed};
        if(!captured.removed)throw Error('Native pagination diagnostic was not available for collection');
      }catch(error){detail.cleanup={network_listeners_removed:true,native_listeners_removed:false,error:error.stack||String(error)};if(!failed)detail.status='diagnostic-failed';}
      detail.finished_at=Date.now();await save();
      if(!failed&&detail.status==='diagnostic-failed')throw Error('Pagination diagnostic cleanup failed: '+detail.cleanup.error);
    }
    return response;
  }
  async function action(who,pathname,method,run,expected=200){
    const [response]=await Promise.all([responseFor(who,pathname,method),run()]),text=await response.text();
    report.receipts.push({engine,actor:who.label,path:pathname,method,status:response.status(),body_sha256:sha(text),at:Date.now()});await save();
    assert.equal(response.status(),expected,text);return text?JSON.parse(text):null;
  }
  async function submitForm(who,pathname,form,{method='POST',expected=200}={}){
    const submitted=await form.elementHandle();assert.ok(submitted);
    const result=await action(who,pathname,method,()=>form.locator('[type=submit]').click(),expected);
    // The real handler releases its original form only after its render or
    // error path finishes. A successful HTTP response alone is not that signal.
    await who.page.waitForFunction(node=>node.getAttribute('aria-busy')!=='true'&&!node.inert,submitted);
    return result;
  }
  const ready=who=>who.page.waitForFunction(()=>{const content=document.querySelector('#content');return content&&!content.inert;});
  async function nav(who,target){
    if(new URL(who.page.url()).hash==='#'+target)await who.page.reload({waitUntil:'domcontentloaded'});
    else await who.page.goto(origin+'/#'+target,{waitUntil:'domcontentloaded'});
    await who.page.waitForFunction(target=>{const content=document.querySelector('#content');return content?.dataset.page===target&&!content.inert;},target);
  }
  async function login(who,secret=password){
    await who.context.clearCookies();await who.page.goto(origin+'/#login');
    await who.page.locator('[name=username]').fill(who.username);await who.page.locator('[name=password]').fill(secret);
    const result=await action(who,'/auth/login','POST',()=>who.page.locator('#auth-form [type=submit]').click());await ready(who);
    if(who.owner)assert.equal(result.session.user.id,who.owner);who.owner=result.session.user.id;
  }
  async function register(who,index){
    const phone='1399900'+String(8300+engineIndex*10+index);
    const challenge=await api(who,'/auth/challenges',{method:'POST',data:{purpose:'register',channel:'sms',destination:phone}});
    const captured=await api(who,'/fixture/pilot-otp/'+challenge.challenge_id);assert.equal(captured.synthetic,true);assert.match(captured.code,/^\d{6}$/);
    const proof=await api(who,'/auth/verify',{method:'POST',data:{challenge_id:challenge.challenge_id,code:captured.code}});
    const registered=await api(who,'/auth/register',{method:'POST',data:{username:who.username,password,display_name:'学院验收 '+engine+' '+who.label,campus_role:who===manager?'teacher':'student',accepted_terms:true,verification_token:proof.verification_token}});
    who.owner=registered.session.user.id;report.actors.push({engine,actor:who.label,username:who.username,owner:who.owner,phone,setup:'Real API registration with a captured synthetic challenge; not counted as a registration UI assertion.'});
  }
  async function chooseContext(who,value){
    const picker=who.page.locator('#workspace-context');await picker.waitFor();
    if(await picker.inputValue()!==value){await action(who,'/profile','PATCH',()=>picker.selectOption(value));await ready(who);}
    assert.equal(await picker.inputValue(),value);
  }
  async function reveal(who,selector){
    const control=who.page.locator(selector).first();await control.waitFor({state:'attached'});
    while(await control.locator('xpath=ancestor::details[not(@open)]').count())await control.locator('xpath=ancestor::details[not(@open)]').first().locator(':scope > summary').click();
    await control.waitFor();return control;
  }
  async function closeDialog(who){const close=who.page.locator('#dialog .dialog-head > [data-action="close-dialog"]');assert.equal(await close.count(),1);await close.click();await who.page.locator('#dialog').waitFor({state:'hidden'});}
  async function memberUi(who,target,role,{grade='',class_name=''}={}){
    await nav(who,'campus/members');const form=who.page.locator('[data-workspace-form=campus-member]');
    await who.page.locator('.campus-member-editor>summary').click();await form.locator('[name=username]').fill(target.username);await form.locator('[name=role]').selectOption(role);
    if(role==='student'){await form.locator('[name=grade]').fill(grade);await form.locator('[name=class_name]').fill(class_name);}
    const result=await submitForm(who,'/campus/members/'+target.username,form,{method:'PUT'});
    await who.page.locator('[data-campus-member-row]').filter({hasText:target.username}).waitFor();return result;
  }
  async function eventually(label,read,predicate,observations){
    const deadline=Date.now()+timeout;let last;
    do{last=await read();observations?.push({at:Date.now(),value:structuredClone(last)});if(predicate(last))return last;
      await new Promise(resolve=>setTimeout(resolve,100));
    }while(Date.now()<deadline);
    throw Error(label+' did not reach its declared state within '+timeout+' ms: '+JSON.stringify(last));
  }
  async function received(who,version,entry){
    const observations=[];entry.delivery_observations=observations;
    const item=await eventually('The actual recipient publication version',async()=>{
      const result=await api(who,'/notices/page?q='+encodeURIComponent(tag)+'&intent=all&sort=collected');
      return {total:result.total,items:result.items.map(n=>({id:n.id,publication_context:n.publication_context}))};
    },result=>result.items.some(item=>item.publication_context?.publication_id===pid&&item.publication_context.version===version),observations);
    const owned=item.items.filter(item=>item.publication_context?.publication_id===pid);assert.equal(owned.length,1);
    const detail=await api(who,'/notices/'+owned[0].id);assert.equal(detail.publication_context.version,version);assert.equal(detail.publication_context.publication_id,pid);return detail;
  }
  const persistentTask=task=>({id:task.id,notice_id:task.notice_id,version:task.version,status:task.status,data:task.data});
  async function personalUnchanged(entry){const result=await api(student,'/tasks/'+personal.id+'/workflow');entry.personal=persistentTask(result.task);assert.deepEqual(entry.personal,personal);}
  async function publicationForm(kind,fields){
    await manager.page.locator(`[data-campus-action=${kind}][data-id="${pid}"]`).click();
    const form=manager.page.locator(`[data-workspace-form=campus-${kind}]`);await form.waitFor();
    for(const [name,value]of Object.entries(fields))await form.locator('[name='+name+']').fill(value);
    return form;
  }
  async function currentPublication(version){
    const result=await api(manager,'/campus/publications/'+pid);assert.equal(result.version,version);return result;
  }
  async function recordVisible(version,state='published'){
    const row=manager.page.locator('[data-campus-publication="'+pid+'"]');await row.waitFor();
    await manager.page.waitForFunction(({pid,state})=>{const row=document.querySelector('[data-campus-publication="'+pid+'"]');return row&&row.innerText.includes(state==='withdrawn'?'已撤回':'已发布')&&!document.querySelector('#dialog')?.open;},{pid,state});
    return currentPublication(version);
  }
  async function showRecipientRevision(entry,text){
    await nav(student,'notice/'+nid);assert.ok((await student.page.locator('.notice-primary h1').innerText()).includes(tag));
    const source=await reveal(student,'.intake-update-text');
    if(text){const target=student.page.locator('.intake-update-text').filter({hasText:text}).last();await target.waitFor({state:'attached'});while(await target.locator('xpath=ancestor::details[not(@open)]').count())await target.locator('xpath=ancestor::details[not(@open)]').first().locator(':scope>summary').click();assert.ok((await target.innerText()).includes(text));}
    entry.visible_revision_text=await source.innerText();await personalUnchanged(entry);
  }
  async function openLifecycle(){
    await nav(student,'notice/'+nid);if(!await student.page.locator('.notice-actions-menu').isVisible())await student.page.locator('.notice-actions>summary').click();
    await student.page.locator('[data-action=notice-lifecycle]').first().click();await student.page.locator('#notice-lifecycle-form').waitFor();return student.page.locator('#notice-lifecycle-form');
  }
  const check=async(index,work)=>{const name=names[index];report.active={engine,name};await save();try{await work();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.stack||String(error)});throw error;}finally{await save();}};
  try{
    console.log('Campus administration: '+engine);
    for(const [index,who]of [manager,student,late,spare].entries())await register(who,index);
    assert.equal(new Set([manager,student,late,spare].map(who=>who.owner)).size,4);
    await login(site,'PilotFixtureOnly2026!');await chooseContext(site,'system');
    await check(0,async()=>{
      assert.equal((await api(manager,'/campus/context')).membership,null,'A self-declared teacher is not an authorized college publisher');
      const assigned=await memberUi(site,manager,'college_admin');assert.equal(assigned.membership.role,'college_admin');assert.equal(assigned.membership.college_id,'sres');
      await login(manager);await chooseContext(manager,'college');await nav(manager,'campus/members');
      await manager.page.locator('[data-campus-action=roster]').click();
      const rows=[{username:student.username,role:'student',grade:'2026',class_name:className},{username:late.username,role:'student',grade:'2026',class_name:className},{username:'missing-'+engine+'-'+randomUUID().slice(0,6),role:'student',grade:'2026',class_name:className}];
      await manager.page.locator('#campus-roster-input [name=roster]').fill(JSON.stringify(rows));
      const preview=await action(manager,'/campus/roster/preview','POST',()=>manager.page.locator('#campus-roster-input [type=submit]').click());
      const entry={engine,assigned,rows,preview,status:'running'};report.roster.push(entry);await save();
      assert.equal(preview.valid,2);assert.equal(preview.invalid,1);assert.equal(preview.items[0].normalized.grade,'2026级');
      const review=manager.page.locator('#campus-roster-review');await review.waitFor();assert.equal(await review.locator('[name=roster_row][value="2"]').isDisabled(),true);
      await review.locator('[name=roster_row][value="1"]').uncheck();await review.locator('[name=reviewed]').check();
      const committed=await action(manager,'/campus/roster/commit','POST',()=>review.locator('[type=submit]').click());entry.committed=committed;
      assert.deepEqual(committed.indices,[0]);assert.equal(committed.changed,1);await manager.page.locator('.roster-receipt').waitFor();assert.match(await manager.page.locator('.roster-receipt').innerText(),new RegExp(student.username));
      entry.student=await api(student,'/campus/context');entry.unselected=await api(late,'/campus/context');assert.equal(entry.student.membership.grade,'2026级');assert.equal(entry.student.membership.class_name,className);assert.equal(entry.unselected.membership,null);
      await manager.page.screenshot({path:path.join(out,engine+'-roster-selected.png')});await closeDialog(manager);entry.status='passed';
      await login(student);await login(late);
    });
    await check(1,async()=>{
      await manager.page.setViewportSize({width:390,height:844});await nav(manager,'campus/publish');
      const form=manager.page.locator('[data-workspace-form=campus-publish]');await form.locator('[name=audience]').selectOption('class');await form.locator('[name=grade]').fill('2026级');await form.locator('[name=class_name]').fill(className);
      const body='【合成官方结果】'+tag+'。本次学院项目正式结果已经公布，'+student.username+' 已入选。请本人核对身份后领取材料；领取地点为学院一楼。此文本仅作隔离界面验收。';
      const attachment={name:'结果原件-'+engine+'.txt',bytes:Buffer.from('合成原件 '+tag+'：请核对本人身份后领取材料。')};
      await form.locator('[name=title]').fill(tag);await form.locator('[name=body]').fill(body);await form.locator('[name=files]').setInputFiles({name:attachment.name,mimeType:'text/plain',buffer:attachment.bytes});
      let review;
      const published=await action(manager,'/campus/publications','POST',async()=>{
        review=await action(manager,'/campus/audience-review','POST',()=>form.locator('[type=submit]').click());
        await manager.page.locator('#dialog [data-action=accept-dialog]').waitFor();assert.match(await manager.page.locator('#dialog').innerText(),new RegExp('学生 '+review.students+' 人'));
        await manager.page.locator('#dialog [data-action=accept-dialog]').click();
      });
      pid=published.id;initial={title:tag,body,attachment_name:attachment.name,attachment_sha256:sha(attachment.bytes)};
      const entry={engine,phase:'published',review,result:published,original:initial,status:'running'};report.publications.push(entry);assert.equal(published.version,1);assert.equal(published.state,'published');assert.equal(published.attachments.length,1);
      await manager.page.waitForFunction(()=>location.hash==='#campus/records'&&!document.querySelector('#content')?.inert);await recordVisible(1);
      const n=await received(student,1,entry);nid=n.id;entry.notice_id=nid;assert.deepEqual(n.tasks,[]);assert.equal((await api(late,'/notices/page?q='+encodeURIComponent(tag))).total,0);
      const source=n.sources.find(source=>source.name===attachment.name);assert.ok(source);const downloaded=await student.context.request.get(origin+'/api/notices/'+nid+'/sources/'+source.id+'/download');assert.equal(downloaded.status(),200);entry.recipient_original_sha256=sha(await downloaded.body());assert.equal(entry.recipient_original_sha256,initial.attachment_sha256);
      await nav(student,'notice/'+nid);assert.equal(await student.page.locator('.notice-primary h1').innerText(),tag);const originals=student.page.locator('.notice-originals');if(!await originals.evaluate(node=>node.open))await originals.locator(':scope>summary').click();assert.ok((await originals.innerText()).includes(attachment.name));
      await manager.page.screenshot({path:path.join(out,engine+'-published-mobile.png')});entry.status='passed';
    });
    await check(2,async()=>{
      let n=await api(student,'/notices/'+nid);
      // Notice responses expose an integer flag; the materials request uses a boolean.
      assert.ok(n.materials_complete===0||n.materials_complete===1,'materials_complete must be the integer flag 0 or 1');
      if(n.materials_complete===0){await action(student,'/notices/'+nid+'/materials','POST',async()=>{await(await reveal(student,'[data-action=materials]')).click();await student.page.locator('#dialog [data-action=accept-dialog]').click();});await student.page.waitForFunction(()=>document.querySelector('[data-action=materials]')?.textContent.includes('改为材料未齐'));}
      assert.equal((await api(student,'/notices/'+nid)).materials_complete,1);
      await action(student,'/notices/'+nid+'/manual','POST',()=>student.page.locator('[data-action=manual]').click());await student.page.locator('[data-action=add-task]').click();
      const editor=student.page.locator('[data-editor]').first();await(await reveal(student,'[data-editor] [name=title]')).fill('本人核对与领取 '+tag);
      await(await reveal(student,'[data-editor] [name=notes]')).fill('本人私有办理备注 '+student.username);await(await reveal(student,'#draft-form [name=reviewed]')).check();
      const confirmed=await submitForm(student,'/notices/'+nid+'/confirm',student.page.locator('#draft-form'));assert.equal(confirmed.task_ids.length,1);
      const tid=confirmed.task_ids[0];await nav(student,'tasks');await(await reveal(student,'[data-id="'+tid+'"][data-action=edit-task]')).click();await student.page.locator('#task-form').waitFor();
      await student.page.locator('#task-form [name=status]').selectOption('cancelled');await student.page.locator('#task-form [name=reason]').fill('本人暂不办理；后续公告不得替我重新开启');
      await submitForm(student,'/tasks/'+tid,student.page.locator('#task-form'),{method:'PUT'});await student.page.locator('#dialog').waitFor({state:'hidden'});
      personal=persistentTask((await api(student,'/tasks/'+tid+'/workflow')).task);assert.equal(personal.status,'cancelled');assert.equal(personal.data.notes,'本人私有办理备注 '+student.username);
      assert.equal((await manager.context.request.get(origin+'/api/tasks/'+tid+'/workflow')).status(),404);report.personal_records.push({engine,record:personal,publisher_read_status:404,status:'passed'});
    });
    await manager.page.setViewportSize({width:1280,height:850});
    await check(3,async()=>{
      await nav(manager,'campus/records');const title=tag+' 正式更正',body=initial.body+' 更正：领取地点调整为学院二楼。';
      const form=await publicationForm('correct',{title,body});assert.equal(await form.locator('[name=keep_attachments]').isChecked(),true);
      const attachment={name:'更正说明-'+engine+'.txt',bytes:Buffer.from('更正原件 '+tag+'：领取地点调整为学院二楼。')};await form.locator('[name=files]').setInputFiles({name:attachment.name,mimeType:'text/plain',buffer:attachment.bytes});
      const result=await submitForm(manager,'/campus/publications/'+pid+'/correct',form);assert.equal(result.version,2);versionTwo=await recordVisible(2);
      const entry={engine,phase:'corrected',result,detail:versionTwo,status:'running'};report.publications.push(entry);assert.equal(versionTwo.attachments.length,2);assert.equal(versionTwo.change_summary.body_changed,true);assert.ok(versionTwo.change_summary.attachments_added.includes(attachment.name));
      const n=await received(student,2,entry);assert.equal(n.id,nid);assert.ok(n.pending_intake_updates>=1);await showRecipientRevision(entry,'领取地点调整为学院二楼');entry.status='passed';
    });
    await check(4,async()=>{
      const reason='合成撤回：结果需要重新复核 '+tag;let form=await publicationForm('withdraw',{reason});
      const withdrawn=await submitForm(manager,'/campus/publications/'+pid+'/withdraw',form);assert.equal(withdrawn.version,3);assert.equal(withdrawn.state,'withdrawn');await recordVisible(3,'withdrawn');
      const entry={engine,phase:'withdrawn',result:withdrawn,status:'running'};report.publications.push(entry);assert.equal((await received(student,3,entry)).id,nid);await showRecipientRevision(entry,reason);entry.status='passed';
      form=await publicationForm('restore',{title:tag+' 正式恢复',body:initial.body+' 正式复核已完成，现恢复该结果通知。',reason:'已经完成正式复核；本次恢复建立新版本。'});assert.equal(await form.locator('[name=keep_attachments]').isChecked(),false);
      await form.locator('[name=keep_attachments]').check();const restored=await submitForm(manager,'/campus/publications/'+pid+'/restore',form);assert.equal(restored.version,4);assert.equal(restored.state,'published');
      const detail=await recordVisible(4);assert.equal(detail.attachments.length,2);const recovery={engine,phase:'restored',result:restored,detail,status:'running'};report.publications.push(recovery);
      assert.equal((await received(student,4,recovery)).id,nid);await showRecipientRevision(recovery,'正式复核已完成');recovery.status='passed';
    });
    await check(5,async()=>{
      await manager.page.locator('[data-campus-action=publication-detail][data-id="'+pid+'"]').click();await manager.page.locator('#dialog details>summary').filter({hasText:'正式版本记录'}).click();
      await manager.page.locator('[data-campus-action=rollback-version][data-version="1"]').click();const form=manager.page.locator('[data-workspace-form=campus-rollback]');await form.waitFor();assert.equal(await form.getAttribute('data-version'),'4');assert.equal(await form.getAttribute('data-target-version'),'1');
      await form.locator('[name=reason]').fill('以第一版原文与附件发布新的正式更正，完整历史继续保留。');const result=await submitForm(manager,'/campus/publications/'+pid+'/rollback',form);assert.equal(result.version,5);
      const detail=await recordVisible(5);assert.equal(detail.title,initial.title);assert.equal(detail.body,initial.body);assert.deepEqual(detail.attachments.map(file=>file.name),[initial.attachment_name]);assert.deepEqual([...detail.history].map(item=>item.version).sort((a,b)=>a-b),[1,2,3,4,5]);assert.equal(detail.version_context.target_version,1);assert.equal(detail.version_context.kind,'rollback');
      const original=detail.history.find(item=>item.version===1).attachments[0],originalResponse=await manager.context.request.get(origin+original.download_url);assert.equal(originalResponse.status(),200);assert.equal(sha(await originalResponse.body()),initial.attachment_sha256);
      const denied=await student.context.request.get(origin+original.download_url);assert.equal(denied.status(),403);
      const entry={engine,phase:'rollback',result,detail,manager_original_status:200,student_management_original_status:403,status:'running'};report.publications.push(entry);assert.equal((await received(student,5,entry)).id,nid);await personalUnchanged(entry);
      await manager.page.locator('[data-campus-action=publication-detail][data-id="'+pid+'"]').click();await manager.page.locator('#dialog details>summary').filter({hasText:'正式版本记录'}).click();assert.equal(await manager.page.locator('#dialog h4').filter({hasText:/第 \d+ 版/}).count(),5);assert.match(await manager.page.locator('#dialog').innerText(),/本人打开[\s\S]*未知/);
      await manager.page.screenshot({path:path.join(out,engine+'-official-five-versions.png')});await closeDialog(manager);entry.status='passed';
    });
    await check(6,async()=>{
      assert.equal((await api(late,'/notices/page?q='+encodeURIComponent(tag))).total,0);
      const assigned=await memberUi(manager,late,'student',{grade:'2026级',class_name:className});assert.equal(assigned.membership.class_name,className);assert.equal((await api(late,'/notices/page?q='+encodeURIComponent(tag))).total,0,'Joining the scope does not itself backfill historical records');
      await nav(manager,'campus/records');let review;
      const deliver=async()=>{const button=manager.page.locator('[data-campus-action=deliver-new][data-id="'+pid+'"]'),clicked=await button.elementHandle();assert.ok(clicked);const result=await action(manager,'/campus/publications/'+pid+'/deliver-new','POST',async()=>{review=await action(manager,'/campus/audience-review','POST',()=>button.click());await manager.page.locator('#dialog [data-action=accept-dialog]').click();});await manager.page.waitForFunction(node=>!node.disabled,clicked);return result;};
      const delivered=await deliver();assert.equal(delivered.delivery.added,1);const entry={engine,phase:'late-member',assigned,review,result:delivered,status:'running'};report.publications.push(entry);
      const n=await received(late,5,entry);entry.notice_id=n.id;assert.notEqual(n.id,nid);assert.deepEqual(n.tasks,[]);await nav(late,'notice/'+n.id);assert.equal(await late.page.locator('.notice-primary h1').innerText(),initial.title);
      const replay=await deliver();assert.equal(replay.delivery.added,0);entry.second_explicit_backfill=replay;const after=await api(late,'/notices/page?q='+encodeURIComponent(tag));assert.equal(after.total,1);assert.equal(after.items[0].id,n.id);await personalUnchanged(entry);entry.status='passed';
    });
    await check(7,async()=>{
      const form=await openLifecycle(),route='/notices/'+nid+'/lifecycle-tracking';await form.locator('[name=phase]').selectOption('result');await form.locator('[name=note]').fill('本人正在核对合成正式结果 '+engine);
      const missingEvidence=await submitForm(student,route,form,{method:'PUT',expected:422});await form.locator('[data-lifecycle-error]').waitFor();assert.match(await form.locator('[data-lifecycle-error]').innerText(),/原文依据/);assert.equal(await form.locator('[name=phase]').inputValue(),'result');
      const citation=form.locator('.lifecycle-evidence-row').filter({hasText:'【合成官方结果】'}).first();await citation.waitFor({state:'attached'});if(!await citation.locator('xpath=ancestor::details[1]').evaluate(node=>node.open))await citation.locator('xpath=ancestor::details[1]').locator(':scope>summary').click();await citation.locator('[name=evidence]').check();
      await form.locator('[name=outcome]').selectOption('selected');const unverified=await submitForm(student,route,form,{method:'PUT',expected:422});assert.match(await form.locator('[data-lifecycle-error]').innerText(),/本人核实身份|身份/);assert.equal(await form.locator('[name=outcome]').inputValue(),'selected');
      await form.locator('[name=identity_confirmed]').check();await form.locator('[name=identity_note]').fill('已核对合成名单中的唯一账号 '+student.username+'，仅本人记录。');
      const saved=await submitForm(student,route,form,{method:'PUT'});await student.page.locator('#dialog').waitFor({state:'hidden'});assert.equal(saved.data.phase,'result');assert.equal(saved.data.outcome,'selected');assert.equal(saved.data.identity_confirmed,true);assert.ok(saved.data.evidence.length>0);
      report.lifecycle.push({engine,phase:'evidence-and-identity',missing_evidence:missingEvidence,unverified_identity:unverified,saved,status:'passed'});
    });
    await check(8,async()=>{
      const form=await openLifecycle(),route='/notices/'+nid+'/lifecycle-tracking',baseline=await api(student,route),localNote='这个窗口尚未提交的备注 '+engine;
      await form.locator('[name=note]').fill(localNote);const newer=await api(student,route,{method:'PUT',data:{version:baseline.version,notice_version:baseline.notice_version,data:{...baseline.data,note:'另一端的已保存备注 '+engine}}});
      const conflict=await submitForm(student,route,form,{method:'PUT',expected:409});await form.locator('[data-lifecycle-error]').waitFor();assert.match(await form.locator('[data-lifecycle-error]').innerText(),/仍保留/);assert.equal(await form.locator('[name=note]').inputValue(),localNote);assert.equal(await form.evaluate(node=>node.isConnected&&node.closest('dialog').open),true);
      const current=await api(student,route);assert.equal(current.version,newer.version);assert.equal(current.data.note,newer.data.note);
      const entry={engine,phase:'conflict-preserved',baseline_version:baseline.version,newer,conflict,local_note:localNote,server_after:current,status:'running'};report.lifecycle.push(entry);await student.page.screenshot({path:path.join(out,engine+'-lifecycle-conflict.png')});await closeDialog(student);
      const reopened=await openLifecycle();assert.equal(await reopened.locator('[name=note]').inputValue(),newer.data.note);await closeDialog(student);entry.status='passed';
    });
    await check(9,async()=>{
      await nav(manager,'campus/audit');
      const [importResponse]=await Promise.all([responseFor(manager,'/campus/audit','GET',query=>query.get('action')==='import_member'&&!query.has('before_id')),manager.page.locator('#campus-audit-action').selectOption('import_member')]);
      assert.equal(importResponse.status(),200);const imported=await importResponse.json();await manager.page.waitForFunction(count=>document.querySelectorAll('.campus-audit li').length===count,imported.items.length);assert.ok(imported.items.some(item=>item.action==='import_member'&&item.target_name==='学院验收 '+engine+' student'));assert.match(await manager.page.locator('.campus-audit').innerText(),/批量设置学院身份/);assert.equal(await manager.page.locator('#campus-audit-action').inputValue(),'import_member');
      const before=await api(manager,'/campus/audit?college_id=sres&page_size=100&action=assign_member'),beforeId=before.items[0]?.id||0,changes=[];let version=0;
      const entry={engine,import_filter:imported,before_id:beforeId,changes,status:'running'};report.audit.push(entry);await save();
      for(let index=0;index<101;index++){
        const result=await api(manager,'/campus/members/'+spare.username,{method:'PUT',data:{college_id:'sres',role:'student',grade:'2026级',class_name:className+'-审计'+index%2,scopes:[],version}});assert.equal(result.membership.version,version+1);version=result.membership.version;changes.push({index,version,class_name:result.membership.class_name});
      }
      const [firstResponse]=await Promise.all([responseFor(manager,'/campus/audit','GET',query=>query.get('action')==='assign_member'&&!query.has('before_id')),manager.page.locator('#campus-audit-action').selectOption('assign_member')]);assert.equal(firstResponse.status(),200);const first=await firstResponse.json();entry.first_page=first;assert.equal(first.items.length,100);assert.equal(first.has_more,true);assert.ok(first.next_cursor);
      await manager.page.waitForFunction(count=>document.querySelectorAll('.campus-audit li').length===count&&!document.querySelector('[data-campus-action="audit-next"]')?.disabled,first.items.length);
      const secondResponse=await auditPagination(manager,'next',query=>query.get('action')==='assign_member'&&query.get('before_id')===String(first.next_cursor),entry);assert.equal(secondResponse.status(),200);const second=await secondResponse.json();entry.second_page=second;
      await manager.page.waitForFunction(count=>document.querySelectorAll('.campus-audit li').length===count&&!document.querySelector('[data-campus-action="audit-prev"]')?.disabled,second.items.length);
      const ids=[...first.items,...second.items].map(item=>item.id);assert.equal(new Set(ids).size,ids.length);assert.ok(first.items.every(item=>item.action==='assign_member'));assert.ok(second.items.every(item=>item.action==='assign_member'&&item.id<first.next_cursor));
      const actual=first.items.concat(second.items).filter(item=>item.id>beforeId&&item.actor_name==='学院验收 '+engine+' manager'&&item.target_name==='学院验收 '+engine+' spare');assert.equal(actual.length,101);assert.deepEqual(actual.map(item=>item.details.class_name).reverse(),changes.map(item=>item.class_name));
      await manager.page.screenshot({path:path.join(out,engine+'-audit-second-page.png')});
      const backResponse=await auditPagination(manager,'prev',query=>query.get('action')==='assign_member'&&!query.has('before_id'),entry);assert.equal(backResponse.status(),200);const back=await backResponse.json();assert.deepEqual(back.items.map(item=>item.id),first.items.map(item=>item.id));await manager.page.waitForFunction(()=>document.querySelectorAll('.campus-audit li').length===100&&document.querySelector('[data-campus-action="audit-prev"]')?.disabled);
      entry.previous_page_ids=back.items.map(item=>item.id);entry.own_real_mutations=actual.length;entry.status='passed';
    });
    await check(10,async()=>{assert.deepEqual(pageErrors,[]);assert.equal(new Set([manager,student,late,spare].map(who=>who.owner)).size,4);assert.equal(report.checks.filter(item=>item.engine===engine&&item.ok).length,names.length-1);});
  }catch(error){
    process.exitCode=1;report.errors.push({engine,kind:'suite failure',error:error.stack||String(error)});
    for(const who of [manager,student,site])await who.page.screenshot({path:path.join(out,engine+'-'+who.label+'-failure.png'),fullPage:true}).catch(()=>{});
  }finally{await save();await Promise.allSettled(actors.map(who=>who.context.close()));await browser.close();}
}
report.active=null;report.complete=report.checks.length===report.expected_checks;report.passed=report.complete&&report.checks.every(check=>check.ok)&&report.errors.length===0;report.status=report.passed?'passed':'failed';if(!report.passed)process.exitCode=1;await save();
console.log(JSON.stringify({checks:report.checks.length,expected:report.expected_checks,passed:report.checks.filter(check=>check.ok).length,errors:report.errors.length,status:report.status}));
