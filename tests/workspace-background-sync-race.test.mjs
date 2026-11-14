import test,{after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=process.env.REPO_UNDER_TEST?pathToFileURL(resolve(process.env.REPO_UNDER_TEST)+'/'):new URL('../',import.meta.url);
const {createCampusUI}=await import(new URL('static/campus.js',root));
const {createSystemHome}=await import(new URL('static/system-home.js',root));
const app=readFileSync(new URL('static/app.js',root),'utf8');
function sourceBetween(start,end){
  const begin=app.indexOf(start),finish=app.indexOf(end,begin+start.length);
  assert.ok(begin>=0&&finish>begin,'The actual app function must be found unchanged');
  return app.slice(begin,finish);
}
const dashboardSource=sourceBetween('async function dashboard(', '\nfunction newNotice(');
const allowedSource=sourceBetween('function backgroundSyncAllowed(', '\nfunction updateNoticeFocus(');
const refreshSource=sourceBetween('async function refreshWorkspace(', '\ndataSync=installDataSync(');
const observations=[];
after(()=>{
  if(!process.env.RACE_PROOF_OUTPUT)return;
  const paths=['static/app.js','static/campus.js','static/system-home.js'];
  writeFileSync(process.env.RACE_PROOF_OUTPUT,JSON.stringify({
    scope:'Controlled deferred transport and pointer state; actual production factories, delegated campus click handler, markup and extracted app functions. Not a browser run or proof of the CI73 pointer event sequence.',
    root:fileURLToPath(root),sources:Object.fromEntries(paths.map(path=>[path,createHash('sha256').update(readFileSync(new URL(path,root))).digest('hex')])),
    observations
  },null,2)+'\n');
});

const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function element(extra={}){
  return {isConnected:true,disabled:false,dataset:{},classList:{contains(){return false;},add(){},remove(){},toggle(){}},
    closest(){return null;},querySelector(){return null;},querySelectorAll(){return [];},...extra};
}

// Only transport and the minimal DOM surface are controlled. Controls are
// reconstructed from the real innerHTML markup, including disabled state; the
// fixture never decides which page/guard/cursor the production code should use.
async function fixture(run,{route='#campus/audit',workContext='college'}={}){
  const keys=['document','window','location'],originals=new Map(keys.map(key=>[key,globalThis[key]]));
  const handlers=new Map(),calls=[],toasts=[],gates=[];
  let markup='',writes=0,nodes=new Map(),accountUpdates=0;
  const content=element();
  Object.defineProperty(content,'innerHTML',{get:()=>markup,set(value){
    for(const node of nodes.values())node.isConnected=false;
    nodes=new Map();markup=value;writes++;
    for(const match of value.matchAll(/<button\b[^>]*data-campus-action="([^"]+)"[^>]*>/g)){
      const action=match[1],button=element({dataset:{campusAction:action},disabled:/\sdisabled(?:[\s>]|$)/.test(match[0])});
      button.closest=selector=>selector==='[data-campus-action]'?button:null;
      nodes.set(action,button);
    }
  }});
  const query=selector=>selector==='#content'?content:null;
  globalThis.document={hidden:false,documentElement:element(),activeElement:null,querySelector:query,querySelectorAll:()=>[],
    addEventListener(type,listener){handlers.set(type,[...(handlers.get(type)||[]),listener]);}};
  globalThis.window={addEventListener(){}};globalThis.location={hash:route};
  const state={session:{user:{id:'manager'},ai:{configured:false,model:'test'}},renderId:1,workContext};
  const context={membership:{role:'college_admin',college_id:'college',college_name:'受控学院',scopes:[]}};
  const row=id=>({id,created_at:1700000000,actor_name:'受控管理员',action:'assign_member',target_name:'受控成员'});
  const page=before=>({items:Array.from({length:100},(_,i)=>row(before?200-i:300-i)),has_more:true,next_cursor:before?101:201});
  const hold=prefix=>{const value={prefix,entered:deferred(),release:deferred(),used:false};gates.push(value);return value;};
  const api=async(path)=>{
    calls.push(path);
    const gate=gates.find(value=>!value.used&&path.startsWith(value.prefix));
    if(gate){gate.used=true;gate.entered.resolve(path);await gate.release.promise;}
    if(path==='/campus/context')return structuredClone(context);
    if(path.startsWith('/campus/audit?'))return page(new URL(path,'https://fixture.invalid').searchParams.get('before_id'));
    if(path.startsWith('/campus/members?'))return {members:[]};
    if(path.startsWith('/campus/publications?'))return {items:[]};
    if(path==='/admin/insights')return {users:{total:2,active_7d:1},notices:{total:1,last_30d:1,confirmed:1},tasks:{pending:1,done:0,cancelled:0},ai_30d:{calls:0,failed:0}};
    if(path==='/integrations')return {qq:{configured:false},wechat_publisher:{configured:false}};
    if(path==='/admin/runtime')return {configuration:{},worker_observation:'not-started',workers:{},analysis:{jobs:{}},note:'受控数据'};
    throw Error('Unexpected request '+path);
  };
  let ui;
  try{
    ui=createCampusUI({state,api,esc:value=>String(value??''),showDialog(){},ask:async()=>true,toast:message=>toasts.push(message),updateAccount(){accountUpdates++;}});
    const systemHome=createSystemHome({state,api,esc:value=>String(value??''),icon:()=>''});
    const environment={state,api,campusUI:ui,systemHome,$:query};
    const runtime=new Function('environment',`
      const {state,api,campusUI,systemHome,$}=environment;
      let workspacePointer=null,workspaceMutation=0,pendingDisplayWrites=0;
      const pendingTaskUpdates=new Set(),taskCollection={},libraryUI={};
      const currentWorkContext=()=>state.workContext;
      const invalidateChangedLists=()=>{};
      ${allowedSource}\n${dashboardSource}\n${refreshSource}
      return {refreshWorkspace,dashboard,backgroundSyncAllowed,setPointer(value){workspacePointer=value;}};
    `)(environment);
    const action=async name=>{
      const button=nodes.get(name);assert.ok(button,'The control must exist in the actual generated markup');assert.equal(button.disabled,false);
      for(const handler of handlers.get('click')||[])await handler({target:button,preventDefault(){}});
    };
    if(route==='#campus/audit'){
      await ui.render();await action('audit-next');assert.equal(nodes.get('audit-prev')?.disabled,false);
      assert.match(markup,/第 2 批 · 100 条/);
    }else await runtime.dashboard();
    await run({state,ui,runtime,hold,calls,toasts,content,action,nodes:()=>nodes,markup:()=>markup,writes:()=>writes,accountUpdates:()=>accountUpdates});
  }finally{
    for(const gate of gates)gate.release.resolve();
    ui?.clearSession();
    for(const [key,value] of originals)if(value===undefined)delete globalThis[key];else globalThis[key]=value;
  }
}

