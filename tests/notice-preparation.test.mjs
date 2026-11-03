import test from 'node:test';
import assert from 'node:assert/strict';
import {createNoticePreparation} from '../static/notice-preparation.js';
import {submissionLinks,currentHandlingStep} from '../static/handling-route.js';

test('one explicit preparation survives navigation and coalesces duplicate clicks',async()=>{
  let finish,calls=0,results=0;
  const controller=createNoticePreparation({getOwner:()=>1,api:()=>{calls++;return new Promise(resolve=>finish=resolve);},onResult:()=>results++});
  const n={id:'one',version:2,status:'received'},first=controller.prepare(n);
  assert.equal(controller.prepare(n),first);assert.equal(controller.isPending('one'),true);
  await Promise.resolve();finish({...n,status:'draft',draft:{tasks:[]}});await first;
  assert.equal(calls,1);assert.equal(results,1);assert.equal(controller.isPending('one'),false);
});

test('logout or account switch suppresses preparation UI and error callbacks',async()=>{
  let owner='alice',finish,results=0;
  const controller=createNoticePreparation({getOwner:()=>owner,api:()=>new Promise(resolve=>finish=resolve),onResult:()=>results++,onError:()=>results++});
  const first=controller.prepare({id:'one',version:1,status:'received'});await Promise.resolve();owner='bob';
  finish({id:'one',status:'draft'});await first;assert.equal(results,0);assert.equal(controller.isPending('one'),false);
});

test('existing work is reused and network failures are not automatically retried',async()=>{
  let calls=0,errors=0;
  const controller=createNoticePreparation({getOwner:()=>1,api:async()=>{calls++;throw Error('network');},onError:()=>errors++});
  for(const n of [{draft:{}},{status:'processing'},{status:'confirmed'}])await controller.prepare({id:'one',version:1,...n});
  assert.equal(calls,0);await controller.prepare({id:'one',version:1,status:'received'});
  assert.equal(calls,1);assert.equal(errors,1);
});

test('handling paths use only supplied destinations and respect optional participation and real submission state',()=>{
  assert.deepEqual(submissionLinks('通过 https://example.edu/form 提交，说明 https://example.edu/help。'),['https://example.edu/form','https://example.edu/help']);
  assert.deepEqual(submissionLinks('javascript:alert(1) https://user:password@example.edu/'),[]);
  const task={status:'pending',data:{title:'提交申请',materials:['申请表'],submission:'学院办公室'},workflow:{data:{execution_mode:'submission',stage:'preparing',action_kind:'optional',participation:'undecided'}}};
  assert.match(currentHandlingStep(task).label,/决定/);
  task.workflow.data.participation='joined';assert.match(currentHandlingStep(task).label,/准备材料/);
  task.workflow.data.stage='submitted';assert.match(currentHandlingStep(task).label,/跟进/);
  task.status='cancelled';assert.equal(currentHandlingStep(task).label,'已取消');
});
