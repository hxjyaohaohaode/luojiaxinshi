import test from 'node:test';
import assert from 'node:assert/strict';
import {memoryListText} from '../static/memory-list-text.js';

test('memory list separates a complete opening sentence from its continuation',()=>{
 const content='办理记录：核对课程材料。当前状态：待办理。本人办理进度：准备中。';
 const excerpt=memoryListText(content);
 assert.equal(excerpt.title,'办理记录：核对课程材料。');
 assert.equal(excerpt.title+excerpt.preview,content);
});
test('memory list respects a first-line summary without dropping the first bullet',()=>{
 assert.deepEqual(memoryListText('待办与计划概览：\r\n• 准备材料\n• 提交申请'),{title:'待办与计划概览：',preview:'• 准备材料\n• 提交申请'});
});
test('long unbroken memory keeps the original preview, including text beyond a clipped title',()=>{
 const content='甲'.repeat(100)+'不能遗漏的条件';
 const excerpt=memoryListText(content);
 assert.ok(excerpt.title.endsWith('…'));
 assert.equal(excerpt.preview,content);
});
test('excerpt boundaries preserve supplementary unicode and short content',()=>{
 const excerpt=memoryListText('😀'.repeat(60));
 assert.equal([...excerpt.title].length,45);
 assert.equal(excerpt.preview,'😀'.repeat(60));
 assert.deepEqual(memoryListText('  下午回复  '),{title:'下午回复',preview:''});
 assert.deepEqual(memoryListText(null),{title:'',preview:''});
});
