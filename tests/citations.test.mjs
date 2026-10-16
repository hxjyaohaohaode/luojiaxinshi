import test from 'node:test';
import assert from 'node:assert/strict';
import {citationEntries,citationPreview} from '../static/genui/citations.js';
import {elapsedLabel} from '../static/genui/work-view.js';
test('source panel groups repeated citations without changing inline numbering',()=>{
  const message={citations:[{source_id:'web',quote:'first',locator:'段1'},{source_id:'user',quote:'hours',locator:'问题1'},{source_id:'web',quote:'second',locator:'段2'}],evidence_sources:[{id:'web',name:'官网',url:'https://www.whu.edu.cn',evidence_kind:'web_page'},{id:'user',name:'你提供的条件'},{id:'uncited',name:'其他检索结果',url:'https://uc.whu.edu.cn',evidence_kind:'web_page'}]};
  const entries=citationEntries(message);assert.equal(entries.length,3);assert.deepEqual(entries[0].quotes.map(q=>q.number),[1,3]);assert.equal(entries[1].quotes[0].number,2);assert.equal(entries[2].quotes.length,0);
  assert.equal(citationEntries({citations:[{source_id:'removed',quote:'saved'}]})[0].quotes[0].quote,'saved');
  assert.equal(citationEntries({evidence_sources:[{id:'private',name:'本地文件',evidence_kind:'material'}]}).length,0);
});
test('elapsed work time uses actual timestamps and never goes negative',()=>{assert.equal(elapsedLabel(100,161),'1分1秒');assert.equal(elapsedLabel(100,99),'0秒');});

test('focused citations show their own exact span instead of unrelated page navigation',()=>{
  const long='国务院日前印发相关文件；这是一段实际登记的正文摘录，用于核对来源与回答之间的支持关系，保留原文限定条件。';
  const entry={source:{preview:'首页 设为首页 加入收藏 网站导航'},quotes:[{number:1,quote:'国发〔2025〕11号'},{number:3,quote:'Produced By CMS 网站群内容管理系统 publishdate:2026/08/28 16:12:40'},{number:2,quote:long}]};
  assert.equal(citationPreview(entry,1),'国发〔2025〕11号');
  assert.equal(citationPreview(entry),long);
  assert.equal(citationPreview({source:{preview:'已读取但未引用的正文摘要'},quotes:[]}),'已读取但未引用的正文摘要');
  const user={source:{evidence_kind:'user_input'},quotes:[{number:1,quote:'原始用户问题与界面协议'}]};
  assert.equal(citationPreview(user),'本次提问与已提交的界面选择；展开引用原文可核对当时内容。');
  assert.equal(citationPreview(user,1),'原始用户问题与界面协议');
});
