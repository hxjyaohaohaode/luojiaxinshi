import test from 'node:test';
import assert from 'node:assert/strict';
import {batchEntry,prepareEntry,noticeState,isNoticeOpen} from '../static/notice-intake.js';
import {stageOptions,workflowStage} from '../static/workflow-kinds.js';
import {filterNotices} from '../static/library.js';

test('informational notices leave pending filters without manufacturing a task',()=>{
  const a={id:'a',title:'开放时间',source_label:'图书馆',status:'received',disposition:'reference',created_at:1};
  const b={...a,id:'b',disposition:'inbox'};
  assert.equal(isNoticeOpen(a),false);assert.equal(noticeState(a)[0],'仅存资料');
  assert.deepEqual(filterNotices([a,b],{status:'received'}).map(n=>n.id),['b']);
  assert.deepEqual(filterNotices([a,b],{status:'reference'}).map(n=>n.id),['a']);
});
test('every batch entry owns its submission identity and exact materials',()=>{
  const a={...batchEntry(),title:'讲座',link_preview:'preview-one'},b=batchEntry();
  assert.notEqual(a.request_id,b.request_id);
  const form=prepareEntry(a,[],value=>value||null);
  assert.equal(form.get('link_preview'),'preview-one');assert.equal(form.get('request_id'),a.request_id);
  assert.equal(form.has('target'),false);assert.equal(form.get('materials_complete'),'false');
  assert.throws(()=>prepareEntry({...a,files:['原件.pdf']},[],x=>x),/重新选择/);
});
test('reading, attendance and custom progress do not masquerade as submissions',()=>{
  assert.equal(stageOptions('reading').recorded,'已阅读');assert.equal(stageOptions('attendance').recorded,'已参加');
  assert.equal(stageOptions('reading').submitted,undefined);
  assert.equal(stageOptions('reading','submitted').submitted,'已提交，等结果');
  assert.equal(workflowStage({execution_mode:'custom',stage:'active',phase_label:'等老师确认'}),'等老师确认');
});
