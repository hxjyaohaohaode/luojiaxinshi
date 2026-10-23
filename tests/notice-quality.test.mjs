import test from 'node:test';
import assert from 'node:assert/strict';
import {qualityPanel,needsQualityResolution} from '../static/notice-quality.js';
import {initializeDraftPlans,plainTask} from '../static/action-plans.js';
const esc=v=>String(v??'').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');

test('findings follow original steps after reorder, not new manual steps',()=>{
  const original=initializeDraftPlans([{title:'甲',origin:'ai'},{title:'乙',origin:'ai'}]);
  const manual=initializeDraftPlans([{title:'手工',origin:'manual'}])[0];
  const tasks=[original[1],manual,original[0]];
  const html=qualityPanel({status:'needs_review',issues:[{task_index:0,message:'<script>bad</script>',evidence:[]},{task_index:null,message:'漏项',evidence:[]}]},tasks,'本人说明',esc);
  assert.match(html,/意见 1 · 甲/);assert.match(html,/data-source-index="0"/);
  assert.match(html,/意见 2 · 整体或漏项/);assert.equal((html.match(/data-action="quality-step"/g)||[]).length,1);
  assert.ok(!html.includes('<script>'));assert.ok(html.includes('本人说明'));
  assert.equal(manual._source_index,null);assert.ok(!('_source_index' in plainTask(original[0])));
});
test('unavailable review needs an explanation and never looks like success',()=>{
  assert.ok(needsQualityResolution({status:'unavailable'}));assert.ok(needsQualityResolution({status:'needs_review'}));
  assert.ok(!needsQualityResolution({status:'passed'}));
  assert.match(qualityPanel({status:'unavailable',reason:'本次未完成'},[],'',esc),/minlength="8"/);
  assert.match(qualityPanel({status:'passed',issues:[]},[],'',esc),/确认没问题再保存/);
  assert.match(qualityPanel(null,[],'',esc),/还没让 AI 自查/);
});
test('retained provider finding uses student terms without changing its original evidence',()=>{
  const quote='plan.action_kind=required';
  const html=qualityPanel({status:'needs_review',issues:[{task_index:null,message:'草稿列为 plan.action_kind=required 的本人事项',evidence:[{source_id:'a',locator:'第1段',quote}]}]},[],'',esc);
  assert.match(html,/草稿列为“必办”的本人事项|草稿列为 “必办” 的本人事项/);
  assert.equal((html.match(/plan.action_kind=required/g)||[]).length,1);
});
test('source coverage keeps its original provenance and fallible attribution',()=>{
  const html=qualityPanel({status:'needs_review',source_checks:[{name:'附件<一>',coverage:'gaps',requirements_summary:'原文要求交付应用',evidence:[{source_id:'source-b',locator:'第8段',quote:'提交手机应用'}]}],issues:[]},[],'',esc);
  assert.match(html,/每份原文的核对情况 · 1 份/);assert.match(html,/AI 提示可能有遗漏/);
  assert.match(html,/附件&lt;一&gt;/);assert.match(html,/data-source="source-b"/);assert.match(html,/提交手机应用/);
});
