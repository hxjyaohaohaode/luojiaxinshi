import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseMessage,StreamParser,messageMarkdown} from '../static/genui/core.js';
import {applyPreview,validateOpenUI} from '../static/genui/openui-codec.js';
import {SSEDecoder} from '../static/genui/transport.js';
const ui=JSON.parse(readFileSync(new URL('../fixtures/genui/openui-planner.json',import.meta.url),'utf8'));
const raw='合成验收。\n```openui\n'+JSON.stringify(ui)+'\n```';
test('authored document streams at byte boundaries and restores without host execution',()=>{
  const expected=parseMessage(raw),bytes=new TextEncoder().encode(raw),parser=new StreamParser();
  for(let i=0;i<bytes.length;i+=17)parser.push(bytes.slice(i,i+17));
  assert.deepEqual(parser.finish(),expected);assert.equal(expected[1].spec.complete,true);assert.deepEqual(expected[1].spec.sandbox,ui);
  assert.match(messageMarkdown(expected),/材料准备/);assert.doesNotMatch(messageMarkdown(expected),/jsFunctions|addEventListener/);
  assert.equal(parseMessage(raw.slice(0,-3))[1].spec.complete,false);
});
test('preview patches append incrementally and reset a rejected attempt',()=>{
  let state=applyPreview(null,{reset:true,css:'h2{',title:'测试'});state=applyPreview(state,{css:'color:red}',cssComplete:true,html:[{index:0,text:'<h2>先到'}]});
  assert.equal(state.html.join(''),'<h2>先到');assert.equal(state.htmlComplete,false);
  state=applyPreview(state,{html:[{index:0,text:'内容</h2>'},{index:1,text:'<p>后到</p>'}],htmlComplete:true});
  assert.equal(state.html.join(''),'<h2>先到内容</h2><p>后到</p>');
  assert.equal(applyPreview(state,{reset:true,html:[{index:0,text:'新草稿'}]}).html.join(''),'新草稿');
  assert.throws(()=>applyPreview(state,{html:[{index:-1,text:'bad'}]}));assert.throws(()=>validateOpenUI({...ui,css:'x'.repeat(24001)}));
});
test('real UI preview is a bounded SSE event before completion',()=>{
  const seen=[],d=new SSEDecoder((type,data)=>seen.push({type,data}));
  const payload=[['ui_preview',{message_id:'m',content:{cssComplete:true,html:[{index:0,text:'<p>已到达'}]}}],['done',{conversation:{}}]];
  const bytes=new TextEncoder().encode(payload.map(([type,data],i)=>`id: ${i+1}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join(''));
  for(const byte of bytes)d.push(new Uint8Array([byte]));d.finish();assert.equal(seen[0].type,'ui_preview');
});
test('complete local code arrives independently of final host authorization',()=>{
  const state=applyPreview(null,{reset:true,cssComplete:true,html:[{index:0,text:'<input id="n">'}],jsFunctions:'function run(){}',jsFunctionsComplete:true,jsExpressions:[{index:0,text:'run();'}],jsExpressionsComplete:true,localReady:true});
  assert.equal(state.localReady,true);assert.equal(state.jsFunctions,'function run(){}');assert.deepEqual(state.jsExpressions,['run();']);
  assert.equal(state.generating,true);assert.throws(()=>applyPreview(state,{jsFunctions:'x'.repeat(32001)}));
  const next=applyPreview(state,{reset:true,css:'p{}'});assert.equal(next.revision,2);assert.equal(next.localReady,false);assert.deepEqual(next.jsExpressions,[]);
});
