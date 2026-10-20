import test from 'node:test';
import assert from 'node:assert/strict';
import {memoryOperationSummary} from '../static/genui/memory-notice.js';

test('memory receipt distinguishes actual persistence from proposals and blocked forgetting',()=>{
  assert.equal(memoryOperationSummary([{status:'accepted'},{status:'pending'},{status:'pending'},{status:'forgotten_blocked'}]),
    '1 条记忆已保存；2 条记忆等你核对；1 条已遗忘内容未重新保存');
  assert.equal(memoryOperationSummary([{status:'rejected',reason:'secret fixture'}]),'1 条记忆建议未保存');
});
test('malformed or model-defined receipt statuses cannot become UI text',()=>{
  assert.equal(memoryOperationSummary([{status:'<img src=x>'},null,{status:'__proto__'}]),'');
  assert.equal(memoryOperationSummary(null),'');
});
