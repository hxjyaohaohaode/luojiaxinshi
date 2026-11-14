import test,{after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=process.env.REPO_UNDER_TEST?pathToFileURL(resolve(process.env.REPO_UNDER_TEST)+'/'):new URL('../',import.meta.url);
const {createOverview}=await import(new URL('static/overview.js',root));
const {createGettingStarted}=await import(new URL('static/getting-started.js',root));
const {preserveListViewport}=await import(new URL('static/list-viewport.js',root));
const {installDataSync}=await import(new URL('static/data-sync.js',root));
const app=readFileSync(new URL('static/app.js',root),'utf8');
function sourceBetween(start,end){
  const begin=app.indexOf(start),finish=app.indexOf(end,begin+start.length);
  assert.ok(begin>=0&&finish>begin,'The actual app function must be found');
  return app.slice(begin,finish);
}
const allowedSource=sourceBetween('function backgroundSyncAllowed(', '\nfunction updateNoticeFocus(');
const refreshSource=sourceBetween('async function refreshWorkspace(', '\ndataSync=installDataSync(');
const syncSource=app.match(/^dataSync=installDataSync\([^\n]+$/m)?.[0];
const focusoutSource=app.match(/^document\.addEventListener\('focusout',[^\n]+$/m)?.[0];
assert.ok(syncSource&&focusoutSource,'Use the actual sync installation and focusout wake handler');
const observations=[];
after(()=>{
  if(!process.env.HOME_FOCUS_PROOF_OUTPUT)return;
  const paths=['static/app.js','static/overview.js','static/getting-started.js','static/list-viewport.js','static/data-sync.js'];
  writeFileSync(process.env.HOME_FOCUS_PROOF_OUTPUT,JSON.stringify({
    scope:'Controlled deferred projection, deterministic wake timers and minimal DOM focus fix-up; actual production factories and extracted app functions. Focusout on removal is deliberately included as a conservative wake case. This is not a browser run or a capture of the CI75 event sequence.',
    root:fileURLToPath(root),sources:Object.fromEntries(paths.map(path=>[path,createHash('sha256').update(readFileSync(new URL(path,root))).digest('hex')])),observations
  },null,2)+'\n',{flag:'wx'});
});
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};

async function fixture(run){
  const keys=['document','window','location','CSS','innerHeight','CustomEvent','setTimeout','clearTimeout','setInterval','clearInterval'];
  const originals=new Map(keys.map(key=>[key,globalThis[key]]));
  const handlers=new Map(),timers=new Map(),intervals=new Map(),loads=[],revisionReads=[],events=[];
  let nextTimer=0,nodes=new Map(),tabs=[],markup='',writes=0,focusCalls=0,sync=null;
  const body={tagName:'BODY',matches:()=>false},document={hidden:false,activeElement:body};
  const dispatch=event=>{events.push(event.type);for(const handler of handlers.get(event.type)||[])handler(event);};
  function element(tag='DIV',attrs={},dataset={}){
    const attributes=new Map(Object.entries(attrs));
    return {tagName:tag,id:attrs.id||'',dataset,isConnected:true,disabled:false,inert:false,scrollTop:0,scrollLeft:0,
      getAttribute(name){return attributes.get(name)??null;},setAttribute(name,value){attributes.set(name,String(value));},closest(){return null;},
      matches(selector){return selector.split(',').some(value=>value.trim().toUpperCase()===tag);},
      focus(options){
        assert.equal(this.isConnected,true);if(options)assert.deepEqual(options,{preventScroll:true});
        const previous=document.activeElement;document.activeElement=this;focusCalls++;
        if(previous!==this)dispatch({type:'focusout',target:previous});
      },
      getBoundingClientRect(){return {top:0,bottom:850,left:0,right:1280};},
      querySelector(){return null;},querySelectorAll(){return [];},classList:{contains:()=>false},
    };
  }
  const content=element(),dialog={open:false};content.dataset.page='dashboard';content.scrollTop=73;content.scrollLeft=9;content.scrollHeight=1700;content.clientHeight=850;
  content.contains=node=>[...nodes.values(),...tabs].includes(node)&&node.isConnected;
  content.querySelector=selector=>selector.replaceAll('\\','')==='a[href="#new"]'?nodes.get('heading-link'):selector==='#overview-items'?nodes.get('items'):selector==='#overview-all'?nodes.get('all'):null;
  Object.defineProperty(content,'innerHTML',{get:()=>markup,set(value){
    const prior=[...nodes.values(),...tabs],focused=document.activeElement;
    if(prior.includes(focused)){document.activeElement=body;dispatch({type:'focusout',target:focused});}
    for(const node of prior)node.isConnected=false;
    markup=value;writes++;
    assert.match(value,/<a class="button primary small" href="#new">/);
    nodes=new Map([['heading-link',element('A',{href:'#new'})],['items',element()],['all',element('A')]]);
    tabs=['tasks','notices','followup'].map(key=>element('BUTTON',{id:'overview-tab-'+key},{overviewSection:key}));
  }});
  document.querySelector=selector=>selector==='#content'?content:selector==='#dialog'?dialog:selector==='#overview-items'?nodes.get('items'):selector==='#overview-all'?nodes.get('all'):null;
  document.querySelectorAll=selector=>selector==='[data-overview-section]'?tabs:[];
  document.addEventListener=(type,handler)=>handlers.set(type,[...(handlers.get(type)||[]),handler]);
  document.removeEventListener=(type,handler)=>handlers.set(type,(handlers.get(type)||[]).filter(value=>value!==handler));
  document.dispatchEvent=dispatch;document.documentElement=element();
  globalThis.document=document;
  globalThis.window={scrollX:11,scrollY:61,scrollTo(x,y){this.scrollX=x;this.scrollY=y;},addEventListener(){},removeEventListener(){}};
  globalThis.location={hash:'#dashboard'};globalThis.CSS={escape:value=>String(value).replace(/[^a-zA-Z0-9_-]/g,char=>'\\'+char)};
  globalThis.innerHeight=850;globalThis.CustomEvent=class{constructor(type){this.type=type;}};
  globalThis.setTimeout=(callback,delay)=>{const id=++nextTimer;timers.set(id,{callback,delay});return id;};
  globalThis.clearTimeout=id=>timers.delete(id);
  globalThis.setInterval=(callback,delay)=>{const id=++nextTimer;intervals.set(id,{callback,delay});return id;};
  globalThis.clearInterval=id=>intervals.delete(id);
  const initialTask={id:'saved-task',status:'pending',overdue:false,data:{scope:'personal',title:'Saved task'}};
  const state={session:{user:{id:'controlled-owner',profile:{campus_role:'student',dismissed_hints:['workspace-capabilities-v1']}},sync:{revision:'before',domains:{tasks:0,clock:0}}},renderId:1,tasks:[initialTask],notices:[],arrangements:[]};
  const esc=value=>String(value??'');
  const overviewUI=createOverview({state,esc,icon:()=>'',taskRow:task=>'<p>'+task.data.title+'</p>',noticeRow:()=>''});
  const gettingStarted=createGettingStarted({state,esc,api:async()=>{throw Error('Unexpected onboarding mutation');},showDialog(){},toast(){}});
  const firstLoad=deferred();
  const workspaceProjection={load(parts,options){const gate=deferred();loads.push({parts,options,gate});firstLoad.resolve();return gate.promise;}};
  let revision;
  const api=async path=>{assert.equal(path,'/proactive/revision');assert.ok(revision);revisionReads.push(path);return revision;};
  const runtime=new Function('environment',`
    const {state,$,api,workspaceProjection,overviewUI,gettingStarted,preserveListViewport,installDataSync}=environment;
    let workspacePointer=null,workspaceMutation=0,pendingDisplayWrites=0,dataSync=null;
    const pendingTaskUpdates=new Set(),taskCollection={},libraryUI={},reminders={refresh(){}},invalidateChangedLists=()=>{};
    const currentWorkContext=()=> 'personal';
    ${allowedSource}\n${refreshSource}
    return {refreshWorkspace,backgroundSyncAllowed,setPointer(value){workspacePointer=value;},installSync(){${syncSource}\n${focusoutSource}\nreturn dataSync;}};
  `)({state,$:document.querySelector,api,workspaceProjection,overviewUI,gettingStarted,preserveListViewport,installDataSync});
  const scroll=()=>({content:[content.scrollTop,content.scrollLeft],window:[window.scrollX,window.scrollY]});
  try{
    overviewUI.render();gettingStarted.mount();
    await run({state,runtime,loads,firstLoad,content,body,document,element,scroll,events,revisionReads,
      writes:()=>writes,focusCalls:()=>focusCalls,link:()=>nodes.get('heading-link'),items:()=>nodes.get('items'),
      installSync(domain){revision={revision:'after',domains:{tasks:Number(domain==='tasks'),clock:Number(domain==='clock')}};sync=runtime.installSync();return sync;},
      async runWake(){
        const pending=[...timers].filter(([,timer])=>timer.delay===80);assert.equal(pending.length,1,'Focus events must coalesce into one scheduled wake');
        const [id,timer]=pending[0];timers.delete(id);timer.callback();await new Promise(setImmediate);
        assert.equal([...timers.values()].filter(timer=>timer.delay===80).length,0,'An unchanged revision must not schedule a new focus/render loop');
      },
    });
  }finally{
    sync?.stop();for(const load of loads)load.gate.resolve({tasks:[],notices:[]});
    for(const [key,value] of originals)if(value===undefined)delete globalThis[key];else globalThis[key]=value;
  }
}

for(const domain of ['tasks','clock'])test('a pending '+domain+' home refresh applies saved data without losing keyboard focus or repeating the focus wake',async()=>fixture(async f=>{
  const old=f.link(),writes=f.writes(),beforeScroll=f.scroll(),sync=f.installSync(domain),pending=sync.probe();await f.firstLoad.promise;
  old.focus();assert.equal(f.document.activeElement,old);assert.equal(f.runtime.backgroundSyncAllowed(),true);
  const task={...f.state.tasks[0],overdue:domain==='clock',data:{scope:'personal',title:domain+' saved projection'}};
  f.loads[0].gate.resolve({tasks:[task],notices:[]});await pending;
  const current=f.link(),focused=f.document.activeElement===current;
  await f.runWake();
  const observed={domain,current_control_focused:focused,old_control_connected:old.isConnected,control_replaced:old!==current,new_task_applied:f.state.tasks[0]===task,content_writes:f.writes()-writes,
    focused_node_survived_followup:f.document.activeElement===current,focusout_events:f.events.filter(type=>type==='focusout').length,projection_requests:f.loads.map(({parts,options})=>({parts,options})),revision_reads:f.revisionReads.length,scroll_before:beforeScroll,scroll_after:f.scroll()};observations.push(observed);
  assert.equal(f.state.tasks[0],task);assert.match(f.items().innerHTML,new RegExp(domain+' saved projection'));
  assert.deepEqual(f.loads.map(({parts,options})=>({parts,options})),[{parts:domain==='clock'?['notices','tasks']:['tasks'],options:{clockOnly:domain==='clock'}}]);
  assert.equal(f.writes(),writes+1);assert.equal(f.revisionReads.length,2);
  assert.equal(focused,true,'A background render must restore the current equivalent keyboard action after replacing its actual focused node');
  assert.equal(f.document.activeElement,current);assert.deepEqual(f.scroll(),beforeScroll);
}));

test('a guarded home response remains retryable and an accepted refresh preserves external focus and scroll',async()=>fixture(async f=>{
  const external=f.element('BUTTON'),old=f.link(),tasks=f.state.tasks,writes=f.writes(),beforeScroll=f.scroll();
  const pending=f.runtime.refreshWorkspace(new Set(['tasks']));await f.firstLoad.promise;external.focus();f.runtime.setPointer(7);
  const task={...tasks[0],data:{scope:'personal',title:'Saved after pointer release'}};
  f.loads[0].gate.resolve({tasks:[task],notices:[]});const denied=await pending;
  assert.equal(denied,false);assert.equal(f.runtime.backgroundSyncAllowed(),false);assert.equal(f.state.tasks,tasks);assert.equal(f.writes(),writes);assert.equal(old.isConnected,true);assert.equal(f.document.activeElement,external);assert.deepEqual(f.scroll(),beforeScroll);
  f.runtime.setPointer(null);const retry=f.runtime.refreshWorkspace(new Set(['tasks']));assert.equal(f.loads.length,2);
  f.loads[1].gate.resolve({tasks:[task],notices:[]});const applied=await retry;
  observations.push({domain:'external-control',denied_result:denied,retry_result:applied,new_task_applied:f.state.tasks[0]===task,external_still_focused:f.document.activeElement===external,focus_calls:f.focusCalls(),content_writes:f.writes()-writes,scroll_before:beforeScroll,scroll_after:f.scroll()});
  assert.equal(applied,true);assert.equal(f.state.tasks[0],task);assert.equal(f.writes(),writes+1);assert.equal(f.document.activeElement,external);assert.equal(f.focusCalls(),1);assert.deepEqual(f.scroll(),beforeScroll);
}));
