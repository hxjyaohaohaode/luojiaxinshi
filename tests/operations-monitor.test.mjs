import test from 'node:test';
import assert from 'node:assert/strict';
import {createOperations} from '../static/operations.js';

const turn=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const decode=value=>String(value).replaceAll('&quot;','"').replaceAll('&#39;',"'").replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
const attributes=text=>Object.fromEntries([...text.matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(([,key,value])=>[key,decode(value??'')]));

// Use the real operations factory and its real owner/route/dialog guards. This
// small DOM implements field values and delegated form/button events only; it
// does not claim browser layout, native validation, or pointer hit testing.
function monitor(t){
  const previous={document:globalThis.document,location:globalThis.location,FormData:globalThis.FormData};
  const state={session:{user:{id:'admin-a'}},renderId:1,dialogRequest:0};
  const nodes=[],requests=[],toasts=[],gates=[],renders=[];
  const server={
    settings:{queue_age_minutes:60,source_failure_minutes:30,disk_min_free_mb:512,backup_age_hours:24,quota_budget_units:null,credential_expiries:{existing:'2030-01-01T00:00:00Z'}},
    settings_revision:1,snapshot:{evaluated_at:1794662467,measurements:{}},unread_events:1,
    incidents:[{id:'incident-a',state:'open',opened_at:1794662400,acknowledged_at:null,details:{title:'队列待核对'}}],
    events:[{id:8,kind:'opened',created_at:1794662467,details:{title:'队列待核对'}}],
  };
  class Element{
    constructor(tag,attrs={},parent=null){this.tagName=tag.toUpperCase();this.attrs=attrs;this.id=attrs.id||'';this.name=attrs.name||'';this.type=attrs.type||'';this.value=attrs.value||'';this.parent=parent;this.isConnected=true;this.disabled=false;this.open=false;this.listeners=new Map();this.textContent='';this.children=[];parent?.children.push(this);}
    get dataset(){return Object.fromEntries(Object.entries(this.attrs).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()),value]));}
    matches(selector){
      if(selector==='dialog[open]')return this.tagName==='DIALOG'&&this.open;
      const id=selector.match(/^#([\w-]+)$/);if(id)return this.id===id[1];
      const match=selector.match(/^(\w+)?(?:\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\])?$/);
      if(!match)return selector==='.form-error'&&this.attrs.class==='form-error';
      return (!match[1]||this.tagName===match[1].toUpperCase())&&(!match[2]||(Object.hasOwn(this.attrs,match[2])&&(match[3]===undefined||this.attrs[match[2]]===match[3])));
    }
    closest(selector){for(let node=this;node;node=node.parent)if(node.matches(selector))return node;return null;}
    querySelectorAll(selector){const alternatives=selector.split(',').map(part=>part.trim());return nodes.filter(node=>node!==this&&node.isConnected&&node.closest(this.tagName==='FORM'?'#'+this.id:this.tagName.toLowerCase())===this&&alternatives.some(part=>node.matches(part)));}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    addEventListener(type,listener){const list=this.listeners.get(type)||[];list.push(listener);this.listeners.set(type,list);}
    async fire(type){const event={target:this,currentTarget:this,preventDefault(){}};await Promise.all((this.listeners.get(type)||[]).map(listener=>listener(event)));}
    setAttribute(name,value){this.attrs[name]=String(value);}
    getAttribute(name){return this.attrs[name]??null;}
    removeAttribute(name){delete this.attrs[name];}
  }
  const dialog=new Element('dialog',{id:'dialog'});nodes.push(dialog);
  globalThis.location={hash:'#profile'};
  globalThis.document={querySelector:selector=>nodes.find(node=>node.isConnected&&node.matches(selector))||null,querySelectorAll:selector=>nodes.filter(node=>node.isConnected&&selector.split(',').some(part=>node.matches(part.trim())))};
  globalThis.FormData=class{
    constructor(form){this.values=form.elements.filter(element=>element.name&&!element.disabled).map(element=>[element.name,element.value]);}
    get(name){return this.values.find(([key])=>key===name)?.[1]??null;}
    [Symbol.iterator](){return this.values[Symbol.iterator]();}
  };
  const showDialog=(title,html)=>{
    for(const node of nodes)if(node!==dialog)node.isConnected=false;
    dialog.children=[];dialog.open=true;state.dialogRequest++;renders.push({title,html});
    const details=new Element('details',{},dialog);nodes.push(details);
    const forms=[];
    for(const match of html.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/g)){
      const form=new Element('form',attributes(match[1]),details);nodes.push(form);forms.push(form);
      form.elements=[];form.elements.namedItem=name=>form.elements.find(element=>element.name===name)||null;
      for(const [,text] of match[2].matchAll(/<input\b([^>]*)>/g)){
        const input=new Element('input',attributes(text),form);nodes.push(input);form.elements.push(input);
      }
      const error=new Element('p',{class:'form-error'},form);nodes.push(error);
      for(const [,text] of match[2].matchAll(/<button\b([^>]*)>/g)){
        const button=new Element('button',attributes(text),form);nodes.push(button);
      }
    }
    const outside=html.replace(/<form\b[^>]*>[\s\S]*?<\/form>/g,'');
    for(const [,text] of outside.matchAll(/<button\b([^>]*)>/g))nodes.push(new Element('button',attributes(text),dialog));
  };
  const api=async(url,options={})=>{
    const request={url,method:options.method||'GET',json:structuredClone(options.json)};requests.push(request);
    const gate=gates.find(item=>!item.used&&item.url===url&&item.method===request.method);
    if(gate){gate.used=true;gate.entered.resolve(request);if(gate.phase==='before')await gate.release.promise;}
    let result;
    if(request.method==='GET'){assert.equal(url,'/admin/monitor');result=structuredClone(server);}
    else if(url==='/admin/monitor/settings'){
      assert.equal(request.method,'PUT');assert.equal(request.json.expected_revision,server.settings_revision,'The real action must keep the current revision contract');
      const {expected_revision,...settings}=request.json;server.settings=structuredClone(settings);server.settings_revision++;result={saved:true};
    }else{
      assert.equal(request.method,'POST');
      assert.ok(['/admin/monitor/scan','/admin/monitor/seen','/admin/monitor/incidents/incident-a/acknowledge'].includes(url));
      result={updated:true};
    }
    if(gate&&gate.phase==='after')await gate.release.promise;
    return result;
  };
  const ui=createOperations({api,state,esc:value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),showDialog,toast:(...value)=>toasts.push(value)});
  const element=selector=>globalThis.document.querySelector(selector);
  const form=id=>element('#monitor-'+id);
  const field=(id,name)=>form(id).elements.namedItem(name);
  const hold=(method,url,phase='after')=>{const item={method,url,phase,used:false,entered:deferred(),release:deferred()};gates.push(item);return item;};
  const finish=async()=>{await turn();await turn();};
  const click=selector=>element(selector).fire('click');
  const submit=id=>form(id).fire('submit');
  const edits=()=>{field('settings','queue_age_minutes').value='777';field('expiry','label').value='未提交期限';field('expiry','expiry').value='2032-01-02T03:04';form('settings').closest('details').open=true;};
  t.after(()=>{globalThis.document=previous.document;globalThis.location=previous.location;globalThis.FormData=previous.FormData;});
  return {ui,state,server,requests,toasts,renders,dialog,element,form,field,hold,finish,click,submit,edits,showDialog};
}

