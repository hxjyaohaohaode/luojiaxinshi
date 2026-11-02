import test from 'node:test';
import assert from 'node:assert/strict';
import {filterNotices,noticeOrigins,publicationDay,sortNotices,sourceOverview,sourceHealthSummary} from '../static/library.js';

test('a merged notice is discoverable from each of its own sources',()=>{
  const notices=[
    {id:'merged',title:'奖学金',source_label:'学院官网',origin_labels:['学院官网','班级群','学院官网']},
    {id:'school',title:'图书馆',source_label:'学校官网'},
    {id:'personal',title:'个人记录',source_label:''}
  ];
  assert.deepEqual(noticeOrigins(notices[0]),['学院官网','班级群']);
  assert.deepEqual(filterNotices(notices,{source:'班级群'}).map(n=>n.id),['merged']);
  assert.deepEqual(filterNotices(notices,{source:'学校官网'}).map(n=>n.id),['school']);
  assert.deepEqual(filterNotices(notices,{source:'个人提交'}).map(n=>n.id),['personal']);
  assert.deepEqual(filterNotices(notices,{query:'班级群'}).map(n=>n.id),['merged']);
});

test('publication order keeps unknown dates explicit and offers receipt order',()=>{
  const notices=[
    {id:'unknown',published_at:null,created_at:300,updated_at:301},
    {id:'older',published_at:'2026-10-01',created_at:200,updated_at:201},
    {id:'newer',published_at:'2026-10-25',created_at:100,updated_at:101},
    {id:'invalid',published_at:'2026-02-30',created_at:50,updated_at:51}
  ];
  assert.deepEqual(sortNotices(notices).map(n=>n.id),['newer','older','unknown','invalid']);
  assert.deepEqual(sortNotices(notices,'collected').map(n=>n.id),['unknown','older','newer','invalid']);
  assert.equal(publicationDay('2026-10-25'),'2026-10-25');
  assert.equal(publicationDay('2026-10-19T16:30:00Z'),'2026-10-20');
  assert.equal(publicationDay('2026-02-30'),'');
  assert.equal(publicationDay('2026-10-25T12:00:00'),'');
  assert.deepEqual(notices.map(n=>n.id),['unknown','older','newer','invalid']);
});

test('website source status distinguishes failed, paused and manual subscriptions',()=>{
  const catalog=[
    {id:'school',data:{name:'学校官网',platform:'website'}},
    {id:'college',data:{name:'学院官网',platform:'website'}},
    {id:'manual',data:{name:'其他网站',platform:'website'}},
    {id:'group',data:{name:'班级群',platform:'qq_group'}}
  ];
  const rows=sourceOverview(catalog,[{source_id:'school',state:'paused',enabled:false,checked_at:10},
    {source_id:'college',state:'error',enabled:true,checked_at:20,pending_count:2}]);
  assert.deepEqual(rows.map(r=>[r.id,r.state]),[['college','error'],['school','paused'],['manual','manual']]);
  assert.equal(rows[0].pending_count,2);
  assert.deepEqual(rows.filter(r=>r.enabled).map(r=>r.id),['college']);
  assert.equal(sourceHealthSummary(rows),'已开启 1 个网站 · 1 个检查未完成 · 1 个已暂停 · 查看详情');
  assert.equal(sourceHealthSummary([]),'尚未添加网站来源 · 查看详情');
  assert.match(sourceHealthSummary([{enabled:true,state:'syncing',pending_count:1}]),/1 个仍在读取或等待/);
});
