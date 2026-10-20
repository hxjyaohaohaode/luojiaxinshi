import test from 'node:test';
import assert from 'node:assert/strict';
import {taskLanes} from '../static/task-views.js';
import {overviewWeek} from '../static/overview.js';
import {numberMarkup,ringMarkup} from '../static/experience-system.js';

const task=(id,overrides={})=>({id,status:'pending',data:{scope:'personal',due_date:'2026-12-31'},workflow:{data:{stage:'preparing'}},...overrides});
test('board partitions current results once, keeping excluded and cancelled actions out of active lanes',()=>{
  const records=[task('prepare'),task('follow',{followup_due:true}),task('submitted',{workflow:{data:{stage:'submitted'}}}),task('blocked',{workflow:{data:{stage:'blocked'}}}),task('done',{status:'done'}),task('cancelled',{status:'cancelled'}),task('declined',{action_excluded:true})];
  const original=structuredClone(records);
  assert.deepEqual(taskLanes(records).map(l=>l.tasks.map(t=>t.id)),[['prepare'],['follow','submitted','blocked'],['done','cancelled','declined']]);
  assert.deepEqual(records,original);
});
test('seven day strip crosses year boundaries and uses only active personal deadlines',()=>{
  const records=[task('today'),task('next',{data:{scope:'personal',due_date:'2027-01-01'}}),task('outside',{data:{scope:'personal',due_date:'2027-01-07'}}),task('other',{data:{scope:'other',due_date:'2026-12-31'}}),task('done',{status:'done'}),task('declined',{action_excluded:true})];
  const days=overviewWeek(records,'2026-12-31');
  assert.equal(days.length,7);assert.equal(days.at(-1).day,'2027-01-06');
  assert.deepEqual(days.map(d=>d.tasks.map(t=>t.id)),[['today'],['next'],[],[],[],[],[]]);
});
test('metric accessibility keeps a stable final value and ring bounds real counts',()=>{
  assert.match(numberMarkup(14),/<span class="sr-only">14<\/span>/);
  assert.match(numberMarkup(Infinity),/data-number="0"/);
  assert.match(ringMarkup(2,4,'个人行动'),/data-ring="50"/);
  assert.match(ringMarkup(8,4,'个人行动'),/个人行动：4 \/ 4/);
  assert.match(ringMarkup(0,0,'个人行动'),/待开始/);
  assert.doesNotMatch(ringMarkup(Infinity,NaN,'个人行动'),/NaN|Infinity/);
});
