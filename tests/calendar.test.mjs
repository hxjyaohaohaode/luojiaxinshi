import test from 'node:test';
import assert from 'node:assert/strict';
import {dayKey,addDays,shiftMonth,weekStart,sundayStart,monthDays,calendarEntries,layoutTimed,periodPosition} from '../static/calendar-model.js';

test('calendar civil days remain correct at leap years, month ends and Beijing midnight',()=>{
  assert.equal(dayKey('2026-10-12T16:00:00Z'),'2026-10-13');
  assert.equal(addDays('2028-02-28',1),'2028-02-29');
  assert.equal(addDays('2028-02-29',1),'2028-03-01');
  assert.equal(shiftMonth('2028-01-31',1),'2028-02-29');
  assert.equal(shiftMonth('2026-12-31',1),'2027-01-31');
  assert.equal(weekStart('2026-11-01'),'2026-10-26');
  assert.equal(sundayStart('2026-10-13'),'2026-10-11');
  const days=monthDays('2026-11-01');assert.equal(days.length,42);assert.equal(days[0],'2026-10-26');assert.equal(days.at(-1),'2026-12-06');
});

const record=(changes={})=>({id:'class',version:1,data:{title:'Test course',category:'course',location:'Test room',notes:'',start_date:'2026-10-13',end_date:'2026-10-13',start_time:'14:05',end_time:'16:30',repeat:'biweekly',repeat_until:'2026-11-10',...changes}});
test('recurring courses appear only on requested weeks, with inclusive last occurrence',()=>{
  let entries=calendarEntries([record()],[],'2026-10-01','2026-11-30');assert.deepEqual(entries.map(e=>e.day),['2026-10-13','2026-10-27','2026-11-10']);
  entries=calendarEntries([record()],[],'2026-10-20','2026-11-09');assert.deepEqual(entries.map(e=>e.day),['2026-10-27']);
  assert.equal(calendarEntries([record()],[],'2026-11-11','2026-12-31').length,0);
});
test('cross-midnight plans and multi-day all-day arrangements occupy the correct dates',()=>{
  const a=record({repeat:'none',repeat_until:null,start_date:'2026-12-31',end_date:'2027-01-01',start_time:'23:00',end_time:'01:00'});
  const entries=calendarEntries([a],[],'2026-12-01','2027-01-31');
  assert.deepEqual(entries.map(e=>[e.day,e.start,e.end]),[['2026-12-31','23:00','24:00'],['2027-01-01','00:00','01:00']]);
  const b=record({repeat:'none',repeat_until:null,start_time:null,end_time:null,end_date:'2026-10-15'});
  assert.equal(calendarEntries([b],[],'2026-10-14','2026-10-14')[0].allDay,true);
});
test('official deadlines and preparation times remain distinct, cancelled and other-person tasks are excluded',()=>{
  const task={id:'task',version:1,status:'pending',data:{title:'test',scope:'personal',due_date:'2026-10-13',due_time:'17:00',deadline_confirmed:false,planned_at:'2026-10-12T23:00:00Z',location:'',details:''}};
  const entries=calendarEntries([], [task], '2026-10-13','2026-10-13');assert.equal(entries.length,2);
  assert.equal(entries.find(e=>e.kind==='plan').start,'07:00');assert.equal(entries.find(e=>e.kind==='deadline').verified,false);
  assert.equal(calendarEntries([], [{...task,status:'done'}], '2026-10-13','2026-10-13').length,0);
  assert.equal(calendarEntries([], [{...task,status:'done'}], '2026-10-13','2026-10-13',{showDone:true}).length,2);
  assert.equal(calendarEntries([], [{...task,status:'cancelled'}], '2026-10-13','2026-10-13',{showDone:true}).length,0);
  assert.equal(calendarEntries([], [{...task,data:{...task.data,scope:'other'}}], '2026-10-13','2026-10-13').length,0);
});
test('overlapping class cards use separate columns; adjacent classes reuse full width',()=>{
  const result=layoutTimed([{key:'a',start:'08:00',end:'10:00'},{key:'b',start:'09:00',end:'11:00'},{key:'c',start:'11:00',end:'12:00'}]);
  assert.equal(result[0].lanes,2);assert.equal(result[1].lanes,2);assert.notEqual(result[0].lane,result[1].lane);assert.equal(result[2].lanes,1);
  assert.equal(result[0].cluster,result[1].cluster);assert.equal(result[0].clusterSize,2);
});

test('the immersive timetable uses the supplied period scale without changing actual times',()=>{
  assert.equal(periodPosition(8*60),0);assert.equal(periodPosition(14*60+5),5);assert.equal(periodPosition(21*60),13);
  assert.equal(periodPosition(7*60),0);assert.equal(periodPosition(23*60),14);assert.equal(periodPosition(8*60+25),.5);
});
