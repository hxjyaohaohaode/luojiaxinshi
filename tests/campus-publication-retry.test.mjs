import test from 'node:test';
import assert from 'node:assert/strict';
import {createCampusUI} from '../static/campus.js';

// Exercise the real delegated submit/input handlers. The transport commits the
// first publication and deletes its draft before losing only the response.
function element(extra={}) {
  const attributes=new Map();
  return {isConnected:true,disabled:false,dataset:{},classList:{add(){},remove(){},toggle(){}},
    setAttribute:(key,value)=>attributes.set(key,value),getAttribute:key=>attributes.get(key)??null,
    removeAttribute:key=>attributes.delete(key),before(){},remove(){},insertAdjacentHTML(){},closest(){return null;},
    querySelector(){return null;},querySelectorAll(){return [];},...extra};
}
async function fixture(run) {
  const originals=Object.fromEntries(['document','window','location','FormData'].map(key=>[key,globalThis[key]]));
  const handlers=new Map(),notices=[],calls=[],toasts=[],content=element(),status=element(),savedFiles=element();
  const submit=element(),fields=Object.fromEntries(Object.entries({audience:'college',grade:'',class_name:'',title:'已确认发布原文',body:'原文必须精确重放。',valid_until:'',reference_only:'',keep_attachments:'true'}).map(([name,value])=>[name,element({name,value,type:name==='keep_attachments'?'hidden':'text',checked:false})]));
  fields.files=element({name:'files',files:[],value:''});
  Object.defineProperty(fields.files,'value',{get:()=>'',set:value=>{if(value==='')fields.files.files=[];}});
  const form=element({dataset:{workspaceForm:'campus-publish',draftId:'draft-original',draftVersion:'0',requestId:'',missingFiles:''},elements:fields,
    querySelector:selector=>selector==='[data-campus-draft-status]'?status:selector==='[data-campus-saved-files]'?savedFiles:null,
    querySelectorAll:selector=>selector==='[type=submit]'?[submit]:[]});
  for(const field of Object.values(fields)){field.form=form;field.closest=selector=>selector.includes('campus-publish')?form:null;}
  let shown=false,remoteDraft=null,cache={revision:0,payload:null},lose=true;
  globalThis.document={addEventListener(type,listener){const listeners=handlers.get(type)||[];listeners.push(listener);handlers.set(type,listeners);},querySelector:selector=>selector==='#content'?content:shown&&selector==='[data-workspace-form="campus-publish"]'?form:null,querySelectorAll:()=>[],createElement:()=>element(),hidden:false};
  globalThis.window={addEventListener(){}};globalThis.location={hash:'#campus'};
  globalThis.FormData=class {constructor(source){this.values=new Map();if(source)for(const field of Object.values(source.elements))if(field.type!=='checkbox'||field.checked)this.append(field.name,field.value);}append(key,value){this.values.set(key,[...(this.values.get(key)||[]),value]);}get(key){return this.values.get(key)?.[0]??null;}getAll(key){return this.values.get(key)||[];}has(key){return this.values.has(key);}};
  const state={session:{user:{id:'alice'}},renderId:1,workContext:'college'};
  const api=async(path,options={})=>{
    calls.push({owner:state.session.user.id,path,method:options.method||'GET',payload:options.body?JSON.parse(options.body.get('data')):options.json});
    if(path==='/campus/context')return {membership:{role:'college_admin',college_id:'college',college_name:'合成学院',scopes:[]}};
    if(path.startsWith('/campus/members'))return {members:[]};
    if(path.startsWith('/campus/publications?'))return {items:[]};
    if(path==='/campus/drafts')return {items:remoteDraft?[remoteDraft]:[]};
    if(path==='/edit-cache/campus-publication'){
      if(options.method==='PUT'){assert.equal(options.json.revision,cache.revision);cache={revision:cache.revision+1,payload:structuredClone(options.json.payload)};}
      return structuredClone(cache);
    }
    if(path.startsWith('/campus/drafts/')&&options.method==='PUT'){
      const data=JSON.parse(options.body.get('data'));
      if(data.version!==(remoteDraft?.version||0))throw Object.assign(Error('发布草稿不存在或已变化'),{status:409});
      const attachments=[...(data.keep_attachments?remoteDraft?.attachments||[]:[]),...options.body.getAll('files').map(file=>({name:file.name,size:file.size}))];
      remoteDraft={...data,id:path.split('/').at(-1),version:data.version+1,attachments};return structuredClone(remoteDraft);
    }
    if(path==='/campus/audience-review')return {review:'review-original',students:1,staff:0};
    if(path==='/campus/publications'){
      const payload=JSON.parse(options.body.get('data')),previous=notices.find(item=>item.payload.request_id===payload.request_id);
      if(previous){assert.deepEqual(payload,previous.payload);return previous.result;}
      assert.equal(payload.draft_version,remoteDraft?.version);
      const result={id:'publication-1',delivery:{delivered:1,total:1,students:1}};
      notices.push({payload,result});remoteDraft=null;
      if(lose){lose=false;throw Object.assign(Error('响应连接中断'),{status:0});}return result;
    }
    throw Error('Unexpected request: '+path);
  };
  const dispatch=async(type,target)=>{for(const handler of handlers.get(type)||[])await handler({target,preventDefault(){}});};
  try{
    const ui=createCampusUI({state,api,esc:value=>String(value??''),showDialog(){},ask:async()=>true,toast:message=>toasts.push(message),updateAccount(){}});
    await ui.render();shown=true;location.hash='#campus/publish';
    await dispatch('input',fields.title);
    try{await run({state,form,fields,dispatch,notices,calls,toasts,ui,cache:()=>cache});}finally{ui.clearSession?.();}
  }finally{for(const [key,value]of Object.entries(originals))if(value===undefined)delete globalThis[key];else globalThis[key]=value;}
}

