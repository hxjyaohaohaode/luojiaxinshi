import test from 'node:test';
import assert from 'node:assert/strict';
import {ReviewClock,observationReceipt} from '../static/review-observation.js';
import {qualityReceipt} from '../static/notice-resolution.js';

test('idle time is bounded and resumes only with activity',()=>{
 const clock=new ReviewClock(0);
 assert.equal(clock.snapshot(90000).active_ms,60000);
 clock.activity(120000);assert.equal(clock.snapshot(130000).active_ms,70000);
});
test('background and request waits do not count and editing is a subset',()=>{
 const clock=new ReviewClock(0);clock.focus(10000,true);clock.visibility(20000,false);
 clock.snapshot(240000);clock.visibility(300000,true);clock.focus(310000,false);
 assert.deepEqual(clock.snapshot(320000),{method:'visible_idle_60s_v1',active_ms:40000,editing_ms:20000});
});
test('submitting freezes an independent snapshot across retries',()=>{
 const clock=new ReviewClock(0);clock.focus(1000,true);clock.visibility(4000,false);
 const submitted=clock.snapshot(4000);clock.snapshot(50000);clock.visibility(80000,true);clock.activity(81000);
 assert.equal(submitted.active_ms,4000);assert.equal(clock.snapshot(82000).active_ms,6000);
 assert.equal(submitted.editing_ms,3000);
});
test('monotonic rollback and upper bound never inflate or produce negative intervals',()=>{
 const clock=new ReviewClock(1000);clock.focus(1000,true);clock.snapshot(2000);clock.activity(0);
 assert.equal(clock.snapshot(2500).active_ms,1500);
 for(let i=1;i<=600;i++)clock.activity(2500+i*60000);
 const value=clock.snapshot(36002500);assert.equal(value.active_ms,28800000);assert.equal(value.editing_ms,28800000);
 assert.deepEqual(Object.keys(value).sort(),['active_ms','editing_ms','method']);
});
test('timing stays visible without model opinions and imported times remain historical',()=>{
 const observation={method:'visible_idle_60s_v1',active_ms:61000,editing_ms:12000};
 assert.match(qualityReceipt({issues:[],observation},String),/1 分 1 秒/);
 assert.match(observationReceipt(observation,true),/历史用时/);
 assert.match(observationReceipt(observation,true),/不能作为纯纠错时间或完整办理时间/);
 assert.equal(qualityReceipt({issues:[]},String),'');
});
