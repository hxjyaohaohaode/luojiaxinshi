import test from 'node:test';
import assert from 'node:assert/strict';
import {createCampusPublicationSubmission} from '../static/campus-publication-submission.js';

const payload={request_id:'confirmed-request',audience:'college',grade:'',class_name:'',title:'正式原文',body:'精确原文\n第二行',audience_review:'original-review',draft_id:'saved-draft',draft_version:3,valid_until:null,reference_only:false};
const draft={id:'saved-draft',version:3,title:payload.title,body:payload.body,requestId:payload.request_id,attachments:[{name:'原件.txt',sha256:'original-file'}]};
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
function backend(){
  let owner='alice';const caches=new Map(),publications=new Map(),attempts=[],cancelled=new Set();let lose=true,reviewExpired=false,hold=null,loseCancel=false,denyDetails=false;
  const current=()=>{if(!caches.has(owner))caches.set(owner,{revision:0,payload:null});return caches.get(owner);};
  const api=async(path,options={})=>{
    const uid=owner;
    if(path==='/edit-cache/campus-publication'){
      const prior=current();
      if(options.method==='PUT'){
        if(prior.revision!==options.json.revision)throw Object.assign(Error('different tab'),{status:409});
        caches.set(uid,{revision:prior.revision+1,payload:structuredClone(options.json.payload)});
      }
      return structuredClone(caches.get(uid));
    }
    if(path.startsWith('/campus/submissions/')){
      const key=uid+':'+path.split('/')[3],existing=publications.get(key);if(existing)return {state:'published',publication_id:existing.id};
      cancelled.add(key);if(loseCancel){loseCancel=false;throw Error('cancel response lost');}return {state:'cancelled'};
    }
    if(path.startsWith('/campus/publications/')){if(denyDetails)throw Object.assign(Error('old scope denied'),{status:403});return [...publications.values()].find(item=>item.id===path.split('/').at(-1));}
    assert.equal(path,'/campus/publications');const value=JSON.parse(options.body.get('data'));attempts.push({uid,value});
    const key=uid+':'+value.request_id;
    if(cancelled.has(key))throw Object.assign(Error('publication_cancelled'),{status:409});
    if(!publications.has(key)){
      if(reviewExpired&&value.audience_review==='original-review')throw Object.assign(Error('核对已过期'),{status:409});
      publications.set(key,{id:'publication-'+uid,delivery:{total:1,delivered:1}});
    }
    if(hold)await hold.promise;
    if(lose){lose=false;throw Object.assign(Error('response lost'),{status:0});}
    return structuredClone(publications.get(key));
  };
  return {api,attempts,caches,publications,owner:()=>owner,switch(value){owner=value;},lose(value){lose=value;},expire(){reviewExpired=true;},hold(value){hold=value;},loseCancel(){loseCancel=true;},denyDetails(){denyDetails=true;}};
}

test('a durable confirmed publication can be recovered after closing and reopening the editor',async()=>{
  const server=backend();let submission=createCampusPublicationSubmission(server);
  try{
    await submission.prepare(payload,draft);await assert.rejects(submission.replay(),/response lost/);submission.clear();
    submission=createCampusPublicationSubmission(server);
    assert.deepEqual((await submission.load()).payload,payload);
    const recovered=await submission.replay();assert.equal(recovered.result.id,'publication-alice');
    assert.deepEqual(server.attempts.map(attempt=>attempt.value),[payload,payload]);assert.equal(server.publications.size,1);
    assert.equal(server.caches.get('alice').payload,null);
  }finally{submission.clear();}
});

test('unresolved publication refuses a new request ID instead of hiding the uncertain original',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server);
  try{await submission.prepare(payload,draft);await assert.rejects(submission.prepare({...payload,request_id:'new-request',body:'new input'},draft),/上一次发布结果/);assert.deepEqual(submission.pending().payload,payload);assert.equal(server.attempts.length,0);}
  finally{submission.clear();}
});

test('preparing the same request ID cannot replace its confirmed content or draft snapshot',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server);
  try{
    await submission.prepare(payload,draft);
    await assert.rejects(submission.prepare({...payload,body:'changed content'},draft),/不能替换原发布/);
    await assert.rejects(submission.prepare({...payload,audience_review:'unreviewed substitution'},draft),/不能替换原发布/);
    await submission.prepare({...payload},{...draft,body:'later editor text',attachments:[]});
    assert.deepEqual(submission.pending().payload,payload);assert.deepEqual(submission.pending().draft,draft);
    assert.equal(server.attempts.length,0);
  }finally{submission.clear();}
});

