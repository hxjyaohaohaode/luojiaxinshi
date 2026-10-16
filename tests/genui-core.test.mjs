import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {StreamParser,parseMessage,Block,StateStore,validateNode,validateAction,evaluateExpression,blockMarkdown,CATALOG} from '../static/genui/core.js';
import {safeClone,safeUrl,safeActionUrl} from '../static/genui/security.js';
const fixture=readFileSync(new URL('../fixtures/genui/study-plan.md',import.meta.url),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const wrap=ops=>'前文中文🌸\n```genui\n'+ops.map(v=>typeof v==='string'?v:JSON.stringify(v)).join('\n')+'\n```\n后文';
const node=(id='x',text='正文')=>({op:'node',id,type:'Markdown',props:{text}});
const begin={op:'begin',v:1},end={op:'end'};

test('every UTF-8 byte boundary gives the same normalized mixed message',()=>{
  const encoded=new TextEncoder().encode(fixture+'\n中文🌸'),expected=plain(parseMessage(fixture+'\n中文🌸'));
  for(let i=0;i<=encoded.length;i++){const parser=new StreamParser();parser.push(encoded.slice(0,i));parser.push(encoded.slice(i));assert.deepEqual(plain(parser.finish()),expected,'split '+i);}
  const parser=new StreamParser();for(const byte of encoded)parser.push(new Uint8Array([byte]));assert.deepEqual(plain(parser.finish()),expected);
});
test('partial JSON lines never apply; text appears first; incomplete UI survives',()=>{
  const p=new StreamParser();p.push('已经收到');assert.equal(p.snapshot()[0].text,'已经收到');p.push('\n```ge');assert.equal(p.snapshot()[0].text,'已经收到\n');
  p.push('nui\n{"op":"begin","v":1}\n{"op":"node","id":"x","type":"Markdown","props":{"text":"🌸"}}');
  assert.equal(Object.keys(p.snapshot()[1].spec.nodes).length,0);p.push('\n');assert.equal(p.snapshot()[1].spec.nodes.x.props.text,'🌸');
  const spec=p.finish()[1].spec;assert.equal(spec.complete,false);assert.ok(spec.errors.some(e=>e.code==='incomplete'));
});
test('duplicate IDs overwrite, patch merges, bad lines do not discard neighbours',()=>{
  const spec=parseMessage(wrap([begin,node(),'not JSON',node('x','新值'),{op:'patch',id:'x',props:{label:'标签'}},node('later'),end]))[1].spec;
  assert.equal(spec.nodes.x.props.text,'新值');assert.equal(spec.nodes.x.props.label,'标签');assert.ok(spec.nodes.later);assert.ok(spec.complete);assert.equal(spec.errors[0].code,'malformed_line');
});
test('unknown type and invalid props are local readable placeholders',()=>{
  const spec=parseMessage(wrap([begin,{op:'node',id:'unknown',type:'ExecuteJS'}, {op:'node',id:'bad',type:'Slider',props:{label:'坏的',bind:'x',style:'url(evil)'}},node('ok'),end]))[1].spec;
  assert.equal(spec.nodes.unknown.type,'Unknown');assert.equal(spec.nodes.bad.type,'Unknown');assert.equal(spec.nodes.ok.type,'Markdown');assert.match(blockMarkdown(spec),/正文/);
});
test('cycles, depth, missing children and 301st node are bounded',()=>{
  const b=new Block();b.apply(begin);for(let i=0;i<301;i++)b.apply({op:'node',id:'n'+i,type:'Stack',children:['n'+(i+1)]});b.apply(end);b.closed=true;
  const spec=b.spec();assert.equal(Object.keys(spec.nodes).length,300);assert.ok(spec.errors.some(e=>e.code==='node_limit'));assert.ok(spec.errors.some(e=>e.code==='depth_limit'));
  const c=new Block();c.apply(begin);c.apply({op:'node',id:'a',type:'Stack',children:['b']});c.apply({op:'node',id:'b',type:'Stack',children:['a','lost']});c.apply(end);
  assert.ok(c.spec().errors.some(e=>e.code==='cycle'));assert.ok(c.spec().errors.some(e=>e.code==='missing_child'));assert.doesNotThrow(()=>blockMarkdown(c.spec()));
});
test('string, block, message, state and operation caps fail safely',()=>{
  const b=new Block({...CATALOG.limits,blockBytes:20});b.line(JSON.stringify(begin));b.line(JSON.stringify(node()));assert.ok(b.spec().errors.some(e=>e.code==='block_limit'));
  assert.throws(()=>validateNode(node('x','中'.repeat(3000))),/string_limit/);
  const s=new StateStore({a:1},{...CATALOG.limits,stateKeys:1});assert.throws(()=>s.defaults({b:2}),/state_limit/);assert.deepEqual(plain(s.snapshot()),{a:1});
  const p=new StreamParser({limits:{messageBytes:30}});p.push('safe text');p.push('x'.repeat(31));assert.match(p.finish()[0].text,/safe text/);
  const limited=new Block({...CATALOG.limits,operations:1});limited.apply(begin);limited.apply(node());assert.equal(Object.keys(limited.spec().nodes).length,0);
});
test('prototype pollution is rejected at every nesting level',()=>{
  for(const key of ['__proto__','constructor','prototype']){
    assert.throws(()=>safeClone(JSON.parse('{"a":{"'+key+'":{"polluted":true}}}')),/forbidden_key/);
    assert.throws(()=>evaluateExpression('x.'+key+'.value',{x:{}}));
  }
  assert.equal({}.polluted,undefined);
});
test('restricted expressions calculate only finite bounded pure values',()=>{
  const state={principal:10000,rate:3,years:10,x:2,list:[1,2,3]};
  assert.equal(evaluateExpression('round(principal*pow(1+rate/100,years),0)',state),13439);
  assert.equal(evaluateExpression('x>1 && x<3 ? sum(list) : 0',state),6);
  assert.equal(evaluateExpression('false && missing.value',state),false);
  assert.equal(evaluateExpression('clamp(20,0,10)',state),10);
  for(const source of ['window.location','globalThis.process','constructor.constructor("x")','(()=>1)()','x[0]','x=3','while(true)','fetch("https://x")','1/0','pow(9,999)','round(2,90)','x;alert(1)','min()'])assert.throws(()=>evaluateExpression(source,state),source);
  assert.throws(()=>evaluateExpression('1+'.repeat(251)+'1',state),/expression_limit/);
  assert.throws(()=>evaluateExpression('1+2+3',state,{...CATALOG.limits,expressionSteps:2}),/expression_steps/);
});
test('dirty state resists streaming defaults, type changes and missing paths',()=>{
  const s=new StateStore({hours:2,checked:[]});let changed=0;s.subscribe(()=>changed++);s.set('hours',4);s.defaults({hours:1});assert.equal(s.get('hours'),4);assert.equal(changed,1);
  assert.throws(()=>s.set('hours','4'),/state_type_changed/);assert.throws(()=>s.set('new',1),/missing_state/);s.set('checked',['one']);assert.equal(s.get('checked.0'),'one');
});
test('untrusted data cannot forge service data and actions stay allowlisted',()=>{
  const b=new Block();b.apply(begin);b.apply({op:'data',id:'records',value:[1]});assert.equal(b.data.records,undefined);b.apply({op:'data',id:'records',value:[2]},{trusted:true});assert.deepEqual(plain(b.data.records),[2]);
  assert.throws(()=>validateAction({kind:'host',name:'delete_all',params:{}}));assert.throws(()=>validateAction({kind:'host',name:'review_material',params:{}}));
  assert.equal(validateAction({kind:'host',name:'open_calendar',params:{}}).name,'open_calendar');
  assert.throws(()=>validateAction({kind:'constructor'}));assert.equal(validateNode({id:'bad',type:'constructor'}).type,'Unknown');
  assert.equal(safeUrl('javascript:alert(1)'),null);assert.equal(safeUrl('https://whu.edu.cn.evil.test'),null);assert.equal(safeUrl('https://www.whu.edu.cn/path'),'https://www.whu.edu.cn/path');
});
test('plain fenced code is never interpreted as a UI block',()=>{
  const raw='```text\n```genui\n'+JSON.stringify(begin)+'\n```\n';assert.equal(parseMessage(raw).filter(p=>p.kind==='ui').length,0);
  const bad=parseMessage(wrap([{op:'begin',v:9},node(),end]));assert.ok(bad[1].spec.errors.some(e=>e.code==='unsupported_version'));
});

test('verified public source buttons open the exact page without trusting an entire host',()=>{
  const source='https://www.news.cn/tech/20250827/report.html';
  const policy={resources:[source],origin:'http://127.0.0.1:8879'};
  assert.equal(safeActionUrl(source,policy),source);
  assert.equal(safeActionUrl(source),null);
  for(const changed of [source+'?redirect=evil',source+'/different','https://www.news.cn/other','https://www.news.cn.evil.test/tech','javascript:alert(1)','https://user:secret@www.news.cn/tech/20250827/report.html'])assert.equal(safeActionUrl(changed,policy),null);
  assert.equal(safeActionUrl('javascript:alert(1)',{resources:['javascript:alert(1)']}),null);
  assert.equal(safeActionUrl('https://www.whu.edu.cn/'), 'https://www.whu.edu.cn/');
});
