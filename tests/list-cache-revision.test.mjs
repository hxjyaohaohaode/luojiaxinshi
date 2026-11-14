import test from 'node:test';
import assert from 'node:assert/strict';
import {createPagedList} from '../static/paged-list.js';
import {createWorkspaceProjection} from '../static/workspace-projection.js';
import {createListClock} from '../static/list-clock.js';
import * as listRevisions from '../static/list-clock.js';
import {installDataSync} from '../static/data-sync.js';

const task=id=>({id,version:1,status:'pending',updated_at:1,workflow:{version:1,data:{stage:'preparing'}},data:{title:id,materials:['材料原文'],details:'完整办理说明'},overdue:false,due_soon:false,followup_due:false,handling_state:{kind:'start',label:'准备办理',detail:'原文细节'}});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};

function workspace(size=60){
  let route='tasks',owner='alice',revision=1,pageRevision=1,latest=null,latestOwner=null,holdNext=null,paints=0,projectionReads=0;
  const rows=Array.from({length:size},(_,i)=>task('task-'+i)),pageReads=[];
  const api=async value=>{
    const url=new URL(value,'https://fixture');
    if(url.pathname==='/workspace/projection'){
      projectionReads++;
      const sparse=url.searchParams.get('clock_only')==='1'&&url.searchParams.get('revision')===String(revision);
      return {projection:'light',revision:String(revision),clock:1,clock_only:sparse,counts:{tasks:rows.length},tasks:rows.map(item=>sparse?{id:item.id,overdue:item.overdue,due_soon:item.due_soon,followup_due:item.followup_due,handling_state:structuredClone(item.handling_state)}:{...structuredClone(item),projection:'light',data:{title:item.data.title,details:'',materials:[]}})};
    }
    assert.equal(url.pathname,'/tasks/page');pageReads.push(url.pathname+url.search);
    const cursor=url.searchParams.get('cursor'),parts=cursor?.split(':');
    if(parts&&Number(parts[0])!==pageRevision)throw Object.assign(new Error('list changed'),{status:409,detail:{code:'list_changed'}});
    const status=url.searchParams.get('status'),selected=rows.filter(item=>!status||status==='all'||item.status===status),offset=parts?Number(parts[1]):0,limit=Number(url.searchParams.get('limit'));
    const body={items:structuredClone(selected.slice(offset,offset+limit)),total:selected.length,has_more:offset+limit<selected.length,next_cursor:offset+limit<selected.length?pageRevision+':'+(offset+limit):null,snapshot:'page-'+pageRevision};
    if(holdNext){const hold=holdNext;holdNext=null;hold.started.resolve();await hold.promise;}
    return body;
  };
  const projection=createWorkspaceProjection({api,owner:()=>owner,context:()=>route});
  // The accepted shared projection is observed from the real controller's
  // returned value. On the old implementation the new list option is ignored,
  // so the red regression fails on stale data rather than a missing method.
  const project=async(clockOnly=false)=>{const value=await projection.load(['tasks'],{clockOnly});if(value){latest=value;latestOwner=owner;}return value;};
  const list=createPagedList({api,path:'/tasks/page',owner:()=>owner,context:()=>route,revision:()=>latestOwner===owner?latest?.revision??null:null,onChange:()=>paints++});
  const clock=createListClock('tasks');
  const refresh=async()=>clock.refresh(list,await project(true),{owner:'alice',reload:options=>list.reload(options)});
  return {rows,list,projection,project,refresh,pageReads,projectionReads:()=>projectionReads,paints:()=>paints,route:value=>{route=value;},owner:value=>{owner=value;},mutate:change=>{change(rows);revision++;pageRevision++;},advanceProjection:()=>revision++,holdPage:()=>{holdNext={...deferred(),started:deferred()};return holdNext;}};
}

for(const operation of ['insert','delete','status'])test('a cached pending list detects an off-route '+operation+' after the home projection advances',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'pending'});await app.refresh();
  const before=app.pageReads.length,previous=app.list.snapshot().items.map(item=>item.id);
  app.route('dashboard');app.mutate(rows=>{if(operation==='insert')rows.unshift(task('new-home-task'));else if(operation==='delete')rows.pop();else{rows.at(-1).status='done';rows.at(-1).version++;}});
  const home=await app.project();assert.equal(home.revision,'2');
  app.route('tasks');await app.list.load({status:'pending'});await app.refresh();
  const result=app.list.snapshot();assert.equal(result.total,operation==='insert'?61:59);
  assert.equal(app.pageReads.length,before+1,'The stale cached page must be revalidated exactly once');
  assert.equal(result.items.length,50);assert.equal(result.items[0].id,operation==='insert'?'new-home-task':previous[0]);
  assert.ok(result.items.every(item=>item.status==='pending'));
  const reads=app.pageReads.length;await app.refresh();assert.equal(app.pageReads.length,reads,'The now-current clock must not reread full pages');
});

