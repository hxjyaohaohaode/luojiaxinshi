import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {legalMarkup} from '../static/legal.js';

// Run the production anonymous route, legal renderer and retry click handler.
// A controlled root and deferred /legal reads expose navigation/session races;
// the separate browser gate verifies these transitions with the actual DOM.
const source=await readFile(new URL('../static/app.js',import.meta.url),'utf8');
const between=(start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);};
const declaration=start=>{const line=source.split('\n').find(value=>value.startsWith(start));assert.ok(line);return line;};
const legalSource=between('async function legalInfo()', '\nasync function deleteAccountDialog(');
const standaloneSource=between('async function standaloneLegal(', '\nfunction modelDialog(');
const routeSource=between('async function route(){', '\nfunction simplifyPageHeading(');
const clickSource=between('async function handleClick(', "\ndocument.addEventListener('click',handleClick);");
const requestSource=(await readFile(new URL('../static/ui-request.js',import.meta.url),'utf8')).split('\nconst pending=')[0].replace('export function','function');
const info={version:'2026-11-14-r2',operator_name:'合成审查团队',operator_contact:'team@example.invalid',model_provider:'合成提供方',backup_retention_days:7};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

function fixture(kind='privacy'){
  const state={session:null,renderId:0,dialogRequest:0,invite:''},location={hash:'#'+kind};
  const app={innerHTML:'<form id="auth-form">原登录表单</form>'},dialog={open:false,close(){this.open=false;}};
  const reads=[],animations=[],toasts=[];
  const $=selector=>selector==='#app'?app:selector==='#dialog'?dialog:null;
  const sandbox={state,location,$,legalMarkup,console,searchTimer:undefined,clearTimeout(){},
    document:{activeElement:null,querySelector:()=>null},
    reviewObserver:{leave(){}},persistCurrentForms(){},drafts:{async flushAll(){}},
    sessionStorage:{setItem(){},removeItem(){}},history:{replaceState(_state,_title,hash){location.hash=hash;}},
    authPage(){app.innerHTML='<form id="auth-form">'+location.hash+'</form>';},
    api(path){assert.equal(path,'/legal');const read=deferred();reads.push(read);return read.promise;},
    icon:()=>'',choreograph:root=>animations.push(root.innerHTML),toast:(message,error)=>toasts.push({message,error}),
  };
  vm.createContext(sandbox);
  vm.runInContext([declaration('const esc = '),declaration('const button = '),declaration('const empty='),requestSource,legalSource,standaloneSource,routeSource,clickSource].join('\n'),sandbox);
  return {state,location,app,reads,animations,toasts,
    route:()=>sandbox.route(),
    navigate:hash=>{location.hash=hash;return sandbox.route();},
    retry(){
      assert.match(app.innerHTML,/data-action="refresh"/);
      const target={dataset:{action:'refresh'},disabled:false,isConnected:true,closest:()=>null};
      return sandbox.handleClick({target:{closest:()=>target}});
    },
  };
}

for(const kind of ['privacy','terms'])test('the current anonymous '+kind+' route renders the real document and a login link',async()=>{
  const f=fixture(kind),pending=f.route();f.reads[0].resolve(info);await pending;
  assert.match(f.app.innerHTML,new RegExp('<h1>'+(kind==='terms'?'用户协议':'隐私政策')+'</h1>'));
  assert.match(f.app.innerHTML,/2026 年 11 月 14 日（修订 2）/);
  assert.match(f.app.innerHTML,/href="#login"/);assert.match(f.app.innerHTML,/返回登录/);
  assert.equal(f.animations.length,1);assert.equal(f.state.session,null);
});

test('cached legal information still supports switching between both anonymous documents',async()=>{
  const f=fixture(),first=f.route();f.reads[0].resolve(info);await first;
  await f.navigate('#terms');assert.equal(f.reads.length,1);assert.match(f.app.innerHTML,/<h1>用户协议<\/h1>/);
});

