import test from 'node:test';
import assert from 'node:assert/strict';
import {File} from 'node:buffer';
import {createHash} from 'node:crypto';
import {createCampusUI} from '../static/campus.js';

function element(extra={}) {
  const attributes=new Map();
  return {isConnected:true,disabled:false,dataset:{},classList:{add(){},remove(){},toggle(){}},
    setAttribute:(key,value)=>attributes.set(key,value),getAttribute:key=>attributes.get(key)??null,
    removeAttribute:key=>attributes.delete(key),before(){},remove(){},insertAdjacentHTML(){},closest(){return null;},
    querySelector(){return null;},querySelectorAll(){return [];},...extra};
}

// The real campus factory and delegated handlers run against deferred draft
// responses. innerHTML creates a fresh attachment checkbox with the actual
// markup attributes, so a response cannot silently reset a later user choice.
// Transport implements the public CAS/material contract; no UI decision is reimplemented.
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
async function fixture(run,{originalFile}={}) {
  let gate=null,nextWriteError=null;
  const hold=()=>{const value={entered:deferred(),release:deferred()};gate=value;return value;};
  const keys=['document','window','location','FormData'],originals=new Map(keys.map(key=>[key,globalThis[key]]));
  const handlers=new Map(),records=new Map(),calls=[],toasts=[],content=element(),status=element(),savedFiles=element(),submit=element();
  const fields=Object.fromEntries(Object.entries({audience:'college',grade:'',class_name:'',title:'原草稿',body:'完整的本地正文',valid_until:'',reference_only:'',keep_attachments:'true'}).map(([name,value])=>[name,element({name,value,type:name==='keep_attachments'?'hidden':'text',checked:false})]));
  fields.files=element({name:'files',files:[]});
  Object.defineProperty(fields.files,'value',{get:()=>'',set:value=>{if(value==='')fields.files.files=[];}});
  const audienceGrid=element(),gradeLabel=element({closest:()=>audienceGrid}),classLabel=element(),matchLabel=element(),classOptions=element();
  const form=element({dataset:{workspaceForm:'campus-publish',draftId:'draft-original',draftVersion:'0',requestId:'',missingFiles:''},elements:fields,
    querySelector:selector=>selector==='[data-campus-draft-status]'?status:selector==='[data-campus-saved-files]'?savedFiles:selector==='[data-campus-grade]'?gradeLabel:selector==='[data-campus-class]'?classLabel:selector==='[data-campus-match]'?matchLabel:selector==='#campus-class-options'?classOptions:null,
    querySelectorAll:selector=>selector==='[type=submit]'?[submit]:[]});
  for(const field of Object.values(fields)){field.form=form;field.closest=()=>form;}
  let missing=null,renderedAttachments='';
  Object.defineProperty(savedFiles,'innerHTML',{set(markup){
    renderedAttachments=markup;
    const input=markup.match(/<input\b[^>]*name="keep_attachments"[^>]*>/)?.[0];assert.ok(input);
    const type=/type="([^"]+)"/.exec(input)?.[1]||'text';
    const next=element({name:'keep_attachments',value:'true',type,checked:/\schecked(?:[\s>]|$)/.test(input)});
    next.form=form;next.closest=()=>form;fields.keep_attachments=next;
  },get:()=>renderedAttachments});
  savedFiles.insertAdjacentHTML=(_position,markup)=>{missing=element({textContent:markup,remove(){missing=null;}});};
  let shown=false;
  globalThis.document={addEventListener(type,listener){handlers.set(type,[...(handlers.get(type)||[]),listener]);},querySelector:selector=>selector==='#campus-missing-files'?missing:selector==='#content'?content:shown&&selector==='[data-workspace-form="campus-publish"]'?form:null,querySelectorAll:()=>[],createElement:()=>element(),hidden:false};
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
      if(nextWriteError){const error=nextWriteError;nextWriteError=null;throw error;}
      if(data.version!==(prior?.version||0))throw Object.assign(Error('草稿已有新版本'),{status:409});
      if((data.pending_attachment_names||[]).length>3)throw Object.assign(Error('待重新选择的附件最多 3 份'),{status:422});
      const uploaded=await Promise.all(options.body.getAll('files').map(async file=>({name:file.name,size:file.size,sha256:typeof file.arrayBuffer==='function'?createHash('sha256').update(Buffer.from(await file.arrayBuffer())).digest('hex'):file.sha256||'synthetic-'+file.name})));
      const attached=[...(data.keep_attachments?prior?.attachments||[]:[]),...uploaded];
      const saved={...data,id,version:data.version+1,attachments:attached,updated_at:1};records.set(id,saved);if(gate){const current=gate;gate=null;current.entered.resolve({data:structuredClone(data),saved:structuredClone(saved)});await current.release.promise;}return structuredClone(saved);
    }
    throw Error('Unexpected request: '+path);
  };
  const dispatch=async(type,target)=>{for(const handler of handlers.get(type)||[])await handler({target,preventDefault(){}});};
  const action=(name,id)=>{const button=element({dataset:{campusAction:name,...(id?{id}:{})},closest:selector=>selector==='[data-campus-action]'?button:form});return dispatch('click',button);};
  let ui;
  try{
    ui=createCampusUI({state,api,esc:value=>String(value??''),showDialog(){},ask:async()=>true,toast:message=>toasts.push(message),updateAccount(){}});
    await ui.render();shown=true;location.hash='#campus/publish';
    await dispatch('input',fields.title);fields.files.files=[originalFile||{name:'原申请表.pdf',size:42}];await dispatch('change',fields.files);await action('save-draft');
    const original=records.get('draft-original');assert.equal(original.version,1);assert.equal(fields.files.files.length,0);

    await run({hold,state,ui,form,fields,records,calls,toasts,content,status,dispatch,action,missing:()=>missing,rejectNextWrite:error=>{nextWriteError=error;}});
  }finally{ui?.clearSession();for(const [key,value]of originals)if(value===undefined)delete globalThis[key];else globalThis[key]=value;}
}


