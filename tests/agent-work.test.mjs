import test from 'node:test';
import assert from 'node:assert/strict';
import {workHeadline} from '../static/genui/work-view.js';

test('work headline reports an actual verified conclusion instead of stage or tool counts',()=>{
  const message={status:'complete',grounding:{work_summary:{verified:true,highlights:['报名资格尚待确认'],tool_calls:3,cited_sources:['a']}}};
  assert.equal(workHeadline(message),'报名资格尚待确认');
  assert.equal(workHeadline({...message,status:'failed'}),'执行未完成');
  assert.equal(workHeadline({...message,status:'processing',_work:[{title:'读取申请表',state:'running'}]}),'读取申请表');
});

test('older saved receipts remain readable without invented highlights',()=>{
  assert.equal(workHeadline({status:'complete',grounding:{work_summary:{verified:true,tool_calls:2,cited_sources:['s']}}}),'引用 1 个来源 · 执行 2 次工具');
  assert.equal(workHeadline({status:'complete',grounding:{}}),'处理记录');
});