test('an unchanged route round trip preserves all 54 loaded records without another page read or paint',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.list.more();await app.refresh();
  const before=app.list.snapshot(),reads=app.pageReads.length,paints=app.paints();
  app.route('dashboard');await app.project();app.route('tasks');await app.list.load({status:'all'});await app.refresh();
  assert.deepEqual(app.list.snapshot().items,before.items);assert.equal(app.list.snapshot().total,54);
  assert.equal(app.pageReads.length,reads);assert.equal(app.paints(),paints);
});

test('a stale 54-record cache revalidates its entire loaded range when returning from another route',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.list.more();await app.refresh();
  const original=app.list.snapshot().items.map(item=>item.id),reads=app.pageReads.length;
  app.route('dashboard');app.mutate(rows=>rows.unshift(task('new-before-loaded-range')));await app.project();
  app.route('tasks');await app.list.load({status:'all'});
  const result=app.list.snapshot();assert.equal(result.total,55);assert.equal(result.items.length,55);
  assert.deepEqual(result.items.map(item=>item.id),['new-before-loaded-range',...original]);
  assert.equal(app.pageReads.length,reads+2,'Both originally loaded pages must be revalidated, not reduced to the first 50');
  const complete=app.pageReads.length;await app.refresh();assert.equal(app.pageReads.length,complete);
});

test('a page started before the shared revision advances cannot certify its late old response with the new revision',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),pending=app.list.reload();
  app.mutate(rows=>rows.push(task('late-new-task')));await app.project();hold.resolve();await pending;
  assert.equal(app.list.snapshot().total,60,'The held response really contains the older total');
  await app.refresh();assert.equal(app.list.snapshot().total,61,'A newer shared cache must not hide the older page response');
});

test('loading more after only the shared projection advances revalidates the cached prefix even when its cursor is accepted',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'all'});await app.refresh();
  const reads=app.pageReads.length;app.advanceProjection();await app.project();await app.list.more();
  assert.equal(new URL(app.pageReads[reads],'https://fixture').searchParams.has('cursor'),false,'The old prefix cannot acquire a new revision from an appended page');
  assert.equal(app.list.snapshot().items.length,60);assert.equal(app.pageReads.length,reads+2);
  const complete=app.pageReads.length;await app.refresh();assert.equal(app.pageReads.length,complete);
});

test('a refused refresh does not advance the cached list revision',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'all'});await app.refresh();
  app.mutate(rows=>rows.push(task('new-while-blocked')));await app.project();
  assert.equal(await app.list.reload({preserveRange:true,canApply:()=>false}),null);
  assert.equal(app.list.snapshot().total,60);
  await app.refresh();assert.equal(app.list.snapshot().total,61,'The rejected response must leave the old baseline invalid');
});

test('the shared revision accessor never returns a previous account revision',async()=>{
  let owner='alice';const projection=createWorkspaceProjection({owner:()=>owner,api:async()=>({revision:owner+'-revision',clock_only:false,tasks:[],counts:{tasks:0}})});
  assert.equal(typeof projection.revision,'function');assert.equal(projection.revision('tasks'),null);
  await projection.load(['tasks']);assert.equal(projection.revision('tasks'),'alice-revision');
  owner='bob';assert.equal(projection.revision('tasks'),null);await projection.load(['tasks']);assert.equal(projection.revision('tasks'),'bob-revision');
});

test('one load-more intent survives a delayed background range refresh without duplicating repeated clicks',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),background=app.list.reload({preserveRange:true});
  const first=app.list.more(),second=app.list.more();assert.equal(first,second);
  hold.resolve();await background;const result=await first;
  assert.equal(result.items.length,60,'The user requested the next page, not merely the pending 50-row refresh');
  assert.equal(app.list.snapshot().items.length,60);assert.equal(app.pageReads.length,3);
});

for(const change of ['owner','route','filter'])test('a queued load-more intent cannot follow an intervening '+change+' change',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),background=app.list.reload({preserveRange:true}),more=app.list.more();
  if(change==='owner')app.owner('bob');else if(change==='route')app.route('calendar');else await app.list.load({status:'done'});
  hold.resolve();await background;assert.equal(await more,null);assert.equal(app.pageReads.length,change==='filter'?3:2,'No late appended page may escape its original user, route and filter');
  if(change==='filter')assert.equal(app.list.snapshot().items.length,0);
});

