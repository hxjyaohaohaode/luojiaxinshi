import test from 'node:test';
import assert from 'node:assert/strict';
import {searchRecords, highlightMatch} from '../static/command-search.js';

test('search ranks exact titles before prefixes and material matches, without mutating records', () => {
  const tasks = [
    {notice_id:'a',data:{title:'其他办理',materials:['申请']}},
    {notice_id:'b',data:{title:'准备申请材料'}},
    {notice_id:'c',data:{title:'申请材料'}},
    {notice_id:'d',data:{title:'申请'}},
  ];
  assert.deepEqual(searchRecords(tasks, [], '  申请 ').tasks.map(t => t.url), ['#notice/d','#notice/c','#notice/b','#notice/a']);
  assert.equal(tasks[0].rank, undefined);
  assert.equal(searchRecords(tasks, [], '不存在').tasks.length, 0);
});

test('search matches notice sources and task source titles, handles empty and incomplete records', () => {
  assert.equal(searchRecords([{notice_id:'a',notice_title:'学院申请'}], [], '学院').tasks.length, 1);
  assert.equal(searchRecords([], [{id:'b',title:'通知',source_label:'学院办公室'}], '学院').notices.length, 1);
  assert.deepEqual(searchRecords([], []), {tasks:[],notices:[]});
  assert.equal(searchRecords([{notice_id:'id/with space'}], []).tasks[0].url, '#notice/id%2Fwith%20space');
});

test('highlighting escapes markup in every segment and treats regex punctuation as text', () => {
  const esc = value => value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  assert.equal(highlightMatch('<img>申请<img>', '申请', esc), '&lt;img&gt;<mark>申请</mark>&lt;img&gt;');
  assert.equal(highlightMatch('A+B A+B', 'a+b', esc), '<mark>A+B</mark> <mark>A+B</mark>');
  assert.equal(highlightMatch('<img>', '<img>', esc), '<mark>&lt;img&gt;</mark>');
});
