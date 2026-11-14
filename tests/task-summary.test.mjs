import test from 'node:test';
import assert from 'node:assert/strict';
import {taskRowSummary} from '../static/task-summary.js';
const task=overrides=>({id:'owned-step',status:'pending',data:{title:'本人提交申请',due_date:'2027-01-20',due_time:'17:00',deadline_confirmed:false,materials:['申请表']},workflow:{data:{execution_mode:'submission',stage:'preparing',action_kind:'required',prepared_materials:[]}},...overrides});

test('submission preparation opens handling and keeps the unverified deadline explicit',()=>{
  const summary=taskRowSummary(task({pending_changes:[{id:'revision-review'}],needs_calendar_sync:true}));
  assert.equal(summary.opensHandling,true);assert.equal(summary.state,'变更待核对');assert.equal(summary.next,'核对变动影响');assert.match(summary.time,/待核实/);
  assert.ok(summary.warnings.some(value=>value.includes('手机日历')));assert.ok(summary.warnings.some(value=>value.includes('不能当作已确认期限')));
});
test('personal completion does not claim official approval, and the next step stays reviewable',()=>{
  const summary=taskRowSummary(task({status:'done',workflow:{data:{execution_mode:'submission',stage:'submitted'}}}));
  assert.equal(summary.state,'已完成个人办理');assert.equal(summary.next,'查看办理记录');assert.equal(summary.opensHandling,false);assert.doesNotMatch(summary.state,/审核通过|录取|受理完成/);
});
test('a real followup time takes priority while prerequisite problems remain visible',()=>{
  const summary=taskRowSummary(task({handling_state:{kind:'followup',label:'到时间跟进了'},workflow:{blocked:true,data:{followup_at:'2027-01-19T08:00:00+08:00',execution_mode:'waiting',stage:'waiting'}}}));
  assert.match(summary.time,/^跟进 /);assert.equal(summary.next,'到时间跟进了');assert.ok(summary.warnings.includes('前置步骤尚未完成'));
});
