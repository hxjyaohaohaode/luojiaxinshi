import test from 'node:test';
import assert from 'node:assert/strict';
import {workContexts,resolveWorkContext,contextForRoute,workspaceNav,primaryWorkspaceNav} from '../static/work-context.js';

const user=(extra={})=>({id:'one',role:'user',profile:{campus_role:'student'},...extra});
test('self-reported personal identities never grant publishing or system access',()=>{
  for(const role of ['student','teacher','staff','other','college_admin','admin']){
    const u=user({profile:{campus_role:role}});
    assert.deepEqual(workContexts(u).map(c=>c.id),['personal']);
    assert.equal(resolveWorkContext(u,'college'),'personal');
    assert.equal(resolveWorkContext(u,'system'),'personal');
  }
});
test('chat is directly available in every mobile context and teacher calendar has priority',()=>{
  for(const context of ['personal','college','system']){
    const items=primaryWorkspaceNav(context);
    assert.equal(items.length,4);
    assert.equal(items[2][0],'chat');
    assert.equal(new Set(items.map(item=>item[0])).size,4);
  }
  assert(primaryWorkspaceNav('personal',user({profile:{campus_role:'teacher'}})).some(([id])=>id==='calendar'));
  assert(primaryWorkspaceNav('personal',user()).some(([id])=>id==='tasks'));
});
test('verified student membership remains a personal workspace',()=>{
  const u=user({campus_membership:{role:'student'}});
  assert.equal(resolveWorkContext(u),'personal');
  assert(!workspaceNav('personal').some(([route])=>route.startsWith('campus')));
});
test('authorized campus staff can switch their work context without merging private content',()=>{
  for(const role of ['college_admin','counselor']){
    const u=user({campus_membership:{role}});
    assert.equal(resolveWorkContext(u),'college');
    assert.equal(resolveWorkContext(u,'personal'),'personal');
    assert(workspaceNav('college').some(([route])=>route==='campus/publish'));
    assert(!workspaceNav('college').some(([route])=>route==='tasks'));
  }
});
test('system administration does not imply campus publishing authority',()=>{
  const u=user({role:'admin'});
  assert.deepEqual(workContexts(u).map(c=>c.id),['personal','system']);
  assert.equal(resolveWorkContext(u),'system');
  assert(!workspaceNav('system').some(([route])=>route==='campus/publish'));
});
test('revoked or stale context choices fall back to roles still issued by the server',()=>{
  assert.equal(resolveWorkContext(user(),'college'),'personal');
  assert.equal(resolveWorkContext(user({role:'admin'}),'college'),'system');
  const u=user({role:'admin',campus_membership:{role:'college_admin'}});
  assert.equal(resolveWorkContext(u,'system'),'system');
  assert.equal(resolveWorkContext(u,'college'),'college');
});
test('deep links activate the relevant context and preserve the selected context for shared settings',()=>{
  const u=user({role:'admin',campus_membership:{role:'counselor'}});
  assert.equal(contextForRoute(u,'college','notice/abc'),'personal');
  assert.equal(contextForRoute(u,'system','tasks/abc'),'personal');
  assert.equal(contextForRoute(u,'personal','campus/records'),'college');
  assert.equal(contextForRoute(u,'system','campus/members'),'system');
  assert.equal(contextForRoute(u,'college','settings'),'college');
  for(const context of ['personal','college','system']){
    assert.equal(workspaceNav(context).filter(([route])=>route==='dashboard').length,1);
    assert.equal(primaryWorkspaceNav(context).length,4);
  }
});
