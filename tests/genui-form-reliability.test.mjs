import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const runtime=readFileSync(new URL('../static/genui/sandbox-runtime.js',import.meta.url),'utf8');
const body=runtime.slice(runtime.indexOf('  function bindForm('),runtime.indexOf('  const api=Object.freeze'));
function setup(values={x:'8',y:'2'},attributes={}){
  const form={listeners:{}};const nodes={};
  for(const [id,value]of Object.entries(values))nodes[id]={id,value,type:'number',checked:false,required:false,validity:{valid:true},form,listeners:{},labels:[{innerText:id}],
    getAttribute:key=>attributes[id]?.[key]??null,matches:()=>true,setAttribute(){},removeAttribute(){}};
  nodes.result={textContent:''};nodes.error={textContent:'',hidden:true};nodes.ask={listeners:{}};let requests=0,published=0;
  const root={querySelector:s=>nodes[s.slice(1)]||null,append(){}};
  const sandbox={root,document:{documentElement:{lang:'zh-CN'}},CSS:{escape:v=>v},Intl,queueMicrotask,setTimeout,Object,Number,Set,Error,
    nativeAdd:{call(node,type,handler){(node.listeners[type]??=[]).push(handler);}},publishText:()=>published++,measure(){},changed:()=>published++,lockActions(){},request:async()=>{requests++;}};
  vm.createContext(sandbox);vm.runInContext(body+';globalThis.bind=bindForm;',sandbox);
  return {nodes,form,bind:sandbox.bind,requests:()=>requests,published:()=>published,emit:async(node,type)=>{for(const handler of node.listeners[type]||[])await handler({preventDefault(){},stopImmediatePropagation(){}});}};
}
test('blank, non-finite and zero-divisor inputs cannot retain a stale result',async()=>{
  const env=setup();env.bind({inputs:{x:{},y:{}},outputs:{result:v=>v.x/v.y},error:'error'});
  assert.equal(env.nodes.result.textContent,'4');env.nodes.x.value='';await env.emit(env.nodes.x,'input');
  assert.equal(env.nodes.result.textContent,'—');assert.match(env.nodes.error.textContent,/不能为空/);
  env.nodes.x.value='8';env.nodes.y.value='0';await env.emit(env.nodes.y,'input');assert.equal(env.nodes.result.textContent,'—');
  env.nodes.y.value='2';await env.emit(env.nodes.y,'input');assert.equal(env.nodes.result.textContent,'4');assert.equal(env.requests(),0);
});
test('DOM ranges and steps remain binding when a generated config is missing or broader',()=>{
  const env=setup({x:'5'}, {x:{min:'10',max:'20',step:'2'}});
  const model=env.bind({inputs:{x:{min:0,max:100}},outputs:{result:v=>v.x},error:'error'});
  assert.equal(env.nodes.result.textContent,'—');env.nodes.x.value='11';model.update();assert.equal(env.nodes.result.textContent,'—');
  env.nodes.x.value='12';model.update();assert.equal(env.nodes.result.textContent,'12');
});
test('a fractional default is a valid native numeric step base',()=>{
  const env=setup({x:'0.3'}, {x:{value:'0.1',step:'0.2'}});
  const model=env.bind({inputs:{x:{}},outputs:{result:v=>v.x},error:'error'});
  assert.equal(env.nodes.result.textContent,'0.3');env.nodes.x.value='0.2';model.update();assert.equal(env.nodes.result.textContent,'—');
});
test('native reset and explicit reset recalculate outputs and publish fresh state',async()=>{
  const env=setup();const model=env.bind({inputs:{x:{},y:{}},outputs:{result:v=>v.x/v.y},error:'error'});
  env.nodes.x.value='20';model.update();assert.equal(env.nodes.result.textContent,'10');
  for(const handler of env.form.listeners.reset)handler();await Promise.resolve();env.nodes.x.value='8';
  await new Promise(resolve=>setTimeout(resolve,1));assert.equal(env.nodes.result.textContent,'4');
  env.nodes.x.value='30';model.update();model.reset();assert.equal(env.nodes.x.value,'8');assert.equal(env.nodes.result.textContent,'4');assert.ok(env.published()>0);
});
test('text constraints and malformed string results do not turn into plausible calculations',()=>{
  const env=setup({x:''});env.nodes.x.type='text';env.nodes.x.required=true;
  const model=env.bind({inputs:{x:{}},outputs:{result:()=> 'NaN'},error:'error'});assert.equal(env.nodes.result.textContent,'—');
  env.nodes.x.value='输入';model.update();assert.equal(env.nodes.result.textContent,'—');
});
test('local edits never request a model; invalid input blocks explicit follow-up',async()=>{
  const env=setup();env.bind({inputs:{x:{},y:{}},outputs:{result:v=>v.x/v.y},error:'error',prompt:{id:'ask',text:'分析当前选择'}});
  env.nodes.x.value='';await env.emit(env.nodes.x,'input');await env.emit(env.nodes.ask,'click');assert.equal(env.requests(),0);
  env.nodes.x.value='10';await env.emit(env.nodes.x,'input');await env.emit(env.nodes.ask,'click');assert.equal(env.requests(),1);
});
