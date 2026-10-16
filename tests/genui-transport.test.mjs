import test from 'node:test';
import assert from 'node:assert/strict';
import {SSEDecoder} from '../static/genui/transport.js';
const packet=(seq,type,data)=>`id: ${seq}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
test('long Chinese answers survive hundreds of frames and a full history checkpoint',()=>{
  const answer='中文长回复🌸，引号与换行保持完整。\n'.repeat(3000)+'结尾',parts=[],seen=[];let seq=1;
  parts.push(packet(seq++,'start',{}));for(let i=0;i<answer.length;i+=233)parts.push(packet(seq++,'delta',{text:answer.slice(i,i+233)}));
  parts.push(packet(seq++,'done',{conversation:{messages:[{content:answer,genui:{raw:answer}}]}}));
  const bytes=new TextEncoder().encode(parts.join('')),decoder=new SSEDecoder((type,data)=>seen.push({type,data}));
  for(let i=0;i<bytes.length;i+=113)decoder.push(bytes.slice(i,i+113));decoder.finish();
  assert.equal(seen.filter(e=>e.type==='delta').map(e=>e.data.text).join(''),answer);
  assert.equal(seen.at(-1).data.conversation.messages[0].genui.raw,answer);
});
test('work summaries carry stable stage IDs and reject malformed state',()=>{
  const steps=[{id:'step-1',title:'确认范围',summary:'正在确认问题涉及的范围。',state:'running'}],seen=[],decoder=new SSEDecoder((t,d)=>seen.push([t,d]));
  decoder.push(new TextEncoder().encode(packet(1,'phase',{phase:'planning',label:'正在确认范围',steps})+packet(2,'work',{steps})+packet(3,'done',{})));decoder.finish();
  assert.equal(seen[1][1].steps[0].id,'step-1');
  assert.throws(()=>new SSEDecoder(()=>{}).push(new TextEncoder().encode(packet(1,'work',{steps:[{...steps[0],state:'pretend-success'}]}))),/摘要无效/);
});
test('verified reply phases preserve ordering without accepting arbitrary events',()=>{
  const seen=[],decoder=new SSEDecoder((type,data)=>seen.push([type,data]));
  decoder.push(new TextEncoder().encode(packet(1,'start',{})+packet(2,'phase',{phase:'verifying',label:'正在核对引用…'})+packet(3,'delta',{text:'核验后的回复'})+packet(4,'done',{})));decoder.finish();
  assert.equal(seen[1][1].phase,'verifying');assert.equal(seen[2][1].text,'核验后的回复');
  assert.throws(()=>new SSEDecoder(()=>{}).push(new TextEncoder().encode(packet(1,'phase',{phase:'execute-private-code',label:'错误'}))),/阶段无效/);
});
test('SSE frames survive every UTF-8 byte split and duplicate delivery',()=>{
  const raw=packet(1,'start',{message_id:'one'})+packet(2,'delta',{text:'中文🌸'})+packet(2,'delta',{text:'中文🌸'})+packet(3,'done',{conversation:{}}),bytes=new TextEncoder().encode(raw);
  for(let cut=0;cut<=bytes.length;cut++){const events=[],p=new SSEDecoder((...v)=>events.push(v));p.push(bytes.slice(0,cut));p.push(bytes.slice(cut));p.finish();assert.equal(events.length,3);assert.equal(events[1][1].text,'中文🌸');}
});
test('SSE gaps, malformed frames and oversized events stop safely',()=>{
  const feed=text=>{const p=new SSEDecoder(()=>{});p.push(new TextEncoder().encode(text));p.finish();};
  assert.throws(()=>feed(packet(2,'delta',{text:'missing'})),/缺失/);assert.throws(()=>feed(packet(1,'delta',{text:'partial'})),/连接中断/);
  assert.throws(()=>feed('id: 1\nevent: delta\ndata: {bad}\n\n'),/解析/);
  assert.throws(()=>{const p=new SSEDecoder(()=>{},{eventBytes:10});p.push(new TextEncoder().encode(packet(1,'delta',{text:'long message'})));},/过长/);
});
