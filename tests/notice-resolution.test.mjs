import test from 'node:test';
import assert from 'node:assert/strict';
import {initializeDraftPlans} from '../static/action-plans.js';
import {prepareQualityConfirmation,qualityReceipt} from '../static/notice-resolution.js';
import {qualityPanel} from '../static/notice-quality.js';
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const notice={quality_resolution_contract:1,draft:{quality:{status:'needs_review',issues:[{task_index:0,code:'procedure',message:'原文没有该手续。',evidence:[]}]}}};

test('unselected finding is recorded without redundant typing and reselection needs an explicit decision',()=>{
 const tasks=initializeDraftPlans([{origin:'ai',title:'不应申请',include:false},{origin:'ai',title:'需要办理',include:true}]);
 assert.deepEqual(prepareQualityConfirmation(tasks,notice,{}).issue_resolutions,[{issue_index:0,action:'excluded',note:'',task_indices:[]}]);
 tasks[0].include=true;
 assert.throws(()=>prepareQualityConfirmation(tasks,notice,{}),/意见 1/);
});
test('correction follows original identity through reorder while targets refer to selected positions',()=>{
 const tasks=initializeDraftPlans([{origin:'ai',title:'甲',include:true},{origin:'ai',title:'乙',include:true}]);
 const result=prepareQualityConfirmation([tasks[1],tasks[0]],notice,{0:{action:'changed',note:''}});
 assert.deepEqual(result.source_indices,[1,0]);assert.deepEqual(result.issue_resolutions[0].task_indices,[1]);
});
test('global omission can link a new manual step and loses that link if it is excluded',()=>{
 const n={quality_resolution_contract:1,draft:{quality:{status:'needs_review',issues:[{task_index:null,code:'omission'}]}}};
 const task=initializeDraftPlans([{origin:'manual',title:'补充交付物',include:true}])[0],decision={0:{action:'changed',task_key:task._plan_id}};
 assert.deepEqual(prepareQualityConfirmation([task],n,decision).source_indices,[null]);
 task.include=false;assert.throws(()=>prepareQualityConfirmation([task],n,decision),/关联步骤未选中/);
});
test('legacy server receives no new fields and saved blanket note remains available but does not waive issues',()=>{
 assert.deepEqual(prepareQualityConfirmation([],{draft:notice.draft},{},true),{});
 const html=qualityPanel(notice.draft.quality,[],'之前已经写下的核实说明',esc,{structured:true,decisions:{}});
 assert.match(html,/之前暂存的总说明/);assert.match(html,/type="hidden" name="quality_resolution"/);
 assert.match(html,/data-quality-decision="0"/);
});
test('receipt retains original opinion and human note with escaped text and source links',()=>{
 const html=qualityReceipt({version:1,issues:[{action:'disagreed',note:'<script>危险</script>',task_titles:[],finding:{message:'原始意见',evidence:[{source_id:'s',locator:'第1段',quote:'原句'}]}}]},esc);
 assert.match(html,/原始意见/);assert.match(html,/&lt;script&gt;/);assert.ok(!html.includes('<script>'));
 assert.match(html,/data-source="s"/);assert.match(html,/不表示模型或学校已经核准/);
});
test('imported receipt remains historical and missing sources have no dead cross-account link',()=>{
 const html=qualityReceipt({version:1,imported:true,issues:[{action:'excluded',finding:{message:'保留原意见',evidence:[{source_id:'',locator:'第1段',quote:'保留引句'}]}}]},esc);
 assert.match(html,/未对当前材料重新核实/);assert.match(html,/原件未导入/);assert.match(html,/保留引句/);
 assert.ok(!html.includes('data-action="evidence"'));
});
