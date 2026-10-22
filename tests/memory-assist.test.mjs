import test from 'node:test';
import assert from 'node:assert/strict';
import {characterRange} from '../static/memory-assist.js';
test('selected UTF-16 text converts to exact API character offsets',()=>{
  assert.deepEqual(characterRange('😀中文👩‍💻尾',2,4),[1,3]);
  assert.deepEqual(characterRange('😀中文👩‍💻尾',4,9),[3,6]);
  assert.deepEqual(characterRange('abc',0,3),[0,3]);
});