test('campus background refresh denied after context response preserves the active control and remains retryable',async()=>fixture(async f=>{
  const before=f.writes(),previous=f.nodes().get('audit-prev'),accountBefore=f.accountUpdates(),auditBefore=f.calls.filter(path=>path.startsWith('/campus/audit?')).length;
  const gate=f.hold('/campus/context'),pending=f.runtime.refreshWorkspace(new Set(['campus']));
  await gate.entered.promise;f.runtime.setPointer(7);assert.equal(f.runtime.backgroundSyncAllowed(),false);
  gate.release.resolve();const result=await pending;
  const observed={case:'context',result,writes:f.writes()-before,old_control_connected:previous.isConnected,account_updates:f.accountUpdates()-accountBefore,audit_requests:f.calls.filter(path=>path.startsWith('/campus/audit?')).length-auditBefore};observations.push(observed);
  assert.equal(result,false);assert.equal(f.writes(),before);assert.equal(previous.isConnected,true);assert.equal(f.accountUpdates(),accountBefore);assert.equal(observed.audit_requests,0);
  f.runtime.setPointer(null);assert.equal(await f.runtime.refreshWorkspace(new Set(['campus'])),true);assert.equal(f.writes(),before+1);
}));

test('campus background refresh denied after audit response preserves the pressed previous control and retries without losing pagination',async()=>fixture(async f=>{
  const before=f.writes(),previous=f.nodes().get('audit-prev'),gate=f.hold('/campus/audit?');
  const pending=f.runtime.refreshWorkspace(new Set(['campus']));await gate.entered.promise;f.runtime.setPointer(7);
  gate.release.resolve();const result=await pending;
  observations.push({case:'audit',result,writes:f.writes()-before,old_control_connected:previous.isConnected});
  assert.equal(result,false);assert.equal(f.writes(),before);assert.equal(previous.isConnected,true);
  f.runtime.setPointer(null);assert.equal(await f.runtime.refreshWorkspace(new Set(['campus'])),true);assert.match(f.markup(),/第 2 批 · 100 条/);
  await f.action('audit-prev');assert.equal(new URL(f.calls.at(-1),'https://fixture.invalid').searchParams.has('before_id'),false);assert.match(f.markup(),/第 1 批 · 100 条/);assert.equal(f.nodes().get('audit-prev').disabled,true);assert.deepEqual(f.toasts,[]);
}));

test('a denied campus render at entry does not invalidate a pending foreground pagination render',async()=>fixture(async f=>{
  const before=f.writes(),gate=f.hold('/campus/audit?'),foreground=f.action('audit-prev');await gate.entered.promise;
  const callsBefore=f.calls.length,denied=await f.ui.render(f.state.renderId,'audit',()=>false);
  gate.release.resolve();await foreground;
  observations.push({case:'entry',result:denied,extra_requests:f.calls.length-callsBefore,writes:f.writes()-before});
  assert.equal(denied,false);assert.equal(f.calls.length,callsBefore);assert.equal(f.writes(),before+1);assert.match(f.markup(),/第 1 批 · 100 条/);assert.deepEqual(f.toasts,[]);
}));

test('college dashboard propagates a denied background render and applies the same revision after interaction ends',async()=>fixture(async f=>{
  const before=f.writes(),gate=f.hold('/campus/publications?'),pending=f.runtime.refreshWorkspace(new Set(['campus']));
  await gate.entered.promise;f.runtime.setPointer(7);gate.release.resolve();const result=await pending;
  observations.push({case:'college-dashboard',result,writes:f.writes()-before});
  assert.equal(result,false);assert.equal(f.writes(),before);
  f.runtime.setPointer(null);assert.equal(await f.runtime.refreshWorkspace(new Set(['campus'])),true);assert.equal(f.writes(),before+1);assert.match(f.markup(),/data-home-context="college"/);
},{route:'#dashboard'}));

test('system dashboard propagates a denied background render and applies the same revision after interaction ends',async()=>fixture(async f=>{
  const before=f.writes(),gate=f.hold('/admin/runtime'),pending=f.runtime.refreshWorkspace(new Set(['campus']));
  await gate.entered.promise;f.runtime.setPointer(7);gate.release.resolve();const result=await pending;
  observations.push({case:'system-dashboard',result,writes:f.writes()-before});
  assert.equal(result,false);assert.equal(f.writes(),before);
  f.runtime.setPointer(null);assert.equal(await f.runtime.refreshWorkspace(new Set(['campus'])),true);assert.equal(f.writes(),before+1);assert.match(f.markup(),/data-home-context="system"/);
},{route:'#dashboard',workContext:'system'}));
