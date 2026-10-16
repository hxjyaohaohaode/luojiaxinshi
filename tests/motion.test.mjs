import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {motionAssets} from '../static/motion-assets.js';
import {brandMotion,loadingState,contextHint,beginRouteFeedback} from '../static/motion.js';

const provenance=JSON.parse(readFileSync(new URL('../static/assets/motion-provenance.json',import.meta.url),'utf8'));
const expected=['stroke','matrix','seal','radar','serene','routing','mesh','greeting','cascade','listening','search'];

test('all eleven approved animations retain the recorded original path geometry',()=>{
  assert.deepEqual(Object.keys(motionAssets),expected);
  for(const record of provenance){
    const asset=motionAssets[record.name],paths=[...asset.svg.matchAll(/\bd="([^"]*)"/g)].map(match=>match[1]);
    assert.equal(createHash('sha256').update(paths.join('\n')).digest('hex'),record.geometry_sha256,record.name);
    assert.ok(paths.length>8,record.name+' has its original detailed geometry');
    assert.doesNotMatch(asset.svg,/<script|<foreignObject|\bon\w+\s*=|\bstyle\s*=|https?:\/\/(?!www\.w3\.org)/i);
  }
});

test('repeated poses across panels have unique masks, gradients and self-contained references',()=>{
  const html=[...expected,...expected].map(name=>brandMotion(name)).join('');
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  assert.equal(new Set(ids).size,ids.length);
  for(const name of expected){
    const svg=brandMotion(name),ownIds=new Set([...svg.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]));
    const refs=[...svg.matchAll(/url\(#([^\)]+)\)|href="#([^"]+)"/g)].map(match=>match[1]||match[2]);
    for(const ref of refs)assert.ok(ownIds.has(ref),name+' references its own '+ref);
  }
});

test('every imported animation references an available keyframe and respects a local selector scope',()=>{
  const css=readFileSync(new URL('../static/motion-source.css',import.meta.url),'utf8');
  for(const match of css.matchAll(/\banimation:\s*([\w-]+)/g))assert.ok(css.includes('@keyframes '+match[1]+' '),match[1]);
  assert.doesNotMatch(css,/:root|\[data-theme=/);
  assert.match(css,/\.brand-motion\.motion-legacy \.anim-splash-2/);
  assert.match(css,/\.brand-motion\.motion-v2 \.anim-s04/);
});

test('status graphics stay decorative and feedback escapes text, without forged percentage progress',()=>{
  assert.doesNotMatch(brandMotion('seal','',{once:true}),/data-motion-once/);
  assert.match(brandMotion('mesh'),/aria-hidden="true"/);
  assert.throws(()=>brandMotion('unknown'),/Unknown brand motion/);
  const loading=loadingState('<img src=x onerror=alert(1)>','still loading');
  const feedback=loading.replace(/<svg\b[\s\S]*?<\/svg>/g,'');
  assert.match(feedback,/role="status"/);assert.match(feedback,/&lt;img/);assert.doesNotMatch(feedback,/<img|progressbar|100%/);
  const hint=contextHint('test','<script>','Use the original notice');
  assert.match(hint,/&lt;script&gt;/);assert.match(hint,/data-dismiss-hint/);
});

test('a superseded navigation cannot leave a loading overlay or erase the current pending route',()=>{
  const originalTimeout=globalThis.setTimeout,originalClear=globalThis.clearTimeout,originalDocument=globalThis.document;
  const timers=new Map(),hosts=[];let id=0;
  globalThis.setTimeout=(callback,delay)=>{const key=++id;timers.set(key,{callback,delay});return key;};
  globalThis.clearTimeout=key=>timers.delete(key);
  globalThis.document={createElement:()=>({isConnected:false,querySelector:()=>({set textContent(value){hosts.at(-1).text=value;}}),insertAdjacentHTML(_position,html){this.action=html;},remove(){this.isConnected=false;}})};
  const content={isConnected:true,before(host){host.isConnected=true;hosts.push(host);}};
  const runNext=()=>{const [key,timer]=[...timers].sort((a,b)=>a[1].delay-b[1].delay)[0];timers.delete(key);timer.callback();};
  let finish;
  try{
    const old=beginRouteFeedback(content,'first');
    finish=beginRouteFeedback(content,'second');
    old(); // A late finally from the first request must not cancel the second.
    assert.equal(timers.size,1);runNext();
    assert.equal(hosts.filter(host=>host.isConnected).length,1);assert.match(hosts[0].innerHTML,/second/);
    runNext();assert.match(hosts[0].text,/连接有些慢/);assert.match(hosts[0].action,/重新加载/);
    const newer=beginRouteFeedback(content,'third');
    assert.equal(hosts[0].isConnected,false);finish();finish=newer;
    runNext();assert.equal(hosts.filter(host=>host.isConnected).length,1);assert.match(hosts[1].innerHTML,/third/);
    finish();assert.equal(timers.size,0);assert.equal(hosts.filter(host=>host.isConnected).length,0);
  }finally{finish?.();globalThis.setTimeout=originalTimeout;globalThis.clearTimeout=originalClear;if(originalDocument===undefined)delete globalThis.document;else globalThis.document=originalDocument;}
});
