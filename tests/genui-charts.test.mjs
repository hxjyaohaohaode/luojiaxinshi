import test from 'node:test';
import assert from 'node:assert/strict';
import {chartLayout} from '../static/genui/chart-layout.js';
test('chart series share the same x domain; grouped bars do not overlap',()=>{
  const data=[{x:'周一',y:2,series:'A'},{x:'周二',y:4,series:'A'},{x:'周一',y:3,series:'B'},{x:'周二',y:-1,series:'B'}];
  for(const width of [220,320,600]){const g=chartLayout('BarChart',data,width);assert.equal(g.domain.length,2);assert.equal(g.x(data[0].x),g.x(data[2].x));assert.ok(g.barX(data[0])+g.barWidth/2<=g.barX(data[2])-g.barWidth/2+.001);for(const d of data){assert.ok(g.barX(d)>g.left&&g.barX(d)<g.right);assert.ok(g.y(d.y)>=g.top&&g.y(d.y)<=g.bottom);}}
});
test('single scatter x remains centered and finite',()=>{const g=chartLayout('ScatterChart',[{x:4,y:0},{x:4,y:5}],260);assert.equal(g.x(4),(g.left+g.right)/2);assert.ok(Number.isFinite(g.y(0)));});
test('finite extreme values cannot create invalid SVG coordinates',()=>{const data=[{x:-1e308,y:-1e308},{x:1e308,y:1e308}],g=chartLayout('ScatterChart',data,260);for(const d of data){assert.ok(Number.isFinite(g.x(d.x)));assert.ok(Number.isFinite(g.y(d.y)));}});
