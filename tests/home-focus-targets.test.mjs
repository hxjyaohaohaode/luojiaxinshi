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
const observations=[];
after(()=>{
  if(!process.env.HOME_TARGET_PROOF_OUTPUT)return;
  const paths=['static/overview.js','static/getting-started.js','static/list-viewport.js'];
  writeFileSync(process.env.HOME_TARGET_PROOF_OUTPUT,JSON.stringify({
    scope:'Actual production overview, onboarding and viewport factories with a minimal parsed-markup DOM. This is a controlled semantic-target regression, not a browser run or a reconstruction of CI75 focus events.',
    root:fileURLToPath(root),sources:Object.fromEntries(paths.map(path=>[path,createHash('sha256').update(readFileSync(new URL(path,root))).digest('hex')])),observations
  },null,2)+'\n',{flag:'wx'});
});

// Parse the controls from the actual rendered HTML. The fixture implements only
// the DOM queries used here; it does not select a desired replacement for the helper.
function fixture(run){
  const keys=['document','window','CSS','innerHeight'],originals=new Map(keys.map(key=>[key,globalThis[key]]));
  const dataName=key=>'data-'+String(key).replace(/[A-Z]/g,char=>'-'+char.toLowerCase());
  let body;
  const document={activeElement:null,addEventListener(){}};
  class Element{
    constructor(tag){
      this.tagName=tag.toUpperCase();this.attributes=new Map();this.children=[];this.parentElement=null;this.scrollTop=0;this.scrollLeft=0;this.scrollHeight=1700;this.clientHeight=850;
      this.dataset=new Proxy({}, {get:(_,key)=>this.getAttribute(dataName(key))??undefined,set:(_,key,value)=>{this.setAttribute(dataName(key),value);return true;}});
    }
    get id(){return this.getAttribute('id')||'';}set id(value){this.setAttribute('id',value);}
    get className(){return this.getAttribute('class')||'';}set className(value){this.setAttribute('class',value);}
    get href(){return this.getAttribute('href');}set href(value){this.setAttribute('href',value);}
    get isConnected(){for(let node=this;node;node=node.parentElement)if(node===body)return true;return false;}
    getAttribute(name){return this.attributes.get(name)??null;}
    setAttribute(name,value){this.attributes.set(name,String(value));}
    contains(other){for(let node=other;node;node=node.parentElement)if(node===this)return true;return false;}
    append(node){node.remove();node.parentElement=this;this.children.push(node);}
    prepend(node){node.remove();node.parentElement=this;this.children.unshift(node);}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(node=>node!==this);this.parentElement=null;}
    matches(selector){return selector.split(',').some(group=>this.matchesPath(group.trim().split(/\s+/)));}
    matchesPath(parts){
      if(!this.matchesSimple(parts.at(-1)))return false;
      if(parts.length===1)return true;
      for(let node=this.parentElement;node;node=node.parentElement)if(node.matchesPath(parts.slice(0,-1)))return true;
      return false;
    }
    matchesSimple(selector){
      selector=selector.replace(/\\(.)/g,'$1');
      const attributes=[...selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
      let base=selector.replace(/\[[^\]]*\]/g,'');
      const tag=base.match(/^[A-Za-z][\w-]*/)?.[0];if(tag){if(this.tagName!==tag.toUpperCase())return false;base=base.slice(tag.length);}
      for(const match of base.matchAll(/([.#])([\w-]+)/g)){
        if(match[1]==='#'&&this.id!==match[2]||match[1]==='.'&&!this.className.split(/\s+/).includes(match[2]))return false;
      }
      if(base.replace(/[.#][\w-]+/g,''))return false;
      return attributes.every(([,name,value])=>value===undefined?this.getAttribute(name)!==null:this.getAttribute(name)===value);
    }
    closest(selector){for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null;}
    querySelectorAll(selector){const out=[];const visit=node=>{for(const child of node.children){if(child.matches(selector))out.push(child);visit(child);}};visit(this);return out;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    focus(options){assert.equal(this.isConnected,true);if(options)assert.deepEqual(options,{preventScroll:true});document.activeElement=this;}
    getBoundingClientRect(){return {top:0,bottom:850,left:0,right:1280};}
    get innerHTML(){return this.markup||'';}
    set innerHTML(value){
      if(this!==document.activeElement&&this.contains(document.activeElement))document.activeElement=body;
      for(const child of this.children)child.parentElement=null;this.children=[];this.markup=value;
      const stack=[this],voids=new Set(['INPUT','IMG','BR','HR','META','LINK','SOURCE','WBR']);
      for(const token of value.matchAll(/<(\/?)([a-z][\w-]*)([^>]*)>/gi)){
        const tag=token[2].toUpperCase();
        if(token[1]){while(stack.length>1){const node=stack.pop();if(node.tagName===tag)break;}continue;}
        const node=new Element(tag);
        for(const [,name,double,single,plain] of token[3].matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s/>]+)))?/g))node.setAttribute(name,double??single??plain??'');
        stack.at(-1).append(node);if(!voids.has(tag)&&!token[3].endsWith('/'))stack.push(node);
      }
    }
  }
  body=new Element('body');const content=new Element('main');content.id='content';content.dataset.page='dashboard';body.append(content);
  document.activeElement=body;document.querySelector=selector=>body.querySelector(selector);document.querySelectorAll=selector=>body.querySelectorAll(selector);document.createElement=tag=>new Element(tag);
  globalThis.document=document;globalThis.window={scrollX:11,scrollY:61,scrollTo(x,y){this.scrollX=x;this.scrollY=y;}};
  globalThis.CSS={escape:value=>String(value).replace(/[^a-zA-Z0-9_-]/g,char=>'\\'+char)};globalThis.innerHeight=850;
  const state={session:{user:{id:'controlled-owner',profile:{campus_role:'student',dismissed_hints:[]}}},tasks:[{id:'saved-task',status:'pending',due_soon:true,followup_due:true,pending_changes:[{field:'title'}],data:{scope:'personal',title:'Saved task'}}],notices:[],arrangements:[]};
  const esc=value=>String(value??'');
  const overview=createOverview({state,esc,icon:()=>'',taskRow:task=>'<p>'+task.data.title+'</p>',noticeRow:()=>''});
  const gettingStarted=createGettingStarted({state,esc,api:async()=>{throw Error('Unexpected mutation');},showDialog(){},toast(){}});
  const render=()=>{overview.render();gettingStarted.mount();};
  try{
    render();content.scrollTop=73;content.scrollLeft=9;
    const scroll=()=>({content:[content.scrollTop,content.scrollLeft],window:[window.scrollX,window.scrollY]});
    return run({state,content,document,render,scroll});
  }finally{
    for(const [key,value] of originals)if(value===undefined)delete globalThis[key];else globalThis[key]=value;
  }
}

test('home refresh retains the distinct pending, follow-up and attention filter actions sharing the same href',()=>fixture(f=>{
  const filters=['pending','followup','soon','changes','unverified'],beforeScroll=f.scroll(),results=[];
  for(const [index,filter] of filters.entries()){
    const selector='a[href="#tasks"][data-overview-filter="'+filter+'"]',previous=f.content.querySelector(selector);
    assert.ok(previous,'The real overview must render '+filter);previous.focus();
    f.state.tasks[0]={...f.state.tasks[0],data:{scope:'personal',title:'Saved revision '+index}};
    preserveListViewport(f.render);
    const current=f.content.querySelector(selector),focused=f.document.activeElement;
    assert.equal(previous.isConnected,false);assert.notEqual(previous,current);assert.match(f.content.querySelector('#overview-items').innerHTML,new RegExp('Saved revision '+index));
    results.push({requested_filter:filter,actual_filter:focused.getAttribute('data-overview-filter'),same_action:focused===current,actual_href:focused.getAttribute('href'),scroll_after:f.scroll()});
  }
  observations.push({case:'overview-filters',results,scroll_before:beforeScroll});
  assert.deepEqual(results.map(row=>row.actual_filter),filters,'Sharing #tasks must not silently switch the restored filter to the first pending link');
  for(const row of results){assert.equal(row.same_action,true);assert.equal(row.actual_href,'#tasks');assert.deepEqual(row.scroll_after,beforeScroll);}
}));

for(const action of ['open','dismiss'])test('home refresh retains the '+action+' onboarding action while its inline guide remains visible',()=>fixture(f=>{
  const selector='[data-getting-started] button[data-onboarding-'+action+']',previous=f.content.querySelector(selector),beforeScroll=f.scroll();
  assert.ok(previous,'The actual undismissed getting-started guide must render the action');assert.equal(previous.getAttribute('data-onboarding-'+action),'');previous.focus();
  f.state.tasks[0]={...f.state.tasks[0],data:{scope:'personal',title:'Updated saved task'}};preserveListViewport(f.render);
  const current=f.content.querySelector(selector),focused=f.document.activeElement;
  observations.push({case:'onboarding-'+action,old_control_connected:previous.isConnected,control_replaced:previous!==current,correct_action_focused:focused===current,actual_open:focused.getAttribute('data-onboarding-open'),actual_dismiss:focused.getAttribute('data-onboarding-dismiss'),scroll_before:beforeScroll,scroll_after:f.scroll()});
  assert.equal(previous.isConnected,false);assert.notEqual(previous,current);assert.match(f.content.querySelector('#overview-items').innerHTML,/Updated saved task/);
  assert.equal(focused===current,true,'The inline guide action must retain its own semantic target after the home markup is replaced');
  assert.equal(focused.getAttribute('data-onboarding-'+action),'');assert.equal(focused.getAttribute('data-onboarding-'+(action==='open'?'dismiss':'open')),null);assert.deepEqual(f.scroll(),beforeScroll);
}));
