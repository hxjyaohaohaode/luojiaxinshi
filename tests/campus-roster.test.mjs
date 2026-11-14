import test from 'node:test';
import assert from 'node:assert/strict';
import {parseRosterInput} from '../static/campus-roster.js';

test('roster parser preserves explicit grade and class for server preflight',()=>{
  assert.deepEqual(parseRosterInput('账号\t角色\t年级\t班级\nstudent-01\t学生\t2026\t一班'),[
    {username:'student-01',role:'student',grade:'2026',class_name:'一班'}]);
  assert.equal(parseRosterInput('账号,角色,年级,班级\n"student-02",学生,一年级,一班')[0].grade,'一年级');
});
test('roster parser supports quoted CSV and explicit counselor scopes',()=>{
  assert.deepEqual(parseRosterInput('账号,角色,年级,班级,负责范围\n"counselor",辅导员,,,"2026级 / 一班;2027级"'),[
    {username:'counselor',role:'counselor',grade:'',class_name:'',scopes:[{grade:'2026级',class_name:'一班'},{grade:'2027级',class_name:''}]}]);
  assert.equal(parseRosterInput('账号,角色,年级,班级\n"name""quoted",学生,2026级,"一,班"')[0].class_name,'一,班');
});
test('roster parsing rejects silent column shifts, duplicate headers, and malformed scopes',()=>{
  for(const text of ['账号,角色\na,学生,多一列','账号,账号\na,a','账号,角色\n"unclosed,学生',
      '账号,角色,负责范围\na,辅导员,2026级 / / 一班'])assert.throws(()=>parseRosterInput(text));
  assert.throws(()=>parseRosterInput('账号,角色\n'+Array.from({length:501},(_,i)=>`a${i},学生`).join('\n')),/500/);
});
test('JSON remains data with server-side row validation',()=>{
  assert.deepEqual(parseRosterInput('[{"username":"one","role":"student","grade":"2026级","class_name":"一班"}]'),[
    {username:'one',role:'student',grade:'2026级',class_name:'一班'}]);
  assert.throws(()=>parseRosterInput('[null]'));
});
