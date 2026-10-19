import {artifactPath} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={scenarios:[],errors:[]};
const sizes=JSON.parse(process.env.MVP_VIEWPORTS||'[{"width":390,"height":844},{"width":1440,"height":900}]');

try{
for(const name of (process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',')){
  const auth=await engines.request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
  let storageState,headers;
  try{
    const registered=await auth.post('/api/auth/register',{data:{username:'draft.'+name+'.'+Date.now(),password:'Draft-Verification-Only-2026',display_name:'虚构草稿验收',accepted_terms:true}});
    if(!registered.ok())throw new Error('Isolated test account creation failed: '+registered.status());
    const session=await (await auth.get('/api/session')).json();headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};storageState=await auth.storageState();
  }finally{await auth.dispose();}
  const browser=await engines[name].launch({headless:true,executablePath:engines[name].executablePath()});
  try{
  for(const viewport of sizes){
    const context=await browser.newContext({viewport,reducedMotion:'reduce',storageState});
    try{
      const page=await context.newPage();page.on('pageerror',e=>report.errors.push({engine:name,width:viewport.width,error:e.message}));
      const read=async path=>{const r=await context.request.get(origin+'/api'+path);if(!r.ok())throw new Error('Fixture read failed: '+r.status());return r.json();};
      const clearCache=async key=>{const old=await read('/edit-cache/'+key);const r=await context.request.put(origin+'/api/edit-cache/'+key,{headers,data:{revision:old.revision,payload:null}});if(!r.ok())throw new Error('Fixture cache reset failed: '+r.status());};
      const open=async(route,selector)=>{await page.goto(origin+'/?draft-check='+Date.now()+'#'+route);await page.waitForSelector(selector);await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});};
      const scenario=async(label,run)=>{
        const result={engine:name,width:viewport.width,label,checks:[]};
        const check=(ok,detail,actual)=>result.checks.push({detail,passed:!!ok,...(actual===undefined?{}:{actual})});
        try{await run(check);result.passed=result.checks.every(c=>c.passed);}catch(error){result.error=error.message;result.passed=false;}
        report.scenarios.push(result);console.log(name+' '+viewport.width+' '+label+': '+(result.passed?'pass':'FAIL'));
      };
      const delayed=async(path,match,submit,edit,done)=>{
        let release,observe,complete,timer,intercepted=false;
        const gate=new Promise(r=>release=r),started=new Promise(r=>observe=r),finished=new Promise(r=>complete=r);
        const pattern=origin+'/api'+path;
        const handler=async route=>{if(!intercepted&&match(route.request())){intercepted=true;observe();try{await gate;await route.continue();}finally{complete();}}else await route.continue();};
        await page.route(pattern,handler);
        try{
          await submit();await Promise.race([started,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Expected delayed request was not sent')),7000);})]);clearTimeout(timer);
          await edit();release();await finished;await done();
        }finally{clearTimeout(timer);release();if(intercepted)await finished;await page.unroute(pattern,handler);}
      };
      const fillNotice=async(title,body)=>{
        await page.locator('#notice-form [name=title]').fill(title);await page.locator('#notice-form [name=body]').fill(body);
        await page.locator('[data-notice-step-to=review]').click();await page.locator('#notice-form [name=rights]').check();await page.locator('#notice-form [name=materials_complete]').check();
      };
      for(const phase of ['business','cleanup']){
        await scenario('通知 '+phase+' 等待期间重开并刷新草稿',async check=>{
          await clearCache('new-notice');await open('new','#notice-form');
          const stamp=Date.now(),old='虚构原提交 '+stamp,newer='虚构新草稿 '+stamp;
          await fillNotice(old,'虚构通知正文 '+stamp+'，请本人准备申请材料。');
          await delayed(phase==='business'?'/notices':'/edit-cache/new-notice',r=>r.method()===(phase==='business'?'POST':'PUT')&&(phase==='business'||r.postDataJSON().payload===null),()=>page.locator('#notice-form [type=submit]').click(),async()=>{
            await page.locator((viewport.width<=850?'.mobile-bottom-nav':'.sidebar')+' a[href="#tasks"]').click();await page.waitForSelector('#task-results');
            if(viewport.width<=850)await page.locator('.mobile-bottom-nav [data-action=menu]').click();
            await page.locator('.sidebar-create').click();await page.waitForSelector('#notice-form');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});
            await page.locator('#notice-form [name=title]').fill(newer);await page.locator('#notice-form [name=body]').fill('后来输入，必须在刷新后保留。'+stamp);
            await page.locator('#notice-form [name=files]').setInputFiles({name:'后来选择的材料.txt',mimeType:'text/plain',buffer:Buffer.from('虚构补充附件')});
            const beforeReleaseTitle=await page.locator('#notice-form [name=title]').inputValue();check(beforeReleaseTitle===newer,'释放旧请求前，新标题已正确填写',beforeReleaseTitle);
          },async()=>{
            await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('通知已保存'));
            check(new URL(page.url()).hash==='#new','旧保存不离开新草稿');const currentTitle=await page.locator('#notice-form [name=title]').inputValue();check(currentTitle===newer,'新标题留在当前表单',currentTitle);
            check(await page.locator('#notice-form [name=files]').evaluate(input=>input.files.length)===1,'新选择的附件未被旧提交清空');
            await page.locator('#notice-form .autosave-status').filter({hasText:'编辑内容已暂存'}).first().waitFor();
            const cache=await read('/edit-cache/new-notice');check(cache.payload?.fields.title===newer,'服务端缓存保留新草稿',cache.payload?.fields.title);
            const notices=await read('/notices');check(notices.filter(n=>n.title===old).length===1&&!notices.some(n=>n.title===newer),'只正式保存原提交一次');
            await page.reload();await page.waitForSelector('#notice-form');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});
            const restoredTitle=await page.locator('#notice-form [name=title]').inputValue();check(restoredTitle===newer,'刷新后恢复新标题',restoredTitle);check((await page.locator('#notice-form [name=body]').inputValue()).includes('后来输入'),'刷新后恢复新正文');
            check((await page.locator('#missing-files').innerText()).includes('后来选择的材料.txt'),'刷新后明确提示重选附件');
          });
        });
        await scenario('安排 '+phase+' 等待期间继续创建下一项',async check=>{
          await clearCache('arrangement-new');await open('calendar','#calendar-body');await page.locator('[data-calendar-action=new]').first().click();
          const stamp=Date.now(),old='虚构第一项 '+stamp,newer='虚构第二项 '+stamp;
          await page.locator('#arrangement-form [name=title]').fill(old);const firstRequest=await page.locator('#arrangement-form').getAttribute('data-request-id');let nextRequest;
          await delayed(phase==='business'?'/arrangements':'/edit-cache/arrangement-new',r=>r.method()===(phase==='business'?'POST':'PUT')&&(phase==='business'||r.postDataJSON().payload===null),()=>page.locator('#arrangement-form [type=submit]').click(),async()=>{
            await page.keyboard.press('Escape');await page.locator('[data-calendar-action=new]').first().click();await page.waitForSelector('#arrangement-form');
            check(await page.locator('#arrangement-form [name=title]').inputValue()==='','第一项仍在保存时，新建入口开启空白表单');
            await page.locator('#arrangement-form [name=title]').fill(newer);nextRequest=await page.locator('#arrangement-form').getAttribute('data-request-id');check(nextRequest!==firstRequest,'第二项使用独立提交标识');
          },async()=>{
            await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('安排已保存'));check(await page.locator('#dialog').evaluate(d=>d.open),'旧保存不关闭新安排');check(await page.locator('#arrangement-form [name=title]').inputValue()===newer,'新安排内容保持');
            await page.locator('#arrangement-form .autosave-status').filter({hasText:'编辑内容已暂存'}).first().waitFor();
            const cache=await read('/edit-cache/arrangement-new');check(cache.payload?.data.title===newer&&cache.payload?.request_id===nextRequest,'新内容及独立提交标识都已暂存');
            await page.reload();await page.waitForSelector('#calendar-body');await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});await page.locator('[data-calendar-action=new]').first().click();
            check(await page.locator('#arrangement-form [name=title]').inputValue()===newer,'刷新后恢复第二项');
            await page.locator('#arrangement-form [type=submit]').click();await page.locator('#dialog[open]').waitFor({state:'detached'});
            const items=await read('/arrangements');check(items.filter(x=>x.data.title===old).length===1&&items.filter(x=>x.data.title===newer).length===1,'两项分别保存，各一次');
          });
        });
      }
      await scenario('重复通知明确另建失败后可重试',async check=>{
        await clearCache('new-notice');const stamp=Date.now(),title='虚构同批内容 '+stamp,body='重复通知重试测试 '+stamp;
        const original=await context.request.post(origin+'/api/notices',{headers,form:{title,body,materials_complete:'true'}});if(!original.ok())throw new Error('Duplicate fixture creation failed: '+original.status());
        await open('new','#notice-form');await fillNotice(title,body);await page.locator('#notice-form [type=submit]').click();await page.waitForSelector('[data-action=duplicate-create]');
        const failure=async route=>{await route.fulfill({status:503,json:{detail:'虚构测试：另建请求暂时失败'}});};
        await page.route(origin+'/api/notices',failure);await page.locator('[data-action=duplicate-create]').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('另建请求暂时失败'));await page.unroute(origin+'/api/notices',failure);
        check(await page.locator('[data-action=duplicate-create]').isEnabled(),'失败后另建按钮恢复');
        await page.locator('[data-action=duplicate-create]').click();await page.waitForSelector('.notice-primary');
        check((await read('/notices')).filter(n=>n.title===title).length===2,'再次点击真正提交，未因一次性监听器失效');
      });
    }finally{await context.close();}
  }
  }finally{await browser.close();}
}
}catch(error){report.errors.push({error:error.stack});}
report.passed=report.scenarios.length>0&&report.scenarios.every(s=>s.passed)&&!report.errors.length;
await writeFile(artifactPath('draft-continuity-report.json'),JSON.stringify(report,null,2));
if(!report.passed)process.exitCode=1;
