import test from 'node:test';
import assert from 'node:assert/strict';
import {branchPreview} from '../static/branch-preview.js';

test('a branch preview owns an independent cutoff without persisting or altering the origin',()=>{
 const origin={id:'parent',version:7,title:'原对话',sources:[{id:'source',name:'原件'}],messages:[{id:'u',role:'user',content:'原问题'},{id:'a',role:'assistant',status:'complete',content:'原回答',genui:{snapshots:{draft:'原值'}}},{id:'later',role:'user',content:'后续问题'}]};
 const draft=branchPreview(origin,'a','owner');
 assert.equal(draft.originId,'parent');assert.equal(draft.version,7);assert.equal(draft.owner,'owner');assert.equal(draft.messageId,'a');
 assert.equal(draft.preview.messages.length,2);assert.equal(draft.preview.title,'原对话 · 分支');
 draft.preview.messages[1].genui.snapshots.draft='分支临时选择';draft.preview.sources[0].name='分支名称';
 assert.equal(origin.messages[1].genui.snapshots.draft,'原值');assert.equal(origin.sources[0].name,'原件');assert.equal(origin.messages.length,3);
});
test('a branch cannot silently target another answer, a user message or a running turn',()=>{
 const origin={messages:[{id:'u',role:'user',status:'complete'},{id:'a',role:'assistant',status:'processing'}]};
 for(const id of ['missing','u','a'])assert.throws(()=>branchPreview(origin,id,'owner'));
 assert.throws(()=>branchPreview({processing:true,messages:[{id:'a',role:'assistant',status:'complete'}]},'a','owner'));
});
