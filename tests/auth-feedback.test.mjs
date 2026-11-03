import test from 'node:test';
import assert from 'node:assert/strict';
import {passwordAssessment,passwordEditor} from '../static/auth-feedback.js';

test('password feedback enforces the exact registration limits and confirmation',()=>{
  assert.deepEqual(passwordAssessment(''),{min:false,max:false,match:false,strength:0,label:'未输入'});
  const weak=passwordAssessment('short','short');assert.equal(weak.min,false);assert.equal(weak.match,true);
  const accepted=passwordAssessment('Password-123','Password-123');assert.equal(accepted.min,true);assert.equal(accepted.max,true);assert.equal(accepted.match,true);
  assert.equal(passwordAssessment('a'.repeat(256)).max,true);
  assert.equal(passwordAssessment('a'.repeat(257)).max,false);
  assert.equal(passwordAssessment('Password-123','Password-124').match,false);
});

test('a strong indicator cannot make an overlong or mismatched password valid',()=>{
  const result=passwordAssessment('Very-Long-Unrelated-Phrase-2026!','Something-Different');
  assert.equal(result.strength,4);assert.equal(result.match,false);
  const over=passwordAssessment('A1!'.repeat(86));assert.equal(over.max,false);
});

test('the editor supplies accessible show controls and a separate confirmation input',()=>{
  const field=(label,name,value,type,attributes)=>`<label>${label}<input name="${name}" type="${type}" ${attributes}></label>`;
  const html=passwordEditor(field,{creating:true,confirm:true});
  assert.match(html,/aria-label="显示密码"/);assert.match(html,/name="confirm_password"/);
  assert.match(html,/maxlength="256"/);assert.match(html,/两次输入一致/);
});
