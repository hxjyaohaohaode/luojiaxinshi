import test from 'node:test';
import assert from 'node:assert/strict';
import {mathTree} from '../static/genui/math.js';
import {parseMessage,blockMarkdown} from '../static/genui/core.js';
import {SAMPLES} from '../static/genui/fixtures.js';
test('math presentation supports fractions roots and indices without execution',()=>{
  const tree=mathTree(String.raw`y=\frac{x_{1}^{2}}{\sqrt{4}}`);
  const raw=JSON.stringify(tree);for(const tag of ['mfrac','msqrt','msubsup'])assert.ok(raw.includes(tag));
  assert.throws(()=>mathTree('{'.repeat(20)+'x'+'}'.repeat(20)));assert.throws(()=>mathTree('x^'));
  assert.throws(()=>mathTree('x'.repeat(2001)));assert.ok(JSON.stringify(mathTree('<script>')).includes('script'));
});
test('all gallery components export readable equivalent text',()=>{
  for(const [name,ops]of Object.entries(SAMPLES)){
    const raw='```genui\n'+ops.map(op=>JSON.stringify(op)).join('\n')+'\n```';
    const spec=parseMessage(raw)[0].spec;assert.ok(blockMarkdown(spec).length>0,name);
  }
});
