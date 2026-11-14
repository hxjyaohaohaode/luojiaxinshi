import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {createPagedList} from '../static/paged-list.js';

// Exercise the production API wrapper and its actual refresh callers. This
// does not copy the mutation counter or the loadTaskList/refreshData logic.
const source=await readFile(new URL('../static/app.js',import.meta.url),'utf8');
function between(start,end){const first=source.indexOf(start),last=source.indexOf(end,first);assert.ok(first>=0&&last>first);return source.slice(first,last);}
const apiSource=between('async function api(path, options={})','\nfunction showDialog(');
const listSource=between('function taskFilters(){','\nconst operationsUI=');
const refreshSource=between('async function refreshData(kinds=','\nasync function route(){');
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};

function fixture(operation,{guarded=true,failFresh=false}={}){
  let sharedRevision='r1',holdNext=null,failed=false,notifications=0;
  const rows=Array.from({length:54},(_,i)=>({id:'task-'+i,version:1,status:'pending',data:{title:'Task '+i}}));
  if(operation==='undo')[rows[49],rows[50]]=[rows[50],rows[49]];
  const reads=[],painted=[],state={session:{user:{id:'alice'},csrf:'fixture-csrf'},renderId:1,query:'',filter:'all',dateFilter:'',taskView:operation==='status'?'list':'board',insightSelection:null,tasks:[]};
  const fetch=async(url,options)=>{
    const value=new URL(url,'https://fixture'),method=options.method||'GET';
    if(value.pathname==='/api/tasks/page'){
      const beforeMutation=runtime.mutation();reads.push({path:value.pathname+value.search,beforeMutation,signal:options.signal});
      if(failFresh&&beforeMutation>0&&!failed){failed=true;throw Error('independent saved-state read failed');}
      const offset=value.searchParams.has('cursor')?50:0;
      const body={items:structuredClone(rows.slice(offset,offset+50)),total:54,has_more:!offset,next_cursor:offset?null:'next'};
      if(holdNext){const hold=holdNext;holdNext=null;await hold.promise;}
      return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
    }
    assert.equal(method,operation==='status'?'PUT':'POST');
    assert.equal(value.pathname,operation==='status'?'/api/tasks/task-50':'/api/tasks/task-50/move');
    if(operation==='move')[rows[49],rows[50]]=[rows[50],rows[49]];
    else if(operation==='undo')[rows[49],rows[50]]=[rows[50],rows[49]];
    else rows.find(row=>row.id==='task-50').status='done';
    rows.find(row=>row.id==='task-50').version++;
    return new Response(JSON.stringify({ok:true}),{status:200,headers:{'Content-Type':'application/json'}});
  };
  const sandbox={state,fetch,AbortController,structuredClone,setTimeout,clearTimeout,Map,location:{hash:'#tasks'},document:new EventTarget(),CustomEvent,reminders:{refresh(){}},workspaceProjection:{load(){throw Error('Task route must use its real paged collection');}},dataSync:{notify(){notifications++;}}};
  vm.createContext(sandbox);vm.runInContext('let workspaceMutation=0;const projections=new Map();\n'+apiSource+'\n'+listSource+'\n'+refreshSource+'\nglobalThis.runtime={api,loadTaskList,refreshData,mutation:()=>workspaceMutation};',sandbox);
  const runtime=sandbox.runtime;
  const list=createPagedList({api:runtime.api,path:'/tasks/page',owner:()=>state.session?.user.id,context:()=>state.renderId,revision:()=>sharedRevision,onChange:value=>{state.tasks=value.items;painted.push(value.items.map(item=>item.id));}});
  sandbox.taskCollection=list;
  const initialize=async()=>{await runtime.loadTaskList();await list.more();assert.equal(state.tasks.length,54);};
  const background=()=>{const mutation=runtime.mutation();return list.reload({preserveRange:true,...(guarded?{canApply:()=>runtime.mutation()===mutation}:{})});};
  const mutate=()=>runtime.api(operation==='status'?'/tasks/task-50':'/tasks/task-50/move',{method:operation==='status'?'PUT':'POST',json:operation==='status'?{version:1,status:'done',data:rows.find(row=>row.id==='task-50').data}:{task_version:1,workflow_version:1,lane:'action',...(operation==='move'?{before_id:'task-49'}:{after_id:'task-49'})}});
  return {runtime,list,rows,reads,painted,state,initialize,background,mutate,notifications:()=>notifications,advanceProjection:()=>{sharedRevision='r2';},hold:()=>{holdNext=deferred();return holdNext;}};
}

for(const operation of ['move','undo','status'])for(const guarded of [true,false])test('the real application '+operation+' refresh supersedes an older '+(guarded?'mutation-guarded':'default-gate')+' pending read',async()=>{
  const f=fixture(operation,{guarded});await f.initialize();if(operation==='status')f.advanceProjection();
  const hold=f.hold(),older=f.background(),before=f.reads.length;let current;
  try{
    await f.mutate();assert.equal(f.runtime.mutation(),1);assert.equal(f.notifications(),1);
    current=operation==='status'?f.runtime.refreshData(['tasks']):f.runtime.loadTaskList(true,{preserveRange:true});
    assert.equal(f.reads.length,before+1,'A forced read after the successful write must start after that write, not inherit the earlier pending response');
    await current;const actual=f.list.snapshot();assert.equal(actual.items.length,54);assert.deepEqual(actual.items,f.rows);
    assert.equal(f.state.tasks.length,54);assert.equal(f.state.tasks.find(item=>item.id==='task-50').version,2);
    hold.resolve();assert.equal(await older,null,'Late pre-write data may not overwrite or certify the saved state');
    assert.deepEqual(f.list.snapshot().items,f.rows);assert.equal(f.list.snapshot().error,'');
  }finally{hold.resolve();await older;await current;}
});

test('ordinary non-forced application loads still share one valid same-scope pending range request',async()=>{
  const f=fixture('move');await f.initialize();const hold=f.hold(),older=f.background(),before=f.reads.length;
  try{
    const first=f.runtime.loadTaskList(false,{preserveRange:true}),second=f.runtime.loadTaskList(false,{preserveRange:true});
    assert.equal(f.reads.length,before);hold.resolve();const results=await Promise.all([older,first,second]);
    assert.ok(results.every(result=>result.items.length===54));assert.equal(f.reads.length,before+1,'Only the held range request fetches its second page');
    assert.equal(f.runtime.mutation(),0);
  }finally{hold.resolve();await older;}
});

test('a failed fresh read after a successful application mutation keeps the range and error even when an old unguarded read arrives',async()=>{
  const f=fixture('move',{guarded:false,failFresh:true});await f.initialize();const beforeIds=f.list.snapshot().items.map(item=>item.id),hold=f.hold(),older=f.background();
  let current;
  try{
    await f.mutate();current=f.runtime.loadTaskList(true,{preserveRange:true});
    assert.equal(f.reads.length,4,'The read of the saved state must actually be attempted');
    assert.equal(await current,null);assert.deepEqual(f.list.snapshot().items.map(item=>item.id),beforeIds);assert.ok(f.list.snapshot().error);
    const error=f.list.snapshot().error;hold.resolve();assert.equal(await older,null);
    assert.deepEqual(f.list.snapshot().items.map(item=>item.id),beforeIds);assert.equal(f.list.snapshot().error,error);
  }finally{hold.resolve();await older;await current;}
});
