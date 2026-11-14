import test from 'node:test';
import assert from 'node:assert/strict';
import {followupIso,followupLocalTime} from '../static/collaboration-followup.js';
import {renderCampusDeliveryEvidence} from '../static/campus-delivery-evidence.js';

test('personal follow-up controls round-trip explicit Beijing time without local machine assumptions',()=>{
  assert.equal(followupLocalTime('2027-01-02T00:30:00Z'),'2027-01-02T08:30');
  assert.equal(followupIso('2027-01-02T08:30'),'2027-01-02T00:30:00.000Z');
  for(const invalid of ['','2027-02-30T08:30','2027-01-01','2027-01-02T25:30'])assert.throws(()=>followupIso(invalid));
});
test('channel evidence keeps unobserved opening and explicit acknowledgement unknown',()=>{
  const esc=value=>String(value).replaceAll('<','&lt;');
  const html=renderCampusDeliveryEvidence({channels:{push:{accepted_events:2,accepted_recipients:1,states:{accepted:{events:2,recipients:1}}}},opened:{count:null,note:'<未测>'},explicit_receipt:{count:null},note:'供应商接受不表示本人打开'},esc);
  assert.match(html,/接受 2 次，涉及 1 人/);assert.match(html,/未知/);assert.match(html,/&lt;未测>/);
  assert.doesNotMatch(html,/已读 2/);
});
