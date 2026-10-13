import test from 'node:test';
import assert from 'node:assert/strict';
import {samplePlot} from '../static/genui/plot.js';
import {validateNode} from '../static/genui/core.js';
const props={expression:'a*pow(x,2)+b',parameters:{a:2,b:1},xMin:-2,xMax:2,samples:81};
test('plot computes a bounded curve and linked parameters deterministically',()=>{
  const a=samplePlot(props),b=samplePlot({...props,parameters:{a:1,b:0}});
  assert.equal(a.length,81);assert.equal(a[0].y,9);assert.equal(a[40].y,1);assert.equal(b[0].y,4);
});
test('plot rejects unsafe expressions, variables, domains and excessive sampling',()=>{
  for(const change of [{expression:'window.alert(1)'},{expression:'constructor(x)'},{expression:'1/0'},
    {expression:'"not a number"'},{samples:121},{xMax:-2},{parameters:{x:3}},{parameters:{a:NaN}},{expression:'pow(10,300)'}])
    assert.throws(()=>samplePlot({...props,...change}));
  assert.throws(()=>validateNode({id:'plot',type:'Plot',props:{...props,expression:'fetch(x)'}}));
});