for(const [name,selector] of [['check','[data-monitor-scan]'],['mark read','[data-monitor-seen]'],['acknowledge','[data-monitor-ack]'],['remove a registered expiry','[data-expiry-remove]']]){
  test('monitor '+name+' refresh preserves both unsaved forms and their expanded section',async t=>{
    const app=monitor(t);await app.ui.monitor();app.edits();
    await app.click(selector);await app.finish();
    assert.equal(app.field('settings','queue_age_minutes').value,'777');
    assert.equal(app.field('expiry','label').value,'未提交期限');
    assert.equal(app.field('expiry','expiry').value,'2032-01-02T03:04');
    assert.equal(app.form('settings').closest('details').open,true);
    assert.equal(app.server.settings.queue_age_minutes,60,'An unrelated action must not silently save the threshold draft');
  });
}

test('saving thresholds keeps the other form and uses the refreshed server baseline for later changes',async t=>{
  const app=monitor(t);await app.ui.monitor();app.edits();await app.submit('settings');await app.finish();
  assert.equal(app.server.settings.queue_age_minutes,777);assert.equal(app.field('settings','queue_age_minutes').value,'777');
  assert.equal(app.field('expiry','label').value,'未提交期限');
  app.server.settings.queue_age_minutes=888;app.server.settings_revision++;
  await app.click('[data-monitor-scan]');await app.finish();
  assert.equal(app.field('settings','queue_age_minutes').value,'888','A successfully saved value must not remain as an unsaved override');
  assert.equal(app.field('expiry','label').value,'未提交期限');
});

