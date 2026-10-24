import assert from 'node:assert/strict';

export async function verifyInsightData(page,base='http://127.0.0.1:8765') {
  await page.goto(base+'/static/system/insight-data.css');
  await page.setContent(`<link rel="stylesheet" href="${base}/static/styles.css"><link rel="stylesheet" href="${base}/static/system/insight-data.css"><main id="content" data-page="insights"></main>`);
  await page.evaluate(async base=>{
    const {createInsightsUI}=await import(base+'/static/insights.js');
    const state={renderId:1,session:{user:{id:'insight-owner',role:'user'}}};
    const model={calls:0,count:1,fail:false,hold:false,state};
    const data=()=>({generated_at:new Date().toISOString(),tasks:{done:0,pending:model.count,total:model.count,manual:model.count,from_ai:0,on_time:0,late:0},dimensions:{tasks:[{key:'pending',label:'待完成',count:model.count,kind:'tasks',ids:Array.from({length:model.count},(_,i)=>'task-'+i)}]},trend:[],horizon:[],sources:[],relevance:{}});
    const api=async()=>{model.calls++;if(model.hold)await new Promise(resolve=>model.release=resolve);if(model.fail)throw Error('合成网络错误');return data();};
    model.ui=createInsightsUI({state,api,esc:String,icon:()=>'<svg class="icon"></svg>',companion:()=>''});
    document.addEventListener('campus:insight-selection',event=>model.selection=event.detail);
    window.insightTest=model;await model.ui.render();
  },base);
  const metric=page.locator('[data-insight-selection="tasks:pending"]');
  assert.equal(await metric.locator('.number-face').textContent(),'1');
  await page.evaluate(()=>window.insightTest.count=2);
  await page.locator('[data-insight-refresh]').click();
  await page.waitForFunction(()=>document.querySelector('[data-insight-selection="tasks:pending"] .number-face')?.textContent==='2');
  await metric.focus();await page.keyboard.press('Enter');
  assert.deepEqual(await page.evaluate(()=>window.insightTest.selection),{kind:'tasks',ids:['task-0','task-1'],label:'待完成'});
  await page.evaluate(()=>{window.insightTest.count=3;document.dispatchEvent(new CustomEvent('campus:data-updated'));});
  await page.waitForFunction(()=>document.querySelector('[data-insight-selection="tasks:pending"] .number-face')?.textContent==='3');
  assert.equal(await metric.evaluate(node=>node===document.activeElement),true);
  await metric.evaluate(node=>window.insightTest.previousMetric=node);
  await page.evaluate(()=>window.insightTest.ui.render());
  assert.equal(await metric.evaluate(node=>node===window.insightTest.previousMetric),true);
  await page.evaluate(()=>window.insightTest.fail=true);await page.locator('[data-insight-refresh]').click();
  await page.waitForFunction(()=>document.querySelector('[data-insight-status]')?.textContent.includes('更新失败'));
  assert.equal(await metric.locator('.number-face').textContent(),'3');
  assert.equal(await page.locator('[data-insight-refresh]').isDisabled(),false);
  for(const width of [1440,390,320]){await page.setViewportSize({width,height:800});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);}
  await page.evaluate(()=>{window.insightTest.fail=false;window.insightTest.hold=true;window.insightTest.ui.render();});
  await page.waitForFunction(()=>!!window.insightTest.release);
  await page.evaluate(()=>{window.insightTest.state.renderId++;document.querySelector('#content').innerHTML='<p>已切换页面</p>';window.insightTest.release();});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('#content').textContent(),'已切换页面');
  await page.evaluate(async()=>{window.insightTest.hold=false;await window.insightTest.ui.render();window.insightTest.beforeNavigationCalls=window.insightTest.calls;document.dispatchEvent(new CustomEvent('campus:data-updated'));window.insightTest.state.renderId++;document.querySelector('#content').dataset.page='settings';document.querySelector('#content').innerHTML='<p>个人设置</p>';});
  await page.waitForTimeout(500);
  assert.equal(await page.locator('#content').textContent(),'个人设置');
  assert.equal(await page.evaluate(()=>window.insightTest.calls),await page.evaluate(()=>window.insightTest.beforeNavigationCalls));
}

export async function verifyInsightNavigation({page,api,nav}) {
  await nav('insights');await page.locator('[data-insight-selection="tasks:pending"]').waitFor();
  const data=await api('/insights'),pending=data.dimensions.tasks.find(row=>row.key==='pending');
  await page.locator('[data-insight-selection="tasks:pending"]').click();
  await page.locator('#task-insight-filter').waitFor();
  assert.equal(await page.locator('#task-count').textContent(),pending.count+' 项');
  await page.locator('#task-insight-filter [data-action="clear-task-filters"]').click();
  assert.equal(await page.locator('#task-count').textContent(),(await api('/tasks')).length+' 项');
  assert.equal(await page.locator('#task-insight-filter').textContent(),'');
  await nav('insights');await page.locator('[data-insight-selection="notices:all"]').waitFor();
  const current=await api('/insights'),notice=current.dimensions.notices.find(row=>row.key!=='all'&&row.count>0)||current.dimensions.notices[0];
  await page.locator('[data-insight-selection="notices:'+notice.key+'"]').click();
  await page.locator('#library-filter-note [data-library-reset]').waitFor();
  assert.equal(await page.locator('#library-count').textContent(),notice.count+' / '+current.notices.total+' 则');
  await page.locator('#library-filter-note [data-library-reset]').click();
  assert.equal(await page.locator('#library-count').textContent(),current.notices.total+' / '+current.notices.total+' 则');
  assert.equal(await page.locator('#library-filter-note').textContent(),'');
}
