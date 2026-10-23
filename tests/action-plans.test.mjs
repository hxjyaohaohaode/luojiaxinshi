import test from 'node:test';
import assert from 'node:assert/strict';
import {initializeDraftPlans,prepareConfirmation} from '../static/action-plans.js';
import {taskMatchesFilter} from '../static/workflow.js';
import {calendarEntries} from '../static/calendar-model.js';

test('optional proposals require an explicit selection and do not decide participation',()=>{
  const d=initializeDraftPlans([{title:'提交',include:true},{title:'推荐咨询',include:true}],{1:{action_kind:'optional'}});
  assert.equal(d[1].include,false);d[1].include=true;
  const result=prepareConfirmation(d,{tasks:[]});
  assert.equal(result.plans[1].participation,'undecided');
  assert.deepEqual(Object.keys(result.tasks[1]),['title']);
});
test('reorder preserves original dependency identity and remaps selected indexes',()=>{
  const d=initializeDraftPlans([{title:'准备',include:true},{title:'提交',include:true},{title:'背景',include:false}],{1:{action_kind:'required',depends_on:[0]}});
  const reordered=[d[2],d[1],d[0]],saved=prepareConfirmation(reordered,{tasks:[]});
  assert.deepEqual(saved.plans[0].depends_on,[1]);assert.equal(saved.tasks[1].title,'准备');
  const restored=initializeDraftPlans(JSON.parse(JSON.stringify(reordered)));
  assert.deepEqual(prepareConfirmation(restored,{tasks:[]}),saved);
});
test('unselected, removed or malformed predecessors are never silently discarded',()=>{
  const d=initializeDraftPlans([{title:'准备',include:false},{title:'提交',include:true}],{1:{depends_on:[0]}});
  assert.throws(()=>prepareConfirmation(d,{tasks:[]}),/前置步骤/);
  assert.throws(()=>prepareConfirmation([d[1]],{tasks:[]}),/已移除步骤/);
  const bad=initializeDraftPlans([{title:'提交',include:true}],{0:{depends_on:[8]}});
  assert.throws(()=>prepareConfirmation(bad,{tasks:[]}),/还没选中/);
});
test('replacement preserves existing execution unless plan update is explicitly selected',()=>{
  const d=initializeDraftPlans([{title:'新要求',include:true,replacement:'existing'}],{0:{action_kind:'optional',conditions:['已获立项']}});
  d[0].include=true;
  const notice={tasks:[{id:'existing',version:6,workflow:{version:4}}]};
  assert.deepEqual(prepareConfirmation(d,notice).plans,{});
  d[0]._plan_update=true;const saved=prepareConfirmation(d,notice);
  assert.equal(saved.plans[0].workflow_version,4);assert.equal(saved.target_versions.existing,6);
  assert.equal(saved.plans[0].participation,'undecided');
});

test('declined optional tasks leave active work and calendar but remain in history',()=>{
  const task={id:'declined',status:'pending',action_excluded:true,workflow:{blocked:false},pending_changes:[],execution_issues:[{code:'participation'}],data:{title:'可选咨询',scope:'personal',due_date:'2026-10-20'}};
  assert.equal(taskMatchesFilter(task,'pending'),false);
  assert.equal(taskMatchesFilter(task,'all'),null); // The caller applies its unfiltered listing.
  assert.deepEqual(calendarEntries([],[task],'2026-10-01','2026-10-31'),[]);
  const joined={...task,action_excluded:false};
  assert.equal(taskMatchesFilter(joined,'pending'),true);
  assert.equal(calendarEntries([],[joined],'2026-10-01','2026-10-31').length,1);
  assert.equal(calendarEntries([],[{...task,status:'done'}],'2026-10-01','2026-10-31',{showDone:true}).length,1);
});
