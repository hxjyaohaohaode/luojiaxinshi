import test from 'node:test';
import assert from 'node:assert/strict';
import {overviewData} from '../static/overview.js';

const task=(id,extra={})=>({id,status:'pending',data:{title:id,scope:'personal',due_date:'2026-10-23',deadline_confirmed:true},...extra});
test('overview excludes other-person, cancelled and declined work from personal progress',()=>{
  const tasks=[task('pending'),task('done',{status:'done'}),task('cancelled',{status:'cancelled'}),
    task('declined',{action_excluded:true}),task('other',{data:{scope:'other'}})];
  const result=overviewData(tasks,[]);
  assert.deepEqual(result.pending.map(t=>t.id),['pending']);
  assert.equal(result.completed,1);assert.equal(result.total,2);
});
test('focus follows saved follow-up, overdue and near-term flags without mutating records',()=>{
  const tasks=[task('ordinary'),task('soon',{due_soon:true}),task('late',{overdue:true}),task('followup',{followup_due:true})];
  const result=overviewData(tasks,[]);
  assert.deepEqual(result.ordered.map(t=>t.id),['followup','late','soon','ordinary']);
  assert.deepEqual(tasks.map(t=>t.id),['ordinary','soon','late','followup']);
  assert.equal(result.urgent.length,2);assert.equal(result.followup.length,1);
});
test('empty accounts and unresolved records retain accurate inventory',()=>{
  const empty=overviewData([],[]);assert.equal(empty.total,0);assert.equal(empty.completed,0);
  const result=overviewData([task('unknown',{data:{scope:'personal',due_date:null,deadline_confirmed:false}})],
    [{status:'confirmed'},{status:'received'},{status:'processing'},{status:'failed'}]);
  assert.equal(result.uncertain.length,1);assert.equal(result.notices.length,3);
});
