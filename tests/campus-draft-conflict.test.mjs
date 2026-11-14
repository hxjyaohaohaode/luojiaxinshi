import test from 'node:test';
import assert from 'node:assert/strict';
import {createCampusUI} from '../static/campus.js';

function element(extra={}) {
  const attributes=new Map();
  return {isConnected:true,disabled:false,dataset:{},classList:{add(){},remove(){},toggle(){}},
    setAttribute:(key,value)=>attributes.set(key,value),getAttribute:key=>attributes.get(key)??null,
    removeAttribute:key=>attributes.delete(key),before(){},remove(){},insertAdjacentHTML(){},closest(){return null;},
    querySelector(){return null;},querySelectorAll(){return [];},...extra};
}

// The real campus delegated handlers and draft renderer run against a transport
// with the public draft CAS/attachment contract. No UI decision is reimplemented.
async function fixture(run) {
  const keys=['document','window','location','FormData'],originals=new Map(keys.map(key=>[key,globalThis[key]]));
  const handlers=new Map(),records=new Map(),calls=[],toasts=[],content=element(),status=element(),savedFiles=element(),submit=element();
  const fields=Object.fromEntries(Object.entries({audience:'college',grade:'',class_name:'',title:'原草稿',body:'完整的本地正文',valid_until:'',reference_only:'',keep_attachments:'true'}).map(([name,value])=>[name,element({name,value,type:name==='keep_attachments'?'hidden':'text',checked:false})]));
  fields.files=element({name:'files',files:[]});
  Object.defineProperty(fields.files,'value',{get:()=>'',set:value=>{if(value==='')fields.files.files=[];}});
  const form=element({dataset:{workspaceForm:'campus-publish',draftId:'draft-original',draftVersion:'0',requestId:'',missingFiles:''},elements:fields,
    querySelector:selector=>selector==='[data-campus-draft-status]'?status:selector==='[data-campus-saved-files]'?savedFiles:null,
    querySelectorAll:selector=>selector==='[type=submit]'?[submit]:[]});
  for(const field of Object.values(fields)){field.form=form;field.closest=()=>form;}
  let shown=false;
  globalThis.document={addEventListener(type,listener){handlers.set(type,[...(handlers.get(type)||[]),listener]);},querySelector:selector=>selector==='#content'?content:shown&&selector==='[data-workspace-form="campus-publish"]'?form:null,querySelectorAll:()=>[],createElement:()=>element(),hidden:false};
  globalThis.window={addEventListener(){}};globalThis.location={hash:'#campus'};
  globalThis.FormData=class {constructor(source){this.values=new Map();if(source)for(const field of Object.values(source.elements))if(field.type!=='checkbox'||field.checked)this.append(field.name,field.value);}append(key,value){this.values.set(key,[...(this.values.get(key)||[]),value]);}get(key){return this.values.get(key)?.[0]??null;}getAll(key){return this.values.get(key)||[];}has(key){return this.values.has(key);}};
  const state={session:{user:{id:'alice'}},renderId:1,workContext:'college'};
  const api=async(path,options={})=>{
    const data=options.body?JSON.parse(options.body.get('data')):options.json;
    calls.push({path,method:options.method||'GET',data:structuredClone(data)});
    if(path==='/campus/context')return {membership:{role:'college_admin',college_id:'college',college_name:'合成学院',scopes:[]}};
    if(path.startsWith('/campus/members'))return {members:[]};
    if(path.startsWith('/campus/publications?'))return {items:[]};
    if(path==='/edit-cache/campus-publication')return {revision:0,payload:null};
    if(path==='/campus/drafts')return {items:[...records.values()].map(item=>structuredClone(item))};
    if(path.startsWith('/campus/drafts/')){
      const id=decodeURIComponent(path.split('/').at(-1)),prior=records.get(id);
      if(options.method!=='PUT'){assert.ok(prior);return structuredClone(prior);}
      if(data.version!==(prior?.version||0))throw Object.assign(Error('草稿已有新版本'),{status:409});
      if((data.pending_attachment_names||[]).length>3)throw Object.assign(Error('待重新选择的附件最多 3 份'),{status:422});
      const attached=[...(data.keep_attachments?prior?.attachments||[]:[]),...options.body.getAll('files').map(file=>({name:file.name,size:file.size}))];
      const saved={...data,id,version:data.version+1,attachments:attached,updated_at:1};records.set(id,saved);return structuredClone(saved);
    }
    throw Error('Unexpected request: '+path);
  };
  const dispatch=async(type,target)=>{for(const handler of handlers.get(type)||[])await handler({target,preventDefault(){}});};
  const action=(name,id)=>{const button=element({dataset:{campusAction:name,...(id?{id}:{})},closest:selector=>selector==='[data-campus-action]'?button:form});return dispatch('click',button);};
  let ui;
  try{
    ui=createCampusUI({state,api,esc:value=>String(value??''),showDialog(){},ask:async()=>true,toast:message=>toasts.push(message),updateAccount(){}});
    await ui.render();shown=true;location.hash='#campus/publish';
    await dispatch('input',fields.title);fields.files.files=[{name:'原申请表.pdf',size:42}];await dispatch('change',fields.files);await action('save-draft');
    const original=records.get('draft-original');assert.equal(original.version,1);assert.equal(fields.files.files.length,0);
    records.set(original.id,{...structuredClone(original),title:'其他设备的新版本',version:2});
    fields.title.value='本人尚未提交的修改';await dispatch('input',fields.title);await action('save-draft');assert.equal(form.dataset.draftConflict,'1');
    await run({state,ui,form,fields,records,calls,toasts,content,status,dispatch,action});
  }finally{ui?.clearSession();for(const [key,value]of originals)if(value===undefined)delete globalThis[key];else globalThis[key]=value;}
}

