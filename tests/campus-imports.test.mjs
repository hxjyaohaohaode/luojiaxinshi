import test from 'node:test';
import assert from 'node:assert/strict';
import {firstWeekMonday,publicSourceUrl,WHU_TIMETABLE_URL} from '../static/campus-imports.js';

test('term day is normalized to the first teaching Monday without device timezone shifts',()=>{
  assert.equal(firstWeekMonday('2026-09-09'),'2026-09-07');
  assert.equal(firstWeekMonday('2027-01-03'),'2026-12-28');
  assert.equal(firstWeekMonday('2026-02-30'),'');assert.equal(firstWeekMonday(''),'');
});
test('public search links cannot introduce active URL schemes or embedded credentials',()=>{
  for(const value of ['javascript:alert(1)','data:text/html,hi','https://user:secret@example.com/','https://example.com:1234/'])assert.equal(publicSourceUrl(value),'');
  assert.equal(publicSourceUrl('https://sres.whu.edu.cn/xxgk/tzgg.htm'),'https://sres.whu.edu.cn/xxgk/tzgg.htm');
  const u=new URL(WHU_TIMETABLE_URL);assert.equal(u.hostname,'jwgl.whu.edu.cn');assert.equal(u.searchParams.get('gnmkdm'),'N2151');
});
