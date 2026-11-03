import test from 'node:test';
import assert from 'node:assert/strict';
import {parseNotificationTerms,evidenceChainMarkup} from '../static/proactive-notifications.js';
test('notification terms retain complete phrases and separate Chinese punctuation',()=>{
  assert.deepEqual(parseNotificationTerms('助学金、课程项目，GIS;GIS\n实习；  学术交流  '),['助学金','课程项目','GIS','实习','学术交流']);
  assert.deepEqual(parseNotificationTerms('   '),[]);
  assert.deepEqual(parseNotificationTerms('machine learning,学生权益'),['machine learning','学生权益']);
});
test('evidence chain labels actual candidates and rejects executable URLs',()=>{
  const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const html=evidenceChainMarkup({documents:[{name:'<script>伪造标题</script>',active:true,sha256:'1234567890abcdef',
    origin:{url:'javascript:alert(1)',relationship:'index_candidate',retrieved_at:123,related_search:{errors:[{error:'暂不可读'}]}},missing_attachments:['one']}],
    related_notices:[{id:'../notice',title:'另一个候选'}]},esc);
  assert(html.includes('关联候选')&&html.includes('仍有 1 份附件')&&html.includes('暂不可读'));
  assert(!html.includes('href="javascript:')&&!html.includes('<script>')&&html.includes('&lt;script&gt;'));
});
