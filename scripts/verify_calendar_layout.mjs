// Local synthetic HTTP fixture; no model calls or production data.
import {artifactPath} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={scenarios:[],errors:[]};
const sizes=JSON.parse(process.env.MVP_VIEWPORTS||'[[320,740],[390,844],[600,800],[640,900],[850,900],[851,800],[1024,800],[1181,900],[1440,900],[1920,1080],[844,390],[1024,540]]');
const auth=await engines.request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
let storageState;
try{
  const registered=await auth.post('/api/auth/register',{data:{username:'layout.'+Date.now(),password:'Layout-Verification-Only-2026',display_name:'虚构布局验收',accepted_terms:true}});
  if(!registered.ok())throw new Error('Fixture registration: '+registered.status());
  const session=await (await auth.get('/api/session')).json(),headers={'X-CSRF-Token':session.csrf};
  const profile=await auth.put('/api/profile',{headers,data:{semester:'2026—2027 学年秋季跨学院联合培养与专项实践第一学期',semester_start:'2026-11-01'}});
  if(!profile.ok())throw new Error('Fixture profile: '+profile.status());
  for(const [day,count] of [['01',1],['02',2],['03',3],['04',4],['30',8]])for(let i=0;i<count;i++){
    const date='2026-11-'+day;
    const response=await auth.post('/api/arrangements',{headers,data:{request_id:randomUUID(),data:{title:`虚构 ${day}-${i+1}｜跨学院项目材料核对与提交安排，含较长的地点和说明`,category:'personal',start_date:date,end_date:date,start_time:String(8+i).padStart(2,'0')+':00',end_time:String(9+i).padStart(2,'0')+':00',location:'虚构综合教学楼与线上材料窗口'}}});
    if(!response.ok())throw new Error('Fixture arrangement: '+response.status());
  }
  storageState=await auth.storageState();
}finally{await auth.dispose();}

