import test from 'node:test';
import assert from 'node:assert/strict';
import {createDraftStore} from '../static/continuity.js';

function server() {
  let stored={revision:0,payload:null};
  const writes=[];
  const api=async (path,opts)=>{
    if(!opts)return structuredClone(stored);
    if(opts.json.revision!==stored.revision){const e=new Error('conflict');e.status=409;throw e;}
    stored={revision:stored.revision+1,payload:structuredClone(opts.json.payload)};
    writes.push(structuredClone(stored));
    return structuredClone(stored);
  };
  return {api,writes,read:()=>stored};
}

test('serialized delayed writes preserve latest input',async()=>{
  const backend=server();let release;
  const gate=new Promise(resolve=>release=resolve);
  let first=true;
  const store=createDraftStore(async(p,o)=>{if(o&&first){first=false;await gate;}return backend.api(p,o);});
  await store.load('new-notice');
  store.stage('new-notice',{title:'第一版'});const one=store.flush('new-notice');
  store.stage('new-notice',{title:'最后一版'});const two=store.flush('new-notice');
  release();await Promise.all([one,two]);
  assert.equal(backend.read().payload.title,'最后一版');
  assert.deepEqual(backend.writes.map(x=>x.revision),[1,2]);
  assert.equal(store.pending(),false);store.clear();
});

test('late input cannot resurrect a retired draft',async()=>{
  const backend=server(),store=createDraftStore(backend.api);
  await store.load('new-notice');store.stage('new-notice',{title:'已提交'});
  const retire=store.retire('new-notice');
  store.stage('new-notice',{title:'旧回调'});await retire;
  store.stage('new-notice',{title:'更迟的旧回调'});await store.flush('new-notice');
  assert.equal(backend.read().payload,null);assert.equal(store.pending(),false);store.clear();
});

test('a second tab cannot silently overwrite a different draft',async()=>{
  const backend=server(),a=createDraftStore(backend.api),b=createDraftStore(backend.api);
  await Promise.all([a.load('new-notice'),b.load('new-notice')]);
  a.stage('new-notice',{title:'窗口一'});await a.flush('new-notice');
  b.stage('new-notice',{title:'窗口二'});
  await assert.rejects(b.flush('new-notice'),/conflict/);
  await assert.rejects(b.flush('new-notice'),/另一页面/);
  assert.equal(b.peek('new-notice').payload.title,'窗口二');
  assert.equal(backend.read().payload.title,'窗口一');a.clear();b.clear();
});

test('network failure can retry without losing latest local text',async()=>{
  const backend=server();let fail=true;
  const store=createDraftStore(async(p,o)=>{if(o&&fail){fail=false;throw new Error('network down');}return backend.api(p,o);});
  await store.load('new-notice');store.stage('new-notice',{title:'保留内容'});
  await assert.rejects(store.flush('new-notice'),/network down/);
  assert.equal(store.pending(),true);await store.flush('new-notice');
  assert.equal(backend.read().payload.title,'保留内容');assert.equal(store.pending(),false);store.clear();
});

test('lost success response is reconciled before retry',async()=>{
  const backend=server();let fail=true;
  const store=createDraftStore(async(p,o)=>{const r=await backend.api(p,o);if(o&&fail){fail=false;throw new Error('lost response');}return r;});
  await store.load('new-notice');store.stage('new-notice',{title:'第一版'});
  await assert.rejects(store.flush('new-notice'));
  store.stage('new-notice',{title:'新编辑'});await store.flush('new-notice');
  assert.equal(backend.read().payload.title,'新编辑');store.clear();
});

test('an old load does not erase input typed while loading',async()=>{
  const backend=server();let release;
  const gate=new Promise(resolve=>release=resolve);
  const store=createDraftStore(async(p,o)=>{if(!o)await gate;return backend.api(p,o);});
  const loading=store.load('new-notice');store.stage('new-notice',{title:'本页新输入'});
  release();await loading;await store.flush('new-notice');
  assert.equal(backend.read().payload.title,'本页新输入');store.clear();
});

test('read failure remains retryable and does not replace user text',async()=>{
  const backend=server();let fail=true;
  const store=createDraftStore(async(p,o)=>{if(!o&&fail){fail=false;throw new Error('read failed');}return backend.api(p,o);});
  await assert.rejects(store.load('new-notice'));
  store.stage('new-notice',{title:'继续编辑'});await store.flush('new-notice');
  assert.equal(backend.read().payload.title,'继续编辑');store.clear();
});
