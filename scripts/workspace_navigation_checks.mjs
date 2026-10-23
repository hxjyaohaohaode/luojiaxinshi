import assert from 'node:assert/strict';
import path from 'node:path';

// Called inside the owned synthetic workspace suite, in all three engines.
export async function verifyWorkspaceNavigation({page,api,nav,resize,check,out,engine}){
  const start=await api('/memory/tree'),tag='目录验收 '+engine+' '+Date.now();
  let parent=start.root_id;const folders=[];
  for(const title of [tag,'课程资料','准备事项.docx']){const n=await api('/memory/tree/folders','POST',{parent_id:parent,title});folders.push(n);parent=n.id;}
  const memory=await api('/memory/items','POST',{content:tag+'：先核对材料，再安排个人行动。',kind:'intention'});
  await api('/memory/tree/placements','PUT',{node_id:parent,items:[{id:memory.id,version:memory.version}]});
  await nav('memory');await page.locator('#memory-tree-nav').waitFor();
  const label=id=>page.locator(`#memory-tree-nav [data-tree-node="${id}"]`);
  const item=id=>page.locator(`#memory-tree-nav [data-tree-id="${id}"]`);
  for(const n of folders.slice(0,-1)){await page.locator(`[data-tree-expand="${n.id}"]`).click();await label(folders[folders.indexOf(n)+1].id).waitFor();}
  await label(parent).click();await page.locator(`[data-tree-record="${memory.id}"]`).waitFor();
  await check('memory tree indents actual nested folders under the enforced CSP',async()=>{
    const ids=[start.root_id,...folders.map(n=>n.id)];
    await page.waitForFunction(ids=>!document.querySelector('.memory-tree-main[aria-busy="true"]')&&ids.every(id=>document.querySelector(`#memory-tree-nav [data-tree-node="${id}"] .memory-type-icon`)?.getBoundingClientRect().width>0),ids);
    const boxes=await page.evaluate(ids=>ids.map(id=>{const r=document.querySelector(`#memory-tree-nav [data-tree-node="${id}"] .memory-type-icon`).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}),ids);
    for(let i=1;i<boxes.length;i++)assert.ok(boxes[i].x-boxes[i-1].x>=16&&boxes[i].x-boxes[i-1].x<=24,JSON.stringify(boxes));
    const g=await page.locator('#memory-tree-nav').evaluate(el=>{const row=el.querySelector('.memory-tree-root'),r=row.getBoundingClientRect(),b=el.getBoundingClientRect();return {left:r.left-b.left,right:b.right-r.right,overflow:document.documentElement.scrollWidth-innerWidth,lines:[...el.querySelectorAll('[role="group"]')].map(n=>getComputedStyle(n).borderLeftWidth),shadow:getComputedStyle(el.querySelector('[aria-selected="true"]>.memory-tree-node')).boxShadow};});
    assert.ok(g.left<=2&&g.right<=2&&g.overflow<=1,JSON.stringify(g));assert.equal(g.shadow,'none');assert.ok(g.lines.every(v=>parseFloat(v)===0));
    assert.equal(await label(parent).locator('[data-memory-icon="folder"]').count(),1,'A user directory named .docx remains a directory');
    assert.equal(await page.locator(`[data-tree-record="${memory.id}"] [data-memory-icon="intention"]`).count(),1);
    await page.screenshot({animations:'disabled',path:path.join(out,engine+'-memory-tree-desktop.png')});
  });
  await check('folder collapse preserves a reachable focus target and keyboard follows displayed order',async()=>{
    await label(folders[0].id).focus();await page.keyboard.press('ArrowLeft');assert.equal(await item(folders[0].id).getAttribute('aria-expanded'),'false');assert.equal(await label(parent).count(),0);
    assert.equal(await page.locator('#memory-tree-nav [data-tree-node][tabindex="0"]').count(),1);
    assert.equal(await label(folders[0].id).locator('[data-memory-icon="folder"]').count(),1);
    await page.keyboard.press('ArrowRight');await label(folders[1].id).waitFor();assert.equal(await label(folders[0].id).locator('[data-memory-icon="folder-open"]').count(),1);
    await page.keyboard.press('Home');await page.keyboard.press('ArrowRight');
    const target=await page.locator('#memory-tree-nav > [role="treeitem"] > [role="group"] > [role="treeitem"] > .memory-tree-node > [data-tree-node]').first().getAttribute('data-tree-node');
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.treeNode),target);
  });
  await check('workspace toggle, title and search share their center with the sidebar open or collapsed',async()=>{
    for(const collapsed of [true,false]){
      if(await page.locator('.shell').evaluate(el=>el.classList.contains('sidebar-collapsed'))!==collapsed)await page.locator('.workspace-chrome-toggle').click();
      await page.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));
      const g=await page.evaluate(()=>{const center=s=>{const r=document.querySelector(s).getBoundingClientRect();return r.top+r.height/2;};return {toggle:center('.workspace-chrome-toggle'),title:center('.topbar-left b'),search:center('.topbar-right .workspace-search')};});
      assert.ok(Math.abs(g.toggle-g.title)<2&&Math.abs(g.toggle-g.search)<2,JSON.stringify(g));
    }
  });
  await check('memory navigation fits narrow viewports without clipping the whole page',async()=>{
    try{for(const width of [390,320]){await resize({width,height:740});await page.locator('[data-tree-action="toggle-nav"]').click();await page.locator('#memory-tree-sidebar').waitFor();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));const g=await page.locator('.workspace-chrome-toggle').boundingBox(),title=await page.locator('.topbar-left b').boundingBox();assert.ok(Math.abs(g.y+g.height/2-title.y-title.height/2)<2);await page.screenshot({animations:'disabled',path:path.join(out,engine+'-memory-tree-'+width+'.png')});await page.locator('[data-tree-action="toggle-nav"]').click();}}finally{await resize({width:1413,height:871});}
  });
  await check('nested settings support cancel, undo and redo without saving',async()=>{
    const before=await api('/memory/settings');
    await page.locator('[data-tree-action="manage"]').click();await page.locator('[data-memory-studio="settings"]').click();await page.locator('#memory-settings-form [data-dialog-cancel]').waitFor();
    const mode=page.locator('#memory-settings-form [name="mode"]'),next=before.mode==='manual'?'auto':'manual';
    await mode.selectOption(next);await page.locator('#memory-settings-form [data-form-undo]').click();assert.equal(await mode.inputValue(),before.mode);
    await page.locator('#memory-settings-form [data-form-redo]').click();assert.equal(await mode.inputValue(),next);
    await page.locator('#memory-settings-form [data-dialog-cancel]').click();await page.locator('.memory-management-hub').waitFor();assert.deepEqual(await api('/memory/settings'),before);
    await page.locator('[data-memory-studio="settings"]').click();assert.equal(await mode.inputValue(),before.mode);await page.locator('#dialog [data-dialog-back]').click();await page.locator('.memory-management-hub').waitFor();
    await page.locator('#dialog [data-action="close-dialog"]').click();await page.locator('#dialog').waitFor({state:'hidden'});
  });
  await check('saved settings undo is acknowledged by the server and rejects a newer version',async()=>{
    const before=await api('/memory/settings');
    const open=async()=>{await page.locator('[data-tree-action="manage"]').click();await page.locator('[data-memory-studio="settings"]').click();await page.locator('#memory-settings-form [name="mode"]').selectOption(before.mode==='manual'?'auto':'manual');await page.locator('#memory-settings-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.locator('#toast .toast-action').waitFor();};
    await open();const saved=await api('/memory/settings');assert.notEqual(saved.mode,before.mode);await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('#toast .toast-copy')?.textContent==='已撤销。');
    const restored=await api('/memory/settings');assert.equal(restored.mode,before.mode);assert.ok(restored.version>saved.version);
    await open();const savedAgain=await api('/memory/settings'),newer=await api('/memory/settings','PUT',{...savedAgain,mode:'off'});await page.locator('#toast .toast-action').click();await page.locator('#toast.error').waitFor();assert.equal((await api('/memory/settings')).mode,'off');assert.equal((await api('/memory/settings')).version,newer.version);
    await api('/memory/settings','PUT',{...before,version:newer.version});await page.locator('#toast [data-toast-close]').click();
  });
  await check('profile save undo restores only changed fields and keeps unrelated newer changes',async()=>{
    await nav('settings');const before=(await api('/session')).user.profile;
    await page.locator('[data-action="settings-preferences"]').click();await page.locator('#preferences-form [name="preferred_name"]').fill('合成撤销验收');await page.locator('#preferences-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.locator('#toast .toast-action').waitFor();
    assert.equal((await api('/session')).user.profile.preferred_name,'合成撤销验收');
    const changed=before.response_style==='direct'?'warm':'direct';await api('/profile','PATCH',{changes:{response_style:changed},expected:{response_style:before.response_style}});
    await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('#toast .toast-copy')?.textContent==='已撤销。');
    const after=(await api('/session')).user.profile;assert.equal(after.preferred_name,before.preferred_name);assert.equal(after.response_style,changed);
  });
  await check('new calendar entry can be cancelled before saving and undone after saving',async()=>{
    await nav('calendar');const before=(await api('/arrangements')).map(r=>r.id);
    await page.locator('[data-calendar-action="new"]').first().click();await page.locator('#arrangement-form [name="title"]').fill('取消这项合成安排');await page.locator('#arrangement-form [data-dialog-cancel]').click();await page.locator('#dialog').waitFor({state:'hidden'});assert.deepEqual((await api('/arrangements')).map(r=>r.id),before);
    await page.locator('[data-calendar-action="new"]').first().click();await page.locator('#arrangement-form [name="title"]').fill(tag+' 撤销安排');await page.locator('#arrangement-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.locator('#toast .toast-action').waitFor();assert.equal((await api('/arrangements')).length,before.length+1);
    await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('#toast .toast-copy')?.textContent==='已撤销。');assert.deepEqual((await api('/arrangements')).map(r=>r.id),before);
  });
  await check('saved memory text undo restores the prior revision through the real API',async()=>{
    await nav('memory');await page.locator(`[data-tree-record="${memory.id}"]`).click();await page.locator('[data-tree-action="edit-inline"]').click();await page.locator('#memory-inline-editor [name="content"]').fill(tag+'：已修改的合成正文。');await page.locator('#memory-inline-editor [type="submit"]').click();await page.locator('#memory-inline-editor').waitFor({state:'detached'});await page.locator('#toast .toast-action').waitFor();
    assert.notEqual((await api('/memory/items/'+memory.id)).content,memory.content);await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('#toast .toast-copy')?.textContent==='已撤销。');assert.equal((await api('/memory/items/'+memory.id)).content,memory.content);
  });
  await check('interactive answer preference undo persists the previous preference',async()=>{
    await nav('settings');const before=(await api('/session')).genui;await page.locator('[data-action="settings-genui"]').click();await page.locator('#genui-settings-form [name="enabled"]').setChecked(!before.enabled);await page.locator('#genui-settings-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.locator('#toast .toast-action').waitFor();assert.equal((await api('/session')).genui.enabled,!before.enabled);await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('#toast .toast-copy')?.textContent==='已撤销。');assert.equal((await api('/session')).genui.enabled,before.enabled);
  });
  await check('task edit undo restores the saved title and state with a fresh version',async()=>{
    const task=(await api('/tasks')).find(t=>t.status==='pending'&&t.data.scope==='personal');assert.ok(task);
    await nav('tasks');await page.evaluate(id=>{location.hash='#tasks/'+id;},task.id);await page.locator('#workflow-form').waitFor();await page.locator('[data-workflow-tab=history]').click();await page.locator(`#workflow-form [data-action="edit-task"][data-id="${task.id}"]`).click();await page.locator('#task-form [name="title"]').fill(tag+' 待办修改');await page.locator('#task-form [name="reason"]').fill('合成撤销验收');await page.locator('#task-form [type="submit"]').click();await page.locator('#dialog').waitFor({state:'hidden'});await page.locator('#toast .toast-action').waitFor();
    const saved=(await api('/tasks')).find(t=>t.id===task.id);assert.equal(saved.data.title,tag+' 待办修改');await page.locator('#toast .toast-action').click();await page.waitForFunction(()=>document.querySelector('#toast .toast-copy')?.textContent==='已撤销。');const restored=(await api('/tasks')).find(t=>t.id===task.id);assert.equal(restored.data.title,task.data.title);assert.equal(restored.status,task.status);assert.ok(restored.version>saved.version);
  });
  const calendarDates=['2026-11-03','2026-11-04'],calendarRecords=[];
  for(const date of calendarDates)calendarRecords.push(await api('/arrangements','POST',{request_id:crypto.randomUUID(),data:{title:tag+' '+date,category:'personal',start_date:date,end_date:date,start_time:'09:00',end_time:'10:00'}}));
  await nav('tasks');await nav('calendar');
  await check('mini calendar filters the selected day while keeping the list view',async()=>{
    await page.locator('[data-calendar-action="options"]').click();await page.locator('#calendar-option-date').fill(calendarDates[0]);await page.locator('#calendar-option-date').press('Tab');await page.locator('#dialog .dialog-head [data-action="close-dialog"]').click();
    await page.locator('[data-calendar-view="list"]').click();await page.locator('#calendar-query').fill(tag);
    assert.equal(await page.locator('.calendar-agenda .agenda-row').count(),2);
    await page.locator('#calendar-mini [data-calendar-day="'+calendarDates[0]+'"]').click();
    assert.equal(await page.locator('#calendar-body').getAttribute('data-view'),'list');assert.equal(await page.locator('.calendar-agenda .agenda-row').count(),1);assert.ok((await page.locator('.calendar-agenda .agenda-title').textContent()).includes(calendarDates[0]));
    await page.locator('#calendar-mini [data-calendar-day="2026-11-02"]').click();assert.equal(await page.locator('#calendar-body').getAttribute('data-view'),'list');assert.equal(await page.locator('.calendar-agenda .agenda-row').count(),0);assert.equal(await page.locator('.calendar-empty').isVisible(),true);
    await page.locator('[data-calendar-action="list-month"]').click();assert.equal(await page.locator('.calendar-agenda .agenda-row').count(),2);
    await page.locator('[data-calendar-view="week"]').click();await page.locator('#calendar-mini [data-calendar-day="'+calendarDates[1]+'"]').click();assert.equal(await page.locator('#calendar-body').getAttribute('data-view'),'day');assert.equal(await page.locator('.time-day').getAttribute('data-day'),calendarDates[1]);
  });
  await check('calendar removes redundant rows, keeps compact controls and a neutral search focus',async()=>{
    assert.equal(await page.locator('.calendar-context,#calendar-active-filters').count(),0);
    const toolbar=await page.locator('.calendar-toolbar').boundingBox();assert.ok(toolbar.height<=54,JSON.stringify(toolbar));
    await page.locator('#calendar-query').focus();const g=await page.locator('#calendar-query').evaluate(el=>({outline:getComputedStyle(el).outlineStyle,shadow:getComputedStyle(el).boxShadow,outer:getComputedStyle(el.parentElement).boxShadow}));assert.equal(g.outline,'none');assert.equal(g.shadow,'none');assert.equal(g.outer,'none');
    await page.screenshot({animations:'disabled',path:path.join(out,engine+'-calendar-desktop.png')});
  });
  await check('date picker keeps keyboard focus across month changes and fits desktop and mobile',async()=>{
    await page.locator('#calendar-title').click();await page.locator('#picker-year').selectOption('2027');assert.equal(await page.locator('#picker-year').evaluate(n=>n===document.activeElement),true);
    await page.locator('#picker-month').selectOption('02');assert.equal(await page.locator('#picker-month').evaluate(n=>n===document.activeElement),true);
    assert.equal(await page.locator('.picker-days .outside').count(),14,'February outside days follow the displayed month');
    const box=await page.locator('#dialog').boundingBox();assert.ok(box.width<=482);
    await page.screenshot({animations:'disabled',path:path.join(out,engine+'-date-picker-desktop.png')});
    try{await resize({width:320,height:740});const bounds=await page.locator('#dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=321);assert.equal(await page.locator('#dialog').evaluate(n=>n.scrollWidth<=n.clientWidth+1),true);await page.screenshot({animations:'disabled',path:path.join(out,engine+'-date-picker-320.png')});}finally{await resize({width:1413,height:871});}
    await page.locator('[data-calendar-action="picker-date"][data-day="2027-02-09"]').click();assert.equal(await page.locator('#calendar-body').getAttribute('data-view'),'day');assert.equal(await page.locator('.time-day').getAttribute('data-day'),'2027-02-09');assert.equal(await page.locator('#calendar-title').evaluate(n=>n===document.activeElement),true);
  });
  await check('calendar navigation stays reachable at narrow and short viewport sizes',async()=>{
    try{for(const [width,height] of [[320,740],[390,740],[844,390]]){
      await resize({width,height});
      const issues=await page.locator('.calendar-toolbar').evaluate(toolbar=>{const b=toolbar.getBoundingClientRect(),buttons=[...toolbar.querySelectorAll('button')].filter(n=>n.getBoundingClientRect().width>0);return buttons.flatMap((n,i)=>{const r=n.getBoundingClientRect(),label=n.ariaLabel||n.textContent,errors=[];if(r.left<b.left-1||r.right>b.right+1||r.top<b.top-1||r.bottom>b.bottom+1)errors.push(label+' outside toolbar');if(r.width<39||r.height<39)errors.push(label+' small target');for(const other of buttons.slice(i+1)){const o=other.getBoundingClientRect();if(Math.min(r.right,o.right)-Math.max(r.left,o.left)>1&&Math.min(r.bottom,o.bottom)-Math.max(r.top,o.top)>1)errors.push(label+' overlaps '+other.textContent);}return errors;});});assert.deepEqual(issues,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({animations:'disabled',path:path.join(out,engine+'-calendar-'+width+'.png')});
    }}finally{await resize({width:1413,height:871});}
  });
  await check('root pages have no Back button; child pages return to their actual parent and retain drafts',async()=>{
    for(const route of ['tasks','notices','sources','settings','calendar','dashboard']){await nav(route);assert.equal(await page.locator('.workspace-back:visible').count(),0,route+' is a root page');}
    await nav('notices');await nav('new');await page.locator('#notice-form [name="body"]').fill('返回后保留的合成通知草稿');assert.equal(await page.locator('.workspace-back:visible').getAttribute('aria-label'),'返回通知资料');await page.locator('.workspace-back:visible').click();await page.waitForFunction(()=>location.hash==='#notices'&&!document.querySelector('#content').inert);await nav('new');assert.equal(await page.locator('#notice-form [name="body"]').inputValue(),'返回后保留的合成通知草稿');
    await nav('settings');await nav('memory');await page.locator('.workspace-back:visible').click();await page.waitForFunction(()=>location.hash==='#settings'&&document.querySelector('#content').dataset.page==='settings'&&!document.querySelector('#content').inert);assert.equal(await page.locator('.workspace-back:visible').count(),0);
    const conversation=await api('/conversations','POST',{title:tag+' 返回验收'});await nav('chat/'+conversation.id);assert.equal(await page.locator('.workspace-back:visible').count(),0);await page.locator('#chat-input').fill('离开后保留的合成草稿');await nav('settings');await nav('chat/'+conversation.id);assert.equal(await page.locator('#chat-input').inputValue(),'离开后保留的合成草稿');
  });
  await check('a directly opened child returns to its real parent without manufacturing a root parent',async()=>{
    await page.goto('http://127.0.0.1:8786/?direct-navigation='+Date.now()+'#memory');await page.locator('#memory-tree-nav').waitFor();await page.locator('.workspace-back:visible').click();await page.waitForFunction(()=>location.hash==='#settings'&&document.querySelector('#content').dataset.page==='settings'&&!document.querySelector('#content').inert);assert.equal(await page.locator('.workspace-back:visible').count(),0);
  });
  for(const record of calendarRecords)await api('/arrangements/'+record.id,'DELETE',{version:record.version});
}