test('saving an expiry clears only that unchanged submitted form and leaves unsaved thresholds local',async t=>{
  const app=monitor(t);await app.ui.monitor();app.edits();await app.submit('expiry');await app.finish();
  assert.equal(app.server.settings.queue_age_minutes,60);assert.equal(app.field('settings','queue_age_minutes').value,'777');
  assert.equal(app.server.settings.credential_expiries['未提交期限'],new Date('2032-01-02T03:04').toISOString());
  assert.equal(app.field('expiry','label').value,'');assert.equal(app.field('expiry','expiry').value,'');
});

test('typing during a save and its delayed refresh preserves the latest input, including a return to the old baseline',async t=>{
  const app=monitor(t);await app.ui.monitor();app.edits();
  const saving=app.hold('PUT','/admin/monitor/settings'),refresh=app.hold('GET','/admin/monitor');
  await app.submit('settings');await saving.entered.promise;
  app.field('settings','queue_age_minutes').value='888';saving.release.resolve();await refresh.entered.promise;
  app.field('settings','queue_age_minutes').value='60';app.field('expiry','label').value='刷新期间编辑';
  refresh.release.resolve();await app.finish();
  assert.equal(app.server.settings.queue_age_minutes,777);
  assert.equal(app.field('settings','queue_age_minutes').value,'60','A post-submit edit back to the previous baseline is still a newer edit');
  assert.equal(app.field('expiry','label').value,'刷新期间编辑');
});

test('monitor actions serialize while fields remain editable and a failed request keeps drafts available',async t=>{
  const app=monitor(t);await app.ui.monitor();app.edits();
  const saving=app.hold('PUT','/admin/monitor/settings','before');await app.submit('settings');await saving.entered.promise;
  assert.equal(app.element('[data-monitor-scan]').disabled,true,'Another action cannot race the shared settings revision');
  await app.click('[data-monitor-scan]');assert.equal(app.requests.filter(request=>request.url.endsWith('/scan')).length,0);
  app.field('settings','queue_age_minutes').value='999';assert.equal(app.field('settings','queue_age_minutes').disabled,false);
  saving.release.reject(new Error('保存失败'));await app.finish();
  assert.equal(app.field('settings','queue_age_minutes').value,'999');assert.equal(app.field('expiry','label').value,'未提交期限');
  assert.equal(app.element('[data-monitor-scan]').disabled,false);assert.equal(app.form('settings').querySelector('button[type=submit]').disabled,false);
  assert.ok(app.toasts.some(([message])=>message.includes('保存失败')));assert.equal(app.server.settings.queue_age_minutes,60);
});

for(const change of ['close','route','owner'])test('a '+change+' during monitor refresh cannot reopen the old dialog or copy its draft into a new owner/view',async t=>{
  const app=monitor(t);await app.ui.monitor();app.edits();
  const refresh=app.hold('GET','/admin/monitor');const action=app.click('[data-monitor-scan]');await refresh.entered.promise;
  if(change==='close')app.dialog.open=false;
  if(change==='route'){globalThis.location.hash='#tasks';app.state.renderId++;}
  if(change==='owner')app.state.session={user:{id:'admin-b'}};
  const count=app.renders.length;refresh.release.resolve();await action;await app.finish();
  assert.equal(app.renders.length,count,'Late monitor data must not replace the newer view');
  if(change==='close')assert.equal(app.dialog.open,false);
  app.showDialog('其他内容','<p>new view</p>');
  await app.ui.monitor();
  assert.equal(app.field('settings','queue_age_minutes').value,'60');assert.equal(app.field('expiry','label').value,'');
});
