import test from 'node:test';
import assert from 'node:assert/strict';
import {createPagedList} from '../static/paged-list.js';
import {clockSensitiveList,createListClock,mergeListClock,sameListDisplay} from '../static/list-clock.js';

const task=id=>({id,version:1,status:'pending',updated_at:1,workflow:{version:1,data:{stage:'preparing'}},data:{materials:['真实材料'],details:'完整办理说明'},overdue:false,due_soon:false,followup_due:false,handling_state:{kind:'start',label:'准备办理',detail:'原文细节'}});
const light=item=>({...structuredClone(item),data:{details:'',materials:[]}});

test('ordinary clock updates merge light fields into all loaded full records without refetching or repainting unchanged content',async()=>{
  const items=Array.from({length:54},(_,i)=>task(String(i)));let reads=0,paints=0;
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',onChange:()=>paints++,api:async url=>{
    reads++;const more=new URL(url,'https://local').searchParams.has('cursor');return {items:items.slice(more?50:0,more?54:50),total:54,has_more:!more,next_cursor:more?null:'next'};
  }});
  await list.load({status:'all',q:'原文'});await list.more();const before=paints,clock=createListClock('tasks');
  const projection={revision:'stable',baseline_known:true,stable_changed:false,tasks:items.map(light)};
  const value=await clock.refresh(list,projection,{owner:'alice',reload:()=>assert.fail('Ordinary filters must not reload full records')});
  assert.equal(value.items.length,54);assert.equal(reads,2);assert.equal(paints,before);
  projection.tasks.at(-1).overdue=true;
  await clock.refresh(list,projection,{owner:'alice',reload:()=>assert.fail('A time label change does not change all-filter membership')});
  assert.equal(paints,before+1);assert.equal(list.snapshot().items.at(-1).overdue,true);
  assert.deepEqual(list.snapshot().items.at(-1).data,items.at(-1).data);
  await clock.refresh(list,projection,{owner:'alice',reload:()=>assert.fail()});assert.equal(paints,before+1);
});

test('notice clock patches preserve full excerpts, evidence and focus summary; evaluation time alone does not repaint',()=>{
  const original={id:'n',source_excerpt:'完整原文',assessment:{focus:{summary:'原始摘要',key_time:null},tracking:{evaluated_at:1,state:'active'}},tracking:{evaluated_at:1,state:'active',open_actions:[{index:2,title:'报名',quote:'原始依据'}]}};
  const patch={id:'n',assessment:{focus:{summary:'',key_time:null},tracking:{evaluated_at:2,state:'active'}},tracking:{evaluated_at:2,state:'active',open_actions:[{index:2,title:'报名'}]}};
  const merged=mergeListClock('notices',original,patch);
  assert.equal(merged.assessment.focus.summary,'原始摘要');assert.equal(merged.source_excerpt,'完整原文');assert.equal(merged.tracking.open_actions[0].quote,'原始依据');
  assert.equal(merged.tracking.evaluated_at,2);assert.equal(sameListDisplay(original,merged),true);
});

test('time-sensitive membership refreshes the loaded range only when its actual clock signature changes',async()=>{
  const items=[task('one'),task('two')];let paints=0,reads=0;
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',onChange:()=>paints++,api:async()=>{reads++;return {items:structuredClone(items),total:2,has_more:false,next_cursor:null};}});
  await list.load({status:'soon'});const clock=createListClock('tasks'),projection={revision:'stable',baseline_known:true,stable_changed:false,tasks:items.map(light)},reload=options=>{assert.equal(options.preserveRange,true);return list.reload(options);};
  await clock.refresh(list,projection,{owner:'alice',reload});assert.equal(reads,2);const painted=paints;
  await clock.refresh(list,projection,{owner:'alice',reload});assert.equal(reads,2);assert.equal(paints,painted);
  items[0].due_soon=true;projection.tasks[0].due_soon=true;
  await clock.refresh(list,projection,{owner:'alice',reload});assert.equal(reads,3);assert.equal(list.snapshot().items[0].due_soon,true);assert.equal(paints,painted+1);
});

test('a stable mutation racing a clock read forces a real range refresh instead of overwriting full data with light entities',async()=>{
  let reads=0;const item=task('one'),list=createPagedList({path:'/tasks/page',owner:()=> 'alice',api:async()=>{reads++;return {items:[{...item,version:reads}],total:1,has_more:false,next_cursor:null};}});
  await list.load({status:'pending'});const clock=createListClock('tasks');
  await clock.refresh(list,{revision:'new',tasks:[{...light(item),version:2}]},{owner:'alice',reload:options=>list.reload(options)});
  assert.equal(reads,2);assert.equal(list.snapshot().items[0].version,2);assert.equal(list.snapshot().items[0].data.details,'完整办理说明');
});

test('clock-sensitive filters match the server membership and sorting contract',()=>{
  for(const status of ['all','pending','done','cancelled','changes','sync','blocked','unverified'])assert.equal(clockSensitiveList('tasks',{status}),false,status);
  for(const status of ['soon','followup'])assert.equal(clockSensitiveList('tasks',{status}),true,status);
  for(const sort of ['collected','newest','updated','published'])assert.equal(clockSensitiveList('notices',{intent:'all',sort}),false,sort);
  for(const filters of [{intent:'current',sort:'collected'},{intent:'closed',sort:'published'},{intent:'all',sort:'priority'},{intent:'all',sort:'deadline'}])assert.equal(clockSensitiveList('notices',filters),true);
});

test('an insertion or deletion outside the loaded range during a clock probe refreshes the real server total',async()=>{
  const item=task('visible');let total=3,reads=0;
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',api:async()=>{reads++;return {items:[item],total,has_more:true,next_cursor:'more'};}});
  await list.load({status:'all'});const clock=createListClock('tasks');
  total=4;
  await clock.refresh(list,{revision:'inserted',baseline_known:true,stable_changed:true,tasks:[light(item),light(task('outside-new'))]},{owner:'alice',reload:async options=>{assert.equal(options.preserveRange,true);return list.load({status:'all'},{force:true});}});
  assert.equal(list.snapshot().total,4);assert.equal(reads,2);
  total=2;
  await clock.refresh(list,{revision:'deleted',baseline_known:true,stable_changed:true,tasks:[light(item)]},{owner:'alice',reload:async options=>{assert.equal(options.preserveRange,true);return list.load({status:'all'},{force:true});}});
  assert.equal(list.snapshot().total,2);assert.equal(reads,3);
});

test('an unknown projection baseline refills once before ordinary warm clock updates can skip reads',async()=>{
  const item=task('one');let reads=0;
  const list=createPagedList({path:'/tasks/page',owner:()=> 'alice',api:async()=>{reads++;return {items:[item],total:1,has_more:false,next_cursor:null};}});
  await list.load({status:'all'});const clock=createListClock('tasks'),projection={revision:'r1',baseline_known:false,stable_changed:false,tasks:[light(item)]};
  await clock.refresh(list,projection,{owner:'alice',reload:options=>list.reload(options)});assert.equal(reads,2);
  projection.baseline_known=true;await clock.refresh(list,projection,{owner:'alice',reload:()=>assert.fail('Warm stable clock must not read pages')});assert.equal(reads,2);
});
