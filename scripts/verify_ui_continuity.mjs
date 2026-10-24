import {artifactPath} from './mvp_check_runtime.mjs';
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';

// Actual local writes, deliberately held while a user navigates or opens a new
// form. The synthetic service has no model credentials and never reads data/.
const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const port=Number(process.env.MVP_PORT||8780);
if(!Number.isInteger(port)||port<1024||port>65535)throw new Error('Invalid synthetic fixture port');
const origin='http://127.0.0.1:'+port;
const report={scenarios:[],errors:[]};
const names=(process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',');
const sizes=JSON.parse(process.env.MVP_VIEWPORTS||'[{"width":390,"height":844},{"width":1440,"height":900}]');

try{
const fixture=await engines.request.newContext({baseURL:origin});
let storageState;
try{
  const login=await fixture.post('/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
  if(!login.ok())throw new Error('Synthetic fixture login failed: '+login.status());
  storageState=await fixture.storageState();
}finally{await fixture.dispose();}
for(const name of names){
  const browser=await engines[name].launch({headless:true,executablePath:engines[name].executablePath()});
  try{
    for(const viewport of sizes){
      const context=await browser.newContext({viewport,reducedMotion:'reduce',storageState});
      try{
        const session=await (await context.request.get(origin+'/api/session')).json();
        const headers={Origin:origin,'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
        const savedProfile=async()=> (await (await context.request.get(origin+'/api/session')).json()).user.profile;
        const patch=async(changes,expected)=>{const response=await context.request.patch(origin+'/api/profile',{headers,data:{changes,expected}});if(!response.ok())throw new Error('Fixture profile patch failed: '+response.status());return (await response.json()).profile;};
        const page=await context.newPage();page.on('pageerror',e=>report.errors.push({engine:name,width:viewport.width,error:e.message}));
        const settingCategory=action=>['settings-security','settings-model','settings-data'].includes(action)?'account':['settings-speech','settings-genui'].includes(action)?'display':'personal';
        const setting=async action=>{const target=page.locator('[data-action='+action+']');if(!await target.isVisible())await page.locator('[data-settings-category='+settingCategory(action)+']').click();await target.click();};
        const open=async(route,selector)=>{await page.goto(origin+'/?ui-check='+Date.now()+'#'+route);if(route==='settings'){await page.locator('.settings-home').waitFor();const action=selector.match(/settings-[a-z]+/)?.[0];if(action)await page.locator('[data-settings-category='+settingCategory(action)+']').click();}await page.waitForSelector(selector);await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});};
        const scenario=async(label,run)=>{
          if(process.env.MVP_SCENARIO&&label!==process.env.MVP_SCENARIO)return;
          const result={engine:name,width:viewport.width,label,checks:[]};
          const check=(condition,detail,observed)=>{result.checks.push({detail,passed:!!condition,...(observed===undefined?{}:{observed})});};
          try{await run(check);result.passed=result.checks.every(c=>c.passed);}catch(error){result.passed=false;result.error=error.message;}
          report.scenarios.push(result);console.log(name+' '+viewport.width+' '+label+': '+(result.passed?'pass':'FAIL'));
          if(!result.passed)console.log(JSON.stringify(result));
        };
        const delay=async(path,method,action,whileWaiting,after,{allowAbort=false}={})=>{
          let release,observed,timeout,complete;
          const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>observed=resolve);
          const completed=new Promise(resolve=>complete=resolve);
          const pattern=origin+'/api'+path;
          let intercepted=false;
          const handler=async route=>{if(route.request().method()===method&&!intercepted){intercepted=true;observed();try{await gate;await route.continue();}finally{complete();}}else await route.continue();};
          await page.route(pattern,handler);
          try{
            await action();await Promise.race([started,new Promise((_,reject)=>{timeout=setTimeout(()=>reject(new Error('Expected request was not sent')),6000);})]);clearTimeout(timeout);
            const received=page.waitForResponse(r=>r.url()===pattern&&r.request().method()===method);
            // Read-only navigation can correctly abort an obsolete request.
            // Observe that event before navigating; writes still require a response.
            const response=allowAbort?Promise.race([received,page.waitForEvent('requestfailed',{predicate:r=>r.url()===pattern&&r.method()===method})]):received;
            await whileWaiting();
            release();await response;await after();
          }finally{clearTimeout(timeout);release();if(intercepted)await completed;await page.unroute(pattern,handler);}
        };
        await scenario('偏好保存后保留新页面',async check=>{
          await open('settings','[data-action=settings-preferences]');
          await setting('settings-preferences');
          await page.locator('#preferences-form [name=response_preferences]').fill('虚构异步验收：先给结论');
          await delay('/profile',process.env.MVP_BASELINE==='true'?'PUT':'PATCH',()=>page.locator('#preferences-form [type=submit]').click(),async()=>{
            await page.keyboard.press('Escape');await page.locator((viewport.width<=850?'.mobile-bottom-nav':'.sidebar')+' a[href="#tasks"]').click();await page.waitForSelector('#task-results');
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('偏好已保存'));check(await page.locator('#task-results').count()===1,'迟到保存不以设置页覆盖待办');check(new URL(page.url()).hash==='#tasks','保持当前路由');});
        });
        if(process.env.MVP_BASELINE==='true')continue;
        await scenario('个人条件保存后保留新弹窗',async check=>{
          let beforeResponse;
          await open('settings','[data-action=settings-profile]');await setting('settings-profile');
          await page.locator('#profile-form [name=college]').fill('虚构动态验收学院');
          await delay('/profile','PATCH',()=>page.locator('#profile-form [type=submit]').click(),async()=>{
            check(await page.locator('#profile-form').getAttribute('aria-busy')==='true','保存状态可感知');
            await page.keyboard.press('Escape');await setting('settings-security');await page.locator('#password-form [name=old_password]').fill('新的未提交输入');beforeResponse=await page.locator('#password-form [name=old_password]').inputValue();
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('身份条件已保存'));check(await page.locator('#dialog').evaluate(d=>d.open),'新弹窗仍打开');const afterResponse=await page.locator('#password-form [name=old_password]').inputValue();check(afterResponse==='新的未提交输入','新表单输入保持',{beforeResponse,afterResponse});});
        });
        await scenario('互动设置保存后保留新偏好',async check=>{
          await open('settings','[data-action=settings-genui]');await setting('settings-genui');
          await delay('/genui/preferences','PUT',()=>page.locator('#genui-settings-form [type=submit]').click(),async()=>{
            await page.keyboard.press('Escape');await setting('settings-preferences');await page.locator('#preferences-form [name=response_preferences]').fill('新偏好尚未提交');
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('互动回答设置已保存'));check(await page.locator('#dialog').evaluate(d=>d.open),'新弹窗仍打开');check(await page.locator('#preferences-form [name=response_preferences]').inputValue()==='新偏好尚未提交','新偏好保持');});
        });
        await scenario('来源保存后保留另一份来源草稿',async check=>{
          await open('sources','[data-source-action=add]');await page.locator('[data-source-action=add]').first().click();
          await page.locator('[data-workspace-form=source-catalog] [name=name]').fill('虚构迟到来源 '+Date.now());
          await delay('/source-catalog','POST',()=>page.locator('[data-workspace-form=source-catalog] [type=submit]').click(),async()=>{
            check(await page.locator('[data-workspace-form=source-catalog]').getAttribute('aria-busy')==='true','来源有保存反馈');await page.keyboard.press('Escape');await page.locator('[data-source-action=add]').first().click();await page.locator('[data-workspace-form=source-catalog] [name=name]').fill('另一份来源未保存');
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('来源存好了'));check(await page.locator('#dialog').evaluate(d=>d.open),'新来源弹窗仍打开');check(await page.locator('[data-workspace-form=source-catalog] [name=name]').inputValue()==='另一份来源未保存','新来源草稿保持');});
        });
        await scenario('学期保存后保留新的日历选项',async check=>{
          await open('calendar','#calendar-body');await page.locator('[data-calendar-action=options]').click();await page.locator('[data-calendar-action=semester]').click();
          await page.locator('#semester-form [name=semester]').fill('虚构学期 '+Date.now());
          await delay('/profile','PATCH',()=>page.locator('#semester-form [type=submit]').click(),async()=>{
            // Escape returns to the real parent options dialog. Keep that newer
            // view open while the child form's delayed save completes.
            await page.keyboard.press('Escape');await page.locator('#calendar-week-start').waitFor();
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('学期与周次已保存'));check(await page.locator('#dialog').evaluate(d=>d.open),'新的日历选项仍打开');check(await page.locator('#calendar-week-start').isVisible(),'当前选项未被替换');});
        });
        await scenario('迟到语音配置不抢走编辑弹窗',async check=>{
          let beforeResponse;
          await open('settings','[data-action=settings-speech]');
          await delay('/speech/config','GET',()=>setting('settings-speech'),async()=>{
            await setting('settings-preferences');await page.locator('#preferences-form [name=response_preferences]').fill('正在编辑的新偏好');beforeResponse=await page.locator('#preferences-form [name=response_preferences]').inputValue();
          },async()=>{await page.locator('[data-action=settings-speech]:disabled').waitFor({state:'detached'});const afterResponse=await page.locator('#preferences-form [name=response_preferences]').inputValue();check(afterResponse==='正在编辑的新偏好','迟到配置不会替换新弹窗',{beforeResponse,afterResponse});});
        });
        await scenario('同字段冲突保留填写并支持核对重试',async check=>{
          await open('settings','[data-action=settings-profile]');await setting('settings-profile');
          const before=await savedProfile(),mine='本人填写 '+Date.now(),other='另一窗口 '+Date.now();
          await page.locator('#profile-form [name=college]').fill(mine);await patch({college:other},{college:before.college});
          await page.locator('#profile-form [type=submit]').click();await page.waitForSelector('.profile-conflict');await page.locator('#profile-form[aria-busy=true]').waitFor({state:'detached'});
          check(await page.locator('#profile-form [name=college]').inputValue()===mine,'冲突保留本次填写');check((await savedProfile()).college===other,'冲突不覆盖另一处保存');check((await page.locator('.profile-conflict').innerText()).includes(other),'显示可核对的最新值');
          if(name==='chromium')await page.screenshot({path:artifactPath('profile-conflict-'+viewport.width+'.png')});
          await page.locator('#profile-form [name=major]').fill('冲突提示后继续编辑');await page.locator('.profile-conflict button').click();
          check(await page.locator('#profile-form [name=major]').inputValue()==='冲突提示后继续编辑','核对过程不丢失后来编辑');
          await page.locator('#profile-form [type=submit]').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('身份条件已保存'));
          const saved=await savedProfile();check(saved.college===mine&&saved.major==='冲突提示后继续编辑','本人核对后才成功写入');
        });
        await scenario('保存失败恢复按钮且重试不覆盖其他资料',async check=>{
          await open('settings','[data-action=settings-preferences]');await setting('settings-preferences');
          const value='失败重试 '+Date.now(),form=page.locator('#preferences-form'),button=form.locator('[type=submit]');await form.locator('[name=response_preferences]').fill(value);await button.scrollIntoViewIfNeeded();
          const before=await button.boundingBox();
          const failing=async route=>{if(route.request().method()==='PATCH')await route.fulfill({status:503,json:{detail:'虚构验收：暂时不可用'}});else await route.continue();};
          await page.route(origin+'/api/profile',failing);await button.click();await page.waitForSelector('#preferences-form .form-error');await page.locator('#preferences-form[aria-busy=true]').waitFor({state:'detached'});await page.unroute(origin+'/api/profile',failing);
          check(await button.isEnabled(),'失败后可以再次保存');check(await form.locator('[name=response_preferences]').inputValue()===value,'失败保留填写');
          const current=await savedProfile(),school='独立更新 '+Date.now();await patch({school},{school:current.school});
          await button.scrollIntoViewIfNeeded();const stable=await button.boundingBox();
          await delay('/profile','PATCH',()=>button.click(),async()=>{
            const during=await button.boundingBox();check(Math.abs(stable.width-during.width)<1&&Math.abs(stable.x-during.x)<1&&Math.abs(stable.y-during.y)<1,'保存反馈不改变按钮尺寸与位置',{stable,during});
            check(await button.getAttribute('aria-busy')==='true','按钮声明处理中');
            if(name==='chromium')await page.screenshot({path:artifactPath('profile-saving-'+viewport.width+'.png')});
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('偏好已保存'));const saved=await savedProfile();check(saved.response_preferences===value&&saved.school===school,'重试只写本次字段，保留独立更新');});
        });
        await scenario('旧记忆页面响应不修改当前路由状态',async check=>{
          await open('settings','a[href="#memory"]');
          await delay('/memory/tree/status','GET',()=>page.locator('a[href="#memory"]').click(),async()=>{
            await page.locator((viewport.width<=850?'.mobile-bottom-nav':'.sidebar')+' a[href="#tasks"]').click();await page.waitForSelector('#task-results');
          },async()=>{await page.waitForFunction(()=>document.querySelector('#content')?.dataset.page==='tasks'&&!document.querySelector('.route-feedback'));check(await page.locator('#task-results').count()===1,'旧页面响应不覆盖待办');check(await page.locator('#content').getAttribute('data-page')==='tasks','当前页面布局标识保持正确');},{allowAbort:true});
        });
        await scenario('补充材料保存后保留新办理表单',async check=>{
          let beforeResponse;
          const post=async(path,data,form=false)=>{const r=await context.request.post(origin+'/api'+path,{headers,...(form?{form:data}:{data})});if(!r.ok())throw new Error('Synthetic notice fixture failed: '+r.status());return r.json();};
          let n=await post('/notices',{title:'虚构材料连续性 '+Date.now(),body:'虚构通知 '+Date.now()+'，准备后提交材料。',materials_complete:'true'},true);
          n=await post('/notices/'+n.id+'/manual',{version:n.version});const confirmed=await post('/notices/'+n.id+'/confirm',{version:n.version,reviewed:true,tasks:[{title:'虚构办理草稿隔离'}]});
          const task={id:confirmed.task_ids[0],notice_id:n.id};
          await open('notice/'+task.notice_id,'.notice-primary');
          const originals=page.locator('.notice-originals');if(!await originals.evaluate(el=>el.open))await originals.locator('summary').first().click();
          await page.locator('[data-action=supplement]').click();await page.locator('#supplement-form [name=body]').fill('虚构补充材料 '+Date.now());
          await delay('/notices/'+task.notice_id+'/supplement','POST',()=>page.locator('#supplement-form [type=submit]').click(),async()=>{
            await page.keyboard.press('Escape');await page.locator('.task-title[data-workflow-task="'+task.id+'"]').click();await page.locator('.workflow-followup > summary').click();await page.locator('#workflow-form [name=next_step]').fill('新的办理草稿尚未提交');beforeResponse=await page.locator('#workflow-form [name=next_step]').inputValue();
          },async()=>{await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('补充材料已保存'));check(await page.locator('#dialog').evaluate(d=>d.open),'新的办理弹窗仍打开');const afterResponse=await page.locator('#workflow-form [name=next_step]').inputValue();check(afterResponse==='新的办理草稿尚未提交','补件结果不覆盖办理草稿',{beforeResponse,afterResponse});});
        });
        await scenario('关闭模型设置后迟到记录不重新弹出',async check=>{
          await open('settings','[data-action=settings-model]');await setting('settings-model');
          await delay('/executions','GET',()=>page.locator('#open-executions').click(),async()=>{
            await page.keyboard.press('Escape');
          },async()=>{await page.waitForFunction(()=>!document.querySelector('#open-executions')?.disabled);check(!await page.locator('#dialog').evaluate(d=>d.open),'已关闭的弹窗不会被迟到记录重新打开');});
        });
        await scenario('开始输入后延迟的弹窗焦点不抢回标题',async check=>{
          await open('settings','[data-action=settings-preferences]');
          // Deterministically delay a render frame, as on a busy device, while
          // allowing focus and text input to happen before the opening callback.
          await page.evaluate(()=>{const native=window.requestAnimationFrame,queued=[];window.requestAnimationFrame=callback=>(queued.push(callback),-queued.length);window.releaseFocusFrame=()=>{window.requestAnimationFrame=native;for(const callback of queued)native(callback);delete window.releaseFocusFrame;};});
          try{
            await page.locator('[data-action=settings-preferences]').dispatchEvent('click');
            await page.locator('#preferences-form [name=response_preferences]').fill('输入开始后保持焦点');
            await page.evaluate(()=>new Promise(resolve=>{window.releaseFocusFrame();requestAnimationFrame(()=>requestAnimationFrame(resolve));}));
            check(await page.locator('#preferences-form [name=response_preferences]').evaluate(input=>document.activeElement===input),'后到的开窗帧尊重已开始的输入');
          }finally{await page.evaluate(()=>window.releaseFocusFrame?.());}
        });
      }finally{await context.close();}
    }
  }finally{await browser.close();}
}}catch(error){report.errors.push({error:error.stack});}
report.passed=report.scenarios.length>0&&report.scenarios.every(s=>s.passed)&&!report.errors.length;
await writeFile(artifactPath('ui-continuity-report.json'),JSON.stringify(report,null,2));
if(!report.passed)process.exitCode=1;
