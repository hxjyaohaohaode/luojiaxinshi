import test from 'node:test';
import assert from 'node:assert/strict';
import {createMemoryDrafts} from '../static/memory-drafts.js';
const storage=()=>{const s={};Object.defineProperties(s,{setItem:{value:(k,v)=>{s[k]=v;}},getItem:{value:k=>s[k]??null},removeItem:{value:k=>{delete s[k];}}});return s;};
test('reload recovers the exact Unicode draft and original version in the same tab',()=>{
 const s=storage(),a=createMemoryDrafts(s);a.select('alice');a.put('m','😀尚未保存\n中文',3,'原文');
 const b=createMemoryDrafts(s);b.select('alice');assert.equal(b.get('m').content,'😀尚未保存\n中文');assert.equal(b.get('m').version,3);
 b.remove('m');const c=createMemoryDrafts(s);c.select('alice');assert.equal(c.has('m'),false);
});
test('account switch and logout destroy prior private drafts',()=>{
 const s=storage(),a=createMemoryDrafts(s);a.select('alice');a.put('m','alice draft',1,'');a.select('bob');assert.equal(a.has('m'),false);
 a.select('alice');assert.equal(a.has('m'),false);a.put('m','another draft',2,'');a.clear();assert.equal(Object.keys(s).length,0);
});
test('new owner on reload removes other owner namespace',()=>{
 const s=storage(),a=createMemoryDrafts(s);a.select('alice');a.put('m','alice draft',1,'');const b=createMemoryDrafts(s);b.select('bob');assert.equal(Object.keys(s).length,0);
});
test('unavailable or malformed storage never blocks editing',()=>{
 const broken={getItem(){throw Error('denied');},setItem(){throw Error('full');},removeItem(){throw Error('denied');}};
 const a=createMemoryDrafts(broken);a.select('alice');a.put('m','draft',1,'');assert.equal(a.get('m').content,'draft');a.clear();
 const s=storage();s.setItem('campus-memory-drafts-v1:alice','{"bad":"shape"}');const b=createMemoryDrafts(s);b.select('alice');assert.equal(b.has('bad'),false);
});
test('unchanged content removes a draft and capacity stays bounded',()=>{
 const a=createMemoryDrafts(storage());a.select('alice');for(let i=0;i<25;i++)a.put('m'+i,'changed',1,'base');assert.equal(a.has('m0'),false);assert.equal(a.has('m24'),true);
 a.put('m24','base',1,'base');assert.equal(a.has('m24'),false);
});
