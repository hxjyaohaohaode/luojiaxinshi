import assert from 'node:assert/strict';

export async function verifyTaskListStability(page,targetId) {
  await page.waitForFunction(()=>document.querySelector('#task-results')?.getAttribute('aria-busy')==='false');
  const query=await page.locator('#task-search').inputValue();
  const expected=await page.locator('#task-results .task-row').evaluateAll(nodes=>nodes.map(node=>node.dataset.taskId));
  const count=await page.locator('#task-count').textContent();
  // This listener runs after the application's view click handler. Recording
  // real DOM nodes here catches a second replacement in an await continuation;
  // a locator resolved after click() alone would silently find the replacement.
  await page.evaluate(targetId=>{
    window.__taskListStability={};
    document.addEventListener('click',function observe(event){
      if(!event.target.closest('[data-task-view="board"]'))return;
      document.removeEventListener('click',observe);
      const row=document.querySelector('#task-results [data-task-id="'+CSS.escape(targetId)+'"]'),handle=row?.querySelector('[data-task-drag-handle]');
      window.__taskListStability={row,handle};handle?.focus({preventScroll:true});
    });
  },targetId);
  await page.locator('[data-task-view=board]').click();
  const stable=await page.evaluate(async targetId=>{
    const probe=window.__taskListStability,started=performance.now();
    while(performance.now()-started<350){
      await new Promise(requestAnimationFrame);
      if(!probe.row?.isConnected||!probe.handle?.isConnected||document.activeElement!==probe.handle)break;
    }
    return {recorded:!!probe.row,connected:!!probe.row?.isConnected,same:probe.row===document.querySelector('#task-results [data-task-id="'+CSS.escape(targetId)+'"]'),focused:document.activeElement===probe.handle};
  },targetId);
  assert.deepEqual(stable,{recorded:true,connected:true,same:true,focused:true},'An unchanged cached view must retain the row and keyboard focus after its click handler');
  await page.evaluate(()=>delete window.__taskListStability);
  await page.locator('a[href="#dashboard"]').first().click();
  await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='dashboard'&&!document.querySelector('#content').inert);
  await page.locator('a[href="#tasks"]').first().click();
  await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='tasks'&&!document.querySelector('#content').inert&&document.querySelector('#task-results')?.getAttribute('aria-busy')==='false');
  assert.equal(await page.locator('#task-search').inputValue(),query);
  assert.equal(await page.locator('#task-count').textContent(),count);
  assert.deepEqual(await page.locator('#task-results .task-row').evaluateAll(nodes=>nodes.map(node=>node.dataset.taskId)),expected,'Returning from the complete home projection restores the cached filtered task page');
}
