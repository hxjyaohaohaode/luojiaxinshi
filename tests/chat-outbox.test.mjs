import test from 'node:test';
import assert from 'node:assert/strict';
import {ChatOutbox} from '../static/chat-outbox.js';
const input=i=>({id:'synthetic-request-'+i,content:'消息'+i,created_at:i});
const memory=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};};

test('rapid submissions preserve each input while one acknowledgement is pending',async()=>{
  const calls=[];const box=new ChatOutbox({key:'one',onSend:async batch=>{calls.push(batch);},delay:100000});
  box.enqueue(input(1));await box.pump();box.enqueue(input(2));box.enqueue(input(3));await box.pump();
  assert.deepEqual(calls.map(batch=>batch.map(i=>i.id)),[['synthetic-request-1']]);
  box.acknowledge([input(1).id]);await box.pump();assert.deepEqual(calls[1].map(i=>i.content),['消息2','消息3']);
  box.acknowledge([input(2).id,input(3).id]);assert.equal(box.items.length,0);box.dispose();
});
test('a burst is grouped up to the server batch bound without dropping the rest',async()=>{
  const calls=[];const box=new ChatOutbox({key:'one',onSend:async b=>calls.push(b),delay:100000});
  for(let i=0;i<19;i++)box.enqueue(input(i));await box.pump();assert.equal(calls[0].length,16);
  box.acknowledge(calls[0].map(i=>i.id));await box.pump();assert.equal(calls[1].length,3);box.dispose();
});
test('refresh keeps unacknowledged inputs uncertain and never silently repeats paid work',async()=>{
  const storage=memory();const old=new ChatOutbox({key:'owner:chat',storage,onSend:async()=>{},delay:100000});old.enqueue(input(1));await old.pump();old.dispose();
  let requests=0;const box=new ChatOutbox({key:'owner:chat',storage,onSend:async()=>requests++,delay:100000});
  assert.equal(box.items[0].state,'uncertain');await box.pump();assert.equal(requests,0);
  box.reconcile([{role:'user',client_request_id:input(1).id}]);assert.equal(box.items.length,0);box.dispose();
});
test('transport failure pauses delivery; an explicit retry uses the identical message identity',async()=>{
  let called=0;const box=new ChatOutbox({key:'one',onSend:async()=>{called++;throw Error('synthetic network failure');},delay:100000});
  box.enqueue(input(1));await box.pump();assert.equal(box.items[0].id,input(1).id);assert.equal(box.items[0].state,'uncertain');
  box.enqueue(input(2));await box.pump();assert.equal(called,1);box.resume();await box.pump();assert.equal(called,2);assert.equal(box.items.length,2);box.dispose();
});
test('a late failure for an acknowledged stream does not pause a newer delivery',async()=>{
  const box=new ChatOutbox({key:'one',onSend:async()=>{},delay:100000});box.enqueue(input(1));await box.pump();
  const first=box.snapshot();box.acknowledge([input(1).id]);box.enqueue(input(2));await box.pump();box.fail(first,'late failure');
  assert.equal(box.paused,false);assert.equal(box.items[0].state,'sending');box.dispose();
});

test('stopping an acknowledged reply allows the next explicit message to send',async()=>{
  const sent=[];const box=new ChatOutbox({key:'one',onSend:async batch=>sent.push(batch.map(item=>item.id)),delay:100000});
  box.enqueue(input(1));await box.pump();box.acknowledge([input(1).id]);box.pause();
  assert.equal(box.continueAfterStop(),true);box.enqueue(input(2));await box.pump();
  assert.deepEqual(sent,[[input(1).id],[input(2).id]]);box.dispose();
});

test('a new message entered during cancellation waits for the stop acknowledgement',async()=>{
  let requests=0;const box=new ChatOutbox({key:'one',onSend:async()=>requests++,delay:100000});
  box.pause();box.enqueue(input(2));await box.pump();assert.equal(requests,0);
  box.continueAfterStop();await box.pump();assert.equal(requests,1);box.dispose();
});

test('stopping never repeats uncertain work and continues only after its real receipt',async()=>{
  const sent=[];const box=new ChatOutbox({key:'one',onSend:async batch=>sent.push(batch.map(item=>item.id)),delay:100000});
  box.enqueue(input(1));await box.pump();box.pause();box.enqueue(input(2));
  assert.equal(box.continueAfterStop(),false);await box.pump();assert.equal(sent.length,1);
  box.reconcile([{role:'user',client_request_id:input(1).id}]);box.continueAfterStop();await box.pump();
  assert.deepEqual(sent,[[input(1).id],[input(2).id]]);box.dispose();
});
