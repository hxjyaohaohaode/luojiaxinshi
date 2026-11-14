import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkspaceProjection} from '../static/workspace-projection.js';
const full=(revision,ids)=>({projection:'light',revision,clock:'now',clock_only:false,counts:{tasks:ids.length},tasks:ids.map(id=>({id,projection:'light',data:{title:id,materials:[]},overdue:false}))});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {resolve,promise};};

test('minute refresh merges derived flags into the complete collection without losing stable task data',async()=>{
  const calls=[];let index=0;const projection=createWorkspaceProjection({owner:()=> 'alice',api:async url=>{calls.push(url);return ++index===1?full('r1',Array.from({length:84},(_,i)=>'task-'+i)):{projection:'light',revision:'r1',clock_only:true,clock:'later',tasks:[{id:'task-83',overdue:true}]};}});
  const first=await projection.load(['tasks']);assert.equal(first.tasks.length,84);
  const second=await projection.load(['tasks'],{clockOnly:true});assert.equal(second.tasks.length,84);assert.equal(second.tasks[83].data.title,'task-83');assert.equal(second.tasks[83].overdue,true);
  assert.equal(new URL(calls[1],'https://fixture').searchParams.get('clock_only'),'1');assert.equal(new URL(calls[1],'https://fixture').searchParams.get('revision'),'r1');
});

test('a changed revision replaces the complete range, and a foreign sparse identity forces a full reload',async()=>{
  let index=0;const responses=[full('r1',['old']),full('r2',['new','second']),{revision:'r2',clock_only:true,tasks:[{id:'foreign',overdue:true}]},full('r3',['current'])],urls=[];
  const projection=createWorkspaceProjection({owner:()=> 'alice',api:async url=>{urls.push(url);return responses[index++];}});
  await projection.load(['tasks']);assert.deepEqual((await projection.load(['tasks'],{clockOnly:true})).tasks.map(item=>item.id),['new','second']);
  assert.deepEqual((await projection.load(['tasks'],{clockOnly:true})).tasks.map(item=>item.id),['current']);assert.equal(new URL(urls[3],'https://fixture').searchParams.has('clock_only'),false);
});

test('late route and account responses cannot repopulate another visible workspace',async()=>{
  let account='alice',route=1;const calls=[];const projection=createWorkspaceProjection({owner:()=>account,context:()=>route,api:()=>{const call=deferred();calls.push(call);return call.promise;}});
  const previous=projection.load(['tasks']);route++;calls[0].resolve(full('r1',['old-route']));assert.equal(await previous,null);
  const alice=projection.load(['tasks']);account='bob';route++;const bob=projection.load(['tasks']);calls[1].resolve(full('alice',['private']));assert.equal(await alice,null);calls[2].resolve(full('bob',['owned']));assert.deepEqual((await bob).tasks.map(item=>item.id),['owned']);
});
