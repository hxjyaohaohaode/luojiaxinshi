import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {artifactPath} from './mvp_check_runtime.mjs';

const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={scenarios:[],errors:[]};
const names=(process.env.MVP_BROWSERS||'chromium').split(',');
const headers={Origin:origin,'X-Requested-With':'campus-notice'};
for(const name of names){
  const browser=await engines[name].launch({headless:true,executablePath:engines[name].executablePath()});
  try{
    for(const width of [1440,390]){
      const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
      const username=`handbook.${name}.${width}.${Date.now()}`;
      const register=await context.request.post(origin+'/api/auth/register',{headers,data:{
        username,password:'Handbook-Verification-Only-2026',
        display_name:'虚构界面验收',accepted_terms:true,
      }});
      assert.equal(register.status(),200,'Synthetic account creation');
      const page=await context.newPage();
      page.on('pageerror',error=>report.errors.push({name,width,error:error.message}));
      page.setDefaultTimeout(10000);
      const open=async route=>{
        await page.goto(origin+'/?handbook-check='+Date.now()+'#'+route);
        await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);
      };
      const navigate=async route=>{
        await page.evaluate(route=>location.hash=route,route);
        await page.waitForFunction(route=>document.querySelector('#content')?.dataset.page===route&&!document.querySelector('#content').hasAttribute('aria-busy'),route);
      };
      const scenario=async(label,run)=>{
        const result={engine:name,width,label};
        try{await run();result.passed=true;}catch(error){result.passed=false;result.error=error.stack;}
        report.scenarios.push(result);console.log(`${name} ${width} ${label}: ${result.passed?'pass':'FAIL'}`);
      };
      const input=()=>page.locator('#notice-form input[name=files]');
      const count=()=>input().evaluate(input=>input.files.length);
      const file=(name,text='虚构测试材料')=>({name,mimeType:'text/plain',buffer:Buffer.from(text)});
      await scenario('空账号有可操作引导，进度不制造完成率',async()=>{
        await open('dashboard');
        assert.equal(await page.locator('.overview-progress .progress-ring').getAttribute('data-ring'),'0');
        assert.equal(await page.locator('.overview-progress .progress-ring').getAttribute('aria-label'),'个人行动完成情况：0 / 0');
        assert.match(await page.locator('.overview-progress .ring-caption').textContent(),/待开始/);
        await page.locator('#overview-focus a').click();await page.waitForSelector('#notice-form');
        assert.equal(await page.locator('.notice-stepper [aria-current=step]').getAttribute('data-notice-stage'),'content');
        await page.screenshot({path:artifactPath(`intake-empty-${name}-${width}.png`),fullPage:true});
      });
      await scenario('步骤条遵循必填校验，材料概览随输入更新',async()=>{
        await page.locator('[data-notice-stage=review]').click();
        assert.equal(await page.locator('[data-notice-step=content]').isVisible(),true);
        await page.locator('[name=title]').fill('虚构验收｜手册前端附件操作');
        await page.locator('[data-notice-stage=review]').click();
        assert.equal(await page.locator('[data-notice-step=content]').isVisible(),true);
        await page.locator('#notice-form [name=body]').fill('这是一则仅用于浏览器验收的虚构通知，提交申请前请核对原文要求。');
        assert.equal(await page.locator('[data-ready=title]').getAttribute('class'),'is-ready');
        assert.equal(await page.locator('[data-ready=body]').getAttribute('class'),'is-ready');
      });
      await scenario('选择文件连续追加，非法格式与体积保留原队列',async()=>{
        await input().setInputFiles(file('第一份.txt'));
        await input().setInputFiles(file('第二份.txt'));
        assert.equal(await count(),2);
        await input().setInputFiles(file('非法.exe'));
        assert.equal(await count(),2);
        assert.match(await page.locator('.file-queue-status').textContent(),/格式暂不支持/);
        await input().setInputFiles({name:'超限.txt',mimeType:'text/plain',buffer:Buffer.alloc(5*1024*1024+1,65)});
        assert.equal(await count(),2);
        assert.match(await page.locator('.file-queue-status').textContent(),/超过 5 MB/);
        assert.equal(await page.locator('.selected-file').count(),2);
        assert.match(await page.locator('.selected-file').first().textContent(),/待保存/);
      });
      await scenario('拖放去重、数量上限与逐项移除保持键盘焦点',async()=>{
        await page.locator('.notice-upload').evaluate(zone=>{
          const data=new DataTransfer();data.items.add(zone.querySelector('input').files[0]);
          zone.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));
        });
        assert.equal(await count(),2);
        assert.match(await page.locator('.file-queue-status').textContent(),/重复附件/);
        await input().setInputFiles([file('第三份.txt'),file('第四份.txt'),file('第五份.txt')]);
        assert.equal(await count(),5);
        await input().setInputFiles(file('第六份.txt'));
        assert.equal(await count(),5);
        await page.locator('[data-notice-file-remove]').first().click();
        assert.equal(await count(),4);
        assert.equal(await page.evaluate(()=>document.activeElement.hasAttribute('data-notice-file-remove')),true);
        while(await page.locator('[data-notice-file-remove]').count())await page.locator('[data-notice-file-remove]').first().click();
        assert.equal(await count(),0);
        await page.waitForFunction(async()=>{
          const draft=await(await fetch('/api/edit-cache/new-notice')).json();
          return draft.payload?.files?.length===0;
        });
      });
      await scenario('合成文件粘贴、切页返回和恢复队列一致',async()=>{
        await page.locator('#notice-form [name=body]').evaluate(body=>{
          const data=new DataTransfer();data.items.add(new File(['虚构粘贴附件'],'粘贴.txt',{type:'text/plain'}));
          // Firefox discards files passed to ClipboardEvent's constructor.
          // Supply a deterministic event fixture without accessing the OS clipboard.
          const event=new Event('paste',{bubbles:true,cancelable:true});
          Object.defineProperty(event,'clipboardData',{value:data});
          body.dispatchEvent(event);
        });
        assert.equal(await count(),1);
        await navigate('tasks');await navigate('new');
        assert.equal(await count(),1);assert.equal(await page.locator('.selected-file').count(),1);
        assert.equal(await page.locator('[data-ready=files] small').textContent(),'1 份待保存');
        await page.locator('[data-notice-file-remove]').click();
        await navigate('tasks');await navigate('new');assert.equal(await count(),0);
        assert.equal(await page.locator('#missing-files').count(),0);
      });
      await scenario('刷新后的缺失附件提示不会被非法文件清除',async()=>{
        await input().setInputFiles(file('刷新前.txt'));
        await navigate('tasks');await open('new');
        assert.equal(await page.locator('#missing-files').isVisible(),true);
        await input().setInputFiles(file('非法.exe'));
        assert.equal(await page.locator('#missing-files').isVisible(),true);
        await input().setInputFiles(file('正式保存.txt','用于正式保存链路验收的纯文本附件。'));
        assert.equal(await page.locator('#missing-files').count(),0);
      });
      await scenario('来源核对、回退和原生链接校验可用',async()=>{
        await page.locator('[data-notice-stage=review]').click();
        assert.equal(await page.locator('[data-notice-stage=content]').getAttribute('class'),'is-complete');
        await page.locator('[data-notice-stage=content]').click();
        assert.equal(await count(),1);
        assert.match(await page.locator('#notice-form [name=body]').inputValue(),/虚构通知/);
        await page.locator('[data-notice-stage=review]').click();
        await page.locator('#notice-form .details summary').click();
        await page.locator('[name=source_url]').fill('invalid-url');
        await page.locator('[name=rights]').check();
        await page.locator('#notice-form .details summary').click();
        await page.locator('#notice-form [type=submit]').click();
        assert.equal(await page.locator('#notice-form .details').evaluate(el=>el.open),true);
        await page.locator('[name=source_url]').fill('');
        await page.locator('[name=source_label]').fill('虚构测试来源');
        await page.locator('[name=materials_complete]').check();
        await page.screenshot({path:artifactPath(`intake-review-${name}-${width}.png`),fullPage:true});
      });
      await scenario('真实表单保存到隔离服务，附件名称与正文完整',async()=>{
        await page.locator('#notice-form [type=submit]').click();
        await page.waitForFunction(()=>location.hash.startsWith('#notice/')&&!document.querySelector('#content')?.hasAttribute('aria-busy'));
        const id=await page.evaluate(()=>location.hash.slice('#notice/'.length));
        const response=await context.request.get(origin+'/api/notices/'+id);
        assert.equal(response.status(),200);
        const saved=await response.json();
        assert.equal(saved.title,'虚构验收｜手册前端附件操作');
        assert.ok(saved.sources.some(source=>source.name==='正式保存.txt'));
        assert.ok(saved.sources.some(source=>source.sections?.some(section=>section.text.includes('虚构通知'))));
      });
      await scenario('系统减少动效与用户关闭动效均生效',async()=>{
        await navigate('dashboard');
        assert.equal(await page.locator('.overview-launch').evaluate(el=>getComputedStyle(el).animationName),'none');
        await page.emulateMedia({reducedMotion:'no-preference'});
        await page.evaluate(()=>localStorage.setItem('campus.motion.enabled','false'));
        await open('dashboard');
        assert.equal(await page.locator('.overview-launch').evaluate(el=>getComputedStyle(el).animationName),'none');
      });
      await scenario('记忆区分首次使用与筛选无结果，清空后恢复真实记录',async()=>{
        await open('memory');
        await page.locator('.memory-empty [data-memory-action=new]').click();
        await page.locator('[data-workspace-form=memory-entry] [name=content]').fill('虚构验收：先列出需要核对的原文，再整理办理顺序。');
        await page.locator('[data-workspace-form=memory-entry] [type=submit]').click();
        await page.waitForSelector('.memory-card');
        await page.locator('#memory-search').fill('不可能匹配的关键词');
        assert.equal(await page.locator('.memory-card').count(),0);
        await page.locator('[data-memory-clear]').click();
        assert.equal(await page.locator('.memory-card').count(),1);
        assert.equal(await page.locator('#memory-search').evaluate(el=>el===document.activeElement),true);
        await page.screenshot({path:artifactPath(`memory-record-${name}-${width}.png`),fullPage:true});
      });
      await scenario('来源卡片可用键盘展开，长名称与操作区保持在列内',async()=>{
        await open('sources');
        await page.locator('.source-directory-empty [data-source-action=add]').click();
        await page.locator('[data-workspace-form=source-catalog] [name=name]').fill('虚构验收｜学院课程实践与活动报名通知');
        await page.locator('[data-workspace-form=source-catalog] [name=purpose]').fill('仅用于界面验收：查找本学期课程调整与活动报名原文。');
        await page.locator('[data-workspace-form=source-catalog] [type=submit]').click();
        await page.waitForSelector('.catalog-card');
        await page.locator('.catalog-card > summary').focus();await page.keyboard.press('Enter');
        assert.equal(await page.locator('.catalog-card').evaluate(el=>el.open),true);
        assert.equal(await page.locator('.catalog-body').isVisible(),true);
        const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
        assert.equal(overflow,false);
        await page.screenshot({path:artifactPath(`source-record-${name}-${width}.png`),fullPage:true});
      });
      await scenario('退出清理内存附件，重新登录后可明确移除缺失记录并持久保存',async()=>{
        await navigate('new');
        await page.locator('#notice-form [name=title]').fill('虚构验收｜退出前的附件草稿');
        await page.locator('#notice-form [name=body]').fill('退出后只恢复文字，不保留上个会话的本地附件。');
        await input().setInputFiles(file('退出前.txt'));
        await navigate('tasks');
        if(width<=850)await page.locator('.mobile-bottom-nav [data-action=menu]').click();
        await page.locator('.sidebar [data-action=logout]').click();
        await page.waitForSelector('#auth-form');
        await page.locator('#auth-form [name=username]').fill(username);
        await page.locator('#auth-form [name=password]').fill('Handbook-Verification-Only-2026');
        await page.locator('#auth-form [type=submit]').click();await page.waitForSelector('#overview-board');
        await navigate('new');
        assert.equal(await count(),0);
        assert.match(await page.locator('#missing-files').textContent(),/退出前.txt/);
        await page.locator('[data-action=discard-missing-files]').click();
        await navigate('tasks');await open('new');
        assert.equal(await page.locator('#missing-files').count(),0);
        const saved=await(await context.request.get(origin+'/api/edit-cache/new-notice')).json();
        assert.equal(saved.payload.files.length,0);
      });
      await context.close();
    }
    const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
    const login=await context.request.post(origin+'/api/auth/login',{headers,data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
    assert.equal(login.status(),200);
    const page=await context.newPage();page.on('pageerror',error=>report.errors.push({name,error:error.message}));
    await page.goto(origin+'/#dashboard');await page.waitForSelector('#overview-board');
    await page.locator('#overview-tab-tasks').focus();await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#overview-items').getAttribute('aria-labelledby'),'overview-tab-followup');
    await page.locator('#overview-focus [data-workflow-task]').click();await page.waitForSelector('#workflow-form');await page.keyboard.press('Escape');
    await page.locator('[data-overview-filter=changes]').click();await page.waitForSelector('#task-results');
    assert.equal(await page.locator('[data-filter=changes]').getAttribute('aria-selected'),'true');
    report.scenarios.push({engine:name,label:'优先事项详情、键盘标签切换与概览筛选接入真实路由',passed:true});
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:900});
      await page.goto(origin+'/?command-check='+Date.now()+'#dashboard');await page.waitForSelector('#overview-board');
      await page.keyboard.press('Control+k');await page.waitForSelector('.command-result');
      assert.equal(await page.locator('#global-search').evaluate(el=>el===document.activeElement),true);
      assert.equal(await page.locator('.command-shortcut').count(),3);
      await page.locator('#global-search').fill('申请');
      assert.ok(await page.locator('.command-result mark').count()>0);
      assert.equal(await page.locator('.command-shortcut').count(),0);
      await page.keyboard.press('ArrowDown');
      assert.equal(await page.locator('.command-result').first().evaluate(el=>el===document.activeElement),true);
      await page.keyboard.press('ArrowUp');
      assert.equal(await page.locator('#global-search').evaluate(el=>el===document.activeElement),true);
      await page.screenshot({path:artifactPath(`command-search-${name}-${width}.png`),fullPage:true});
      await page.locator('#global-search').fill('查不到的虚构条目');
      await page.locator('#global-results [data-clear-global-search]').click();
      assert.equal(await page.locator('#global-search').inputValue(),'');
      await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
      await page.waitForSelector('#notice-form');
      assert.equal(await page.locator('#dialog').evaluate(el=>el.open),false);
      report.scenarios.push({engine:name,width,label:'分组搜索、快捷入口、高亮、清空与方向键导航',passed:true});

      await page.route('**/api/notices',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'虚构断网验收'})}));
      await page.keyboard.press('Control+k');
      await page.locator('#global-search').fill('学院');
      await page.waitForSelector('[data-command-retry]');
      await page.unroute('**/api/notices');
      await page.locator('[data-command-retry]').click();await page.waitForSelector('.command-result');
      assert.equal(await page.locator('#global-search').inputValue(),'学院');
      assert.ok(await page.locator('#command-notices-heading').count());
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#dialog').evaluate(el=>el.open),false);
      report.scenarios.push({engine:name,width,label:'搜索失败保留关键词，重试按来源匹配并恢复',passed:true});
    }
    const notices=await (await context.request.get(origin+'/api/notices')).json();
    await page.route('**/api/notices',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(Array.from({length:18},(_,i)=>({...notices[0],title:'虚构批量搜索记录 '+i})))}));
    await page.keyboard.press('Control+k');await page.waitForSelector('[data-command-more]');
    await page.locator('#global-search').fill('虚构批量搜索记录');
    assert.equal(await page.locator('.command-result').count(),6);
    await page.locator('[data-command-more]').click();
    assert.equal(await page.locator('.command-result').count(),12);
    assert.equal(await page.locator('[data-command-key=notices-6]').evaluate(el=>el===document.activeElement),true);
    await page.locator('[data-command-more]').click();
    assert.equal(await page.locator('.command-result').count(),18);
    assert.equal(await page.locator('[data-command-more]').count(),0);
    await page.keyboard.press('Escape');await page.unroute('**/api/notices');
    report.scenarios.push({engine:name,label:'批量搜索按需展开，无隐藏结果丢失，展开后焦点连续',passed:true});
    await page.route('**/api/notices',async route=>{await new Promise(resolve=>setTimeout(resolve,600));await route.continue();});
    await page.keyboard.press('Control+k');await page.waitForSelector('#global-results[aria-busy=true]');
    await page.keyboard.press('Escape');
    await page.goto(origin+'/?late-search='+Date.now()+'#settings');await page.waitForSelector('.settings-home');
    await page.locator('[data-action=settings-profile]').click();await page.waitForSelector('#profile-form');
    await page.waitForTimeout(700);
    assert.equal(await page.locator('#profile-form').isVisible(),true);
    assert.equal(await page.locator('#global-results').count(),0);
    await page.keyboard.press('Escape');await page.unroute('**/api/notices');
    report.scenarios.push({engine:name,label:'过期搜索响应不会覆盖后续页面或个人条件弹窗',passed:true});
    for(const [width,sidebar] of [[1100,460],[1440,460],[1440,180],[768,234],[320,234]]){
      await page.setViewportSize({width,height:900});
      await page.evaluate(sidebar=>localStorage.setItem('campus.sidebar.width',sidebar),sidebar);
      await page.goto(origin+'/#dashboard');await page.waitForSelector('#overview-board');
      const geometry=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
      report.scenarios.push({engine:name,label:`侧栏 ${sidebar}px / 视口 ${width}px`,passed:geometry.scroll<=width+1,...geometry});
    }
    await page.route('**/api/notices',async route=>{await new Promise(resolve=>setTimeout(resolve,850));await route.continue();});
    await page.goto(origin+'/?handbook-loading='+Date.now()+'#dashboard');
    await page.waitForSelector('.route-skeleton');
    assert.equal(await page.locator('.route-skeleton').getAttribute('aria-hidden'),'true');
    await page.waitForSelector('.route-skeleton',{state:'detached'});
    report.scenarios.push({engine:name,label:'骨架只在真实加载期间显示，完成后移除',passed:true});
    await context.close();
  }catch(error){report.errors.push({engine:name,error:error.stack});}
  finally{await browser.close();}
}
await writeFile(artifactPath('handbook-interactions.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:report.scenarios.filter(item=>item.passed).length,total:report.scenarios.length,errors:report.errors,failures:report.scenarios.filter(item=>!item.passed)},null,2));
if(report.errors.length||report.scenarios.some(item=>!item.passed))process.exitCode=1;
