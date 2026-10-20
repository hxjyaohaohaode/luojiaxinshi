import test from 'node:test';
import assert from 'node:assert/strict';
import {selectNoticeFiles,formatFileSize} from '../static/notice-files.js';

const file=(name,size=12,lastModified=1)=>({name,size,lastModified});
test('attachment additions retain earlier selections and ignore identical files',()=>{
  const first=file('原文.PDF'),second=file('附件.xlsx');
  const previous=[first];
  const result=selectNoticeFiles(previous,[first,second]);
  assert.deepEqual(result.files,[first,second]);assert.equal(result.duplicates,1);
  assert.deepEqual(previous,[first]);assert.equal(result.error,'');
  // A revised attachment with the same name must not be silently discarded.
  assert.equal(selectNoticeFiles(previous,[file('原文.PDF',12,2)]).files.length,2);
});
test('invalid batches preserve the full earlier queue without partial acceptance',()=>{
  const previous=[file('已选.txt')];
  for(const incoming of [[file('有效.pdf'),file('不支持.exe')],[file('巨大.png',5*1024*1024+1)],[file('README')]]){
    const result=selectNoticeFiles(previous,incoming);
    assert.ok(result.error);assert.deepEqual(result.files,previous);
  }
  assert.equal(selectNoticeFiles(previous,[file('恰好.pdf',5*1024*1024)]).error,'');
});
test('attachment count is checked after deduplication; an empty batch is stable',()=>{
  const previous=Array.from({length:5},(_,i)=>file(`材料${i}.txt`));
  assert.equal(selectNoticeFiles(previous,[previous[0]]).error,'');
  assert.match(selectNoticeFiles(previous,[file('第六份.txt')]).error,/5/);
  assert.deepEqual(selectNoticeFiles(previous,[]).files,previous);
  assert.deepEqual(selectNoticeFiles([],[]).files,[]);
  assert.equal(formatFileSize(0),'0 B');assert.equal(formatFileSize(1024),'1 KB');
  assert.equal(formatFileSize(5*1024*1024),'5.0 MB');
});
