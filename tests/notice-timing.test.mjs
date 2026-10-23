import test from 'node:test';
import assert from 'node:assert/strict';
import {calendarEntries} from '../static/calendar-model.js';
import {taskTimeLabel,needsTimingReview,calendarReady,taskOnDay} from '../static/notice-timing.js';
import {overviewData,overviewWeek} from '../static/overview.js';

const activity=()=>({id:'event',status:'pending',data:{title:'讲座',scope:'personal',scheduled:{kind:'event',start_date:'2027-10-20',start_time:'23:00',end_date:'2027-10-21',end_time:'01:00',confirmed:true}},workflow:{data:{execution_mode:'attendance'}}});
test('notice activities span days without becoming deadlines or inventing an end',()=>{
  const t=activity();let entries=calendarEntries([],[t],'2027-10-20','2027-10-21');
  assert.deepEqual(entries.map(e=>[e.kind,e.start,e.end]),[['notice_event','23:00','24:00'],['notice_event','00:00','01:00']]);
  t.data.scheduled.end_time='00:00';assert.equal(calendarEntries([],[t],'2027-10-20','2027-10-21').length,1);
  t.data.scheduled.end_time=null;t.data.scheduled.end_date=null;
  entries=calendarEntries([],[t],'2027-10-20','2027-10-21');assert.equal(entries.length,1);assert.equal(entries[0].end,null);
  assert.match(taskTimeLabel(t.data),/活动 2027-10-20 23:00/);assert.doesNotMatch(taskTimeLabel(t.data),/截止/);
});
test('activity confirmation and deadline confirmation independently gate export',()=>{
  const t=activity();assert.equal(calendarReady(t.data),true);assert.equal(needsTimingReview(t),false);
  t.data.due_date='2027-10-18';t.data.deadline_confirmed=false;
  assert.equal(calendarReady(t.data),false);assert.equal(needsTimingReview(t),true);
  t.data.deadline_confirmed=true;t.data.scheduled.confirmed=false;assert.equal(calendarReady(t.data),false);
});
test('reading without a deadline and archived notices no longer inflate unfinished timing work',()=>{
  const t={...activity(),data:{title:'阅读指南',scope:'personal'},workflow:{data:{execution_mode:'reading'}}};
  assert.equal(needsTimingReview(t),false);
  const overview=overviewData([t,activity()],[{status:'received',disposition:'reference'},{status:'draft',disposition:'inbox'}]);
  assert.equal(overview.uncertain.length,0);assert.equal(overview.notices.length,1);
  assert.equal(overviewWeek([activity()],'2027-10-20')[1].tasks.length,1);
  assert.equal(taskOnDay(activity().data,'2027-10-21'),true);
});