const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('an earlier save response preserves a later unchecked attachment choice and the queued save removes it',async()=>fixture(async({hold,form,fields,records,calls,status,dispatch,action})=>{
  fields.title.value='正在保存的新标题';await dispatch('input',fields.title);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);const queued=action('save-draft');
  gate.release.resolve();await Promise.all([saving,queued]);
  assert.equal(calls.filter(value=>value.method==='PUT').at(-1).data.keep_attachments,false);
  assert.deepEqual(records.get(form.dataset.draftId).attachments,[]);assert.match(status.textContent,/0 份附件/);
}));

test('a later removal stays visible before its next save and cannot be described as already saved',async()=>fixture(async({hold,fields,status,dispatch,action})=>{
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);gate.release.resolve();await saving;
  assert.equal(fields.keep_attachments.checked,false);assert.match(status.textContent,/较早修改已保存|尚未保存/);
}));

test('rechecking attachments during their accepted removal creates a persistent missing-file obligation',async()=>fixture(async({hold,form,fields,records,status,dispatch,action,missing})=>{
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);gate.release.resolve();await saving;
  assert.deepEqual(records.get(form.dataset.draftId).attachments,[],'The already accepted removal is not fabricated away');
  assert.equal(form.dataset.missingFiles,'1');assert.match(missing()?.textContent||'',/原申请表/);assert.match(status.textContent,/重新选择/);
  await action('save-draft');assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,['原申请表.pdf']);
}));

test('a file with the same name but different bytes does not conceal a removed original that was rechecked',async()=>fixture(async({hold,form,fields,records,dispatch,action})=>{
  fields.keep_attachments.checked=false;fields.files.files=[{name:'原申请表.pdf',size:99,sha256:'different-bytes'}];await dispatch('change',fields.files);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);
  gate.release.resolve();await saving;assert.equal(form.dataset.missingFiles,'1');await action('save-draft');
  assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,['原申请表.pdf']);assert.equal(records.get(form.dataset.draftId).attachments[0].sha256,'different-bytes');
}));

test('an exact uploaded replacement already retained by the server needs no invented missing-file obligation',async()=>fixture(async({hold,form,fields,records,dispatch,action})=>{
  fields.keep_attachments.checked=false;fields.files.files=[{name:'原申请表.pdf',size:42,sha256:'synthetic-原申请表.pdf'}];await dispatch('change',fields.files);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);
  gate.release.resolve();await saving;assert.equal(form.dataset.missingFiles,'');await action('save-draft');
  assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,[]);assert.equal(records.get(form.dataset.draftId).attachments.length,1);
}));

