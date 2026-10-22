import test from 'node:test';
import assert from 'node:assert/strict';
import {speechChunks} from '../static/speech-text.js';
import {memoryUseCount} from '../static/genui/memory-notice.js';
test('read aloud normalizes dates, clock times and reference syntax',()=>{
 const result=speechChunks('## 安排\n2026-10-22 09:05 提交[申请](https://example.com)[E1]。\n| 项目 | 时刻 |\n| --- | --- |\n| 材料 | 17:00 |').join('');
 assert.ok(result.includes('2026年10月22日 9点5分'));assert.ok(result.includes('17点'));assert.ok(!result.includes('---'));assert.ok(!result.includes('https'));assert.ok(!result.includes('[E1]'));
});
test('read aloud chunks preserve every character and Unicode at configurable limits',()=>{
 const text='申请。😀需要核对！'.repeat(200);const chunks=speechChunks(text,100);
 assert.equal(chunks.join(''),text);assert.ok(chunks.every(c=>c.length<=100&&!/[\uD800-\uDBFF]$/.test(c)));
});
test('retrieval candidates alone never count as memories actually used',()=>{
 assert.equal(memoryUseCount({grounding:{memory_operations:{}},citations:null,evidence_sources:{}}),0);
 assert.equal(memoryUseCount({grounding:{memory:{selected:4}},evidence_sources:[{id:'memo-a',evidence_kind:'memory'}]}),0);
 assert.equal(memoryUseCount({grounding:{memory_operations:[{id:'a',status:'used'},{id:'b',status:'accepted'}]},citations:[{source_id:'memo-a'},{source_id:'memo-c'}],evidence_sources:[{id:'memo-a',evidence_kind:'memory'},{id:'memo-c',evidence_kind:'memory'}]}),2);
});