test('a temporary background paint gate cannot discard an explicit same-scope load-more intent',async()=>{
  const app=workspace();await app.project();await app.list.load({status:'all'});await app.refresh();let allowed=true;
  const hold=app.holdPage(),background=app.list.reload({preserveRange:true,canApply:()=>allowed}),more=app.list.more();
  // A real pointer interaction closes the background paint gate briefly.
  // The explicit user request has its own scope and must not inherit that gate.
  allowed=false;hold.resolve();assert.equal(await background,null);const result=await more;
  assert.equal(result.items.length,60);assert.equal(app.pageReads.length,3);assert.equal(app.list.snapshot().items.length,60);
});

for(const failure of ['network','invalid response'])test('a background '+failure+' remains an error and does not release queued more through a closed paint gate',async()=>{
  const hold=deferred();let reads=0,allowed=true;
  const list=createPagedList({owner:()=> 'alice',context:()=> 'tasks',path:'/tasks/page',api:async()=>{
    if(++reads===1)return {items:Array.from({length:50},(_,i)=>task('task-'+i)),total:60,has_more:true,next_cursor:'next'};
    await hold.promise;if(failure==='network')throw Error('真实网络失败');return {items:null,total:60};
  }});
  await list.load({status:'all'});const background=list.reload({preserveRange:true,canApply:()=>allowed}),more=list.more();
  allowed=false;hold.resolve();assert.equal(await background,null);assert.equal(await more,null);
  assert.equal(reads,2);assert.equal(list.snapshot().items.length,50);assert.match(list.snapshot().error,failure==='network'?/真实网络失败/:/列表响应不完整/);
});

async function withoutProjectionSync(app,run){
  const beforeWindow=globalThis.window,beforeDocument=globalThis.document;
  globalThis.window=new EventTarget();globalThis.document=Object.assign(new EventTarget(),{hidden:false});
  let current={revision:'signal-1',domains:{tasks:1,notices:1,account:1,clock:1}},changes=0;
  const state={session:{user:{id:'alice'},sync:structuredClone(current)}};
  // This is the same production invalidation dispatch used before the
  // application selects a route's data needs. Settings and sources do not
  // fetch a task projection, but the real sync controller consumes the signal.
  const sync=installDataSync({state,api:async path=>{assert.equal(path,'/proactive/revision');return structuredClone(current);},onChange:async domains=>{changes++;listRevisions.invalidateChangedLists?.(domains,[app.list]);return true;}});
  try{await sync.probe();await run({sync,changes:()=>changes,signal:domains=>{current={revision:'signal-'+(changes+2),domains:{...current.domains,...domains}};}});}
  finally{sync.stop();globalThis.window=beforeWindow;globalThis.document=beforeDocument;}
}

for(const route of ['settings','sources'])for(const operation of ['insert','delete','status'])test('an authoritative off-route '+operation+' signal consumed on '+route+' invalidates the full cached range without a projection read',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'pending'});await app.list.more();await app.refresh();
  const before=app.pageReads.length,projectionReads=app.projectionReads();app.route(route);
  await withoutProjectionSync(app,async({sync,signal,changes})=>{
    app.mutate(rows=>{if(operation==='insert')rows.unshift(task('off-route-insert'));else if(operation==='delete')rows.pop();else{rows.at(-1).status='done';rows.at(-1).version++;}});
    signal({tasks:2});await sync.probe();await sync.probe();assert.equal(changes(),1,'The stable signal has already been consumed off route');
    assert.equal(app.projectionReads(),projectionReads);
    app.route('tasks');await app.list.load({status:'pending'});
    const expected=operation==='insert'?55:53,result=app.list.snapshot();assert.equal(result.total,expected);assert.equal(result.items.length,expected);
    assert.equal(app.pageReads.length,before+2,'Revalidation preserves both loaded pages');assert.ok(result.items.every(item=>item.status==='pending'));
    const reads=app.pageReads.length;await app.list.load({status:'pending'});assert.equal(app.pageReads.length,reads);
  });
});

test('a consumed clock-only or unrelated signal does not invalidate the unchanged cached range off route',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.list.more();await app.refresh();
  const before=app.pageReads.length,paints=app.paints();app.route('settings');
  await withoutProjectionSync(app,async({sync,signal})=>{
    signal({clock:2,delivery:1});await sync.probe();await sync.probe();app.route('tasks');await app.list.load({status:'all'});
    assert.equal(app.list.snapshot().items.length,54);assert.equal(app.pageReads.length,before);assert.equal(app.paints(),paints);
  });
});

