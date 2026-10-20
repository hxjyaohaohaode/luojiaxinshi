import test from 'node:test';
import assert from 'node:assert/strict';
import {speechChunks} from '../static/speech.js';
import {readableSnapshot} from '../static/genui/citations.js';
import {SSEDecoder} from '../static/genui/transport.js';

test('speech covers the complete reply, splits long paragraphs and keeps emoji intact',()=>{
 const text='这是一段用于测试长回答的文字。'.repeat(240)+'🌸结束';
 const chunks=speechChunks(text);
 assert.ok(chunks.length>1);assert.equal(chunks.join(''),text);
 assert.ok(chunks.every(s=>s.length<=1800&&!/[\uD800-\uDBFF]$/.test(s)));
 assert.equal(speechChunks('## 建议\n[查看原文](https://example.com)[1]\n```js\nsecret-code\n```')[0],'建议\n查看原文');
});
test('citation snapshots use readable date and material labels, preserving original inputs',()=>{
 const raw=JSON.stringify({record_type:'快照',values:{due_date:'2026-10-27',materials:['申请表'],deadline_confirmed:false},status:'pending'});
 const preview=readableSnapshot(raw,'task');
 assert.ok(preview.includes('正式期限：2026-10-27'));assert.ok(preview.includes('状态：待完成'));assert.ok(preview.includes('期限待核实'));assert.ok(!preview.includes('record_type'));
 assert.equal(readableSnapshot(raw,'notice'),raw);
 assert.ok(!readableSnapshot('{"values":','task').includes('{'));
});
test('preview events are distinct from committed deltas and resets do not mark completion',()=>{
 const seen=[];const decoder=new SSEDecoder((type,data)=>seen.push({type,data}));
 const frame=(id,event,data)=>new TextEncoder().encode(`id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
 decoder.push(frame(1,'preview',{text:'正在写',message_id:'one'}));assert.equal(decoder.done,false);
 decoder.push(frame(2,'preview',{text:'',reset:true,message_id:'one'}));
 decoder.push(frame(3,'delta',{text:'最终内容',message_id:'one'}));
 decoder.push(frame(4,'done',{conversation:{}}));decoder.finish();
 assert.deepEqual(seen.map(x=>x.type),['preview','preview','delta','done']);
});
