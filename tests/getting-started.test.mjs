import test from 'node:test';
import assert from 'node:assert/strict';
import {GETTING_STARTED_HINT,guideDismissed,needsFirstUseGuide,capabilityIdentity} from '../static/getting-started.js';

test('self-reported teachers and site admins do not become verified campus publishers',()=>{
  for(const user of [{profile:{campus_role:'teacher'}},{role:'admin',profile:{campus_role:'staff'}}]){
    const identity=capabilityIdentity(user);assert.equal(identity.state,'pending');assert.match(identity.description,/不会获得学院发布或管理权限/);
  }
  assert.equal(capabilityIdentity({campus_membership:{role:'counselor',college_name:'合成学院'}}).state,'verified');
  assert.match(capabilityIdentity({campus_membership:{role:'student',college_name:'合成学院'}}).label,/学生/);
});

test('guide dismissal belongs to the current account profile and leaves unrelated hints alone',()=>{
  const first={dismissed_hints:['existing-hint',GETTING_STARTED_HINT]},second={dismissed_hints:['existing-hint']};
  assert.equal(guideDismissed(first),true);assert.equal(guideDismissed(second),false);assert.equal(guideDismissed(null),false);
  assert.deepEqual(first.dismissed_hints,['existing-hint',GETTING_STARTED_HINT]);
});

test('only a new account that never saw or dismissed the guide gets an automatic tour',()=>{
  assert.equal(needsFirstUseGuide({first_use_guide_seen:false}),true);
  for(const profile of [{}, {first_use_guide_seen:null}, {first_use_guide_seen:true}, {first_use_guide_seen:false,dismissed_hints:[GETTING_STARTED_HINT]}]){
    assert.equal(needsFirstUseGuide(profile),false);
  }
});
