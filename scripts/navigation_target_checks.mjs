import assert from 'node:assert/strict';

// Render the real view modules in an isolated document: no login or user writes.
export async function verifyNavigationTargets(page,base='http://127.0.0.1:8765') {
  const errors=[];const onError=error=>errors.push(error.message);page.on('pageerror',onError);
  await page.goto(base+'/static/system/navigation-targets.css');
  await page.setContent(`<link rel="stylesheet" href="${base}/static/styles.css"><link rel="stylesheet" href="${base}/static/system/navigation-targets.css"><main id="content"></main>`);
  await page.evaluate(async base=>{
    const {createLibraryUI}=await import(base+'/static/library.js');
    const {createOverview}=await import(base+'/static/overview.js');
    const state={session:{user:{id:'navigation-test'}},notices:[{id:'notice-one',title:'可选择并复制的通知标题',status:'received',source_label:'合成来源',created_at:1800000000}],tasks:[]};
    const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
    const common={state,esc,icon:()=>'<svg class="icon" aria-hidden="true"></svg>',moveSelection:()=>{},noticeRow:()=>'',empty:()=>''};
    window.targetViews={library:createLibraryUI(common),overview:createOverview({...common,taskRow:()=>'',reminders:{summary:()=>''}})};
    window.targetViews.library.render();
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
  const progress=page.locator('a#overview-progress');
  assert.equal(await progress.locator('a,button,input,[tabindex]').count(),0);
  await progress.click({position:{x:8,y:8}});assert.ok(page.url().endsWith('#insights'));
  await page.locator('a.week-heading').focus();await page.keyboard.press('Enter');assert.ok(page.url().endsWith('#calendar'));
  assert.ok((await page.locator('a.week-heading').boundingBox()).height>=44);
  await page.locator('[data-overview-day]').nth(1).click();assert.ok(page.url().endsWith('#calendar'));
  assert.equal(await page.locator('[data-overview-day]').nth(1).getAttribute('aria-pressed'),'true');
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:900});
    const layout=await progress.evaluate(n=>({padding:parseFloat(getComputedStyle(n).paddingLeft),width:n.getBoundingClientRect().width}));
    assert.ok(layout.padding>=14&&layout.width>100);
  }
  assert.deepEqual(errors,[]);page.off('pageerror',onError);
}