test('new file selection survives an earlier response, stays unsaved, and is uploaded exactly once',async()=>fixture(async({hold,form,fields,records,calls,status,dispatch,action})=>{
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  const newer={name:'新补充.txt',size:19};fields.files.files=[newer];await dispatch('change',fields.files);gate.release.resolve();await saving;
  assert.equal(fields.files.files[0],newer);assert.match(status.textContent,/较早修改已保存|尚未保存/);
  await action('save-draft');await action('save-draft');assert.equal(fields.files.files.length,0);
  assert.deepEqual(records.get(form.dataset.draftId).attachments.map(file=>file.name),['原申请表.pdf','新补充.txt']);
}));

test('explicit missing-file removal while a save is pending is preserved and correctly marked as newer input',async()=>fixture(async({hold,form,records,status,action})=>{
  const original=records.get(form.dataset.draftId);records.set(original.id,{...original,version:original.version+1});await action('save-draft');await action('copy-draft');
  assert.equal(form.dataset.missingFiles,'1');const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  await action('clear-files');gate.release.resolve();await saving;
  assert.equal(form.dataset.missingFiles,'');assert.match(status.textContent,/较早修改已保存|尚未保存/);
  await action('save-draft');assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,[]);
}));

test('reselecting a missing file while a save is pending keeps the new upload and clears only the submitted missing state',async()=>fixture(async({hold,form,fields,records,status,dispatch,action})=>{
  const original=records.get(form.dataset.draftId);records.set(original.id,{...original,version:original.version+1});await action('save-draft');await action('copy-draft');
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  const file={name:'重新选的表.pdf',size:43};fields.files.files=[file];await dispatch('change',fields.files);gate.release.resolve();await saving;
  assert.equal(fields.files.files[0],file);assert.equal(form.dataset.missingFiles,'');assert.match(status.textContent,/较早修改已保存|尚未保存/);
  await action('save-draft');const saved=records.get(form.dataset.draftId);assert.deepEqual(saved.pending_attachment_names,[]);assert.deepEqual(saved.attachments.map(item=>item.name),['重新选的表.pdf']);
}));

test('a later checkbox choice is included when the same local draft is rendered again',async()=>fixture(async({ui,fields,content,dispatch})=>{
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);await ui.render();
  const input=content.innerHTML.match(/<input[^>]*name="keep_attachments"[^>]*>/)?.[0];assert.ok(input);assert.doesNotMatch(input,/\schecked(?:[\s>]|$)/);
}));

for(const change of ['owner','draft'])test('a response for the previous '+change+' cannot rewrite current fields or attachment selections',async()=>fixture(async({hold,state,form,fields,dispatch,action})=>{
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  const file={name:'新账号或草稿.txt',size:18};fields.files.files=[file];fields.keep_attachments.checked=false;
  if(change==='owner')state.session={user:{id:'bob'}};
  else {form.dataset.draftId='draft-next';form.dataset.draftVersion='0';await dispatch('input',fields.title);}
  const version=form.dataset.draftVersion;gate.release.resolve();await saving;
  assert.equal(fields.files.files[0],file);assert.equal(fields.keep_attachments.checked,false);assert.equal(form.dataset.draftVersion,version);
}));

test('a failed response keeps the latest attachment choice and selected files available for retry',async()=>fixture(async({hold,fields,status,dispatch,action})=>{
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=false;const file={name:'待重试.txt',size:21};fields.files.files=[file];await dispatch('change',fields.files);
  gate.release.reject(Error('网络断开'));await saving;
  assert.equal(fields.keep_attachments.checked,false);assert.equal(fields.files.files[0],file);assert.match(status.textContent,/网络断开/);
}));

test('publishing rechecks missing originals created by an earlier pending save before requesting an audience review',async()=>fixture(async({hold,form,fields,calls,toasts,dispatch,action})=>{
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);
  const publishing=dispatch('submit',form);await tick();gate.release.resolve();await Promise.all([saving,publishing]);
  assert.equal(form.dataset.missingFiles,'1');
  assert.equal(calls.some(value=>value.path==='/campus/audience-review'||value.path==='/campus/publications'),false);
  assert.match(toasts.at(-1),/重新选择附件|不再附加/);
}));


