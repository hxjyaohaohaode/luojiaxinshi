import test from 'node:test';
import assert from 'node:assert/strict';
import {groupNotices,filterNotices} from '../static/library.js';

test('matter grouping retains every matching notice without mixing different groups',()=>{
 const a={id:'a',matter:{id:'g1',title:'甲',member_count:3}},b={id:'b'},c={id:'c',matter:a.matter},d={id:'d',matter:{id:'g2',title:'乙',member_count:2}};
 const units=groupNotices([a,b,c,d]);assert.equal(units.length,3);assert.deepEqual(units.flatMap(u=>u.notices.map(n=>n.id)).sort(),['a','b','c','d']);assert.deepEqual(units[0].notices,[a,c]);assert.equal(units[2].matter.id,'g2');
});
test('grouping a filtered list does not reintroduce irrelevant or closed members',()=>{
 const g={id:'g',title:'同一事项',member_count:3},items=[{id:'a',title:'A',intent:'act',matter:g},{id:'b',title:'B',intent:'closed',matter:g},{id:'c',title:'C',intent:'irrelevant',matter:g}];
 const units=groupNotices(filterNotices(items,{intent:'act'}));assert.equal(units.length,1);assert.deepEqual(units[0].notices.map(n=>n.id),['a']);assert.equal(units[0].matter.member_count,3);
});