test('expired audience review can renew only its token while retaining the original request and attachment draft version',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server);server.expire();server.lose(false);
  try{
    await submission.prepare(payload,draft);await assert.rejects(submission.replay(),/核对已过期/);
    assert.equal(server.publications.size,0);assert.deepEqual(submission.pending().payload,payload);
    const recovered=await submission.replay({audienceReview:'fresh-reviewed-token'});
    assert.equal(recovered.result.id,'publication-alice');assert.deepEqual(server.attempts.at(-1).value,{...payload,audience_review:'fresh-reviewed-token'});
    assert.equal(server.publications.size,1);
  }finally{submission.clear();}
});

test('account switches and late publication responses never load or retire another account intent',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server),gate=deferred();server.lose(false);
  try{
    await submission.prepare(payload,draft);server.hold(gate);const sending=submission.replay();
    while(!server.attempts.length)await new Promise(resolve=>setImmediate(resolve));
    server.switch('bob');assert.equal(await submission.load(),null);
    await submission.prepare({...payload,request_id:'bob-confirmed'},draft);
    gate.resolve();const late=await sending;assert.equal(late.current,false);
    assert.equal(server.caches.get('bob').payload.payload.request_id,'bob-confirmed');
    assert.equal(server.caches.get('alice').payload.payload.request_id,payload.request_id);
    assert.equal(server.attempts.length,1);assert.equal(server.attempts[0].uid,'alice');
  }finally{gate.resolve();submission.clear();}
});

test('another tab cannot replace or clear a different confirmed submission by stale cache revision',async()=>{
  const server=backend(),first=createCampusPublicationSubmission(server),second=createCampusPublicationSubmission(server);
  try{
    await Promise.all([first.load(),second.load()]);await first.prepare(payload,draft);
    await assert.rejects(second.prepare({...payload,request_id:'second-tab'},draft),/different tab/);
    await assert.rejects(second.replay(),/另一页面/);
    assert.equal(server.caches.get('alice').payload.payload.request_id,payload.request_id);assert.equal(server.attempts.length,0);
  }finally{first.clear();second.clear();}
});

test('leaving the original route during a renewed review cache write does not start a late publication',async()=>{
  const server=backend(),gate=deferred(),began=deferred();let visible=true,hold=false;
  const submission=createCampusPublicationSubmission({...server,api:async(path,options)=>{
    if(hold&&options?.method==='PUT'){began.resolve();await gate.promise;}return server.api(path,options);
  }});
  try{
    await submission.prepare(payload,draft);hold=true;
    const retry=submission.replay({audienceReview:'renewed',canSend:()=>visible});await began.promise;visible=false;gate.resolve();
    assert.equal(await retry,null);assert.equal(server.attempts.length,0);assert.equal(server.caches.get('alice').payload.payload.audience_review,'renewed');
  }finally{gate.resolve();submission.clear();}
});

test('concurrent recovery controls share one publication request',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server),gate=deferred();server.lose(false);server.hold(gate);
  try{await submission.prepare(payload,draft);const first=submission.replay(),second=submission.replay();assert.equal(first,second);gate.resolve();await Promise.all([first,second]);assert.equal(server.attempts.length,1);assert.equal(server.publications.size,1);}
  finally{gate.resolve();submission.clear();}
});

test('a lost cancellation response remains retryable and never permits the stopped request to publish later',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server);server.loseCancel();
  try{
    await submission.prepare(payload,draft);await assert.rejects(submission.cancel(),/cancel response lost/);assert.deepEqual(submission.pending().payload,payload);
    const result=await submission.cancel();assert.equal(result.state,'cancelled');assert.equal(server.caches.get('alice').payload,null);
    const body=new FormData();body.append('data',JSON.stringify(payload));await assert.rejects(server.api('/campus/publications',{method:'POST',body}),/publication_cancelled/);assert.equal(server.publications.size,0);
    await submission.prepare({...payload,request_id:'explicit-new-confirmation'},draft);assert.equal(submission.pending().payload.request_id,'explicit-new-confirmation');
  }finally{submission.clear();}
});

test('an authoritative already-published cancellation receipt retires the old intent even when its details are no longer authorized',async()=>{
  const server=backend(),submission=createCampusPublicationSubmission(server);
  try{
    await submission.prepare(payload,draft);await assert.rejects(submission.replay(),/response lost/);server.denyDetails();
    const receipt=await submission.cancel();assert.equal(receipt.state,'published');assert.equal(receipt.publication_id,'publication-alice');assert.equal(receipt.result,null);assert.equal(receipt.detailError.status,403);
    assert.equal(submission.pending(),null);assert.equal(server.caches.get('alice').payload,null);assert.equal(server.publications.size,1);
  }finally{submission.clear();}
});