test('a stable signal received after a page starts cannot be acknowledged by that late page response',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),pending=app.list.reload({preserveRange:true});
  app.mutate(rows=>rows.unshift(task('changed-after-request')));listRevisions.invalidateChangedLists?.(new Set(['tasks']),[app.list]);
  hold.resolve();await pending;await app.list.load({status:'all'});
  assert.equal(app.list.snapshot().total,55);assert.equal(app.list.snapshot().items[0].id,'changed-after-request');
});

for(const change of ['domain invalidation','shared projection'])test('an active range refresh cannot reuse an older pending request after '+change+' advances',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.list.more();await app.refresh();
  const hold=app.holdPage(),older=app.list.reload({preserveRange:true}),reads=app.pageReads.length;
  try{
    app.mutate(rows=>rows.unshift(task('active-new-task')));
    if(change==='domain invalidation')listRevisions.invalidateChangedLists?.(new Set(['tasks']),[app.list]);else await app.project();
    const current=app.list.load({status:'all'},{force:change==='domain invalidation',preserveRange:true});
    assert.equal(app.pageReads.length,reads+1,'The current refresh must start its own request instead of reusing the older pending read');
    const result=await current;assert.equal(result.total,55);assert.equal(result.items.length,55);assert.equal(result.items[0].id,'active-new-task');
    hold.resolve();assert.equal(await older,null,'The superseded old response cannot replace the committed current range');
    assert.equal(app.list.snapshot().total,55);
  }finally{hold.resolve();await older;}
});

test('a range refresh in a new route view cannot reuse an old-view pending request at the same newer revision',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.list.more();await app.refresh();
  app.mutate(rows=>rows.unshift(task('new-view-task')));await app.project();
  const hold=app.holdPage(),older=app.list.reload({preserveRange:true}),reads=app.pageReads.length;
  try{
    app.route('tasks-new-render');const current=app.list.reload({preserveRange:true});
    assert.equal(app.pageReads.length,reads+1,'A request bound to the old render cannot serve the current view');
    const result=await current;assert.equal(result.total,55);assert.equal(result.items.length,55);assert.equal(result.items[0].id,'new-view-task');
    hold.resolve();assert.equal(await older,null);
  }finally{hold.resolve();await older;}
});

for(const change of ['domain invalidation','shared projection'])test('an explicit next-page target survives a newer '+change+' refresh that starts while the append is in flight',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),more=app.list.more();
  try{
    app.mutate(rows=>rows.unshift(task('insert-during-append')));
    if(change==='domain invalidation')listRevisions.invalidateChangedLists(new Set(['tasks']),[app.list]);else await app.project();
    const background=app.list.reload({preserveRange:true});await background;hold.resolve();
    const result=await more;
    assert.equal(app.list.snapshot().items.length,55,'A stable refresh may not replace the requested next-page range with only its committed prefix');
    assert.equal(result?.items.length,55,'The original user promise must resolve with the completed requested range');
    assert.deepEqual(result.items.map(item=>item.id),app.rows.map(item=>item.id));
    assert.equal(result.has_more,false);assert.equal(result.projection_stale,false);
  }finally{hold.resolve();await more;}
});

test('repeated more clicks coalesce across a superseding range refresh without requesting a third page',async()=>{
  const app=workspace(140);await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),more=app.list.more();
  try{
    app.list.invalidate();const background=app.list.reload({preserveRange:true});
    const repeat=app.list.more();assert.equal(repeat,more);
    await background;hold.resolve();const result=await more;
    assert.equal(result.items.length,100);assert.equal(app.list.snapshot().items.length,100);assert.equal(result.has_more,true);
    assert.equal(app.pageReads.filter(path=>new URL(path,'https://fixture').searchParams.get('cursor')?.endsWith(':100')).length,0);
  }finally{hold.resolve();await more;}
});

for(const change of ['owner','route','filter'])test('an in-flight explicit next-page target cannot be transferred across a '+change+' change',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),more=app.list.more();
  try{
    if(change==='owner')app.owner('bob');else if(change==='route')app.route('calendar');else await app.list.load({status:'done'});
    hold.resolve();assert.equal(await more,null);
    assert.equal(app.pageReads.length,change==='filter'?3:2);
    if(change==='filter')assert.equal(app.list.snapshot().items.length,0);
  }finally{hold.resolve();await more;}
});

