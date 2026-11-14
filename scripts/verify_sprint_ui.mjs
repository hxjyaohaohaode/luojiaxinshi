/** Real API + native UI regression for the 2026 sprint; all data belongs to the loopback fixture. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {browserExecutable} from './browser-runtime.mjs';
const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/sprint-ui-browser');
const engines=(process.env.UI_ENGINES||'chromium,firefox,webkit').split(','),checksPerEngine=25;
const report={fixture:'Isolated real application APIs; synthetic publications, tasks and provider; no external recipients',network_fixture:{service_workers:'block',reason:'Controlled request delays and failures require Playwright routing; PWA behavior is exercised separately by verify_push_browser.mjs.'},status:'running',complete:false,passed:false,expected_checks:engines.length*checksPerEngine,active:null,checks:[],errors:[],performance:[],query_races:[],mobile_controls:[],recent_requests:[]};
await fs.mkdir(out,{recursive:true});
report.review_regressions={clock_ranges:[],board_ranges:[],publication_retries:[],publication_cancellations:[]};
async function saveReport(){const temporary=path.join(out,'report.json.tmp');await fs.writeFile(temporary,JSON.stringify(report,null,2));await fs.rename(temporary,path.join(out,'report.json'));}
async function within(work,ms,message){let timer;try{return await Promise.race([work,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);})]);}finally{clearTimeout(timer);}}
await saveReport();
for(const engine of engines){
  const browser=await pw[engine].launch({headless:true,executablePath:browserExecutable(pw[engine])});
  // Playwright documents that service workers can bypass page.route. Keep
  // this network-fault fixture explicit; the separate push suite retains its
  // real worker registration, account binding and explicit notification opt-in.
  const context=await browser.newContext({viewport:{width:1280,height:850},serviceWorkers:'block'}),page=await context.newPage();
  await page.addInitScript(()=>{window.__sprintLongTasks=[];window.__sprintLongTaskSupported=typeof PerformanceObserver==='function'&&PerformanceObserver.supportedEntryTypes.includes('longtask');if(window.__sprintLongTaskSupported)new PerformanceObserver(list=>window.__sprintLongTasks.push(...list.getEntries().map(entry=>({startTime:entry.startTime,duration:entry.duration})))).observe({type:'longtask',buffered:true});});
  page.setDefaultTimeout(15000);page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
  const recordRequest=(kind,request,extra={})=>{const url=new URL(request.url());if(url.origin!==origin)return;report.recent_requests.push({engine,kind,method:request.method(),path:url.pathname+url.search,...extra});report.recent_requests=report.recent_requests.slice(-40);};
  page.on('request',request=>recordRequest('request',request));page.on('response',response=>recordRequest('response',response.request(),{status:response.status(),from_service_worker:response.fromServiceWorker()}));page.on('requestfailed',request=>recordRequest('requestfailed',request,{error:request.failure()?.errorText||'unknown'}));
  const api=async(route,method='GET',data)=>{const session=await context.request.get(origin+'/api/session').then(r=>r.json());const response=await context.request.fetch(origin+'/api'+route,{method,headers:{Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf,...(data?{'Content-Type':'application/json'}:{})},...(data?{data}:{})});assert.equal(response.status(),200,await response.text());return response.json();};
  const nav=async hash=>{await page.evaluate(hash=>{location.hash='#'+hash;},hash);await page.waitForFunction(hash=>document.querySelector('#content')?.dataset.page===hash&&!document.querySelector('#content')?.inert,hash);};
  const login=async(username,password)=>{await page.goto(origin+'/#login');await page.locator('[name=username]').fill(username);await page.locator('[name=password]').fill(password);await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();};
  const check=async(name,run)=>{
    report.active={engine,name,started_at:new Date().toISOString()};console.log(engine+' START '+name);await saveReport();
    try{await run();report.checks.push({engine,name,ok:true});console.log(engine+' PASS '+name);}
    catch(error){report.checks.push({engine,name,ok:false,error:error.stack});console.error(engine+' FAIL '+name+'\n'+error.stack);await saveReport();await page.screenshot({path:path.join(out,engine+'-failure-'+report.checks.length+'.png'),timeout:5000}).catch(()=>{});throw error;}
    finally{report.active=null;await saveReport();}
  };
  const watchCelebration=()=>page.evaluate(()=>{window.__sprintConfetti=0;new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1&&node.matches('.confetti-bit'))window.__sprintConfetti++;}).observe(document.body,{childList:true});});
  const taskResponse=(query,response)=>{const url=new URL(response.url());return url.origin===origin&&url.pathname==='/api/tasks/page'&&url.searchParams.get('q')===query&&response.request().method()==='GET';};
  const searchTasks=async query=>{const [response]=await Promise.all([page.waitForResponse(response=>taskResponse(query,response),{timeout:10000}),page.locator('#task-search').fill(query)]);assert.equal(response.status(),200);return response.json();};
  const settledTaskSearch=async(query,total)=>{await page.waitForFunction(({query,total})=>document.querySelector('#task-search')?.value===query&&document.querySelector('#task-results')?.getAttribute('aria-busy')==='false'&&document.querySelector('#task-count')?.textContent==='已加载 '+Math.min(total,50)+' / '+total+' 项',{query,total});};
  const publicationPayload=request=>{
    const data=request.postData()?.match(/name="data"\r?\n\r?\n([\s\S]*?)\r?\n--/);assert.ok(data,'The actual multipart publication request carries its data part');return JSON.parse(data[1]);
  };
  const readyPublication=()=>page.waitForFunction(()=>{const form=document.querySelector('[data-workspace-form="campus-publish"]');return form&&!form.inert&&form.getAttribute('aria-busy')!=='true';});
  const fillPublication=async(title,{attachment=false}={})=>{
    const form=page.locator('[data-workspace-form=campus-publish]');await form.waitFor();
    await form.locator('[name=audience]').selectOption('class');await form.locator('[name=grade]').fill('2026级');await form.locator('[name=class_name]').fill('试点一班');
    await form.locator('[name=title]').fill(title);await form.locator('[name=body]').fill('合成发布恢复验收；只有隔离夹具内的已核实范围，无外部接收者。');
    if(attachment)await form.locator('[name=files]').setInputFiles({name:'恢复原件.txt',mimeType:'text/plain',buffer:Buffer.from('用于验证发布后未决结果及新草稿缺件提示的合成原件。')});
    return form;
  };
  const confirmPublication=async form=>{await form.locator('[type=submit]').click();await page.locator('#dialog [data-action=accept-dialog]').click();};
  const measureLoad=async(label,operation,selector)=>{
    await operation();const input=page.locator(selector);await input.waitFor({state:'visible'});await page.waitForFunction(selector=>{const node=document.querySelector(selector);return node&&!node.disabled&&!node.readOnly&&!node.closest('[inert]');},selector);await input.focus();assert.equal(await input.isEditable(),true);
    const metrics=await page.evaluate(()=>{const nav=performance.getEntriesByType('navigation')[0],resources=performance.getEntriesByType('resource'),files=resources.filter(item=>/\/static\//.test(item.name));return {can_input_at_ms:performance.now(),dom_content_loaded_ms:nav?.domContentLoadedEventEnd||null,load_event_ms:nav?.loadEventEnd||null,request_count:resources.length,static_request_count:files.length,css_request_count:files.filter(item=>/\.css(?:$|\?)/.test(item.name)).length,transfer_size:resources.reduce((sum,item)=>sum+item.transferSize,0),encoded_body_size:resources.reduce((sum,item)=>sum+item.encodedBodySize,0),longtask_supported:window.__sprintLongTaskSupported,longtasks:window.__sprintLongTaskSupported?window.__sprintLongTasks:null,parse_duration_ms:null,parse_duration_note:'No portable browser API separates JavaScript parsing from execution; unmeasured.',cache_note:'Zero transferSize is allowed on warm loads and is not treated as a network failure.',resources:files.map(item=>({url:item.name.replace(location.origin,''),initiator:item.initiatorType,duration:item.duration,transferSize:item.transferSize,encodedBodySize:item.encodedBodySize}))};});
    report.performance.push({engine,label,...metrics});
  };
  const prefix='冲刺分页 '+engine,needle='跨页独有 '+engine;
  let tasks=[],noticeId;
  try{
    await check('cold and warm loads expose usable input and record honest performance evidence',async()=>{
      await measureLoad('cold-login',()=>page.goto(origin+'/#login',{waitUntil:'domcontentloaded'}),'[name=username]');
      await measureLoad('warm-login-same-context',()=>page.reload({waitUntil:'domcontentloaded'}),'[name=username]');
      await page.locator('[name=username]').fill('sprint-'+engine);await page.locator('[name=password]').fill('PilotFixtureOnly2026!');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
    });
    await check('first arrival guide is optional, honest about unverified identity, and persisted per account',async()=>{
      const guide=page.locator('[data-getting-started]');await guide.waitFor();
      assert.equal(await guide.locator('[data-identity-state]').getAttribute('data-identity-state'),'pending');
      assert.match(await guide.innerText(),/填写教师、员工等个人条件不会获得学院发布或管理权限/);
      await guide.locator('[data-onboarding-dismiss]').click();await guide.waitFor({state:'detached'});
      assert.ok((await api('/session')).user.profile.dismissed_hints.includes('workspace-capabilities-v1'));
      await page.reload();await page.locator('.personal-home').waitFor();assert.equal(await page.locator('[data-getting-started]').count(),0);
    });
    await check('the skipped guide remains accessible from the personal page',async()=>{
      await nav('settings');await page.locator('[data-action=getting-started]').click();
      const guide=page.locator('[data-onboarding-guide]');await guide.waitFor();
      assert.match(await guide.innerText(),/个人完成、校方受理与审核结果分别记录/);assert.equal(await guide.locator('[data-onboarding-link]').count(),3);
      await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});
    });
    await check('54 actual tasks are committed through ordinary intake and confirmation',async()=>{
      for(let batch=0;batch<2;batch++){
        const session=await api('/session');
        const r=await context.request.post(origin+'/api/notices',{headers:{Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf},multipart:{title:prefix+' 原件 '+batch,body:'合成自选整理清单，仅作工程验收。本人自行整理以下事项；无官方期限，也不触发外部提交。',materials_complete:'true'}});assert.equal(r.status(),200,await r.text());
        let notice=await r.json();notice=await api('/notices/'+notice.id+'/manual','POST',{version:notice.version});noticeId=notice.id;
        const result=await api('/notices/'+notice.id+'/confirm','POST',{version:notice.version,reviewed:true,tasks:Array.from({length:27},(_,i)=>({title:prefix+' '+String(batch*27+i).padStart(2,'0'),scope:'personal',materials:[],submission:'',details:'合成本人整理事项，无外部提交。'})),plans:Object.fromEntries(Array.from({length:27},(_,i)=>[i,{execution_mode:'task'}]))});tasks.push(...result.task_ids);
      }
      assert.equal(tasks.length,54);
      const first=await api('/tasks/page?status=all&limit=50&q='+encodeURIComponent(prefix)),present=new Set(first.items.map(task=>task.id)),outside=tasks.find(id=>!present.has(id));assert.ok(outside,'A real record must be outside the first page');const task=(await api('/tasks/'+outside+'/workflow')).task;await api('/tasks/'+outside,'PUT',{version:task.version,data:{...task.data,title:task.data.title+' '+needle},status:'pending',reason:'合成验收跨页搜索'});tasks=tasks.filter(id=>id!==outside).concat(outside);
    });
    await check('home totals and calendar use the full lightweight account projection',async()=>{
      const seen=[],observe=request=>{if(request.method()==='GET')seen.push(new URL(request.url()).pathname);};page.on('request',observe);
      try{
        await nav('dashboard');await page.waitForFunction(()=>document.querySelector('.home-counts [data-overview-filter=pending] b')?.textContent==='54');
        const visible=page.locator('.personal-home [data-action=toggle-task]').first(),id=await visible.getAttribute('data-id'),before=(await api('/tasks/'+id+'/workflow')).task;
        assert.ok(before.data.details.length>0,'The fixture must carry real data omitted by the projection');
        assert.equal(before.workflow.data.execution_mode,'task','Direct completion requires an explicitly confirmed personal task, not a legacy submission workflow');
        await visible.click();await page.locator('#toast .toast-action').waitFor();const saved=(await api('/tasks/'+id+'/workflow')).task;assert.equal(saved.status,'done');assert.deepEqual(saved.data,before.data,'A light home row must fetch full task data before changing status');
        await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('.home-counts [data-overview-filter=pending] b')?.textContent==='54');assert.equal((await api('/tasks/'+id+'/workflow')).task.status,'pending');
        const target=(await api('/tasks/'+tasks.at(-1)+'/workflow')).task;
        await api('/tasks/'+target.id,'PUT',{version:target.version,data:{...target.data,details:'日历备注独有 '+engine,planned_at:new Date().toISOString()},status:'pending',reason:'合成日历备注检索'});
        await nav('calendar');await page.locator('#calendar-body').waitFor();await page.locator('[data-calendar-view=list]').click();
        await page.locator('#calendar-query').fill('日历备注独有 '+engine);
        await page.waitForFunction(()=>document.querySelector('#calendar-body')?.getAttribute('aria-busy')==='false'&&document.querySelector('#calendar-count')?.textContent.includes('1 项匹配安排'));
        const event=page.locator('#calendar-body [data-calendar-event="'+target.id+':plan"]');assert.equal(await event.count(),1);await event.click();await page.locator('.event-detail').waitFor();assert.match(await page.locator('.event-detail').innerText(),new RegExp('日历备注独有 '+engine));await page.keyboard.press('Escape');
        assert.ok(seen.includes('/api/workspace/projection'));assert.equal(seen.includes('/api/notices'),false);assert.equal(seen.includes('/api/tasks'),false);
      }finally{page.off('request',observe);}
    });
    await nav('tasks');
    if(await page.locator('#task-status-select').isVisible())await page.locator('#task-status-select').selectOption('all');else await page.locator('[data-action=filter][data-filter=all]').click();
    await check('a clock-only signal preserves all 54 loaded tasks, focused node and scroll without reloading unchanged full records',async()=>{
      await searchTasks(prefix);await settledTaskSearch(prefix,54);
      const baseline=await api('/proactive/revision');let tick=0;const paths=[];
      const handler=route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...baseline,revision:baseline.revision+':clock-fixture:'+tick,domains:{...baseline.domains,clock:tick?String(baseline.domains.clock)+':fixture:'+tick:baseline.domains.clock}})});
      const observer=request=>{const url=new URL(request.url());if(url.origin===origin&&request.method()==='GET')paths.push(url.pathname+url.search);};
      const probe=()=>Promise.all([page.waitForResponse(response=>new URL(response.url()).pathname==='/api/proactive/revision'),page.evaluate(()=>window.dispatchEvent(new Event('focus')))]);
      await page.route('**/api/proactive/revision',handler);
      let node;
      try{
        // A revision response precedes its awaited UI refresh. The sync
        // controller serializes probes, so the second real response proves
        // that the initial stable refresh finished before measurement begins.
        await probe();await probe();
        if(await page.locator('[data-action=task-more]').count())await page.locator('[data-action=task-more]').click();
        await page.waitForFunction(()=>document.querySelector('#task-count')?.textContent==='已加载 54 / 54 项'&&document.querySelector('#task-results')?.getAttribute('aria-busy')==='false');
        const ids=await page.locator('#task-results [data-task-id]').evaluateAll(nodes=>nodes.map(node=>node.dataset.taskId)),target=ids.at(-1),button=page.locator('[data-task-id="'+target+'"] .task-primary');
        await button.scrollIntoViewIfNeeded();await button.focus();node=await button.elementHandle();
        const before=await page.evaluate(()=>({content:document.querySelector('#content').scrollTop,window:scrollY}));
        await page.evaluate(()=>{window.__clockListMutations=0;window.__clockListObserver=new MutationObserver(()=>window.__clockListMutations++);window.__clockListObserver.observe(document.querySelector('#task-results'),{childList:true,subtree:true,attributes:true});});
        page.on('request',observer);tick++;
        const projection=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workspace/projection');await probe();assert.equal((await projection).status(),200);
        // The next serialized probe also waits out the tick's final DOM work;
        // checking immediately at response time could miss a late redraw.
        await probe();
        assert.deepEqual(await page.locator('#task-results [data-task-id]').evaluateAll(nodes=>nodes.map(node=>node.dataset.taskId)),ids);
        assert.equal(await node.evaluate(element=>element.isConnected&&document.activeElement===element),true);
        assert.equal(await page.evaluate(()=>window.__clockListMutations),0,'Unchanged lightweight flags must not redraw list rows');
        const after=await page.evaluate(()=>({content:document.querySelector('#content').scrollTop,window:scrollY}));assert.ok(Math.abs(after.content-before.content)<2&&Math.abs(after.window-before.window)<2,JSON.stringify({before,after}));
        assert.equal(paths.some(url=>url.startsWith('/api/tasks/page')),false,'A stable all filter must not reread its full loaded task records');
        const readCount=paths.filter(url=>url.startsWith('/api/workspace/projection')).length;await probe();await page.waitForTimeout(250);assert.equal(paths.filter(url=>url.startsWith('/api/workspace/projection')).length,readCount,'An unchanged clock revision is not another refresh');
        report.review_regressions.clock_ranges.push({engine,loaded:ids.length,controlled_clock_signal:true,real_entity_endpoint:'/api/workspace/projection',full_page_reads:paths.filter(url=>url.startsWith('/api/tasks/page')).length,dom_mutations:await page.evaluate(()=>window.__clockListMutations),focused_node_preserved:true,before,after});
      }finally{page.off('request',observer);await page.unroute('**/api/proactive/revision',handler);await page.evaluate(()=>window.__clockListObserver?.disconnect());await node?.dispose();}
    });
    await check('a card loaded from the second board page remains on page one after an actual upward move',async()=>{
      const boardResponse=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/tasks/page'&&url.searchParams.get('q')===prefix&&url.searchParams.get('sort')==='board'&&!url.searchParams.has('cursor');});
      await page.locator('[data-task-view=board]').click();const initial=await(await boardResponse).json();assert.equal(initial.items.length,50);await page.locator('[data-action=task-more]').click();
      await page.waitForFunction(()=>document.querySelectorAll('#task-results [data-task-id]').length===54);
      const ordered=await page.locator('[data-task-lane=action] [data-task-id]').evaluateAll(nodes=>nodes.map(node=>node.dataset.taskId));assert.equal(ordered.length,54);const moved=ordered[50];assert.equal(initial.items.some(item=>item.id===moved),false);
      await page.locator('[data-task-id="'+moved+'"] [data-task-drag-handle]').click();
      const moveResponse=page.waitForResponse(response=>response.url()===origin+'/api/tasks/'+moved+'/move'&&response.request().method()==='POST');
      const refreshed=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/tasks/page'&&url.searchParams.get('q')===prefix&&url.searchParams.get('sort')==='board'&&!url.searchParams.has('cursor');});
      await page.locator('.task-move-menu').getByRole('button',{name:'上移一位',exact:true}).click();assert.equal((await moveResponse).status(),200);const result=await(await refreshed).json();assert.equal(result.items.length,50);assert.equal(result.items[49].id,moved);
      await page.waitForFunction(id=>document.querySelectorAll('#task-results [data-task-id]').length===50&&!!document.querySelector('[data-task-id="'+id+'"]'),moved);
      const ids=await page.locator('[data-task-lane=action] [data-task-id]').evaluateAll(nodes=>nodes.map(node=>node.dataset.taskId));assert.deepEqual(ids,[...ordered.slice(0,49),moved]);
      report.review_regressions.board_ranges.push({engine,initial_page:50,loaded:54,moved_id:moved,from_index:50,to_index:49,after_first_page:ids});
      await page.screenshot({path:path.join(out,engine+'-desktop-board-page-move.png')});
      const listResponse=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/tasks/page'&&url.searchParams.get('q')===prefix&&!url.searchParams.has('sort');});await page.locator('[data-task-view=list]').click();assert.equal((await listResponse).status(),200);
    });
    await page.locator('#task-search').fill(prefix);
    await check('task list reports a bounded first page and loads the remaining real records',async()=>{
      await page.waitForFunction(()=>document.querySelector('#task-count')?.textContent==='已加载 50 / 54 项');
      assert.equal(await page.locator('#task-results .task-row').count(),50);
      await page.locator('[data-action=task-more]').click();await page.waitForFunction(()=>document.querySelector('#task-count')?.textContent==='已加载 54 / 54 项');
      assert.equal(await page.locator('#task-results .task-row').count(),54);assert.equal(await page.locator('[data-action=task-more]').count(),0);
    });
    await check('full collection search finds a record beyond the initial page',async()=>{
      assert.equal((await searchTasks(needle)).total,1);await settledTaskSearch(needle,1);
      assert.match(await page.locator('#task-results').innerText(),new RegExp(needle));
    });
    await check('an obsolete query response cannot overwrite the latest server filter',async()=>{
      let release,observed,rejected,finished;const gate=new Promise(resolve=>release=resolve),began=new Promise((resolve,reject)=>{observed=resolve;rejected=reject;}),completed=new Promise(resolve=>finished=resolve);
      const race={engine,old_query:prefix,new_query:needle,service_worker_controller:await page.evaluate(()=>navigator.serviceWorker?.controller?.scriptURL||null),old_handler_entered:false,old_response_captured:false,old_browser_response_observed:false,old_request_failure:null,late_fulfill_attempted:false,late_fulfill_result:null,requests:[]};report.query_races.push(race);
      assert.equal(race.service_worker_controller,null,'The controlled delay fixture must not be service-worker controlled');
      const requested=request=>{const url=new URL(request.url());if(url.origin===origin&&url.pathname==='/api/tasks/page')race.requests.push({query:url.searchParams.get('q'),method:request.method()});};page.on('request',requested);
      const failed=request=>{const url=new URL(request.url());if(url.origin===origin&&url.pathname==='/api/tasks/page'&&url.searchParams.get('q')===prefix)race.old_request_failure=request.failure()?.errorText||'unknown';};
      const responded=response=>{if(taskResponse(prefix,response))race.old_browser_response_observed=true;};page.on('requestfailed',failed);page.on('response',responded);
      const handler=async route=>{
        if(new URL(route.request().url()).searchParams.get('q')!==prefix){await route.continue();return;}
        race.old_handler_entered=true;
        try{const response=await route.fetch({timeout:10000});assert.equal(response.status(),200);race.old_response_captured=true;observed();await gate;race.late_fulfill_attempted=true;try{await route.fulfill({response});race.late_fulfill_result='fulfill_call_completed';}catch(error){race.late_fulfill_result='fulfill_call_rejected';race.late_fulfill_error=error.message;}}
        catch(error){race.fetch_error=error.message;rejected(error);await route.abort().catch(()=>{});}
        finally{finished();}
      };
      await page.route('**/api/tasks/page?**',handler);
      try{
        await Promise.all([within(began,10000,'The older task query was not captured within 10 seconds; recent_requests records the observed UI requests.'),page.locator('#task-search').fill(prefix)]);
        assert.equal((await searchTasks(needle)).total,1);await settledTaskSearch(needle,1);
        release();await within(completed,10000,'The held older query did not finish its late fulfill attempt.');await page.waitForTimeout(800);
        race.outcome=race.old_request_failure?'old_request_aborted_late_fulfill_attempted':race.old_browser_response_observed?'old_response_observed_after_new_query':'late_fulfill_attempt_without_observed_browser_response';
        assert.equal(await page.locator('#task-search').inputValue(),needle);assert.equal(await page.locator('#task-results .task-row').count(),1);assert.match(await page.locator('#task-results').innerText(),new RegExp(needle));assert.equal(await page.locator('#task-results').getAttribute('aria-busy'),'false');
      }finally{release();await page.unroute('**/api/tasks/page?**',handler);page.off('request',requested);page.off('requestfailed',failed);page.off('response',responded);}
    });
    await check('failed completion rolls back and persistent error stays above the mobile navigation',async()=>{
      await page.setViewportSize({width:390,height:844});
      await watchCelebration();
      const tid=tasks.at(-1),url=origin+'/api/tasks/'+tid,handler=route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'合成失败：服务端尚未保存'})});
      await page.route(url,handler);
      try{await page.locator('[data-action=toggle-task][data-id="'+tid+'"]').click();await page.locator('#toast').filter({hasText:'合成失败'}).waitFor();await page.waitForFunction(tid=>document.querySelector('[data-action=toggle-task][data-id="'+tid+'"]')?.getAttribute('aria-pressed')==='false',tid);assert.equal(await page.evaluate(()=>window.__sprintConfetti),0);await page.waitForTimeout(6100);assert.equal(await page.locator('#toast').isVisible(),true);const toast=await page.locator('#toast').boundingBox(),navBox=await page.locator('.mobile-bottom-nav').boundingBox();assert.ok(toast.y+toast.height<=navBox.y-1,JSON.stringify({toast,navBox}));}finally{await page.unroute(url,handler);}
      const task=(await api('/tasks/'+tid+'/workflow')).task;assert.equal(task.status,'pending');
      await page.locator('#toast [data-toast-close]').click();
    });
    await check('confirmed completion persists and task controls have separate 44 pixel targets',async()=>{
      const tid=tasks.at(-1),control=page.locator('[data-action=toggle-task][data-id="'+tid+'"]');
      const row=control.locator('..'),boxes=await row.locator('.task-check,.task-main,.task-more>summary').evaluateAll(nodes=>nodes.filter(n=>n.getClientRects().length).map(n=>{const r=n.getBoundingClientRect();return {name:n.className,x:r.x,right:r.right,y:r.y,bottom:r.bottom,width:r.width,height:r.height};}));
      for(const box of boxes)assert.ok(box.width>=43.9&&box.height>=43.9,JSON.stringify(box));for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const a=boxes[i],b=boxes[j];assert.ok(a.right<=b.x+1||b.right<=a.x+1||a.bottom<=b.y+1||b.bottom<=a.y+1,JSON.stringify(boxes));}
      await control.click();await page.waitForFunction(tid=>document.querySelector('[data-action=toggle-task][data-id="'+tid+'"]')?.getAttribute('aria-pressed')==='true',tid);assert.equal((await api('/tasks/'+tid+'/workflow')).task.status,'done');
    });
    await check('a pending submission opens its handling record without completion or celebration',async()=>{
      const tid=tasks.at(-1),completed=(await api('/tasks/'+tid+'/workflow')).task;
      await api('/tasks/'+tid,'PUT',{version:completed.version,data:completed.data,status:'pending',reason:'合成验收：恢复本人记录以核对办理入口'});
      const current=(await api('/tasks/'+tid+'/workflow')).task;
      await api('/tasks/'+tid+'/workflow','PUT',{version:current.workflow.version,task_version:current.version,data:{...current.workflow.data,execution_mode:'submission',stage:'preparing'}});
      // These preceding writes use a second API client. Reload as a user would
      // before testing one click on the newly committed submission workflow.
      await page.reload();await page.locator('#task-search').waitFor();
      if(await page.locator('#task-status-select').isVisible())await page.locator('#task-status-select').selectOption('all');else await page.locator('[data-action=filter][data-filter=all]').click();
      const fresh=await searchTasks(needle);assert.equal(fresh.total,1);assert.equal(fresh.items[0].status,'pending');assert.equal(fresh.items[0].workflow.data.execution_mode,'submission');assert.equal(fresh.items[0].workflow.data.stage,'preparing');await settledTaskSearch(needle,1);
      const control=page.locator('[data-action=toggle-task][data-id="'+tid+'"]');assert.equal(await control.getAttribute('aria-pressed'),'false');assert.match(await control.getAttribute('aria-label'),/办理/);await watchCelebration();
      const before=await page.evaluate(()=>window.__sprintConfetti);
      await control.click();await page.locator('#workflow-form').waitFor();
      assert.equal((await api('/tasks/'+tid+'/workflow')).task.status,'pending');assert.equal(await page.evaluate(()=>window.__sprintConfetti),before);
      await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});
    });
    await check('notification matrix and plan are actual account data; category change is saved',async()=>{
      await nav('settings');await page.locator('[data-settings-category=account]').click();await page.locator('[data-action=settings-notification]').click();const form=page.locator('#proactive-preferences');await form.waitFor();
      await form.locator('[name=collaboration_delivery]').selectOption('digest');await form.locator('[name=source_health_delivery]').selectOption('in_app');
      await form.locator('[data-notification-plan]>summary').click();await page.locator('[data-notification-plan][data-loaded="1"]').waitFor();assert.match(await form.innerText(),/当前计划/);
      await form.locator('[type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});assert.equal((await api('/notifications/routes')).preferences.collaboration_delivery,'digest');
    });
    await check('per-notice override preserves all other preferences',async()=>{
      const before=(await api('/notifications/routes')).preferences;await nav('notice/'+noticeId);await page.locator('.notice-actions>summary').click();await page.locator('[data-action=notice-notification-decision]').click();
      const form=page.locator('#proactive-notice-route');await form.locator('[name=notice_override]').selectOption('in_app');await form.locator('[type=submit]').click();await page.locator('#toast').filter({hasText:'本事项提醒方式已保存'}).waitFor();const after=(await api('/notifications/routes?notice_id='+noticeId)).preferences;assert.equal(after.notice_delivery[noticeId],'in_app');assert.equal(after.collaboration_delivery,before.collaboration_delivery);assert.deepEqual(after.source_delivery,before.source_delivery);await page.keyboard.press('Escape');
    });
    await check('lifecycle editor opens from the original notice with explicit phase and evidence controls',async()=>{
      if(!await page.locator('.notice-actions-menu').isVisible())await page.locator('.notice-actions>summary').click();await page.locator('[data-action=notice-lifecycle]').first().click();await page.locator('.notice-lifecycle').waitFor();assert.match(await page.locator('.notice-lifecycle').innerText(),/公示结束不会自动变成最终结果/);await page.keyboard.press('Escape');
    });
    const chat=await api('/conversations','POST',{title:'冲刺交互 '+engine});await nav('chat/'+chat.id);
    await check('composer prioritizes text and its More menu supports keyboard exit at 320 pixels',async()=>{
      await page.setViewportSize({width:320,height:640});const plus=page.locator('.composer-plus');await plus.click();assert.equal(await page.locator('#composer-menu').isVisible(),true);await page.keyboard.press('Escape');assert.equal(await plus.evaluate(n=>document.activeElement===n),true);assert.equal(await page.locator('#composer-menu').isVisible(),false);const controls=await page.locator('#chat-composer .composer-plus,#chat-composer .send-button').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return [r.width,r.height];}));for(const [w,h]of controls)assert.ok(w>=43.9&&h>=43.9);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    });
    await check('secondary reply actions remain available behind an accessible disclosure',async()=>{
      await page.setViewportSize({width:390,height:844});await page.locator('#chat-input').fill('【合成验收】输出代码块');await page.locator('#chat-composer [type=submit]').click();await page.waitForFunction(()=>document.querySelector('.message-assistant pre code')&&!document.querySelector('#chat-composer')?.classList.contains('is-processing'));const more=page.locator('.message-assistant .reply-more').last();assert.equal(await more.getAttribute('open'),null);await more.locator('summary').focus();await page.keyboard.press('Enter');assert.equal(await more.locator('[data-chat-action=speak]').isVisible(),true);await page.keyboard.press('Escape');assert.equal(await more.getAttribute('open'),null);assert.equal(await more.locator('summary').evaluate(n=>n===document.activeElement),true);
    });
    await page.screenshot({path:path.join(out,engine+'-mobile-chat.png')});
    await check('warm chat reload records route asset costs and retains usable composer',()=>measureLoad('warm-chat-same-context',()=>page.reload({waitUntil:'domcontentloaded'}),'#chat-input'));
    await context.clearCookies();await login('pilot-counselor','PilotFixtureOnly2026!');
    await check('another account does not inherit dismissal and shows its actual authorized identity',async()=>{
      await nav('dashboard');const guide=page.locator('[data-getting-started]');await guide.waitFor();
      assert.equal(await guide.locator('[data-identity-state]').getAttribute('data-identity-state'),'verified');
      assert.match(await guide.innerText(),/学院身份已核实 · 辅导员/);
      assert.equal(((await api('/session')).user.profile.dismissed_hints||[]).includes('workspace-capabilities-v1'),false);
    });
    await nav('campus/publish');
    await check('incomplete publication draft and attachment survive a full browser reload',async()=>{
      const form=page.locator('[data-workspace-form=campus-publish]'),title='持久草稿 '+engine;await form.locator('[name=title]').fill(title);await form.locator('[name=body]').fill('合成草稿，尚未选择发布范围，不应发送。');await form.locator('[name=files]').setInputFiles({name:'合成原件.txt',mimeType:'text/plain',buffer:Buffer.from('合成草稿附件，唯一证据文本。')});await form.locator('[data-campus-action=save-draft]').click();await page.waitForFunction(()=>document.querySelector('[data-campus-draft-status]')?.textContent.startsWith('已保存第'));const draftId=await form.getAttribute('data-draft-id');assert.equal((await api('/campus/drafts/'+draftId)).attachments.length,1);
      await page.reload();await page.locator('.campus-drafts>summary').click();await page.locator('[data-campus-action=open-draft][data-id="'+draftId+'"]').click();await page.waitForFunction(title=>document.querySelector('[data-workspace-form=campus-publish] [name=title]')?.value===title,title);assert.equal(await page.locator('[name=title]').inputValue(),title);assert.equal(await page.locator('[name=audience]').inputValue(),'');await page.locator('[data-campus-saved-files] details>summary').click();assert.match(await page.locator('[data-campus-saved-files]').innerText(),/合成原件.txt/);assert.equal((await api('/campus/drafts/'+draftId)).attachments.length,1);
      // A screenshot taken mid-scroll can put the footer behind the fixed
      // navigation. Prove that normal document scrolling exposes the complete
      // publication control without submitting the incomplete draft.
      const publish=page.locator('[data-workspace-form="campus-publish"] [type=submit]');
      await publish.evaluate(button=>button.scrollIntoView({block:'center',behavior:'instant'}));
      await publish.click({trial:true});
      const control=await publish.boundingBox(),navigation=await page.locator('.mobile-bottom-nav').boundingBox();
      report.mobile_controls.push({engine,name:'publication control after normal document scroll',control,navigation});
      assert.ok(control.height>=43.9&&control.y>=0&&control.y+control.height<=navigation.y-1,JSON.stringify({control,navigation}));
    });
    await page.screenshot({path:path.join(out,engine+'-mobile-draft.png')});
    await check('a committed publication with a lost response retries the identical confirmed payload without saving its deleted draft',async()=>{
      const title='丢响应直接恢复 '+engine,form=await fillPublication(title),attempts=[],writes=[];let committed=null;
      const observe=request=>{if(request.method()==='PUT'&&new URL(request.url()).pathname.startsWith('/api/campus/drafts/'))writes.push(new URL(request.url()).pathname);};
      const handler=async route=>{const payload=publicationPayload(route.request());attempts.push(payload);const response=await route.fetch();assert.equal(response.status(),200,await response.text());if(!committed){committed=await response.json();await route.abort('failed');}else await route.fulfill({response});};
      page.on('request',observe);await page.route(origin+'/api/campus/publications',handler);
      try{
        await confirmPublication(form);await page.locator('[data-campus-publication-recovery]').waitFor();await readyPublication();assert.ok(committed?.id);
        const original=(await api('/edit-cache/campus-publication')).payload.payload;assert.deepEqual(original,attempts[0]);assert.equal((await context.request.get(origin+'/api/campus/drafts/'+original.draft_id)).status(),404);
        const saved=writes.length;
        const replayResponse=page.waitForResponse(response=>response.url()===origin+'/api/campus/publications'&&response.request().method()==='POST');
        await form.locator('[type=submit]').click();const replayed=await replayResponse;
        assert.equal(replayed.status(),200,await replayed.text());assert.equal((await replayed.json()).id,committed.id);
        // Successful recovery performs this navigation itself. Changing the
        // hash here would cancel a not-yet-sent retry through its route guard.
        await page.waitForFunction(()=>location.hash==='#campus/records'&&document.querySelector('#content')?.dataset.page==='campus/records'&&!document.querySelector('#content')?.inert);
        assert.equal(attempts.length,2);assert.deepEqual(attempts[1],original);assert.equal(writes.length,saved);
        const records=await api('/campus/publications?page_size=100&q='+encodeURIComponent(title));assert.equal(records.items.length,1);assert.equal(records.items[0].id,committed.id);assert.equal((await api('/edit-cache/campus-publication')).payload,null);
        report.review_regressions.publication_retries.push({engine,scenario:'same form retry',publication_id:committed.id,request_id:original.request_id,attempts:2,additional_draft_writes:0,stored_publications:records.items.length});
      }finally{await page.unroute(origin+'/api/campus/publications',handler);page.off('request',observe);}
    });
    await check('an uncertain publication survives reload and its recovery preserves new draft input and unresolved attachment names',async()=>{
      await nav('campus/publish');const title='刷新恢复原发布 '+engine,form=await fillPublication(title,{attachment:true}),attempts=[],writes=[];let committed=null;
      const observe=request=>{if(request.method()==='PUT'&&new URL(request.url()).pathname.startsWith('/api/campus/drafts/'))writes.push(new URL(request.url()).pathname);};
      const handler=async route=>{attempts.push(publicationPayload(route.request()));const response=await route.fetch();assert.equal(response.status(),200,await response.text());if(!committed){committed=await response.json();await route.abort('failed');}else await route.fulfill({response});};
      page.on('request',observe);await page.route(origin+'/api/campus/publications',handler);
      try{
        await confirmPublication(form);await page.locator('[data-campus-publication-recovery]').waitFor();await readyPublication();const original=(await api('/edit-cache/campus-publication')).payload.payload;
        await page.reload();await page.locator('[data-campus-publication-recovery]').waitFor();await readyPublication();assert.equal(await form.locator('[name=title]').inputValue(),title);
        const newTitle='后来编辑暂不发布 '+engine,newBody='保留这份新输入；恢复上次确认的发布不得把它一起发送。';await form.locator('[name=title]').fill(newTitle);await form.locator('[name=body]').fill(newBody);
        const newDraft=await form.getAttribute('data-draft-id');assert.notEqual(newDraft,original.draft_id);await form.locator('[data-campus-action=save-draft]').click();
        // A preceding autosave can show this status too. Wait for the actual
        // manual save handler to finish its serialized write before reading.
        await form.locator('[data-campus-action=save-draft]:enabled').waitFor();await page.waitForFunction(()=>document.querySelector('[data-campus-draft-status]')?.textContent.startsWith('正文已保存'));
        const saved=await api('/campus/drafts/'+newDraft);assert.equal(saved.body,newBody);assert.deepEqual(saved.pending_attachment_names,['恢复原件.txt']);
        await page.reload();await page.locator('.campus-drafts>summary').click();await page.locator('[data-campus-action=open-draft][data-id="'+newDraft+'"]').click();await page.waitForFunction(title=>document.querySelector('[data-workspace-form=campus-publish] [name=title]')?.value===title,newTitle);
        assert.equal(await form.getAttribute('data-missing-files'),'1');assert.match(await page.locator('#campus-missing-files').innerText(),/恢复原件/);
        await page.screenshot({path:path.join(out,engine+'-mobile-publication-recovery.png')});
        const oldWrites=writes.filter(path=>path.endsWith('/'+original.draft_id)).length;
        await page.locator('[data-campus-action=recover-publication]').click();await page.locator('[data-campus-publication-recovery]').waitFor({state:'detached'});await readyPublication();assert.equal(attempts.length,2);assert.deepEqual(attempts[1],original);
        assert.equal(await form.locator('[name=title]').inputValue(),newTitle);assert.equal(await form.locator('[name=body]').inputValue(),newBody);assert.equal(writes.filter(path=>path.endsWith('/'+original.draft_id)).length,oldWrites);
        await form.locator('[type=submit]').click();await page.locator('#toast').filter({hasText:'请重新选择附件'}).waitFor();assert.equal(attempts.length,2,'A new draft with unresolved attachments must not publish');
        await form.locator('[data-campus-action=clear-files]').click();await form.locator('[data-campus-action=save-draft]').click();await form.locator('[data-campus-action=save-draft]:enabled').waitFor();await page.waitForFunction(()=>document.querySelector('[data-campus-draft-status]')?.textContent.startsWith('已保存第'));assert.deepEqual((await api('/campus/drafts/'+newDraft)).pending_attachment_names,[]);
        const records=await api('/campus/publications?page_size=100&q='+encodeURIComponent(title));assert.equal(records.items.length,1);assert.equal(records.items[0].id,committed.id);assert.equal((await api('/campus/publications?q='+encodeURIComponent(newTitle))).items.length,0);
        report.review_regressions.publication_retries.push({engine,scenario:'reload with new draft',publication_id:committed.id,request_id:original.request_id,new_draft_id:newDraft,new_input_preserved:true,missing_attachments_persisted:true,attempts:2,stored_publications:records.items.length});
      }finally{await page.unroute(origin+'/api/campus/publications',handler);page.off('request',observe);}
    });
    await check('stopping an uncommitted publication preserves its draft and rejects a later replay of the stopped request',async()=>{
      const title='停止尚未发布 '+engine,form=await fillPublication(title);let original;
      const handler=async route=>{original=publicationPayload(route.request());await route.abort('failed');};await page.route(origin+'/api/campus/publications',handler);
      try{await confirmPublication(form);await page.locator('[data-campus-publication-recovery]').waitFor();await readyPublication();}finally{await page.unroute(origin+'/api/campus/publications',handler);}
      assert.ok(original?.request_id);await page.locator('[data-campus-action=cancel-publication]').click();await page.locator('#dialog [data-action=accept-dialog]').click();await page.locator('[data-campus-publication-recovery]').waitFor({state:'detached'});
      const newDraft=await form.getAttribute('data-draft-id');assert.notEqual(newDraft,original.draft_id);assert.equal(await form.locator('[name=title]').inputValue(),title);assert.equal((await api('/edit-cache/campus-publication')).payload,null);
      const session=await api('/session'),late=await context.request.post(origin+'/api/campus/publications',{headers:{Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf},multipart:{data:JSON.stringify(original)}});assert.equal(late.status(),409);assert.equal((await late.json()).detail.code,'publication_cancelled');assert.equal((await api('/campus/publications?q='+encodeURIComponent(title))).items.length,0);
      report.review_regressions.publication_cancellations.push({engine,request_id:original.request_id,replacement_draft_id:newDraft,late_status:409,late_code:'publication_cancelled',published_count:0});
    });
    await check('new routes and interactions finish without uncaught page errors',()=>assert.deepEqual(report.errors.filter(item=>item.engine===engine),[]));
  }catch(error){console.error(engine,error.message);if(!report.checks.some(item=>item.engine===engine&&!item.ok))report.checks.push({engine,name:'setup or fatal execution',ok:false,error:error.stack});}finally{await saveReport();await browser.close();}
}
report.complete=report.checks.length===report.expected_checks;report.passed=report.complete&&!report.errors.length&&report.checks.every(check=>check.ok);report.status=report.passed?'passed':report.complete?'failed':'incomplete';await saveReport();console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
