import test from 'node:test';
import assert from 'node:assert/strict';
import {traceRecords,traceDuration} from '../static/genui/execution-trace.js';
import {EndPullState} from '../static/chat-end-gesture.js';
import {timeGroups} from '../static/genui/chat-policy.js';

test('trace keeps actual step times and outcomes; missing measurements remain unknown',()=>{
  const message={grounding:{steps:[{id:'read',stage:'agent_tool',title:'读取资料',state:'complete',started_at:100,finished_at:105,summary:'读取2项记录',arguments:{secret:'must not expose'}},{id:'check',stage:'verifying',title:'核验',state:'running',started_at:106},{id:'missing',stage:'writing',title:'生成',state:'complete'}],private_reasoning:'must not expose'}};
  const records=traceRecords(message,110);assert.equal(records[0].duration,5);assert.equal(records[0].lane,'tools');assert.equal(records[1].duration,4);assert.equal(records[1].lane,'check');assert.equal(records[2].duration,null);
  assert.doesNotMatch(JSON.stringify(records),/must not expose|arguments|private_reasoning/);assert.equal(traceDuration(null),'未记录');assert.equal(traceDuration(61),'1分1秒');assert.equal(traceDuration(0),'0秒');
});
test('pull-to-new-chat can retreat before the threshold; a small movement never arms it',()=>{
  const pull=new EndPullState(110);pull.pull(12);assert.equal(pull.armed,false);pull.pull(120);assert.equal(pull.armed,true);pull.pull(55);assert.equal(pull.armed,false);assert.equal(pull.progress,.5);pull.reset();assert.equal(pull.progress,0);
});
test('slow replies and later revision creation never insert another time separator in the same user turn',()=>{
  const at=new Date(2026,9,27,9).getTime()/1000;
  const messages=[{id:'u1',role:'user',created_at:at},{id:'a1',role:'assistant',created_at:at+1200},{id:'u2',role:'user',created_at:at+1500},{id:'a2-new-version',role:'assistant',created_at:at+8000}];
  assert.deepEqual([...timeGroups(messages).keys()],['u1','u2']);
});
