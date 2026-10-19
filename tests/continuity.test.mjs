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

test('a new editor opened before the old save finishes keeps its draft',async()=>{
  const backend=server(),store=createDraftStore(backend.api);
  try{
    await store.load('new-notice');store.activate('new-notice');store.stage('new-notice',{title:'已提交的第一份'});await store.flush('new-notice');
    const submitted=store.checkpoint?.('new-notice');
    store.activate('new-notice');store.stage('new-notice',{title:'后来编辑的第二份'});
    await store.retire('new-notice',submitted);await store.flush('new-notice');
    assert.equal(backend.read().payload?.title,'后来编辑的第二份');
    assert.equal(store.peek('new-notice').retired,false);
  }finally{store.clear();}
});

test('a reopened editor survives an old cache deletion already in flight',async()=>{
  const backend=server();let release,observe;
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>observe=resolve);
  const store=createDraftStore(async(p,o)=>{if(o?.json.payload===null){observe();await gate;}return backend.api(p,o);});
  try{
    await store.load('new-notice');store.activate('new-notice');store.stage('new-notice',{title:'原提交'});await store.flush('new-notice');
    const submitted=store.checkpoint?.('new-notice'),clearing=store.retire('new-notice',submitted);await started;
    store.activate('new-notice');store.stage('new-notice',{title:'删除请求期间的新输入'});
    const saving=store.flush('new-notice');release();await Promise.all([clearing,saving]);
    assert.equal(backend.read().payload?.title,'删除请求期间的新输入');
    assert.equal(store.pending(),false);
    const reloaded=createDraftStore(backend.api);assert.equal((await reloaded.load('new-notice')).payload?.title,'删除请求期间的新输入');reloaded.clear();
  }finally{release();store.clear();}
});

test('a lost deletion response reconciles before saving a new editor',async()=>{
  const backend=server();let release,observe;
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>observe=resolve);
  const store=createDraftStore(async(p,o)=>{if(o?.json.payload===null){observe();await gate;await backend.api(p,o);throw new Error('lost deletion response');}return backend.api(p,o);});
  try{
    await store.load('new-notice');store.activate('new-notice');store.stage('new-notice',{title:'已提交'});await store.flush('new-notice');
    const clearing=store.retire('new-notice',store.checkpoint('new-notice'));await started;
    store.activate('new-notice');store.stage('new-notice',{title:'新内容'});const saving=store.flush('new-notice');
    release();const [oldResult,newResult]=await Promise.allSettled([clearing,saving]);
    assert.equal(oldResult.status,'rejected');assert.equal(newResult.status,'fulfilled');
    assert.equal(backend.read().payload.title,'新内容');assert.equal(store.peek('new-notice').retired,false);assert.equal(store.pending(),false);
  }finally{release();store.clear();}
});

test('a failed deletion cannot retire or overwrite a newer editor',async()=>{
  const backend=server();let release,observe;
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>observe=resolve);
  const store=createDraftStore(async(p,o)=>{if(o?.json.payload===null){observe();await gate;throw new Error('offline');}return backend.api(p,o);});
  try{
    await store.load('new-notice');store.activate('new-notice');store.stage('new-notice',{title:'原提交'});await store.flush('new-notice');
    const clearing=store.retire('new-notice');await started;store.activate('new-notice');store.stage('new-notice',{title:'离线期间的新输入'});
    const saving=store.flush('new-notice');release();const results=await Promise.allSettled([clearing,saving]);
    assert.equal(results[0].status,'rejected');assert.equal(results[1].status,'fulfilled');
    assert.equal(backend.read().payload.title,'离线期间的新输入');assert.equal(store.peek('new-notice').retired,false);
  }finally{release();store.clear();}
});

test('a deletion conflict leaves another tab intact and keeps this tab recoverable',async()=>{
  const backend=server(),a=createDraftStore(backend.api),b=createDraftStore(backend.api);
  try{
    await a.load('new-notice');a.activate('new-notice');a.stage('new-notice',{title:'原提交'});await a.flush('new-notice');
    const submitted=a.checkpoint('new-notice');await b.load('new-notice');b.stage('new-notice',{title:'另一窗口的新内容'});await b.flush('new-notice');
    await assert.rejects(a.retire('new-notice',submitted),/conflict/);
    a.activate('new-notice');a.stage('new-notice',{title:'本窗口新内容'});await assert.rejects(a.flush('new-notice'),/另一页面/);
    assert.equal(backend.read().payload.title,'另一窗口的新内容');assert.equal(a.peek('new-notice').payload.title,'本窗口新内容');assert.equal(a.pending(),true);
  }finally{a.clear();b.clear();}
});

test('a stale checkpoint from a cleared store cannot delete a new session draft',async()=>{
  const backend=server(),store=createDraftStore(backend.api);
  try{
    await store.load('new-notice');store.stage('new-notice',{title:'第一会话'});await store.flush('new-notice');const ticket=store.checkpoint('new-notice');
    store.clear();await store.load('new-notice');store.activate('new-notice');store.stage('new-notice',{title:'新会话'});await store.flush('new-notice');
    assert.equal(await store.retire('new-notice',ticket),false);assert.equal(backend.read().payload.title,'新会话');
  }finally{store.clear();}
});

test('navigation flush does not wait for cleanup of already saved content',async()=>{
  const backend=server();let release,observe;
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>observe=resolve);
  const store=createDraftStore(async(p,o)=>{if(o?.json.payload===null){observe();await gate;}return backend.api(p,o);});
  try{
    await store.load('new-notice');store.stage('new-notice',{title:'已正式保存'});await store.flush('new-notice');
    const clearing=store.retire('new-notice');await started;
    let flushed=false;const navigation=store.flushAll().then(()=>flushed=true);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(flushed,true);release();await Promise.all([clearing,navigation]);
  }finally{release();store.clear();}
});