// Inspect relationships between controls, rather than only document width.
async function layoutMetrics(page){
  return page.evaluate(()=>{
    const failures=[],rect=e=>e.getBoundingClientRect(),visible=e=>{const r=rect(e);return r.width>0&&r.height>0;};
    const rgba=value=>value.match(/[\d.]+/g).map(Number),luminance=color=>color.slice(0,3).map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4;}).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0);
    function contrast(element){
      const layers=[];for(let node=element;node;node=node.parentElement)layers.unshift(rgba(getComputedStyle(node).backgroundColor));
      const background=layers.reduce((base,layer)=>base.map((v,i)=>layer[i]*(layer[3]??1)+v*(1-(layer[3]??1))),[255,255,255]);
      const color=rgba(getComputedStyle(element).color),a=luminance(color),b=luminance(background);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    }
    const toolbar=document.querySelector('.calendar-toolbar'),buttons=[...toolbar.querySelectorAll('button')].filter(visible),bounds=rect(toolbar);
    for(const [i,button] of buttons.entries()){
      const box=rect(button),name=button.getAttribute('aria-label')||button.textContent.trim();
      if(box.left<bounds.left-1||box.right>bounds.right+1||box.top<bounds.top-1||box.bottom>bounds.bottom+1)failures.push('Toolbar control leaves its surface: '+name);
      if(box.width<39||box.height<39)failures.push('Toolbar touch target below 40px: '+name);
      if(button.classList.contains('icon-button')&&contrast(button)<3)failures.push('Toolbar icon contrast below 3:1: '+name);
      for(const other of buttons.slice(i+1)){
        const next=rect(other);
        if(Math.min(box.right,next.right)-Math.max(box.left,next.left)>1&&Math.min(box.bottom,next.bottom)-Math.max(box.top,next.top)>1)failures.push('Toolbar controls overlap: '+name+' / '+other.textContent.trim());
      }
      const hit=document.elementFromPoint((box.left+box.right)/2,(box.top+box.bottom)/2);
      if(!button.contains(hit))failures.push('Toolbar control is covered: '+name);
    }
    const title=toolbar.querySelector('.calendar-date-trigger');
    if(!title.querySelector('.calendar-term')&&(title.scrollWidth>title.clientWidth+1||title.scrollHeight>title.clientHeight+1))failures.push('Date title is clipped');
    for(const cell of document.querySelectorAll('.month-cell')){
      const list=cell.querySelector('.month-events'),total=Number(list.dataset.total),shown=[...list.querySelectorAll('.calendar-event')].filter(visible),more=list.querySelector('.calendar-more'),remaining=visible(more)?Number(more.textContent.match(/\d+/)?.[0]):0;
      if(shown.length+remaining!==total)failures.push('Hidden entries are not counted: '+cell.dataset.calendarCell);
      if(!total&&visible(more))failures.push('Empty day has a remainder');
      let bottom=rect(cell.querySelector('.month-date')).bottom;
      for(const button of [...shown,...(visible(more)?[more]:[])]){
        const box=rect(button),edge=rect(cell);
        if(box.top<bottom-1||box.bottom>edge.bottom-1||box.left<edge.left||box.right>edge.right+1)failures.push('Month control overlaps or is clipped: '+cell.dataset.calendarCell);
        if(button.scrollWidth>button.clientWidth+1&&button===more)failures.push('Remainder label is clipped');
        bottom=box.bottom;
      }
    }
    if(document.documentElement.scrollWidth>innerWidth+1)failures.push('Whole page overflows horizontally');
    return {failures:[...new Set(failures)],toolbarRows:getComputedStyle(toolbar).gridTemplateRows,monthRows:document.querySelector('.month-grid')?.childElementCount/7||0,mainWidth:Math.round(rect(document.querySelector('.calendar-main')).width)};
  });
}
async function settle(page){
  await page.mouse.move(1,1);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
}
async function selectDate(page,date){
  await page.locator('.calendar-toolbar [data-calendar-action=options]').click();
  await page.locator('#calendar-option-date').fill(date);await page.locator('#calendar-option-date').press('Tab');
  await page.locator('dialog .dialog-head [data-action=close-dialog]').click();
  await settle(page);
}
try{
for(const name of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
  const browser=await engines[name].launch({headless:true,executablePath:engines[name].executablePath()});
  try{
    const context=await browser.newContext({storageState,reducedMotion:'reduce'}),page=await context.newPage();
    page.on('pageerror',error=>report.errors.push({engine:name,error:error.message}));
    page.setDefaultTimeout(12000);
    for(const [width,height] of sizes){
      await page.setViewportSize({width,height});
      await page.goto(origin+'/#calendar');
      await page.waitForSelector('.calendar-toolbar');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});
      await selectDate(page,'2026-11-30');
      for(const view of ['month','week','day','list']){
        await page.locator(`[data-calendar-view=${view}]`).click();await settle(page);
        const result={engine:name,width,height,view,...await layoutMetrics(page)};
        if(view==='month'){
          const more=page.locator('[data-calendar-cell="2026-11-30"] .calendar-more');
          await more.scrollIntoViewIfNeeded();await more.click();
          const count=await page.locator('#calendar-body [data-calendar-event]').count();
          if(count!==8)result.failures.push('Remainder does not open all eight saved arrangements');
          await page.locator('[data-calendar-view=month]').click();await settle(page);
          if(name==='chromium'&&[320,390,1024,1440].includes(width))await page.screenshot({path:artifactPath(`calendar-${width}-${height}.png`),animations:'disabled'});
          const lastDate=page.locator('.month-date[data-calendar-day="2026-12-06"]');
          await lastDate.scrollIntoViewIfNeeded();await lastDate.focus();await page.keyboard.press('ArrowLeft');
          if(await page.locator('.month-date:focus').getAttribute('data-calendar-day')!=='2026-12-05')result.failures.push('Last calendar row is not keyboard reachable');
        }
        report.scenarios.push(result);console.log(name,width,height,view,result.failures.length?'FAIL':'pass');
      }
    }
    // Four-, five-, six-row months; sidebar drag and collapse change the
    // available width without changing the viewport or refreshing the page.
    await page.setViewportSize({width:1024,height:800});
    for(const [date,rows] of [['2027-02-14',4],['2026-10-18',5],['2026-11-30',6]]){
      await selectDate(page,date);await page.locator('[data-calendar-view=month]').click();await settle(page);
      const result={engine:name,label:date+' row geometry',...await layoutMetrics(page)};
      if(result.monthRows!==rows)result.failures.push('Incorrect month row count');report.scenarios.push(result);
    }
    for(const key of ['End','Home']){
      await page.locator('.sidebar-resize').press(key);await settle(page);
      report.scenarios.push({engine:name,label:'Sidebar width '+key,...await layoutMetrics(page)});
    }
    await page.locator('[data-shell-toggle]').first().click();await settle(page);
    report.scenarios.push({engine:name,label:'Sidebar collapsed',...await layoutMetrics(page)});
    await page.locator('[data-shell-toggle]').first().click();await settle(page);
    report.scenarios.push({engine:name,label:'Sidebar reopened',...await layoutMetrics(page)});
    await selectDate(page,'2026-11-03');await page.locator('[data-calendar-view=month]').click();
    await page.setViewportSize({width:1440,height:1200});await settle(page);
    const third=page.locator('[data-calendar-cell="2026-11-03"] .calendar-event').nth(2);
    await third.focus();await page.setViewportSize({width:1440,height:540});await settle(page);
    const focusedMore=await page.locator('[data-calendar-cell="2026-11-03"] .calendar-more').evaluate(e=>document.activeElement===e);
    const shrink={engine:name,label:'Focused preview follows remainder on height reduction',...await layoutMetrics(page)};
    if(!focusedMore)shrink.failures.push('Resizing left keyboard focus in a hidden preview');report.scenarios.push(shrink);
    await page.setViewportSize({width:1440,height:1200});await settle(page);
    const focusedDate=await page.locator('.month-date[data-calendar-day="2026-11-03"]').evaluate(e=>document.activeElement===e);
    const expand={engine:name,label:'Focused remainder follows date when all previews fit',...await layoutMetrics(page)};
    if(!focusedDate)expand.failures.push('Resizing left keyboard focus in a hidden remainder');report.scenarios.push(expand);
    await page.setViewportSize({width:320,height:740});await selectDate(page,'2026-11-02');
    await page.locator('[data-calendar-view=month]').click();await page.locator('.month-date[data-calendar-day="2026-11-02"]').focus();
    for(const direction of ['ArrowDown','ArrowUp']){
      for(let i=0;i<4;i++)await page.keyboard.press(direction);await settle(page);
      const focus=await page.evaluate(()=>{const node=document.activeElement,r=node.getBoundingClientRect(),body=document.querySelector('#calendar-body').getBoundingClientRect(),head=document.querySelector('.month-week').getBoundingClientRect();return {date:node.dataset.calendarDay,visible:r.bottom<=body.bottom+1&&r.top>=head.bottom-1};});
      const result={engine:name,label:'Month keyboard scrolling '+direction,...await layoutMetrics(page)};
      if(!focus.visible||focus.date!==(direction==='ArrowDown'?'2026-11-30':'2026-11-02'))result.failures.push('Keyboard selection is outside the visible month area');
      report.scenarios.push(result);
    }
    await context.close();
  }finally{await browser.close();}
}
}catch(error){report.errors.push({error:error.stack});}
report.passed=!report.errors.length&&report.scenarios.every(x=>!x.failures.length);
await writeFile(artifactPath('calendar-layout-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:report.passed,scenarios:report.scenarios.length,failed:report.scenarios.filter(x=>x.failures.length),errors:report.errors},null,2));
if(!report.passed)process.exitCode=1;
