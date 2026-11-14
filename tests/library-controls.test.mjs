import test from 'node:test';
import assert from 'node:assert/strict';
import {createLibraryUI} from '../static/library.js';

const turn=()=>new Promise(resolve=>setImmediate(resolve));
const rows=(owner='alice')=>['a','b','c'].map((id,index)=>({
  id:owner+'-'+id,title:owner+' notice '+id,version:1,status:index<2?'confirmed':'received',
  disposition:'inbox',created_at:1794662467,source_label:'个人提交',intent:'act',recommended:true,
  ...(index<2?{matter:{id:owner+'-matter',title:owner+' grouped notices',member_count:2}}:{}),
}));
const page=items=>({items:structuredClone(items),total:items.length,has_more:false,next_cursor:null,limit:50,facets:{sources:['个人提交']}});

// The surrounding presentation shell is already mounted. The real library
// factory creates the grouping control, handles delegated events, and uses its
// real PagedList; only the page transport and debounce scheduler are controlled.
// This layout-free DOM does not simulate native pointer hit testing.
function library(t){
  const previous={document:globalThis.document,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
  const nodes=new Map(),listeners=new Map(),timers=new Map(),requests=[],controlWrites=[];
  let now=0,nextTimer=0;
  class Element{
    constructor(selector){this.selector=selector;this.id=selector.startsWith('#')?selector.slice(1):'';this.attributes=new Map();this.dataset={};this.innerHTML='';this.textContent='';this.value='';this._hidden=false;this.disabled=false;this.isConnected=true;}
    get hidden(){return this._hidden;}
    set hidden(value){this._hidden=!!value;if(this.selector==='[data-library-group]')controlWrites.push({type:'hidden',value:this._hidden});}
    classList={add(){},remove(){},toggle(){}};
    setAttribute(name,value){this.attributes.set(name,String(value));}
    getAttribute(name){return this.attributes.get(name)??null;}
    closest(selector){return selector===this.selector?this:null;}
    querySelector(){return null;}
    querySelectorAll(){return [];}
    focus(){}
    scrollIntoView(){}
    insertAdjacentHTML(position,html){
      assert.equal(this.selector,'.library-refine');assert.equal(position,'beforeend');
      assert.match(html,/<button\b[^>]*\bdata-library-group\b/);
      assert.equal(nodes.has('[data-library-group]'),false,'The live grouping control must not be replaced or duplicated');
      const group=new Element('[data-library-group]');
      for(const [,name,value] of html.matchAll(/([\w-]+)="([^"]*)"/g))group.setAttribute(name,value);
      group.textContent='按事项归组';nodes.set(group.selector,group);controlWrites.push({type:'insert',node:group});
    }
  }
  for(const selector of ['#content','#library-results','#library-summary','#library-unreviewed-note','.library-view-toggle','.library-refine','.library-toolbar','#library-source','#library-sort','#library-sort-note','#library-intent-filter','#library-count','#library-filter-note','#library-pages','#library-search','#library-from','#library-to','.tabs'])nodes.set(selector,new Element(selector));
  globalThis.document={querySelector:selector=>nodes.get(selector)||null,querySelectorAll:()=>[],addEventListener(type,listener){const values=listeners.get(type)||[];values.push(listener);listeners.set(type,values);}};
  globalThis.setTimeout=(callback,delay)=>{const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;};
  globalThis.clearTimeout=id=>timers.delete(id);
  const state={session:{user:{id:'alice'}},renderId:1,notices:[],insightSelection:null};
  const api=(url,options={})=>{
    assert.ok(url.startsWith('/notices/page?'));
    let resolve,reject;const promise=new Promise((done,fail)=>{resolve=done;reject=fail;});
    requests.push({url,resolve,reject,promise,signal:options.signal,owner:state.session.user.id});return promise;
  };
  const ui=createLibraryUI({state,api,esc:String,icon:()=>'',noticeRow:n=>n.title,empty:()=>'<p>empty</p>',moveSelection(){},refreshData(){},projectionRevision:()=>null});
  const dispatch=(type,target)=>{for(const listener of listeners.get(type)||[])listener({target,isComposing:false});};
  const group=()=>nodes.get('[data-library-group]');
  const clickGroup=()=>{const node=group();assert.ok(node,'Grouping is an available display preference');assert.equal(node.hidden,false);assert.equal(node.disabled,false);dispatch('click',node);};
  const advance=milliseconds=>{now+=milliseconds;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.callback();}};
  const search=value=>{const input=nodes.get('#library-search');input.value=value;dispatch('input',input);};
  const respond=async(index,items)=>{requests[index].resolve(page(items));await turn();};
  const mount=async(items=rows())=>{const rendering=ui.render();assert.equal(requests.length,1);await respond(0,items);await rendering;};
  const result=()=>nodes.get('#library-results').innerHTML;
  t.after(()=>{ui.clear();globalThis.document=previous.document;globalThis.setTimeout=previous.setTimeout;globalThis.clearTimeout=previous.clearTimeout;});
  return {ui,state,nodes,requests,controlWrites,group,clickGroup,advance,search,respond,mount,result,dispatch};
}

