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
test('lifecycle receipts distinguish temporary context, checkpoints, actual use and clearing',()=>{
  assert.equal(memoryOperationSummary([{status:'session_saved'},{status:'checkpointed'},{status:'used'},{status:'all_forgotten'}]),
    '1 条条件仅保留在本会话；1 次工作记忆已更新；1 条记忆被 Agent 报告采用；1 次记忆已全部清空');
});