const originalBytes='the exact original material bytes';
const originalFile=()=>new File([originalBytes],'原申请表.pdf',{type:'application/pdf'});

test('an original reselected before the removal response is confirmed by server SHA and clears the persisted missing obligation',async()=>fixture(async({hold,form,fields,records,calls,status,dispatch,action})=>{
  const expected=records.get(form.dataset.draftId).attachments[0].sha256;
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);
  const selected=originalFile();fields.files.files=[selected];await dispatch('change',fields.files);
  const queued=action('save-draft');gate.release.resolve();await Promise.all([saving,queued]);
  const saved=records.get(form.dataset.draftId);
  assert.equal(saved.attachments[0].sha256,expected);assert.equal(saved.attachments.length,1);
  assert.deepEqual(saved.pending_attachment_names,[]);assert.equal(form.dataset.missingFiles,'');assert.equal(fields.files.files.length,0);
  assert.match(status.textContent,/已保存.*1 份附件/);
  const writes=calls.filter(call=>call.method==='PUT');assert.deepEqual(writes.at(-1).data.pending_attachment_names,[]);
  await action('save-draft');assert.equal(records.get(form.dataset.draftId).attachments.length,1,'Metadata reconciliation never uploads the consumed file again');
},{originalFile:originalFile()}));

test('same-name replacement bytes never satisfy a missing original, including a later file reselection',async()=>fixture(async({hold,form,fields,records,status,dispatch,action})=>{
  const expected=records.get(form.dataset.draftId).attachments[0].sha256;
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);
  const gate=hold(),saving=action('save-draft');await gate.entered.promise;
  fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);
  fields.files.files=[new File(['different bytes'],'原申请表.pdf')];await dispatch('change',fields.files);
  gate.release.resolve();await saving;await action('save-draft');
  assert.notEqual(records.get(form.dataset.draftId).attachments[0].sha256,expected);assert.equal(form.dataset.missingFiles,'1');
  fields.files.files=[new File(['another replacement'],'原申请表.pdf')];await dispatch('change',fields.files);await action('save-draft');
  assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,['原申请表.pdf']);assert.equal(form.dataset.missingFiles,'1');assert.match(status.textContent,/重新选择/);
  await action('clear-files');await action('save-draft');
  assert.equal(form.dataset.missingFiles,'');assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,[],'Only an explicit discard resolves the unfulfilled original choice');
},{originalFile:originalFile()}));

test('failed recovery metadata reconciliation keeps later inputs and permits a retry without uploading the original twice',async()=>fixture(async({hold,form,fields,records,status,dispatch,action,rejectNextWrite})=>{
  fields.keep_attachments.checked=false;await dispatch('input',fields.keep_attachments);
  const removal=hold(),saving=action('save-draft');await removal.entered.promise;
  fields.keep_attachments.checked=true;await dispatch('input',fields.keep_attachments);
  fields.files.files=[originalFile()];await dispatch('change',fields.files);removal.release.resolve();await saving;
  const upload=hold(),recovering=action('save-draft');await upload.entered.promise;
  const latest=new File(['latest supplement'],'补充说明.txt');fields.files.files=[latest];await dispatch('change',fields.files);
  fields.title.value='恢复期间继续修改的标题';await dispatch('input',fields.title);
  rejectNextWrite(Error('恢复记录暂未保存'));upload.release.resolve();await recovering;
  assert.match(status.textContent,/未保存.*恢复记录暂未保存/);assert.equal(fields.files.files[0],latest);
  assert.equal(records.get(form.dataset.draftId).attachments.length,1);assert.deepEqual(records.get(form.dataset.draftId).pending_attachment_names,['原申请表.pdf']);
  await action('save-draft');const saved=records.get(form.dataset.draftId);
  assert.equal(saved.title,'恢复期间继续修改的标题');assert.deepEqual(saved.pending_attachment_names,[]);
  assert.deepEqual(saved.attachments.map(file=>file.name),['原申请表.pdf','补充说明.txt']);assert.equal(form.dataset.missingFiles,'');assert.equal(fields.files.files.length,0);
  assert.match(status.textContent,/已保存.*2 份附件/);
},{originalFile:originalFile()}));
