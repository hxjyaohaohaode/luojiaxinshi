import test from 'node:test';
import assert from 'node:assert/strict';
import {noticeFocusModel} from '../static/notice-focus.js';
import {sortNotices} from '../static/library.js';
test('shared evidence time is seconds, with date-only display precision retained',()=>{
  const now=Date.parse('2026-11-02T12:00:00+08:00');
  const focus={key_time:{at:now/1000+3600,label:'原文截止',date:'2026-11-02',time:'',date_only:true}};
  const decision=noticeFocusModel({assessment:{focus}},now);assert.equal(decision.urgent,true);assert.equal(decision.next.time,'');
  assert.equal(noticeFocusModel({assessment:{focus:{key_time:null}},draft:{tasks:[{scope:'personal',due_date:'2026-11-02',deadline_evidence:[{}]}]}},now).next,null);
});
test('priority order respects chosen work, verified deadlines and personal interest without hiding unknowns',()=>{
  const rows=[{id:'new-unknown',published_at:'2026-11-02',assessment:{priority:'R',quality:'unavailable'}},
    {id:'urgent',published_at:'2026-01-01',assessment:{priority:'P1',quality:'passed',urgency:{state:'due_soon',closing_at:1234}}},
    {id:'existing-change',intent:'verify',task_count:1},
    {id:'interest',assessment:{priority:'P2',quality:'passed',interest_match:true}},
    {id:'restored',feedback:{mode:'include'},assessment:{quality:'unavailable'}},
    {id:'excluded',recommended:false,assessment:{priority:'P1',quality:'passed'}}];
  assert.deepEqual(sortNotices(rows,'priority').map(n=>n.id),['existing-change','urgent','restored','interest','new-unknown','excluded']);
  assert.equal(sortNotices(rows,'published')[0].id,'new-unknown');assert.equal(rows[0].id,'new-unknown');
});
test('unverified claims of urgency do not receive the verified deadline rank',()=>{
  const rows=[{id:'unverified',assessment:{priority:'P1',quality:'needs_review',urgency:{state:'due_soon',closing_at:1}}},
    {id:'verified-opportunity',assessment:{priority:'P2',quality:'passed'}}];
  assert.equal(sortNotices(rows,'priority')[0].id,'verified-opportunity');
});
