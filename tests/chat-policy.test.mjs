import test from 'node:test';
import assert from 'node:assert/strict';
import {replyPolicy,timeGroups,TIME_GROUP_SECONDS} from '../static/genui/chat-policy.js';
import {reminderGroups} from '../static/reminders.js';
import {graphemes} from '../static/genui/stream-text.js';

const user=(id,at=1000)=>({id,role:'user',status:'complete',created_at:at});
const reply=(id,parent_id,status='complete')=>({id,parent_id,role:'assistant',status,content:'真实的回答'});
test('only the last user turn can regenerate; old answers remain useful for copy and branching',()=>{
  const old=reply('a1','u1'),last=reply('a2','u2'),messages=[user('u1'),old,user('u2'),last];
  const prior=replyPolicy(messages,old),latest=replyPolicy(messages,last);
  assert.equal(prior.regenerate,false);assert.equal(latest.regenerate,true);
  for(const action of ['copy','speak','branch','share','like'])assert.equal(prior[action],true,action);
  assert.equal(replyPolicy([...messages,user('u3')],last).regenerate,false,'a saved next question already makes the old answer historical');
});
test('in-flight, partial, branch-preview, and unavailable speech actions have distinct capabilities',()=>{
  const complete=reply('a1','u1'),pending=reply('a2','u2','processing'),messages=[user('u1'),complete,user('u2'),pending];
  const active=replyPolicy(messages,complete);assert.equal(active.copy,true);assert.equal(active.like,true);
  assert.equal(active.branch,false);assert.equal(active.regenerate,false);
  assert.equal(replyPolicy(messages,pending).copy,false);assert.equal(replyPolicy(messages,pending).share,false);
  const preview=replyPolicy(messages,complete,{readOnly:true,speech:false});assert.equal(preview.copy,true);assert.equal(preview.branch,false);assert.equal(preview.like,false);assert.equal(preview.speak,false);
});
test('retry belongs to the final attempt of the final question and a snapshot needs verified completion',()=>{
  const failed=reply('a1','u1','failed'),messages=[user('u1'),failed];
  assert.equal(replyPolicy(messages,failed).retry,true);
  assert.equal(replyPolicy([...messages,user('u2')],failed).retry,false);
  assert.equal(replyPolicy([...messages,reply('a2','u1')],failed).retry,false);
  assert.equal(replyPolicy([user('u1'),{...failed,versions:[failed,reply('a2','u1')]}],{...failed,versions:[failed,reply('a2','u1')]}).retry,false);
  assert.equal(replyPolicy(messages,failed,{busy:true}).retry,false);
  const done={...reply('a3','u1'),genui:{raw:'text',validated:false}};
  assert.equal(replyPolicy([user('u1'),done],done).save,false);done.genui.validated=true;
  assert.equal(replyPolicy([user('u1'),done],done).save,true);
});
test('time grouping uses first message, five minute gaps and local calendar day changes',()=>{
  const start=new Date(2026,9,27,9,0).getTime()/1000,now=new Date(2026,9,27,12);
  const groups=timeGroups([user('first',start),user('near',start+299),user('gap',start+299+TIME_GROUP_SECONDS)],now);
  assert.deepEqual([...groups.keys()],['first','gap']);assert.equal(groups.get('first').label,'09:00');
  const midnight=new Date(2026,9,27,0,0).getTime()/1000;
  const days=timeGroups([user('yesterday',midnight-20),user('today',midnight+5),user('invalid',NaN)],now);
  assert.deepEqual([...days.keys()],['yesterday','today']);assert.match(days.get('yesterday').label,/昨天/);
  assert.match(timeGroups([user('old',new Date(2025,9,27,9).getTime()/1000)],now).get('old').label,/2025年10月27日/);
});
test('reminders group courses and notice events by actual kind, independent of read state and urgency',()=>{
  const items=[{id:'course',kind:'arrangement',level:'info'},{id:'event',kind:'notice_event',level:'attention',is_read:true},{id:'late',kind:'overdue',level:'urgent'},{id:'change',kind:'change',level:'attention'}];
  const grouped=reminderGroups(items);assert.equal(grouped[0].label,'已过期限');
  assert.deepEqual(grouped.find(group=>group.id==='calendar').items.map(item=>item.id),['course','event']);
  assert.equal(grouped.some(group=>group.label==='其他'),false);
});
test('streaming graphemes do not break flags, combining marks or joined emoji',()=>{
  const text='中👨‍👩‍👧‍👦é🇨🇳文';assert.deepEqual(graphemes(text),['中','👨‍👩‍👧‍👦','é','🇨🇳','文']);
});
