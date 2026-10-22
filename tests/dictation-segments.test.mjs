import test from 'node:test';
import assert from 'node:assert/strict';
import {SpeechSegments,appendTranscript} from '../static/dictation-segments.js';
test('recording segments contain every voiced sample once, including the final tail',()=>{
  const parts=[],segmenter=new SpeechSegments(1000,x=>parts.push(x));
  for(let i=0;i<65;i++)segmenter.push(new Float32Array(100).fill(.2));
  segmenter.flush();segmenter.flush();
  assert.deepEqual(parts.map(p=>p.length),[6000,500]);
  assert.equal(parts.flatMap(p=>[...p]).length,6500);
});
test('silence does not trigger paid transcription and a pause flushes voiced audio',()=>{
  const parts=[],segmenter=new SpeechSegments(1000,x=>parts.push(x));
  for(let i=0;i<70;i++)segmenter.push(new Float32Array(100));
  assert.equal(parts.length,0);
  for(let i=0;i<10;i++)segmenter.push(new Float32Array(100).fill(.2));
  for(let i=0;i<7;i++)segmenter.push(new Float32Array(100));
  assert.equal(parts.length,1);
});
test('late transcription preserves typed edits and selection; limits never erase existing text',()=>{
  const input={value:'手工补充',selectionStart:1,selectionEnd:2,maxLength:30,dispatchEvent(){},setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}};
  appendTranscript(input,'转写内容');
  assert.equal(input.value,'手工补充\n转写内容');assert.equal(input.selectionStart,1);
  assert.throws(()=>appendTranscript(input,'长'.repeat(100)),/上限/);
  assert.equal(input.value,'手工补充\n转写内容');
});
