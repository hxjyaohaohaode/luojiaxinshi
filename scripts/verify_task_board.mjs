import {browserOverride} from './browser-runtime.mjs';
import {verifyTaskListStability} from './task_list_stability_checks.mjs';
// Fault-injection routes must reach Playwright; actual workers are exercised by verify_push_browser.mjs.
/** Real pointer movement with isolated synthetic tasks, never the user's data. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const pw=createRequire(import.meta.url)(process.env.PLAYWRIGHT_PATH||'playwright');
const origin=process.env.CAMPUS_VERIFY_ORIGIN||'http://127.0.0.1:8786',out=path.resolve(process.env.OPENUI_ARTIFACT_DIR||'artifacts/task-board-browser');
await fs.mkdir(out,{recursive:true});
const report={fixture:'Synthetic tasks; real pointer events, storage, conflict guards and undo',checks:[],errors:[],motion_observations:[]};
for(const engine of (process.env.UI_ENGINES||process.env.OPENUI_BROWSER||'chromium,firefox,webkit').split(',')){
  const browser=await pw[engine].launch({headless:true,...browserOverride(pw[engine]),...(process.platform==='win32'&&engine==='chromium'?{channel:'msedge'}:{})});
  const page=await browser.newPage({serviceWorkers:'block',viewport:{width:1440,height:950},locale:'zh-CN'});page.setDefaultTimeout(12000);
  page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
  const api=(url,method='GET',data=null,form=false)=>page.evaluate(async({url,method,data,form})=>{
    const session=await fetch('/api/session').then(r=>r.json()),headers={'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
    let body;if(data){if(form){body=new FormData();for(const [key,value] of Object.entries(data))body.set(key,value);}else{headers['Content-Type']='application/json';body=JSON.stringify(data);}}
    const response=await fetch('/api'+url,{method,headers,body});const result=await response.json();if(!response.ok)throw Error(JSON.stringify(result));return result;
  },{url,method,data,form});
  const settle=async()=>{await page.waitForTimeout(300);await page.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity&&!a.effect?.target?.closest?.('#toast')).map(a=>a.finished.catch(()=>{}))));};
  const check=async(name,fn)=>{try{await fn();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.message});console.log('FAIL',engine,name,error.message);await page.screenshot({path:path.join(out,engine+'-failure-'+report.checks.length+'.png')});}};
  const row=id=>page.locator(`#task-results [data-task-id="${id}"]`);
  const ids=lane=>page.locator(`[data-task-lane="${lane}"] .task-row`).evaluateAll(nodes=>nodes.map(n=>n.dataset.taskId));
  const motionSnapshot=()=>page.evaluate(()=>window.__boardMotionObservation.snapshot());
  const prepareBoardMotion=async observation=>{
    // Routing releases inert before its first WAAPI entrances finish. Observe
    // those real instances separately from the later drag/ack measurement.
    await page.locator('#content[data-page="tasks"]:not([inert])').waitFor();
    await page.waitForFunction(()=>document.querySelector('#task-results')?.getAttribute('aria-busy')==='false');
    await page.evaluate(()=>{
      window.__boardMotionObservation?.stop?.();
      const nodeIds=new WeakMap(),animationIds=new WeakMap();let nodeSequence=0,animationSequence=0,frame=0,frames=0,active=false,stopped=null;
      const observed=new Map();
      const nodeId=node=>{if(!nodeIds.has(node))nodeIds.set(node,++nodeSequence);return nodeIds.get(node);};
      const animationId=animation=>{if(!animationIds.has(animation))animationIds.set(animation,++animationSequence);return animationIds.get(animation);};
      const nodes=()=>[...document.querySelectorAll('.task-board-column,.task-board .task-row')];
      const animations=()=>nodes().flatMap(node=>node.getAnimations()).filter(animation=>animation.constructor.name==='Animation');
      const describe=animation=>{
        const target=animation.effect?.target;
        return {id:animationId(animation),constructor:animation.constructor.name,play_state:animation.playState,pending:animation.pending,
          current_time:animation.currentTime,start_time:animation.startTime,timing:animation.effect?.getTiming(),computed_timing:animation.effect?.getComputedTiming(),
          target:target?{node:nodeId(target),tag:target.tagName,id:target.id,classes:target.className,task_id:target.dataset.taskId||null,lane:target.closest('[data-task-lane]')?.dataset.taskLane||null,connected:target.isConnected}:null};
      };
      const snapshot=()=>({at:performance.now(),hash:location.hash,content_inert:document.querySelector('#content')?.inert,
        busy:document.querySelector('#task-results')?.getAttribute('aria-busy'),toast:document.querySelector('#toast .toast-copy')?.textContent||'',
        lanes:[...document.querySelectorAll('[data-task-lane]')].map(lane=>({lane:lane.dataset.taskLane,ids:[...lane.querySelectorAll('.task-row')].map(node=>node.dataset.taskId)})),
        animations:animations().map(describe)});
      const sample=()=>{frames++;for(const animation of animations()){
        const value=describe(animation),previous=observed.get(value.id);
        observed.set(value.id,{first_seen:previous?.first_seen??performance.now(),last_seen:performance.now(),first:previous?.first||value,last:value});
      }};
      const tick=()=>{if(!active)return;sample();frame=requestAnimationFrame(tick);};
      const stop=()=>{if(stopped)return stopped;active=false;cancelAnimationFrame(frame);sample();return stopped={frames,observed_animations:[...observed.values()],final:snapshot()};};
      window.__boardMotionObservation={animations,snapshot,stop,start(){observed.clear();frames=0;stopped=null;active=true;this.previousToast=document.querySelector('#toast .toast-copy');tick();}};
    });
    observation.precondition={before:await motionSnapshot()};
    await page.evaluate(async()=>{
      const finite=window.__boardMotionObservation.animations().filter(animation=>animation.effect?.getTiming().iterations!==Infinity);
      let timer;
      try{await Promise.race([Promise.all(finite.map(animation=>animation.finished.catch(()=>{}))),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Initial board entrances did not finish within the existing 12000ms deadline')),12000);})]);}
      finally{clearTimeout(timer);}
    });
    observation.precondition.after=await motionSnapshot();
    assert.equal(observation.precondition.after.animations.length,0,'Initial route entrances must finish before measuring drag acknowledgements');
    await page.evaluate(()=>window.__boardMotionObservation.start());
  };
  const drag=async(id,x,y,{cancel=false,expectMove=!cancel,expectedStatus=200}={})=>{
    const observation={engine,task_id:id,cancel,expect_move:expectMove,expected_status:expectMove?expectedStatus:null,status:'running',requests:[],responses:[]};
    report.motion_observations.push(observation);
    let moveResponse,refreshResponse,resolveMove,resolveRefresh;
    const moveReady=new Promise(resolve=>{resolveMove=resolve;}),refreshReady=new Promise(resolve=>{resolveRefresh=resolve;});
    const moveRequests=new Set(),refreshRequests=new Set();
    const query=await page.locator('#task-search').inputValue();
    const requestDetails=request=>({method:request.method(),path:new URL(request.url()).pathname,query:new URL(request.url()).search,at:Date.now()});
    const onRequest=request=>{
      const url=new URL(request.url());
      if(request.method()==='POST'&&url.pathname==='/api/tasks/'+id+'/move'){
        moveRequests.add(request);observation.requests.push({...requestDetails(request),kind:'move',payload:request.postDataJSON()});
      }else if(moveResponse&&request.method()==='GET'&&url.pathname==='/api/tasks/page'&&url.searchParams.get('q')===query&&url.searchParams.get('sort')==='board'&&!url.searchParams.has('cursor')){
        refreshRequests.add(request);observation.requests.push({...requestDetails(request),kind:'after_move_refresh'});
      }
    };
    const onResponse=response=>{
      const request=response.request();
      if(moveRequests.has(request)){
        observation.responses.push({...requestDetails(request),kind:'move',status:response.status()});
        if(!moveResponse){moveResponse=response;resolveMove(response);}
      }else if(refreshRequests.has(request)){
        observation.responses.push({...requestDetails(request),kind:'after_move_refresh',status:response.status()});
        if(!refreshResponse){refreshResponse=response;resolveRefresh(response);}
      }
    };
    const bounded=async(promise,label)=>{
      let timer;
      try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+' did not arrive within the existing 12000ms deadline')),12000);})]);}
      finally{clearTimeout(timer);}
    };
    page.on('request',onRequest);page.on('response',onResponse);
    try{
      await prepareBoardMotion(observation);
      const box=await row(id).locator('.task-primary').boundingBox();
      const sourceBox=await row(id).boundingBox(),offsetX=box.x+12-sourceBox.x,offsetY=box.y+12-sourceBox.y;
      await page.mouse.move(box.x+12,box.y+12);await page.mouse.down();
      for(let i=1;i<=14;i++){await page.mouse.move(box.x+12+(x-box.x-12)*i/14,box.y+12+(y-box.y-12)*i/14);await page.waitForTimeout(16);}
      await page.locator('.task-drag-ghost').waitFor();
      const ghost=await page.locator('.task-drag-ghost').boundingBox();assert.ok(Math.abs(ghost.x-(x-offsetX))<1.5&&Math.abs(ghost.y-(y-offsetY))<1.5,'The ghost follows the pointer without a spring delay');assert.ok(Math.abs(ghost.width-sourceBox.width)<1.5);
      if(cancel)await page.keyboard.press('Escape');
      await page.mouse.up();assert.equal(await page.locator('.task-drag-ghost').count(),0,'Release must remove the ghost immediately, without a landing animation');
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      observation.after_release=await motionSnapshot();
      assert.equal(await page.locator('.task-board-column,.task-board .task-row').evaluateAll(nodes=>nodes.flatMap(node=>node.getAnimations()).filter(animation=>animation.constructor.name==='Animation').length),0,'Server acknowledgements must not replay card or lane entrances');
      if(expectMove){
        const response=await bounded(moveReady,'The drag move response');observation.move_response_body=await response.json();
        assert.equal(response.status(),expectedStatus,'The actual move response must match this scenario');
        const refreshed=await bounded(refreshReady,'The page read started after the move response');observation.refresh_response_body=await refreshed.json();
        assert.equal(refreshed.status(),200,'The post-move page read must return the saved server state');
        const expectedIds=observation.refresh_response_body.items.map(item=>item.id).sort();
        // The visible operation receipt is produced only after the application
        // applies its page read. A new receipt node prevents an earlier move's
        // toast or the optimistic pointer position from satisfying this wait.
        await page.waitForFunction(({expectedIds,expectedStatus})=>{
          const toast=document.querySelector('#toast'),copy=toast?.querySelector('.toast-copy'),probe=window.__boardMotionObservation;
          const actual=[...document.querySelectorAll('#task-results .task-row')].map(node=>node.dataset.taskId).sort();
          return copy&&copy!==probe.previousToast&&toast.classList.contains('visible')&&
            (expectedStatus===200?toast.getAttribute('role')==='status'&&!!toast.querySelector('.toast-action')&&/^(位置已保存|已标记完成)$/.test(copy.textContent):toast.getAttribute('role')==='alert'&&/更新|重试|重拖/.test(copy.textContent))&&
            document.querySelector('#task-results')?.getAttribute('aria-busy')==='false'&&JSON.stringify(actual)===JSON.stringify(expectedIds);
        },{expectedIds,expectedStatus});
        observation.after_acknowledgement=await motionSnapshot();
        assert.equal(observation.after_acknowledgement.animations.length,0,'The acknowledged page update must not replay card or lane entrances');
      }
      observation.measurement=await page.evaluate(()=>window.__boardMotionObservation.stop());
      assert.equal(observation.measurement.observed_animations.length,0,'No card or lane entrance may occur between the settled route and the acknowledged move');
      if(!expectMove)assert.equal(moveRequests.size,0,'A cancelled or outside drop must not send a move request');
      observation.status='passed';await settle();
    }catch(error){observation.status='failed';observation.error=error.message;throw error;}
    finally{
      page.off('request',onRequest);page.off('response',onResponse);
      observation.measurement=await page.evaluate(()=>window.__boardMotionObservation?.stop?.()).catch(error=>({error:error.message}));
      await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
    }
  };
  try{
    await page.goto(origin);await page.locator('[name=username]').fill(process.env.CAMPUS_VERIFY_USER||'workflow.demo');await page.locator('[name=password]').fill(process.env.CAMPUS_VERIFY_PASSWORD||'Mvp-Verification-Only-2026');await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
    const prefix='拖动验收 '+engine+' '+Date.now();
    const notice=await api('/notices','POST',{title:prefix,body:prefix+'：仅用于测试个人安排，不包含真实办理要求。',source_label:'工程夹具',materials_complete:'true'},true);
    const manual=await api('/notices/'+notice.id+'/manual','POST',{version:notice.version});
    const saved=await api('/notices/'+notice.id+'/confirm','POST',{version:manual.version,reviewed:true,tasks:['A','B','C'].map(letter=>({title:prefix+' '+letter,origin:'manual',scope:'personal'}))});
    const [a,b,c]=saved.task_ids;
    await page.goto(origin+'/#tasks');await page.locator('[data-task-view=board]').click();await page.locator('#task-search').fill(prefix);if(await page.locator('#task-status-select').isVisible())await page.locator('#task-status-select').selectOption('all');else await page.locator('[data-filter=all]').click();await page.waitForFunction(()=>document.querySelectorAll('#task-results .task-row').length===3);await settle();
    const initial=await ids('action');
    await check('cached task views retain live row nodes and focus, and restore filters after the home route',()=>verifyTaskListStability(page,initial[0]));
    await check('whole-card drag reorders, persists after reload, and does not open the task',async()=>{
      const target=await row(initial[0]).boundingBox();await drag(initial[2],target.x+target.width/2,target.y+12);
      assert.deepEqual(await ids('action'),[initial[2],initial[0],initial[1]]);assert.equal(await page.locator('#dialog').evaluate(n=>n.open),false);
      await page.reload();await page.locator('[data-task-view=board]').click();await page.locator('#task-search').fill(prefix);if(await page.locator('#task-status-select').isVisible())await page.locator('#task-status-select').selectOption('all');else await page.locator('[data-filter=all]').click();await page.waitForFunction(()=>document.querySelectorAll('#task-results .task-row').length===3);await settle();
      assert.deepEqual(await ids('action'),[initial[2],initial[0],initial[1]]);
    });
    await check('cross-lane move changes personal progress while preserving formal evidence',async()=>{
      const target=await page.locator('[data-task-lane=followup] .task-lane-items').boundingBox();await drag(a,target.x+target.width/2,target.y+50);
      assert.ok((await ids('followup')).includes(a));const task=(await api('/tasks/'+a+'/workflow')).task;assert.equal(task.status,'pending');assert.equal(task.workflow.data.stage,'preparing');
      await page.screenshot({path:path.join(out,engine+'-desktop.png')});
    });
    await check('completion and undo update the real task without a confirmation modal',async()=>{
      const target=await page.locator('[data-task-lane=closed] .task-lane-items').boundingBox();await drag(a,target.x+target.width/2,target.y+50);
      assert.equal((await api('/tasks/'+a+'/workflow')).task.status,'done');assert.ok((await ids('closed')).includes(a));
      await page.locator('#toast .toast-action').click();await settle();assert.equal((await api('/tasks/'+a+'/workflow')).task.status,'pending');assert.ok((await ids('followup')).includes(a));
    });
    await check('escape and outside drops cancel cleanly without requests or accidental navigation',async()=>{
      const before=await ids('action');let moves=0;const count=r=>{if(r.url().endsWith('/move'))moves++;};page.on('request',count);
      const target=await page.locator('[data-task-lane=closed]').boundingBox();await drag(b,target.x+20,target.y+60,{cancel:true});await drag(b,80,200,{expectMove:false});
      page.off('request',count);assert.equal(moves,0);assert.deepEqual(await ids('action'),before);assert.equal(await page.locator('#dialog').evaluate(n=>n.open),false);assert.equal(await page.locator('.task-drop-placeholder').count(),0);
    });
    await check('failed save restores the current server position and offers recovery',async()=>{
      await page.route('**/api/tasks/*/move',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'这项待办刚有更新，已恢复最新位置，请重试'})}));
      const before=await ids('action'),target=await page.locator('[data-task-lane=followup] .task-lane-items').boundingBox();await drag(b,target.x+30,target.y+30,{expectedStatus:409});
      await page.unroute('**/api/tasks/*/move');assert.deepEqual(await ids('action'),before);assert.match(await page.locator('#toast').innerText(),/更新|重试|重拖/);
    });
    await check('keyboard move menu works with reduced motion',async()=>{
      await page.emulateMedia({reducedMotion:'reduce'});await row(b).locator('[data-task-drag-handle]').focus();await page.keyboard.press('Enter');
      const saved=page.waitForResponse(r=>r.url().endsWith('/tasks/'+b+'/move')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'移到留意反馈',exact:true}).click();assert.equal((await saved).status(),200);await row(b).locator('xpath=ancestor::section[@data-task-lane="followup"]').waitFor();assert.ok((await ids('followup')).includes(b));assert.equal(await page.locator('.task-drag-ghost').count(),0);
    });
    if(engine==='chromium')await check('native touch reorders, crosses stacked lanes through the dock, undoes, and leaves ordinary swipes as scrolling',async()=>{
      const mobileContext=await browser.newContext({serviceWorkers:'block',viewport:{width:390,height:844},hasTouch:true,isMobile:true,storageState:await page.context().storageState()});
      const mobile=await mobileContext.newPage();
      try{
        await mobile.goto(origin+'/#tasks');await mobile.locator('[data-task-view=board]').click();await mobile.locator('#task-search').fill(prefix);if(await mobile.locator('#task-status-select').isVisible())await mobile.locator('#task-status-select').selectOption('all');else await mobile.locator('[data-filter=all]').click();
        await mobile.waitForFunction(()=>document.querySelectorAll('#task-results .task-row').length===3);await mobile.waitForTimeout(350);
        const follow=mobile.locator('[data-task-lane=followup] .task-row'),before=await follow.evaluateAll(nodes=>nodes.map(n=>n.dataset.taskId));assert.equal(before.length,2);
        await follow.last().scrollIntoViewIfNeeded();await mobile.waitForTimeout(250);
        const handle=await follow.last().locator('[data-task-drag-handle]').boundingBox(),target=await follow.first().boundingBox();
        const session=await mobileContext.newCDPSession(mobile),x=handle.x+handle.width/2,y=handle.y+handle.height/2;
        await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1}]});await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+4,y,id:1}]});
        await mobile.locator('.task-drag-ghost').waitFor();
        for(let i=1;i<=12;i++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+(target.x+80-x)*i/12,y:y+(target.y+12-y)*i/12,id:1}]});await mobile.waitForTimeout(16);}
        await fs.writeFile(path.join(out,engine+'-touch-placement.json'),JSON.stringify(await mobile.evaluate(()=>({moving:document.documentElement.classList.contains('task-dragging'),ghosts:document.querySelectorAll('.task-drag-ghost').length,placeholderLane:document.querySelector('.task-drop-placeholder')?.closest('[data-task-lane]')?.dataset.taskLane,next:document.querySelector('.task-drop-placeholder')?.nextElementSibling?.dataset.taskId})),null,2));
        assert.equal(await mobile.locator('.task-drag-ghost').count(),1,'Transferring implicit touch capture to the board must keep dragging active');
        await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await mobile.locator('.task-drag-ghost').waitFor({state:'detached'});await mobile.waitForTimeout(350);
        assert.deepEqual(await follow.evaluateAll(nodes=>nodes.map(n=>n.dataset.taskId)),[before[1],before[0]]);
        assert.equal(await mobile.locator('#dialog').evaluate(n=>n.open),false);
        const movedId=await follow.last().getAttribute('data-task-id');
        await follow.last().locator('[data-task-drag-handle]').scrollIntoViewIfNeeded();
        const grip=await follow.last().locator('[data-task-drag-handle]').boundingBox();
        await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:grip.x+grip.width/2,y:grip.y+grip.height/2,id:3}]});
        await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:grip.x+grip.width/2+4,y:grip.y+grip.height/2,id:3}]});
        await mobile.locator('.task-drag-dock').waitFor();
        const drop=await mobile.locator('[data-task-drop-lane=action]').boundingBox();
        for(let i=1;i<=12;i++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:grip.x+grip.width/2+(drop.x+drop.width/2-grip.x-22)*i/12,y:grip.y+grip.height/2+(drop.y+drop.height/2-grip.y-22)*i/12,id:3}]});await mobile.waitForTimeout(16);}
        const dockSaved=mobile.waitForResponse(r=>r.url().endsWith('/tasks/'+movedId+'/move')&&r.request().method()==='POST');
        await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});assert.equal((await dockSaved).status(),200);await mobile.locator('.task-drag-dock').waitFor({state:'detached'});
        await mobile.locator(`[data-task-lane=action] [data-task-id="${movedId}"]`).waitFor();
        assert.equal((await api('/tasks/'+movedId+'/workflow')).task.workflow.data.board_lane,'action');
        const undone=mobile.waitForResponse(r=>r.url().endsWith('/tasks/'+movedId+'/move')&&r.request().method()==='POST');
        await mobile.locator('#toast .toast-action').click();assert.equal((await undone).status(),200);await mobile.locator(`[data-task-lane=followup] [data-task-id="${movedId}"]`).waitFor();
        await mobile.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity&&!a.effect?.target?.closest?.('#toast')).map(a=>a.finished.catch(()=>{}))));
        await mobile.locator('.task-board-scroll').evaluate(el=>{el.scrollLeft=0;});await mobile.waitForTimeout(100);
        await mobile.locator('[data-task-lane=followup] .task-row').first().scrollIntoViewIfNeeded();const boardBox=await mobile.locator('[data-task-lane=followup] .task-row').first().boundingBox(),swipeY=Math.min(boardBox.y+boardBox.height/2,600);const scrollBefore=await mobile.locator('#content').evaluate(n=>n.scrollTop);
        await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:160,y:swipeY,id:2}]});
        for(let i=1;i<=10;i++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:160,y:swipeY-i*16,id:2}]});await mobile.waitForTimeout(16);}
        await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await mobile.waitForTimeout(250);
        assert.equal(await mobile.locator('.task-drag-ghost').count(),0);
        assert.ok(await mobile.locator('#content').evaluate(n=>n.scrollTop)>scrollBefore,'A normal card swipe scrolls the stacked board');assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
        await mobile.screenshot({path:path.join(out,'chromium-touch.png')});
      }finally{await mobileContext.close();}
    });
    for(const width of [390,320])await check('compact '+width+'px layout retains reachable move targets and no horizontal overflow',async()=>{
      await page.setViewportSize({width,height:844});await settle();const handle=row(c).locator('[data-task-drag-handle]');await handle.scrollIntoViewIfNeeded();
      const box=await handle.boundingBox();assert.ok(box.width>=43.9&&box.height>=43.9,JSON.stringify(box));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await handle.click();await page.getByRole('button',{name:'移到留意反馈',exact:true}).waitFor();await page.keyboard.press('Escape');
      await page.screenshot({path:path.join(out,engine+'-'+width+'.png')});
    });
  }catch(error){report.errors.push({engine,error:error.message});console.log('ERROR',engine,error.message);}
  finally{await browser.close();}
}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,failed:report.checks.filter(c=>!c.ok).length,errors:report.errors.length}));
if(report.errors.length||report.checks.some(c=>!c.ok))process.exitCode=1;