test('lost publication response replays the confirmed payload before touching its deleted draft',async()=>fixture(async({form,dispatch,notices,calls})=>{
  await dispatch('submit',form);
  assert.equal(notices.length,1,'The first request committed before its response was lost');
  const first=structuredClone(notices[0].payload),draftWrites=calls.filter(call=>call.path.startsWith('/campus/drafts/')&&call.method==='PUT').length;
  await dispatch('submit',form);
  const attempts=calls.filter(call=>call.path==='/campus/publications');
  assert.equal(attempts.length,2,'Retry must reach request-ID replay, rather than fail saving the deleted draft');
  assert.deepEqual(attempts[1].payload,first);
  assert.equal(notices.length,1);
  assert.equal(calls.filter(call=>call.path.startsWith('/campus/drafts/')&&call.method==='PUT').length,draftWrites);
}));

test('input after an uncertain publication becomes a separate draft and cannot replace the replay payload',async()=>fixture(async({form,fields,dispatch,notices,calls})=>{
  await dispatch('submit',form);const first=structuredClone(notices[0].payload);
  fields.title.value='后来编辑的新草稿';await dispatch('input',fields.title);
  assert.notEqual(form.dataset.draftId,first.draft_id);
  assert.equal(form.dataset.draftVersion,'0');
  await dispatch('submit',form);
  assert.equal(notices.length,1);assert.deepEqual(calls.filter(call=>call.path==='/campus/publications').at(-1).payload,first);
  assert.equal(location.hash,'#campus/publish');assert.equal(fields.title.value,'后来编辑的新草稿');
  const button=element({dataset:{campusAction:'save-draft'},closest:selector=>selector==='[data-campus-action]'?button:selector==='form'?form:null});
  await dispatch('click',button);
  const saved=calls.filter(call=>call.path.startsWith('/campus/drafts/')&&call.method==='PUT').at(-1);
  assert.equal(saved.payload.title,'后来编辑的新草稿');assert.equal(saved.payload.version,0);
}));

test('saving a separated draft preserves unresolved attachment names until an explicit removal',async()=>fixture(async({form,fields,dispatch,calls,toasts})=>{
  fields.files.files=[{name:'原提交附件.txt',size:12}];await dispatch('change',fields.files);await dispatch('submit',form);
  fields.title.value='需要重新选择原附件的新草稿';await dispatch('input',fields.title);assert.equal(form.dataset.missingFiles,'1');
  const button=action=>{const node=element({dataset:{campusAction:action},closest:selector=>selector==='[data-campus-action]'?node:selector==='form'?form:null});return node;};
  await dispatch('click',button('save-draft'));
  assert.equal(form.dataset.missingFiles,'1');assert.deepEqual(calls.filter(call=>call.path.startsWith('/campus/drafts/')&&call.method==='PUT').at(-1).payload.pending_attachment_names,['原提交附件.txt']);
  await dispatch('submit',form);assert.equal(calls.filter(call=>call.path==='/campus/publications').length,2);
  await dispatch('submit',form);assert.equal(calls.filter(call=>call.path==='/campus/publications').length,2);assert.match(toasts.at(-1),/重新选择附件/);
  await dispatch('click',button('clear-files'));await dispatch('click',button('save-draft'));
  assert.equal(form.dataset.missingFiles,'');assert.deepEqual(calls.filter(call=>call.path.startsWith('/campus/drafts/')&&call.method==='PUT').at(-1).payload.pending_attachment_names,[]);
}));
