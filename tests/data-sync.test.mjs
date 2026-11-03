import test from 'node:test';
import assert from 'node:assert/strict';
import {installDataSync} from '../static/data-sync.js';

test('owner changes discard stale probes; deferred edits retry before advancing the cursor',async()=>{
  const old={document:globalThis.document,window:globalThis.window,setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
  globalThis.document=Object.assign(new EventTarget(),{hidden:false});globalThis.window=new EventTarget();
  globalThis.setInterval=()=>1;globalThis.clearInterval=()=>{};
  try{
    const state={session:{user:{id:'one'}}};let revision='a',changes=0,accept=true,resolve;
    let defer=false;
    const api=async()=>defer?await new Promise(r=>resolve=r):{revision};
    const sync=installDataSync({state,api,onChange:async()=>{changes++;return accept;}});
    await sync.probe();assert.equal(changes,1);revision='b';accept=false;await sync.probe();assert.equal(changes,2);
    accept=true;await sync.probe();assert.equal(changes,3);await sync.probe();assert.equal(changes,3);
    defer=true;const pending=sync.probe();state.session={user:{id:'two'}};resolve({revision:'other'});await pending;
    assert.equal(changes,3);
    defer=false;await sync.probe();assert.equal(changes,4);sync.stop();
  }finally{Object.assign(globalThis,old);}
});
