import test from 'node:test';
import assert from 'node:assert/strict';
import {createPagedList} from '../static/paged-list.js';

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const response = (ids, extra = {}) => ({items: ids.map(id => ({id})), total: ids.length, limit: 50, next_cursor: null, has_more: false, ...extra});

test('a superseded search cannot replace the current server filtered result', async () => {
  const calls = [];
  const list = createPagedList({path: '/tasks/page', owner: () => 'alice', api: (url, options) => { const request = deferred(); calls.push({url, options, ...request}); return request.promise; }});
  const first = list.load({q: '旧条件', status: 'all'});
  const second = list.load({q: '新条件', status: 'pending'});
  assert.equal(calls[0].options.signal.aborted, true);
  calls[1].resolve(response(['new'], {total: 220, has_more: true, next_cursor: 'second-page'})); await second;
  calls[0].resolve(response(['old'])); await first;
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['new']);
  assert.equal(list.snapshot().total, 220);
  assert.equal(new URL(calls[1].url, 'https://local').searchParams.get('q'), '新条件');
});

test('load more is bounded, deduplicates identities and refreshes a changed snapshot with the same filters', async () => {
  const urls = []; let call = 0;
  const list = createPagedList({path: '/notices/page', owner: () => 'alice', api: async url => {
    urls.push(url); call++;
    if (call === 1) return response(['one', 'two'], {total: 80, has_more: true, next_cursor: 'cursor-a'});
    if (call === 2) return response(['two', 'three'], {total: 80, has_more: true, next_cursor: 'cursor-b'});
    if (call === 3) throw Object.assign(Error('changed'), {status: 409, detail: {code: 'list_changed'}});
    return response(['fresh'], {total: 1, has_more: false, next_cursor: null});
  }});
  await list.load({source: '学院官网', intent: 'current'}); await list.more();
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['one', 'two', 'three']);
  assert.equal(new URL(urls[1], 'https://local').searchParams.get('cursor'), 'cursor-a');
  await list.more();
  const refresh = new URL(urls[3], 'https://local');
  assert.equal(refresh.searchParams.has('cursor'), false);
  assert.equal(refresh.searchParams.get('source'), '学院官网');
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['fresh']);
  assert.match(list.snapshot().notice, /已保留筛选/);
});

test('owner and route transitions discard delayed records without exposing another account', async () => {
  let owner = 'alice', route = 1;
  const requests = [];
  const list = createPagedList({path: '/tasks/page', owner: () => owner, context: () => route, api: () => { const request = deferred(); requests.push(request); return request.promise; }});
  const old = list.load({status: 'all'}); owner = 'bob'; route++;
  const current = list.load({status: 'all'});
  requests[0].resolve(response(['alice-secret'])); await old;
  requests[1].resolve(response(['bob-record'])); await current;
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['bob-record']);
  const after = list.reload(); route++;
  requests[2].resolve(response(['stale-route'])); await after;
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['bob-record']);
  list.clear(); assert.deepEqual(list.snapshot().items, []);
});

test('a failed page retains the loaded range and can be retried without claiming emptiness', async () => {
  let failed = true, call = 0;
  const list = createPagedList({path: '/tasks/page', owner: () => 'alice', api: async () => {
    if (++call === 1) return response(['one'], {total: 60, next_cursor: 'next', has_more: true});
    if (failed) throw Error('网络暂时中断');
    return response(['two'], {total: 60, next_cursor: 'last', has_more: true});
  }});
  await list.load(); await list.more();
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['one']);
  assert.match(list.snapshot().error, /网络/); assert.equal(list.snapshot().total, 60);
  failed = false; await list.more();
  assert.deepEqual(list.snapshot().items.map(item => item.id), ['one', 'two']);
  assert.equal(list.snapshot().error, '');
});

test('reentering a route while its previous page is pending starts an owner-valid replacement request',async()=>{
  let route=1;const calls=[];
  const list=createPagedList({api:()=>new Promise(resolve=>calls.push(resolve)),path:'/tasks/page',owner:()=> 'same-owner',context:()=>route});
  const first=list.load({q:'same'});route=2;const second=list.load({q:'same'});assert.equal(calls.length,2);
  calls[0]({items:[{id:'obsolete'}],total:1,has_more:false});assert.equal(await first,null);
  calls[1]({items:[{id:'current'}],total:1,has_more:false});await second;assert.equal(list.snapshot().loading,false);assert.deepEqual(list.snapshot().items.map(item=>item.id),['current']);
});

test('clock refresh preserves every loaded page and only exposes the complete refreshed range',async()=>{
  const calls=[],painted=[];let minute=0;
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',onChange:value=>painted.push(value.items.map(item=>item.id)),api:async url=>{
    const params=new URL(url,'https://local').searchParams;calls.push(params);
    const offset=params.has('cursor')?50:0,ids=Array.from({length:offset?10:50},(_,i)=>String(offset+i));
    return {...response(ids,{total:60,has_more:!offset,next_cursor:offset?null:'cursor-'+minute}),items:ids.map(id=>({id,overdue:!!minute}))};
  }});
  await list.load({q:'本人记录',status:'all',sort:'board'});await list.more();assert.equal(list.snapshot().items.length,60);
  const before=painted.length;minute++;
  await list.reload({preserveRange:true});
  assert.equal(list.snapshot().items.length,60,'A minute boundary must not collapse an accumulated list to page one');
  assert.equal(list.snapshot().items.every(item=>item.overdue),true);
  assert.ok(painted.slice(before).every(ids=>ids.length===60),'No intermediate first page may replace the visible range');
  assert.equal(calls.at(-1).get('cursor'),'cursor-1');assert.equal(calls.at(-1).get('sort'),'board');
});