test('a superseding background paint gate does not discard an already in-flight explicit next-page target',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.refresh();
  const hold=app.holdPage(),more=app.list.more();
  try{
    app.list.invalidate();assert.equal(await app.list.reload({preserveRange:true,canApply:()=>false}),null);
    hold.resolve();const result=await more;
    assert.equal(result?.items.length,54);assert.equal(app.list.snapshot().items.length,54);
  }finally{hold.resolve();await more;}
});

test('a next-page intent in cursor-conflict recovery survives a newer stable refresh with the same requested range',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all'});await app.refresh();
  app.mutate(rows=>rows.push(task('cursor-revision-two')));
  const hold=app.holdPage(),more=app.list.more();
  try{
    await hold.started.promise;assert.ok(app.pageReads[1].includes('cursor='));assert.ok(!app.pageReads[2].includes('cursor='));
    app.mutate(rows=>rows.push(task('cursor-revision-three')));app.list.invalidate();
    await app.list.reload({preserveRange:true});hold.resolve();const result=await more;
    assert.equal(result?.items.length,56);assert.deepEqual(result.items.map(item=>item.id),app.rows.map(item=>item.id));
    assert.equal(result.has_more,false);assert.equal(app.list.snapshot().error,'');
  }finally{hold.resolve();await more;}
});

test('multiple newer refreshes retain one fixed next-page target and old responses cannot settle it early',async()=>{
  const app=workspace(140);await app.project();await app.list.load({status:'all'});await app.refresh();
  const appendHold=app.holdPage(),more=app.list.more(),refreshHold=app.holdPage();let older,current,currentHold,settled=false;more.then(()=>{settled=true;});
  try{
    app.list.invalidate();older=app.list.reload({preserveRange:true});
    currentHold=app.holdPage();app.list.invalidate();current=app.list.reload({preserveRange:true});
    appendHold.resolve();refreshHold.resolve();await older;await Promise.resolve();
    assert.equal(settled,false,'An obsolete append or refresh cannot complete the still-current user range request');
    currentHold.resolve();const result=await more;await current;
    assert.equal(result.items.length,100);assert.equal(app.list.snapshot().items.length,100);assert.equal(result.has_more,true);
    assert.equal(app.list.snapshot().items.length,100);assert.equal(app.pageReads.some(path=>new URL(path,'https://fixture').searchParams.get('cursor')?.endsWith(':100')),false);
  }finally{appendHold.resolve();refreshHold.resolve();currentHold?.resolve();await more;await older;await current;}
});

for(const failure of ['network','invalid response'])test('a real '+failure+' failure in a superseding refresh cancels the original more intent and keeps the visible prefix',async()=>{
  const hold=deferred();let reads=0;
  const list=createPagedList({owner:()=> 'alice',context:()=> 'tasks',path:'/tasks/page',api:async()=>{
    const call=++reads;
    if(call===1)return {items:Array.from({length:50},(_,i)=>task('task-'+i)),total:54,has_more:true,next_cursor:'next'};
    if(call===2){await hold.promise;return {items:Array.from({length:4},(_,i)=>task('task-'+(50+i))),total:54,has_more:false,next_cursor:null};}
    if(failure==='network')throw Error('读取更新失败');return {items:null,total:54};
  }});
  await list.load({status:'all'});const more=list.more();
  try{
    list.invalidate();assert.equal(await list.reload({preserveRange:true}),null);hold.resolve();assert.equal(await more,null);
    assert.equal(list.snapshot().items.length,50);assert.match(list.snapshot().error,failure==='network'?/读取更新失败/:/列表响应不完整/);
    await Promise.resolve();await Promise.resolve();assert.equal(list.snapshot().items.length,50);assert.equal(reads,3);
  }finally{hold.resolve();await more;}
});

test('a confirmed board move and undo preserve the complete loaded range even before the shared revision advances',async()=>{
  const app=workspace(54);await app.project();await app.list.load({status:'all',sort:'board'});await app.list.more();await app.refresh();
  const original=app.rows.map(item=>item.id),moved=app.rows[50];
  app.mutate(rows=>{rows.splice(50,1);rows.splice(49,0,moved);});
  const result=await app.list.load({status:'all',sort:'board'},{force:true,preserveRange:true});
  const expected=[...original.slice(0,49),original[50],original[49],...original.slice(51)];
  assert.equal(result.items.length,54);assert.deepEqual(result.items.map(item=>item.id),expected);
  app.mutate(rows=>{rows.splice(49,1);rows.splice(50,0,moved);});
  const undone=await app.list.load({status:'all',sort:'board'},{force:true,preserveRange:true});
  assert.equal(undone.items.length,54);assert.deepEqual(undone.items.map(item=>item.id),original);
});
