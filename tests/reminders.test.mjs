import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as nextTurn} from 'node:timers/promises';
import {createReminders} from '../static/reminders.js';

const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const snapshot=(...items)=>({items,upcoming:[]});
const item=(id,is_read=false)=>({id,title:id,kind:'due',level:'urgent',is_read,is_archived:false,task_id:id});
function harness(t,api){
  const saved={document:globalThis.document,location:globalThis.location};
  const doc=new EventTarget();doc.querySelector=()=>null;doc.hidden=false;
  globalThis.document=doc;globalThis.location={hash:'#settings'};
  const state={session:{user:{id:'alice'}},renderId:1,dialogRequest:0},toasts=[],dialogs=[];
  const reminders=createReminders({state,api,esc:String,icon:()=>'',toast:(...args)=>toasts.push(args),showDialog:(...args)=>dialogs.push(args)});
  t.after(()=>{reminders.stop();for(const [key,value] of Object.entries(saved)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  function readAll(){
    const control={disabled:false,matches:selector=>selector==='[data-reminder-all]'};
    const event=new Event('click');Object.defineProperty(event,'target',{value:{closest:()=>control}});doc.dispatchEvent(event);
  }
  return {reminders,state,toasts,dialogs,readAll};
}

test('a late refresh from the previous account cannot publish into the next account',async t=>{
  const alice=deferred(),bob=deferred();let count=0;
  const {reminders,state}=harness(t,()=>++count===1?alice.promise:bob.promise);
  reminders.start();const old=reminders.refresh();
  state.session={user:{id:'bob'}};reminders.start();const fresh=reminders.refresh();
  bob.resolve(snapshot(item('bob')));await fresh;
  alice.resolve(snapshot(item('alice')));await old;
  assert.deepEqual(reminders.latest().items.map(x=>x.id),['bob']);
});

test('all-read uses the displayed snapshot and an older GET cannot undo the saved state',async t=>{
  const stale=deferred(),mutation=deferred(),posts=[];let gets=0;
  const {reminders,readAll}=harness(t,(path,options)=>{
    if(options){posts.push(options.json);return mutation.promise;}
    return ++gets===1?Promise.resolve(snapshot(item('old'))):stale.promise;
  });
  reminders.start();await reminders.refresh();const oldRefresh=reminders.refresh();readAll();
  assert.deepEqual(posts,[{ids:['old'],state:'read'}]);
  mutation.resolve(snapshot(item('old',true),item('new')));await nextTurn();
  stale.resolve(snapshot(item('old')));await oldRefresh;
  assert.equal(reminders.latest().items[0].is_read,true);
  assert.equal(reminders.latest().items[1].is_read,false);
});

test('failed writes retain unread items and allow a successful retry',async t=>{
  let fail=true;
  const {reminders,toasts,readAll}=harness(t,async(path,options)=>{
    if(!options)return snapshot(item('a'));
    if(fail)throw new Error('合成网络失败');
    return snapshot(item('a',true));
  });
  reminders.start();await reminders.refresh();readAll();await nextTurn();
  assert.equal(reminders.latest().items[0].is_read,false);
  assert.deepEqual(toasts,[['合成网络失败',true]]);
  fail=false;readAll();await nextTurn();assert.equal(reminders.latest().items[0].is_read,true);
});

test('a delayed open cannot replace a dialog after the user leaves the route',async t=>{
  const loading=deferred();const {reminders,state,dialogs}=harness(t,()=>loading.promise);
  reminders.start();const opened=reminders.open();state.renderId++;globalThis.location.hash='#calendar';
  loading.resolve(snapshot(item('a')));await opened;assert.equal(dialogs.length,0);
});

test('switching accounts during a large bulk write stops the remaining batches',async t=>{
  const mutation=deferred(),posts=[];let gets=0;
  const {reminders,state,readAll}=harness(t,(path,options)=>{
    if(options){posts.push(options.json);return mutation.promise;}
    return Promise.resolve(++gets===1?snapshot(...Array.from({length:1001},(_,i)=>item(String(i)))):snapshot(item('bob')));
  });
  reminders.start();await reminders.refresh();readAll();assert.equal(posts[0].ids.length,1000);
  state.session={user:{id:'bob'}};reminders.start();await reminders.refresh();
  mutation.resolve(snapshot(item('alice',true)));await nextTurn();
  assert.equal(posts.length,1);assert.deepEqual(reminders.latest().items.map(x=>x.id),['bob']);
});
