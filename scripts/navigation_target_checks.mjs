import assert from 'node:assert/strict';

// Render the real view modules in an isolated document: no login or user writes.
export async function verifyNavigationTargets(page,base='http://127.0.0.1:8765') {
  const errors=[];const onError=error=>errors.push(error.message);page.on('pageerror',onError);
  await page.goto(base+'/static/system/navigation-targets.css');
  await page.setContent(`<link rel="stylesheet" href="${base}/static/styles.css"><link rel="stylesheet" href="${base}/static/system/navigation-targets.css"><link rel="stylesheet" href="${base}/static/system/workspace-clarity.css"><main id="content"></main>`);
  await page.evaluate(async base=>{
    const {createLibraryUI}=await import(base+'/static/library.js');
    const {createOverview}=await import(base+'/static/overview.js');
    const notice={id:'notice-one',title:'可选择并复制的通知标题',status:'received',source_label:'合成来源',created_at:1800000000};
    const state={renderId:1,session:{user:{id:'navigation-test'}},notices:[notice],tasks:[]};
    const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
    const api=async route=>{
      if(route.startsWith('/notices/page?'))return {items:[notice],total:1,limit:50,next_cursor:null,has_more:false,snapshot:'navigation-fixture',filters:{},facets:{sources:['合成来源']}};
      if(route==='/source-catalog'||route==='/source-subscriptions')return [];
      throw Error('Unexpected navigation fixture request: '+route);
    };
    const common={state,api,esc,icon:()=>'<svg class="icon" aria-hidden="true"></svg>',moveSelection:()=>{},noticeRow:()=>'',empty:()=>''};
    window.targetViews={library:createLibraryUI(common),overview:createOverview({...common,taskRow:()=>'',reminders:{summary:()=>''}})};
    await window.targetViews.library.render();
  },base);
  const card=page.locator('a.notice-card');
  assert.equal(await card.count(),1);
  assert.equal(await card.locator('a,button,input,[tabindex]').count(),0);
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:900});
    const box=await card.boundingBox();
    await card.click({position:{x:8,y:8}});
    assert.ok(page.url().endsWith('#notice/notice-one'));
    await page.evaluate(()=>location.hash='');
    await card.focus();await page.keyboard.press('Enter');
    assert.ok(page.url().endsWith('#notice/notice-one'));
    assert.ok(box.x>=0&&box.x+box.width<=width+1);
  }
  await page.evaluate(()=>{document.querySelector('#content').innerHTML='';window.targetViews.overview.render();location.hash='';});
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:900});
    for(const [selector,route]of [['.home-counts>a[href="#tasks"]','tasks'],['.home-counts>a[href="#notices"]','notices'],['.home-agenda .home-section-heading>a','calendar']]){
      const link=page.locator(selector).first();assert.equal(await link.locator('a,button,input,[tabindex]').count(),0);
      const box=await link.boundingBox();assert.ok(box.height>=24&&box.width>=24&&box.x>=0&&box.x+box.width<=width+1);
      await link.click();assert.ok(page.url().endsWith('#'+route));await page.evaluate(()=>location.hash='');
      await link.focus();await page.keyboard.press('Enter');assert.ok(page.url().endsWith('#'+route));
    }
  }
  assert.deepEqual(errors,[]);page.off('pageerror',onError);
}
