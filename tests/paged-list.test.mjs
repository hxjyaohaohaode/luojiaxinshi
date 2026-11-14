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
    return response(['fresh'], {total: 81, has_more: true, next_cursor: 'cursor-c'});
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