test('conflicting draft copied without original files persists missing names, blocks publishing and survives reopening',async()=>fixture(async({form,records,calls,toasts,content,action,dispatch})=>{
  await action('copy-draft');const id=form.dataset.draftId,saved=records.get(id);
  assert.notEqual(id,'draft-original');assert.equal(saved.title,'本人尚未提交的修改');assert.deepEqual(saved.attachments,[]);
  assert.deepEqual(saved.pending_attachment_names,['原申请表.pdf']);assert.equal(form.dataset.missingFiles,'1');
  const count=calls.length;await dispatch('submit',form);assert.match(toasts.at(-1),/重新选择附件/);assert.equal(calls.slice(count).some(call=>call.path==='/campus/audience-review'||call.path==='/campus/publications'),false);
  await action('open-draft',id);assert.match(content.innerHTML,/data-missing-files="1"/);assert.match(content.innerHTML,/原申请表\.pdf/);
  await action('clear-files');await action('save-draft');assert.deepEqual(records.get(id).pending_attachment_names,[]);assert.equal(form.dataset.missingFiles,'');
  assert.equal(records.get('draft-original').version,2);assert.equal(records.get('draft-original').title,'其他设备的新版本');
}));

test('conflict copy keeps an existing new upload separate from unresolved original attachment names',async()=>fixture(async({form,fields,records,action,dispatch})=>{
  fields.files.files=[{name:'新补充说明.txt',size:13}];await dispatch('change',fields.files);await action('copy-draft');
  const saved=records.get(form.dataset.draftId);assert.deepEqual(saved.attachments.map(file=>file.name),['新补充说明.txt']);
  assert.deepEqual(saved.pending_attachment_names,['原申请表.pdf']);assert.equal(form.dataset.missingFiles,'1');
  assert.equal(fields.files.files.length,0,'A saved upload is not submitted again by the next autosave');
  await action('save-draft');assert.deepEqual(records.get(form.dataset.draftId).attachments.map(file=>file.name),['新补充说明.txt']);
  assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,['原申请表.pdf']);
}));

test('an explicit choice not to retain original attachments does not create a missing-files obligation',async()=>fixture(async({form,fields,records,action,dispatch})=>{
  fields.keep_attachments.type='checkbox';fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);await action('copy-draft');
  const saved=records.get(form.dataset.draftId);assert.deepEqual(saved.attachments,[]);assert.deepEqual(saved.pending_attachment_names,[]);assert.equal(form.dataset.missingFiles,'');
  assert.deepEqual(records.get('draft-original').attachments.map(file=>file.name),['原申请表.pdf']);
}));

test('explicit reselection or removal resolves only the copied draft missing-files record',async()=>fixture(async({form,fields,records,action,dispatch})=>{
  await action('copy-draft');const id=form.dataset.draftId;assert.deepEqual(records.get(id).pending_attachment_names,['原申请表.pdf']);
  fields.files.files=[{name:'重新选择的申请表.pdf',size:53}];await dispatch('change',fields.files);await action('save-draft');
  assert.deepEqual(records.get(id).pending_attachment_names,[]);assert.deepEqual(records.get(id).attachments.map(file=>file.name),['重新选择的申请表.pdf']);assert.equal(form.dataset.missingFiles,'');
  assert.deepEqual(records.get('draft-original').attachments.map(file=>file.name),['原申请表.pdf']);
}));

test('a repeated conflict copy keeps its current identity and input until attachment names fit the actual limit',async()=>fixture(async({form,fields,records,calls,toasts,action,dispatch})=>{
  fields.files.files=[1,2,3].map(index=>({name:'新材料-'+index+'.txt',size:index+12}));await dispatch('change',fields.files);await action('copy-draft');
  const id=form.dataset.draftId,first=structuredClone(records.get(id));
  assert.deepEqual(first.pending_attachment_names,['原申请表.pdf']);assert.equal(first.attachments.length,3);
  records.set(id,{...structuredClone(first),title:'另一端再次保存',version:first.version+1});
  fields.title.value='第二次冲突仍要保留的正文标题';await dispatch('input',fields.title);await action('save-draft');assert.equal(form.dataset.draftConflict,'1');
  const before=calls.length;await action('copy-draft');
  assert.equal(form.dataset.draftId,id,'The over-limit copy must not replace the current identity before a concrete attachment choice');
  assert.equal(form.dataset.draftConflict,'1');assert.equal(fields.title.value,'第二次冲突仍要保留的正文标题');
  assert.equal(calls.slice(before).some(call=>call.method==='PUT'),false);assert.match(toasts.at(-1),/最多 3 份/);assert.match(toasts.at(-1),/保留这些附件/);
  fields.keep_attachments.type='checkbox';fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);await action('copy-draft');
  const saved=records.get(form.dataset.draftId);assert.notEqual(saved.id,id);assert.equal(saved.title,'第二次冲突仍要保留的正文标题');
  assert.deepEqual(saved.pending_attachment_names,['原申请表.pdf']);assert.deepEqual(saved.attachments,[]);
  assert.equal(records.get(id).title,'另一端再次保存');assert.equal(records.get(id).attachments.length,3);
}));
