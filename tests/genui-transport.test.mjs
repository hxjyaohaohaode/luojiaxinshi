import test from 'node:test';
import assert from 'node:assert/strict';
import {SSEDecoder} from '../static/genui/transport.js';
const packet=(seq,type,data)=>`id: ${seq}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
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
