import test from 'node:test';
import assert from 'node:assert/strict';
import {currentHandlingStep,handlingGuide} from '../static/handling-route.js';
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const task=()=>({id:'task',notice_id:'notice',status:'pending',data:{title:'提交申请',materials:['申请表'],submission:'学院办公室'},pending_changes:[],workflow:{data:{stage:'preparing',action_kind:'required',dependencies:[]}}});

test('a due follow-up cannot bypass changed requirements or an unfinished prerequisite',()=>{
 const value=task();value.followup_due=true;value.workflow.data.next_step='提交申请';value.workflow.blocked=true;
 assert.equal(currentHandlingStep(value).kind,'prerequisites');
 value.pending_changes=[{id:'change'}];assert.equal(currentHandlingStep(value).kind,'changes');
 for(const status of ['done','cancelled']){value.status=status;assert.equal(currentHandlingStep(value).kind,'closed');}
});

test('unverified changes offer the actual versioned change record',()=>{
 const value=task();value.pending_changes=[{id:'change'}];const html=handlingGuide(value,{esc});
 assert.ok(html.includes('data-change-open="change"')&&html.includes('data-notice-id="notice"'));
 assert.ok(html.includes('核对这条变动'));
});

test('the any-prerequisite rule never asks for an unnecessary sibling',()=>{
 const value=task();value.workflow.blocked=true;Object.assign(value.workflow.data,{dependencies:['one','two'],dependency_mode:'any'});
 const candidates=[{id:'one',title:'已完成签字',status:'done'},{id:'two',title:'另一种证明',status:'pending'}];
 const any=handlingGuide(value,{esc,candidates});assert.ok(!any.includes('data-workflow-task='));
 value.workflow.data.dependency_mode='all';const all=handlingGuide(value,{esc,candidates});
 assert.ok(all.includes('data-workflow-task="two"')&&!all.includes('data-workflow-task="one"'));
});

test('preparing and optional participation provide in-place actionable destinations',()=>{
 const value=task();assert.ok(handlingGuide(value,{esc}).includes('data-workflow-focus="materials"'));
 value.workflow.data.action_kind='optional';assert.ok(handlingGuide(value,{esc}).includes('data-workflow-focus="choice"'));
 value.workflow.data.participation='joined';assert.equal(currentHandlingStep(value).kind,'materials');
});

test('completed prerequisites do not silently erase a separately recorded obstacle',()=>{
 const value=task();Object.assign(value.workflow.data,{stage:'blocked',outcome:'签字环节尚未完成',next_step:'查询结果'});value.followup_due=true;
 assert.equal(currentHandlingStep(value).kind,'blocked');
 const html=handlingGuide(value,{esc});assert.ok(html.includes('更新阻碍与办理进度')&&!html.includes('到时间跟进了'));
});

test('blocked channel links remain readable without claiming submission readiness',()=>{
 const value=task();value.workflow.blocked=true;value.data.submission='https://example.edu/apply';
 const html=handlingGuide(value,{esc});assert.ok(html.includes('查看原通知中的渠道')&&!html.includes('前往办理入口'));
 const escaped=handlingGuide({...value,pending_changes:[{id:'<script>"'}]},{esc});assert.ok(!escaped.includes('<script>'));
});

test('current server projection is used by the guide and declined participation stays explicit',()=>{
 const value=task();value.handling_state={kind:'followup',label:'到时间跟进了',detail:'核对原渠道回执'};
 assert.deepEqual(currentHandlingStep(value),value.handling_state);
 assert.ok(handlingGuide(value,{esc}).includes('data-workflow-focus="followup"'));
 delete value.handling_state;Object.assign(value.workflow.data,{action_kind:'optional',participation:'declined'});
 assert.equal(currentHandlingStep(value).label,'已选择不参加');
});
