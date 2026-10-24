import test from 'node:test';
import assert from 'node:assert/strict';
import {readableSnapshot,recordPreviewKind} from '../static/record-preview.js';
test('profile and memory records show meaningful values without internal keys',()=>{
 const profile=readableSnapshot(JSON.stringify({campus_role:'student',school:'武汉大学',major:'软件工程',level:'硕士',response_style:'academic',version:2}),'profile');
 for(const text of ['学生','武汉大学','软件工程','硕士','严谨规范'])assert.ok(profile.includes(text));
 for(const text of ['campus_role','response_style','version'])assert.ok(!profile.includes(text));
 assert.equal(readableSnapshot('{"content":"请先给结论","internal_id":"secret"}','memory'),'内容：请先给结论');
 assert.ok(!readableSnapshot('{"internal_id":"secret"}','memory').includes('internal_id'));
});
test('full material previews recognize application snapshots but preserve user JSON originals',()=>{
 const snapshot=JSON.stringify({record_type:'用户确认的待办记录，期限是否已核实以 deadline_confirmed 为准',values:{title:'申请奖学金',scheduled:{start_date:'2026-10-24',start_time:'09:00',confirmed:false}},version:4,workflow:{data:{stage:'waiting',outcome:'accepted'}}});
 assert.equal(recordPreviewKind(snapshot,'text'),'task');
 const rendered=readableSnapshot(snapshot,'text',{multiline:true});
 for(const value of ['事项：申请奖学金','活动开始：2026-10-24 09:00','活动时间待核实','办理进度：等待中','办理结果：已受理'])assert.ok(rendered.includes(value));
 assert.ok(rendered.includes('\n'));assert.ok(!rendered.includes('record_type'));assert.ok(!rendered.includes('version'));
 const userFile='{"record_type":"experiment","values":{"temperature":22},"version":3}';
 assert.equal(readableSnapshot(userFile,'json'),userFile);
 assert.equal(readableSnapshot('材料中含有 { 字符','text'),'材料中含有 { 字符');
});
test('incomplete record citations never expose partial protocol fields',()=>{
 for(const quote of ['{"values":','"deadline_confirmed":false,','[]','null'])assert.ok(!/[{}]|deadline_confirmed/.test(readableSnapshot(quote,'task')));
});
test('calendar query and saved operation receipts hide database fields in all citation views',()=>{
 const query=JSON.stringify({kind:'task',id:'private-record',notice_id:'notice-id',status:'pending',version:3,exported_version:2,created_at:123,updated_at:124,data:{title:'提交课程作业',due_date:'2026-10-30',deadline_confirmed:true}});
 const receipt=JSON.stringify({operation_id:'internal',status:'committed',operation:'task_create',target_id:'private-record',record:{data:{title:'提交课程作业',notes:'需附实验报告'}},undo_available:true,destination:'database',replayed:false});
 for(const raw of [query,receipt]){const rendered=readableSnapshot(raw,'execution');assert.ok(rendered.includes('提交课程作业'));assert.ok(!/notice_id|private-record|version|operation_id|database|created_at/.test(rendered));}
 assert.equal(readableSnapshot('{"deadline_text":"下周五前"}','execution'),'期限说明：下周五前');
 assert.equal(readableSnapshot('{"notes":"需附实验报告"}','execution'),'备注：需附实验报告');
});
