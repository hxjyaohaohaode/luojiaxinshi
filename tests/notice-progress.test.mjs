import test from 'node:test';
import assert from 'node:assert/strict';
import {createNoticeProgress,metricLines} from '../static/notice-progress.js';

function harness(api){
  const state={renderId:1,session:{user:{id:'one'}}},fields={},queue=[];
  const field=name=>fields[name]??={textContent:''};
  const root={querySelector:name=>name==='[data-notice-progress]'?{querySelector:field}:field(name)};
  let refreshed=0;
  const controller=createNoticeProgress({state,api,root,refresh:async()=>{refreshed++;},schedule:fn=>{queue.push(fn);return queue.length;},unschedule:()=>{}});
  return{state,fields,queue,controller,refreshed:()=>refreshed};
}

test('a result arriving after navigation or logout does not update the new screen',async()=>{
  for(const change of [h=>h.state.renderId++,h=>h.state.session=null]){
    let resolve;const h=harness(()=>new Promise(r=>resolve=r));h.controller.watch({id:'n',status:'processing'});
    const poll=h.queue.shift()();change(h);resolve({status:'draft'});await poll;
    assert.equal(h.refreshed(),0);assert.deepEqual(h.fields,{});assert.equal(h.queue.length,0);
  }
});
test('read-only polling waits for acceptance and refreshes once on completion',async()=>{
  const results=[{status:'received'},{status:'processing',execution:{stage:'receiving'},elapsed_seconds:220},{status:'draft'}];
  const paths=[];const h=harness(async path=>{paths.push(path);return results.shift();});
  h.controller.watch({id:'n',status:'received'},{pending:true});
  await h.queue.shift()();assert.equal(h.refreshed(),0);
  await h.queue.shift()();assert.match(h.fields['[data-notice-phase]'].textContent,/接收/);assert.match(h.fields['[data-notice-elapsed]'].textContent,/220/);
  await h.queue.shift()();assert.equal(h.refreshed(),1);assert.equal(h.queue.length,0);
  assert.ok(paths.every(p=>p==='/notices/n/processing'));
});
test('status errors never trigger regeneration; unknown timings are not displayed as zero',async()=>{
  const h=harness(async()=>{throw new Error('offline');});h.controller.watch({id:'n',status:'processing'});
  await h.queue.shift()();assert.match(h.fields['[data-notice-elapsed]'].textContent,/不会自动重新调用/);
  assert.equal(h.refreshed(),0);assert.equal(h.queue.length,1);
  assert.deepEqual(metricLines({}),[]);
  assert.ok(metricLines({first_answer_seconds:0,validation_seconds:.015,input_tokens:0,output_tokens:100}).length===3);
});
