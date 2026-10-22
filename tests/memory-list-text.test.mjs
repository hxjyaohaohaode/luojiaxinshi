import test from 'node:test';
import assert from 'node:assert/strict';
import {memoryListText,memoryTimestamp} from '../static/memory-list-text.js';

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

test('memory dates use the campus day across the UTC midnight boundary',()=>{
 assert.equal(memoryTimestamp(Date.parse('2026-10-22T15:59:59Z')/1000),'2026/10/22');
 assert.equal(memoryTimestamp(Date.parse('2026-10-22T16:00:00Z')/1000),'2026/10/23');
 assert.equal(memoryTimestamp(Date.parse('2026-10-22T16:30:00Z')/1000,true),'2026/10/23 00:30:00');
});
test('memory dates never expose invalid timestamps as visible text',()=>{
 for(const value of [null,undefined,'',false,true,NaN,Infinity,'unknown',1e30])assert.equal(memoryTimestamp(value),'');
});
test('memory dates accept epoch seconds and do not treat zero as missing',()=>{
 assert.equal(memoryTimestamp(0),'1970/01/01');
 assert.equal(memoryTimestamp(String(Date.parse('2026-10-22T16:30:00Z')/1000)),'2026/10/23');
});
