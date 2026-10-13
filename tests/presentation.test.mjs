import test from 'node:test';
import assert from 'node:assert/strict';
import {filterNotices} from '../static/library.js';
import {formatAnswer} from '../static/message-format.js';

test('notice search covers records beyond the first page and combines date/status/source filters',()=>{
  const items=Array.from({length:50},(_,i)=>({title:'通知'+i,source_label:i===41?'学院计划':'其他',status:i===41?'draft':'confirmed',created_at:Date.parse('2026-10-12T16:00:00Z')/1000}));
  assert.deepEqual(filterNotices(items,{query:'学院',status:'draft',from:'2026-10-13',to:'2026-10-13'}),[items[41]]);
  assert.equal(filterNotices(items,{to:'2026-10-12'}).length,0);
  assert.equal(filterNotices(items,{query:'通知49'}).length,1);
});
test('model formatting keeps headings, lists and code readable without rendering executable HTML or external media',()=>{
  const text='# 下一步\n- **核对**原文\n- `<script>alert(1)</script>`\n\n![pic](https://evil.example/a)\n```html\n<img src=x onerror=alert(1)>\n```';
  const html=formatAnswer(text);
  assert.match(html,/<h3>下一步<\/h3>/);assert.match(html,/<ul><li><strong>核对/);assert.match(html,/&lt;script&gt;/);assert.match(html,/<pre><code>&lt;img/);
  assert.doesNotMatch(html,/<script|<img|<iframe|<a\s/i);
});
