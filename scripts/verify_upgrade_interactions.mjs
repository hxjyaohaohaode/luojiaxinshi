import {createRequire} from 'node:module';
import {writeFile,readFile} from 'node:fs/promises';
import {artifactPath} from './mvp_check_runtime.mjs';
const require=createRequire(import.meta.url),engines=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={checks:[],errors:[]},browsers=(process.env.MVP_BROWSERS||'chromium,firefox,webkit').split(',');
let auth;
for(const engine of browsers){
  const browser=await engines[engine].launch({headless:true,executablePath:engines[engine].executablePath()});
  try{
    for(const width of [1440,390,320]){
      const context=await browser.newContext({viewport:{width,height:900},...(auth?{storageState:auth}:{})});
      if(!auth){
        const response=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
        if(!response.ok())throw Error('Fixture login failed');auth=await context.storageState();
      }
      const page=await context.newPage();
      page.setDefaultTimeout(10000);page.on('pageerror',error=>report.errors.push({engine,width,error:error.message}));
      page.on('console',message=>{if(message.type()==='error'&&/Content Security Policy|Refused to/.test(message.text()))report.errors.push({engine,width,error:message.text()});});
      const check=(detail,passed,actual)=>{report.checks.push({engine,width,detail,passed,...(actual===undefined?{}:{actual})});if(!passed)console.log('FAIL',engine,width,detail,actual);};
      const go=async route=>{await page.goto(origin+'/?upgrade='+Date.now()+'#'+route);await page.waitForFunction(route=>{const node=document.querySelector('#content');return node?.dataset.page===route&&!node.hasAttribute('aria-busy')&&!node.inert;},route);};
      const noOverlap=()=>page.evaluate(()=>[...document.querySelectorAll('.task-row')].every(row=>{
        const title=row.querySelector('.task-title')?.getBoundingClientRect(),actions=row.querySelector('.task-actions')?.getBoundingClientRect();
        return !title||!actions||title.bottom<=actions.top+1||title.right<=actions.left+1||actions.right<=title.left+1;
      }));
      await go('dashboard');
      await page.locator('.number-ticker').first().waitFor();
      const tasks=await (await context.request.get(origin+'/api/tasks')).json();
      const pending=tasks.filter(t=>t.data.scope==='personal'&&t.status==='pending'&&!t.action_excluded);
      check('Metric exposes final saved count',await page.locator('[data-overview-filter=pending] .number-ticker .sr-only').first().textContent()===String(pending.length));
      const metricNode=await page.locator('#action-metrics').evaluate(node=>{node.dataset.probe='kept';return true;});
      const firstTitle=await page.locator('#overview-focus h2').textContent();
      if(pending.length>1){
        await page.locator('[data-focus-step="1"]').click();
        check('Focus deck advances to another saved task',await page.locator('#overview-focus h2').textContent()!==firstTitle);
        check('Deck switch does not rebuild unrelated metrics',await page.locator('#action-metrics').getAttribute('data-probe')==='kept');
        await page.locator('[data-focus-step="-1"]').click();
        check('Focus deck can return',await page.locator('#overview-focus h2').textContent()===firstTitle);
      }
      await page.locator('[data-overview-section=notices]').click();
      check('Overview tabs keep selected state',await page.locator('[data-overview-section=notices]').getAttribute('aria-selected')==='true');
      const deadline=pending.find(t=>awaitableDay(t.data.due_date))?.data.due_date;
      if(deadline&&await page.locator(`[data-overview-day="${deadline}"]`).count()){
        await page.locator(`[data-overview-day="${deadline}"]`).click();
        check('Date strip shows actual due task',await page.locator('.week-agenda [data-workflow-task]').count()>0);
        await page.locator('.week-agenda [data-workflow-task]').click();
        await page.locator('#workflow-form').waitFor();
        check('Date strip opens the original workflow',await page.locator('#dialog').evaluate(d=>d.open));
        await page.keyboard.press('Escape');
      }
      if(width===1440){
        await page.locator('.overview-letter').hover({position:{x:80,y:70}});
        await page.waitForFunction(()=>document.querySelector('.overview-letter').classList.contains('pointer-active'));
        check('Fine pointer drives local spotlight',await page.locator('.overview-letter').evaluate(n=>n.style.getPropertyValue('--spot-x')!==''));
      }
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.waitForTimeout(40);
      check('Reduced motion pauses ornaments',await page.locator('[data-orbit]').evaluateAll(nodes=>nodes.every(n=>n.classList.contains('fx-paused'))));
      check('Reduced motion cancels finite experience animations',await page.evaluate(()=>!document.getAnimations().some(a=>a.playState==='running'&&a.effect?.target?.closest('.number-ticker,.progress-ring,.letter-illustration'))));
      await page.emulateMedia({reducedMotion:'no-preference'});
      await go('tasks');
      check('Task board is the default',await page.locator('.task-board').isVisible());
      check('Board titles never overlap action controls',await noOverlap());
      const boardIds=await page.locator('.task-title').evaluateAll(nodes=>nodes.map(n=>n.dataset.workflowTask).sort());
      await page.getByRole('button',{name:'清单视图',exact:true}).click();
      const listIds=await page.locator('.task-title').evaluateAll(nodes=>nodes.map(n=>n.dataset.workflowTask).sort());
      check('Board and list contain identical records',JSON.stringify(boardIds)===JSON.stringify(listIds));
      await page.locator('#task-search').fill('准备申请材料');
      await page.waitForTimeout(250);
      const count=await page.locator('.task-title').count();
      await page.getByRole('button',{name:'看板视图',exact:true}).click();
      check('View switch preserves active search',await page.locator('#task-search').inputValue()==='准备申请材料'&&await page.locator('.task-title').count()===count);
      await page.locator('.task-date-filter > summary').click();
      check('Open date filter fits viewport',await page.locator('#task-date').evaluate(n=>{const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));
      const unchanged=await (await context.request.get(origin+'/api/tasks')).json();
      check('View changes never modify task data',JSON.stringify(tasks)===JSON.stringify(unchanged));
      // Exercise the original reversible completion action on the synthetic task.
      const completedId=await page.locator('.task-check').first().getAttribute('data-id');
      await page.locator('.task-check').first().click();
      await page.locator('#toast.has-action .toast-action').waitFor();
      check('Completion feedback retains the undo action',(await page.locator('.toast-copy').textContent()).includes('已记录为完成'));
      check('Actionable toast stays within viewport',await page.locator('#toast').evaluate(n=>{const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1;}));
      await page.locator('#toast .toast-action').click();
      await page.waitForFunction(()=>document.querySelector('.toast-copy')?.textContent.includes('已撤回'));
      const restored=await (await context.request.get(origin+'/api/tasks')).json();
      check('Undo restores the same saved task',restored.find(t=>t.id===completedId)?.status==='pending');
      await go('notices');
      const noticeCount=await page.locator('.notice-card').count();
      await page.locator('[data-library-view=list]').click();
      check('Notice list preserves card count',await page.locator('.notice-row').count()===noticeCount);
      await page.locator('#library-search').fill('秋季');
      await page.locator('[data-library-view=cards]').click();
      check('Notice view preserves filter',await page.locator('#library-search').inputValue()==='秋季'&&await page.locator('.notice-card').count()===1);
      await page.locator('.notice-card [data-action=open-notice]').click();
      await page.locator('.source-pane').waitFor();
      check('Notice card opens original material',await page.locator('.source-section').count()>0);
      if(width===1440){
        // Render a long synthetic original in this browser only; no saved record changes.
        await page.locator('.source-section').first().evaluate(node=>{node.textContent=Array.from({length:80},(_,i)=>`虚构长原文 ${i+1}：用于检查阅读位置反馈。`).join('\n');});
        await page.locator('.source-pane').evaluate(node=>{node.scrollTop=node.scrollHeight;});
        await page.waitForFunction(()=>document.querySelector('.source-reading-progress span')?.textContent.includes('100%'));
        check('Reading position follows the actual original scroller',await page.locator('.source-reading-progress').isVisible());
      }
      await go('new');
      check('Upload illustration remains visible on small screens',await page.locator('.upload-symbol .icon').isVisible());
      await page.locator('[name=title]').fill('虚构测试：收件预览');
      await page.locator('[name=body]').fill('这是用于界面验收的本地材料，不代表真实校园通知。');
      check('Intake preview follows title and original text',await page.locator('#compose-preview-title').textContent()==='虚构测试：收件预览'&&(await page.locator('#compose-preview-body').textContent()).includes('本地材料'));
      const pixel=await readFile(new URL('../static/assets/campus-notice-icon-v4-32.png',import.meta.url));
      await page.locator('input[name=files]').setInputFiles({name:'local-preview.png',mimeType:'image/png',buffer:pixel});
      await page.locator('.selected-file-preview').waitFor();
      check('Selected image has a local preview',await page.locator('.selected-file-preview').evaluate(img=>img.complete&&img.naturalWidth>0&&img.src.startsWith('data:')));
      await page.locator('input[name=files]').setInputFiles({name:'damaged.png',mimeType:'image/png',buffer:Buffer.from('damaged synthetic image')});
      await page.waitForTimeout(80);
      check('Damaged image keeps a readable type tile',await page.locator('.selected-file').count()===2&&await page.locator('.selected-file-preview').count()===1);
      await page.getByRole('button',{name:'移除附件 damaged.png',exact:true}).click();
      await page.locator('[data-notice-step-to=review]').click();
      check('Animated stepper reflects real active stage',await page.locator('[data-notice-stage=review]').getAttribute('aria-current')==='step');
      await page.locator('[data-notice-step-to=content]').click();
      check('Step transition retains the file and original body',await page.locator('input[name=files]').evaluate(i=>i.files.length===1)&&(await page.locator('[name=body]').inputValue()).includes('本地材料'));
      // Exercise a real validation error and toast lifecycle without a server mutation.
      await page.locator('input[name=files]').setInputFiles({name:'unsupported.exe',mimeType:'application/octet-stream',buffer:Buffer.from('fixture')});
      await page.locator('#toast.visible').waitFor();
      check('Error feedback preserves existing queue',await page.locator('input[name=files]').evaluate(i=>i.files.length===1&&i.files[0].name==='local-preview.png'));
      await page.waitForFunction(async()=>{
        const draft=await(await fetch('/api/edit-cache/new-notice')).json();
        return draft.payload?.files?.length===1&&draft.payload.files[0]==='local-preview.png';
      });
      check('Rejected file never replaces the persisted attachment names',true);
      await page.locator('#toast').hover();
      check('Hover pauses feedback lifetime',await page.locator('.toast-lifetime').evaluate(n=>n.getAnimations().some(a=>a.playState==='paused')));
      await page.mouse.move(0,0);
      check('Leaving feedback resumes its lifetime',await page.locator('.toast-lifetime').evaluate(n=>n.getAnimations().some(a=>a.playState==='running')));
      await page.locator('[data-toast-close]').focus();await page.waitForTimeout(100);
      check('Toast supports keyboard dismissal',await page.locator('[data-toast-close]').evaluate(n=>n===document.activeElement));
      await page.keyboard.press('Enter');
      check('Toast dismissal removes the message',!(await page.locator('#toast').getAttribute('class'))?.includes('visible'));
      await page.locator('input[name=files]').setInputFiles({name:'unsupported.exe',mimeType:'application/octet-stream',buffer:Buffer.from('fixture')});
      await page.locator('[data-toast-close]').click();
      check('Feedback is also dismissible by pointer',!(await page.locator('#toast').getAttribute('class'))?.includes('visible'));
      // Clear this synthetic form so subsequent views do not inherit file reminders.
      await page.locator('[data-notice-file-remove]').click();
      await page.locator('[name=title]').fill('');await page.locator('[name=body]').fill('');
      await page.locator('#notice-form .autosave-status').filter({hasText:'编辑内容已暂存'}).waitFor();
      await page.waitForFunction(async()=>{
        const draft=await(await fetch('/api/edit-cache/new-notice')).json();
        return draft.payload?.files?.length===0&&!draft.payload.fields.title&&!draft.payload.fields.body;
      });
      await go('sources');
      if(await page.locator('[data-source-action=preset]').count()){
        await page.locator('[data-source-action=preset][data-id=wechat_public]').click();
        check('Source starter preselects the corresponding platform',await page.locator('#dialog [name=platform]').inputValue()==='wechat_public');
        check('Platform-specific field is visible',await page.locator('[data-followed-field]').isVisible());
        await page.keyboard.press('Escape');
      }
      await go('memory');
      await page.locator('[data-memory-scope=project]').click();
      check('Memory scope is selected and keyboard reachable',await page.locator('[data-memory-scope=project]').getAttribute('aria-selected')==='true'&&await page.locator('[data-memory-scope=project]').getAttribute('tabindex')==='0');
      await page.locator('[data-memory-scope=project]').focus();await page.keyboard.press('ArrowRight');
      check('Scope tabs follow keyboard navigation',await page.locator('[data-memory-scope=topic]').getAttribute('aria-selected')==='true');
      check('Document stays within viewport',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      // User setting takes precedence, independently of OS reduced-motion.
      await page.evaluate(()=>localStorage.setItem('campus.motion.enabled','false'));
      await go('dashboard');
      check('Saved motion preference survives navigation/reload',await page.locator('html').getAttribute('data-ui-motion')==='off'&&await page.locator('[data-orbit]').evaluateAll(nodes=>nodes.every(n=>n.classList.contains('fx-paused'))));
      await context.close();
      console.log('Upgrade flows complete:',engine,width);
    }
  }finally{await browser.close();}
}
function awaitableDay(day){return /^\d{4}-\d{2}-\d{2}$/.test(day||'');}
await writeFile(artifactPath('upgrade-interactions.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({checks:report.checks.length,failed:report.checks.filter(c=>!c.passed),errors:report.errors},null,2));
if(report.errors.length||report.checks.some(c=>!c.passed))process.exitCode=1;