test('grouping is a selectable display preference before the first page and on an ungrouped or empty page',async t=>{
  const app=library(t),rendering=app.ui.render();
  assert.equal(app.requests.length,1);
  const control=app.group();assert.ok(control,'The display choice must not depend on the first response containing a group');
  assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'true');
  app.clickGroup();assert.equal(control.getAttribute('aria-pressed'),'false');
  await app.respond(0,[]);await rendering;
  assert.equal(app.group(),control);assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'false');
  app.clickGroup();assert.equal(control.getAttribute('aria-pressed'),'true');
  app.search('ungrouped');app.advance(180);await app.respond(1,rows().map(({matter,...notice})=>notice));
  assert.equal(app.group(),control);assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'true');
  assert.equal((app.result().match(/class="notice-card notice-row"/g)||[]).length,3);
  assert.equal(app.controlWrites.filter(item=>item.type==='insert').length,1);
});

test('a debounced search keeps the same grouping control selectable while pending and preserves its chosen mode on response',async t=>{
  const app=library(t);await app.mount();const control=app.group();
  assert.match(app.result(),/matter-library-card/);app.search('new query');
  app.clickGroup();assert.equal(control.getAttribute('aria-pressed'),'false');
  assert.equal((app.result().match(/class="notice-card notice-row"/g)||[]).length,3);
  const start=app.controlWrites.length;
  app.advance(179);assert.equal(app.requests.length,1);
  app.advance(1);assert.equal(app.requests.length,2);
  assert.equal(new URL(app.requests[1].url,'https://fixture').searchParams.get('q'),'new query');
  assert.equal(app.ui.snapshot().loading,true);assert.deepEqual(app.ui.snapshot().items,[]);
  assert.equal(app.group(),control);assert.equal(control.hidden,false,'Loading must not remove the live control');
  assert.equal(control.getAttribute('aria-pressed'),'false');
  app.clickGroup();assert.equal(control.getAttribute('aria-pressed'),'true');
  await app.respond(1,rows().slice(0,2));
  assert.equal(app.group(),control);assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'true');
  assert.match(app.result(),/matter-library-card/);assert.equal(app.ui.snapshot().items.length,2);
  assert.equal(app.controlWrites.slice(start).some(item=>item.type==='hidden'&&item.value),false,'No intermediate update may hide the control');
  assert.equal(app.controlWrites.filter(item=>item.type==='insert').length,1);
});

for(const outcome of ['empty','error'])test('a '+outcome+' search result keeps grouping selectable and its choice survives retry',async t=>{
  const app=library(t);await app.mount();const control=app.group();app.clickGroup();
  app.search('no matching group');app.advance(180);
  if(outcome==='error'){app.requests[1].reject(new Error('读取失败'));await turn();assert.match(app.ui.snapshot().error,/读取失败/);}
  else{await app.respond(1,[]);assert.equal(app.ui.snapshot().total,0);}
  assert.equal(app.ui.snapshot().loading,false);assert.equal(app.group(),control);
  assert.equal(control.hidden,false,'A settled empty/error page must retain the display choice');
  assert.equal(control.getAttribute('aria-pressed'),'false');app.clickGroup();assert.equal(control.getAttribute('aria-pressed'),'true');
  const reload=app.ui.reload();assert.equal(app.requests.length,3);
  assert.equal(app.group(),control);assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'true');
  await app.respond(2,rows());await reload;
  assert.equal(app.ui.snapshot().error,'');assert.equal(app.group(),control);assert.match(app.result(),/matter-library-card/);
  assert.equal(control.getAttribute('aria-pressed'),'true');assert.equal(app.controlWrites.filter(item=>item.type==='insert').length,1);
});

test('an owner change resets the grouping preference and an old pending response cannot restore another owner mode or records',async t=>{
  const app=library(t);await app.mount();const control=app.group();app.clickGroup();
  app.search('alice pending');app.advance(180);assert.equal(app.requests[1].owner,'alice');
  app.state.session={user:{id:'bob'}};app.state.renderId++;
  const rendering=app.ui.render();assert.equal(app.requests.length,3);assert.equal(app.requests[2].owner,'bob');
  assert.equal(new URL(app.requests[2].url,'https://fixture').searchParams.has('q'),false);
  assert.equal(app.group(),control);assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'true','A new owner starts with the default display preference');
  app.clickGroup();await app.respond(2,rows('bob'));await rendering;
  assert.equal(control.getAttribute('aria-pressed'),'false');assert.ok(app.ui.snapshot().items.every(n=>n.id.startsWith('bob-')));
  await app.respond(1,rows('alice'));
  assert.equal(app.group(),control);assert.equal(control.hidden,false);assert.equal(control.getAttribute('aria-pressed'),'false');
  assert.deepEqual(app.state.notices.map(n=>n.id),['bob-a','bob-b','bob-c']);
  assert.doesNotMatch(app.result(),/alice-/);assert.doesNotMatch(app.result(),/matter-library-card/);
});
