import test from 'node:test';
import assert from 'node:assert/strict';
import {replyWaitHint} from '../static/chat-wait.js';

test('waiting guidance follows the actual stage and survives a restored running turn',()=>{
  const message={role:'assistant',status:'processing',_phase:'searching'};
  assert.match(replyWaitHint(message),/查找相关资料/);
  assert.match(replyWaitHint(message),/切换页面.*后台会继续处理/);
  const restored={role:'assistant',status:'processing',grounding:{steps:[{stage:'searching',state:'complete'},{stage:'verifying',state:'running'}]}};
  assert.match(replyWaitHint(restored),/核对回复依据/);
  assert.doesNotMatch(replyWaitHint(restored),/查找/);
});

test('unacknowledged and finished turns do not promise background processing',()=>{
  for(const message of [null,{role:'user',status:'queued'},{role:'assistant',status:'complete'},{role:'assistant',status:'failed'},{role:'assistant',status:'cancelled'}]){
    assert.equal(replyWaitHint(message),'');
  }
  assert.match(replyWaitHint({role:'assistant',status:'processing'}),/处理中/);
  assert.doesNotMatch(replyWaitHint({role:'assistant',status:'processing'}),/查找/);
});