test('a delayed anonymous legal response cannot replace a later login route',async()=>{
  const f=fixture(),pending=f.route();await f.navigate('#login');const later=f.app.innerHTML;
  f.reads[0].resolve(info);await pending;
  assert.equal(f.app.innerHTML,later);assert.equal(f.animations.length,0);assert.equal(f.location.hash,'#login');
});

test('an adopted session blocks the anonymous legal result even before the next route starts',async()=>{
  const f=fixture(),pending=f.route(),accepted={user:{id:'accepted-owner'}};
  f.state.session=accepted;f.app.innerHTML='已登录的协议工作区';const later=f.app.innerHTML;
  f.reads[0].resolve(info);await pending;
  assert.equal(f.app.innerHTML,later);assert.equal(f.state.session,accepted);assert.equal(f.animations.length,0);
});

test('a changed hash blocks the old legal result before the hashchange route callback runs',async()=>{
  const f=fixture(),pending=f.route();f.location.hash='#recover';f.app.innerHTML='稍后将显示找回密码';
  f.reads[0].resolve(info);await pending;
  assert.equal(f.app.innerHTML,'稍后将显示找回密码');assert.equal(f.animations.length,0);
});

test('a newer render at the same anonymous hash also blocks the old legal result',async()=>{
  const f=fixture(),pending=f.route();f.state.renderId++;f.app.innerHTML='同一地址的较新页面';
  f.reads[0].resolve(info);await pending;
  assert.equal(f.app.innerHTML,'同一地址的较新页面');assert.equal(f.animations.length,0);
});

test('reverse completion of privacy then terms keeps the newer terms page',async()=>{
  const f=fixture(),privacy=f.route(),terms=f.navigate('#terms');
  f.reads[1].resolve(info);await terms;const later=f.app.innerHTML;
  f.reads[0].resolve(info);await privacy;
  assert.equal(f.app.innerHTML,later);assert.match(later,/<h1>用户协议<\/h1>/);assert.equal(f.animations.length,1);
});

test('a stale legal failure settles without replacing or reporting an error on the later login route',async()=>{
  const f=fixture(),pending=f.route();await f.navigate('#login');const later=f.app.innerHTML;
  f.reads[0].reject(new Error('旧请求断开'));await assert.doesNotReject(pending);
  assert.equal(f.app.innerHTML,later);assert.equal(f.animations.length,0);assert.deepEqual(f.toasts,[]);
});

test('a stale legal failure cannot affect a newly adopted session at the same hash',async()=>{
  const f=fixture(),pending=f.route(),accepted={user:{id:'accepted-owner'}};
  f.state.session=accepted;f.app.innerHTML='已登录的协议工作区';
  f.reads[0].reject(new Error('旧匿名请求失败'));await assert.doesNotReject(pending);
  assert.equal(f.app.innerHTML,'已登录的协议工作区');assert.equal(f.state.session,accepted);assert.equal(f.animations.length,0);assert.deepEqual(f.toasts,[]);
});

for(const kind of ['privacy','terms'])test('a current '+kind+' failure offers a working route retry and never fabricates policy content',async()=>{
  const f=fixture(kind),pending=f.route();f.reads[0].reject(new Error('连接断开'));await assert.doesNotReject(pending);
  assert.match(f.app.innerHTML,/暂时|未能|无法/);assert.match(f.app.innerHTML,/href="#login"/);
  assert.doesNotMatch(f.app.innerHTML,/class="legal-body"|版本 2026/);assert.equal(f.state.legal,undefined);
  const retry=f.retry();assert.equal(f.reads.length,2);f.reads[1].resolve(info);await retry;
  assert.match(f.app.innerHTML,new RegExp('<h1>'+(kind==='terms'?'用户协议':'隐私政策')+'</h1>'));
  assert.match(f.app.innerHTML,/版本 2026/);assert.doesNotMatch(f.app.innerHTML,/data-action="refresh"/);assert.deepEqual(f.toasts,[]);
});
