import test from 'node:test';
import assert from 'node:assert/strict';
import {evaluateExpression,parseMessage,blockMarkdown,validateNode,validateAction} from '../static/genui/core.js';
import {SCENARIOS} from '../static/genui/scenarios.js';

test('unsupported action expressions fail validation before any user clicks',()=>{
  const bad={kind:'state',key:'notes',value:{$expr:"concat(notes, [{id: 'n2', text: draft}])"}};
  assert.throws(()=>validateAction(bad),/invalid_expression_token|forbidden_function/);
  assert.throws(()=>validateNode({id:'add',type:'Button',props:{label:'添加到清单'},on:{click:bad}}));
  assert.throws(()=>validateAction({kind:'ask_model',prompt:'继续',values:{nested:[{$expr:'fetch(secret)'}]}}),/forbidden_function/);
  assert.equal(validateAction({kind:'state',key:'count',value:{$expr:'count+1'}}).value.$expr,'count+1');
  assert.throws(()=>validateNode({id:'save',type:'Button',props:{label:'保存本回答进度'},on:{click:{kind:'state',key:'saved',value:true}}}),/unsupported_persistent_save/);
});
test('model-authored array conditions filter sections with the same bounded grammar',()=>{
  assert.equal(evaluateExpression('contains(["全部","文学"],filter)',{filter:'文学'}),true);
  assert.equal(evaluateExpression('contains(["全部","文学"],filter)',{filter:'科学'}),false);
  assert.equal(evaluateExpression('sum([2,hours,4])',{hours:3}),9);
  for(const expression of ['[1,]','[constructor]','[1][0]','['.repeat(100)+'1'+']'.repeat(100)])assert.throws(()=>evaluateExpression(expression,{}),expression);
});
test('data pipelines keep derived counts, totals, rows and chart points in agreement',()=>{
  const state={rows:[{id:'b',kind:'x',cost:3},{id:'a',kind:'x',cost:2},{id:'c',kind:'y',cost:9}],kind:'x'};
  const filtered='where(rows,"kind",kind)';
  assert.equal(evaluateExpression('sumBy('+filtered+',"cost")',state),5);
  assert.equal(evaluateExpression('count('+filtered+')',state),2);
  assert.deepEqual(evaluateExpression('series(orderBy('+filtered+',"cost"),"id","cost")',state),[{x:'a',y:2},{x:'b',y:3}]);
  assert.equal(evaluateExpression('count(search(rows,"no match"))',state),0);
  assert.equal(state.rows[0].id,'b');
  for(const expr of ['pluck(rows,"constructor")','orderBy(rows,"cost","desc")','take(rows,-1)','sumBy(rows,"kind")','search(rows,9)'])assert.throws(()=>evaluateExpression(expr,state));
  assert.throws(()=>evaluateExpression('orderBy(rows,"cost")',{rows:Array(1000).fill({cost:1})}));
});
test('arbitrary repeated content and conditional sections export the visible state',()=>{
  const raw='```genui\n'+SCENARIOS.compose.ops.map(op=>JSON.stringify(op)).join('\n')+'\n```',spec=parseMessage(raw)[0].spec;
  assert.equal(spec.errors.length,0);
  const state={...spec.state,query:'',category:'表达',showDetail:false};
  const text=blockMarkdown(spec,state);
  assert.match(text,/阅读札记/);assert.match(text,/5.5/);assert.doesNotMatch(text,/植物图鉴|如何阅读/);
});
test('copy and share export the selected tab from the saved view',()=>{
  const operations=[{op:'begin',v:1},{op:'node',id:'tabs',type:'Tabs',props:{labels:['甲','乙']},children:['first','second']},{op:'node',id:'first',type:'Markdown',props:{text:'未选择的分组'}},{op:'node',id:'second',type:'Markdown',props:{text:'当前选择的分组'}},{op:'end'}];
  const spec=parseMessage('```genui\n'+operations.map(v=>JSON.stringify(v)).join('\n')+'\n```')[0].spec;
  const exported=blockMarkdown(spec,spec.state,{tabs:{selected:1}});assert.match(exported,/当前选择的分组/);assert.doesNotMatch(exported,/未选择的分组/);
});
