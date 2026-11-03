import test from 'node:test';
import assert from 'node:assert/strict';
import {ChatFeedback} from '../static/chat-feedback.js';
test('a stale stream completion cannot remove an acknowledged local reaction',()=>{
  const feedback=new ChatFeedback(),chat={messages:[{id:'one',emojis:[],reaction:0}]};feedback.reset(chat);
  feedback.patch(chat.messages[0],{emojis:['🎉']});
  const stale={messages:[{id:'one',emojis:[],reaction:0}]};feedback.apply(stale);assert.deepEqual(stale.messages[0].emojis,['🎉']);
});
test('an older in-flight feedback fetch cannot overwrite a newer click',()=>{
  const feedback=new ChatFeedback(),chat={messages:[{id:'one',emojis:[],reaction:0}]};feedback.reset(chat);const before=feedback.epoch;
  feedback.patch(chat.messages[0],{reaction:1});assert.equal(feedback.accept(chat,{signature:'old',emojis:{},reactions:{}},before),false);assert.equal(chat.messages[0].reaction,1);
});
test('remote removal synchronizes feedback without replacing the UI draft object',()=>{
  const ui={snapshots:{choice:'unsaved'}},chat={messages:[{id:'one',emojis:['👍'],reaction:1,genui:ui}]};const feedback=new ChatFeedback();feedback.reset(chat);
  assert.equal(feedback.accept(chat,{signature:'new',emojis:{},reactions:{}},feedback.epoch),true);
  assert.equal(chat.messages[0].genui,ui);assert.deepEqual(chat.messages[0].emojis,[]);assert.equal(chat.messages[0].reaction,0);
});
