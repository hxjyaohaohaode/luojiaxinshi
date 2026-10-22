import test from 'node:test';
import assert from 'node:assert/strict';
import {listNavigationIndex} from '../static/reference-interactions.js';

test('list keyboard navigation stays inside the current list and handles an empty result',()=>{
 assert.equal(listNavigationIndex('ArrowUp',0,5),0);
 assert.equal(listNavigationIndex('ArrowDown',4,5),4);
 assert.equal(listNavigationIndex('ArrowDown',2,5),3);
 assert.equal(listNavigationIndex('Home',3,5),0);
 assert.equal(listNavigationIndex('End',0,5),4);
 assert.equal(listNavigationIndex('End',0,0),-1);
});