test('range refresh re-evaluates time filters and retains the previous range if a later page fails',async()=>{
  let phase='initial';const painted=[];
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',limit:2,onChange:value=>painted.push(value.items.map(item=>item.id)),api:async url=>{
    const p=new URL(url,'https://local').searchParams;assert.equal(p.get('status'),'soon');
    if(phase==='fail'&&p.has('cursor'))throw Error('second page unavailable');
    if(p.has('cursor'))return response(['three','four'],{total:4});
    return response(phase==='initial'?['one','two']:['newly-due','two'],{total:4,has_more:true,next_cursor:phase+'-next'});
  }});
  await list.load({status:'soon'});await list.more();phase='fail';await list.reload({preserveRange:true});
  assert.deepEqual(list.snapshot().items.map(item=>item.id),['one','two','three','four']);assert.match(list.snapshot().error,/second page/);
  phase='updated';await list.reload({preserveRange:true});
  assert.deepEqual(list.snapshot().items.map(item=>item.id),['newly-due','two','three','four']);
  assert.equal(list.snapshot().error,'');
});

test('a search or owner change cancels an in-flight multi-page clock refresh',async()=>{
  let owner='alice',hold=false;const second=deferred(),started=deferred();
  const list=createPagedList({path:'/notices/page',owner:()=>owner,limit:2,api:async url=>{
    const p=new URL(url,'https://local').searchParams;
    if(p.get('q')==='new')return response(['latest-filter']);
    if(p.has('cursor')){if(hold){started.resolve();return second.promise;}return response(['three','four'],{total:4});}
    return response(['one','two'],{total:4,has_more:true,next_cursor:'next'});
  }});
  await list.load({q:'old'});await list.more();hold=true;
  const refresh=list.reload({preserveRange:true});await started.promise;
  owner='bob';await list.load({q:'new'});second.resolve(response(['alice-private']));
  assert.equal(await refresh,null);assert.deepEqual(list.snapshot().items.map(item=>item.id),['latest-filter']);
});

test('clock refresh restarts an expired snapshot once without publishing a partial page',async()=>{
  let phase=0;const calls=[],painted=[];
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',limit:2,onChange:value=>painted.push(value.items.length),api:async url=>{
    const p=new URL(url,'https://local').searchParams;calls.push(p);
    if(phase===1&&p.has('cursor')){phase=2;throw Object.assign(Error('changed'),{status:409,detail:{code:'list_changed'}});}
    return p.has('cursor')?response(['three','four'],{total:4}):response(['one','two'],{total:4,has_more:true,next_cursor:'phase-'+phase});
  }});
  await list.load();await list.more();const count=painted.length;phase=1;await list.reload({preserveRange:true});
  assert.deepEqual(painted.slice(count),[],'An identical successful refresh updates its cursor without repainting');assert.equal(calls.at(-1).get('cursor'),'phase-2');
});

test('a clock response arriving during a new user interaction remains pending instead of replacing the list',async()=>{
  let allow=true,hold=false;const delayed=deferred();
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',api:async()=>hold?delayed.promise:response(['before'])});
  await list.load();hold=true;const refreshing=list.reload({preserveRange:true,canApply:()=>allow});allow=false;delayed.resolve(response(['during-edit']));
  assert.equal(await refreshing,null);assert.deepEqual(list.snapshot().items.map(item=>item.id),['before']);assert.equal(list.snapshot().loading,false);
});

test('returning to a cached route binds subsequent light clock patches to the new visible route',async()=>{
  let route=1,reads=0;const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',context:()=>route,api:async()=>{reads++;return response(['cached']);}});
  await list.load({status:'all'});route=3;await list.load({status:'all'});
  const patched=list.patch(item=>({...item,overdue:true}));assert.ok(patched);assert.equal(patched.items[0].overdue,true);assert.equal(reads,1);
});

test('load more after a time-sensitive cursor expires keeps the complete loaded range and adds the next page',async()=>{
  let expired=false,firstExpired=true;const painted=[];
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',limit:2,onChange:value=>painted.push(value.items.length),api:async url=>{
    const p=new URL(url,'https://local').searchParams,cursor=p.get('cursor');
    if(expired&&firstExpired&&cursor==='old-4'){firstExpired=false;throw Object.assign(Error('clock moved'),{status:409,detail:{code:'list_changed'}});}
    const offset=cursor?Number(cursor.split('-')[1]):0;
    return response(Array.from({length:2},(_,i)=>String(offset+i)),{total:6,has_more:offset<4,next_cursor:offset<4?(expired?'new-':'old-')+(offset+2):null});
  }});
  await list.load({status:'soon'});await list.more();assert.equal(list.snapshot().items.length,4);const before=painted.length;expired=true;
  await list.more();assert.deepEqual(list.snapshot().items.map(item=>item.id),['0','1','2','3','4','5']);
  assert.ok(painted.slice(before).every(count=>count>=4),'An expired cursor never exposes just the first page again');
});
