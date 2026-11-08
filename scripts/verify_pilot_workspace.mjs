/** Independent browser contexts, real storage and routes, captured synthetic SMS. */
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';

const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/pilot-workspace-browser');
const report={fixture:'Independent desktop/mobile browser contexts, real application APIs, local SMS capture',checks:[],errors:[],timings:[]};
await fs.mkdir(out,{recursive:true});
const password='PilotFixtureOnly2026!';
const measured=(engine,name,elapsed,status)=>report.timings.push({engine,name,ms:Math.round(elapsed*10)/10,status});

for(const [engineIndex,engine] of (process.env.UI_ENGINES||'chromium,firefox,webkit').split(',').entries()){
  const browser=await pw[engine].launch({headless:true,executablePath:pw[engine].executablePath()});
  const [a,b,c]=await Promise.all([
    browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'}),
    browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),
    browser.newContext({viewport:{width:1240,height:850},reducedMotion:'reduce'}),
  ]);
  const [desktop,mobile,counselor]=await Promise.all([a.newPage(),b.newPage(),c.newPage()]);
  for(const page of [desktop,mobile,counselor]){
    page.setDefaultTimeout(12000);
    page.on('pageerror',error=>report.errors.push({engine,error:error.message}));
  }
  const site=await pw.request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
  const username='pilot-student-'+engine,phone='1399900'+String(7000+engineIndex);
  let tid,task,caseId;
  const headers={'Origin':origin,'X-Requested-With':'campus-notice'};
  const api=async(ctx,route,method='GET',data=null,expected=200,label=route)=>{
    const client=ctx.request||ctx;
    const session=method==='GET'?null:await client.get(origin+'/api/session').then(r=>r.json());
    const start=performance.now();
    const response=await client.fetch(origin+'/api'+route,{method,headers:{...headers,...(session?.csrf?{'X-CSRF-Token':session.csrf}:{})},...(data?{data}:{})});
    measured(engine,label,performance.now()-start,response.status());
    assert.equal(response.status(),expected,await response.text());
    return (response.headers()['content-type']||'').includes('json')?response.json():response.text();
  };
  async function intake(route,multipart,label){
    const session=await api(a,'/session');
    const start=performance.now();
    const response=await a.request.post(origin+'/api'+route,{headers:{...headers,'X-CSRF-Token':session.csrf},multipart});
    measured(engine,label,performance.now()-start,response.status());
    assert.equal(response.status(),200,await response.text());
    return response.json();
  }
  async function nav(page,hash){
    await page.goto(origin+'/#'+hash,{waitUntil:'domcontentloaded'});
    await page.waitForFunction(target=>{
      const content=document.querySelector('#content');
      return content?.dataset.page===target&&!content.inert;
    },hash);
  }
  const check=async(name,run)=>{
    try{await run();report.checks.push({engine,name,ok:true});}
    catch(error){report.checks.push({engine,name,ok:false,error:error.message});throw error;}
  };
  async function submit(page,route,click,label){
    const start=performance.now();
    const [response]=await Promise.all([
      page.waitForResponse(r=>r.url()===origin+'/api'+route&&r.request().method()==='POST'),click(),
    ]);
    measured(engine,label,performance.now()-start,response.status());
    assert.equal(response.status(),200,await response.text());
    return response.json();
  }
  async function visibleAfter(label,commit,ready){
    await commit();
    const start=performance.now();
    await ready();
    const elapsed=performance.now()-start;
    measured(engine,label,elapsed,'visible');
    assert.ok(elapsed<5000,label+' exceeded the five-second local visibility target');
  }
  try{
    console.log('Pilot workspace: '+engine);
    await check('SMS signup, distinct device login, and authorized student membership',async()=>{
      await desktop.goto(origin+'/#register');
      await desktop.locator('[data-otp-destination]').fill(phone);
      await desktop.locator('[name=verification_consent]').check();
      const challenge=await submit(desktop,'/auth/challenges',()=>desktop.locator('[data-otp-send]').click(),'signup: provider accepted');
      const fixture=await api(a,'/fixture/pilot-otp/'+challenge.challenge_id,'GET',null,200,'fixture code receipt');
      assert.equal(fixture.synthetic,true);
      await desktop.locator('[data-otp-code]').fill(fixture.code);
      await submit(desktop,'/auth/verify',()=>desktop.locator('[data-signup-next="1"]').click(),'signup: proof');
      await desktop.locator('[name=display_name]').fill('独立设备测试 '+engine);
      await desktop.locator('[name=username]').fill(username);
      await desktop.locator('[data-signup-next="2"]').click();
      await desktop.locator('[name=password]').fill(password);
      await desktop.locator('[name=confirm_password]').fill(password);
      await desktop.locator('[name=accepted_terms]').check();
      const started=performance.now();
      const registered=await submit(desktop,'/auth/register',()=>desktop.locator('#auth-form [type=submit]').click(),'signup: commit');
      assert.equal(registered.session.user.username,username);
      await desktop.locator('#content[data-page=dashboard]:not([inert])').waitFor();
      measured(engine,'signup: dashboard visible',performance.now()-started,'visible');
      await mobile.goto(origin+'/#login');
      await mobile.locator('[name=username]').fill(phone);
      await mobile.locator('[name=password]').fill(password);
      const loginStart=performance.now();
      const signed=await submit(mobile,'/auth/login',()=>mobile.locator('#auth-form [type=submit]').click(),'login: password');
      assert.equal(signed.session.user.id,registered.session.user.id);
      await mobile.locator('#content[data-page=dashboard]:not([inert])').waitFor();
      measured(engine,'login: dashboard visible',performance.now()-loginStart,'visible');
      const sessions=[(await a.cookies()).find(x=>x.name==='campus_session'),(await b.cookies()).find(x=>x.name==='campus_session')];
      assert.ok(sessions.every(Boolean));assert.notEqual(sessions[0].value,sessions[1].value);
      await api(site,'/auth/login','POST',{username:'pilot-site',password},200,'site admin login');
      await api(site,'/campus/members/'+username,'PUT',{college_id:'sres',role:'student',grade:'2026级',class_name:'试点一班',version:0},200,'grant scoped student role');
      await api(c,'/auth/login','POST',{username:'pilot-counselor',password},200,'counselor login');
    });
    await check('account display preferences synchronize with separate local storage',async()=>{
      await nav(desktop,'settings');await nav(mobile,'settings');
      for(const page of [desktop,mobile]){
        await page.locator('[data-settings-category=display]').click();
        await page.locator('.settings-usage>summary').click();
      }
      const input=desktop.locator('#companion-enabled');
      await desktop.bringToFront();
      await input.evaluate(node=>{window.pilotDisplayToggle=node;});
      const previous=(await api(b,'/session')).user.profile.preferred_name;
      const preferredName='跨端更新 '+engine;
      await visibleAfter('settings: profile summary visible',()=>api(b,'/profile','PATCH',{
        changes:{preferred_name:preferredName},expected:{preferred_name:previous}
      },200,'settings: save profile name'),()=>desktop.locator('.settings-person h2').filter({hasText:preferredName}).waitFor());
      assert.equal(await input.evaluate(node=>node===window.pilotDisplayToggle),true);
      await mobile.bringToFront();
      assert.equal(await mobile.locator('#companion-enabled').isChecked(),true);
      const start=performance.now();
      const [response]=await Promise.all([
        desktop.waitForResponse(r=>r.url()===origin+'/api/profile'&&r.request().method()==='PATCH'),input.uncheck(),
      ]);
      measured(engine,'settings: write',performance.now()-start,response.status());
      assert.equal(response.status(),200,await response.text());
      await visibleAfter('settings: other device visible',async()=>{},()=>mobile.waitForFunction(()=>!document.querySelector('#companion-enabled')?.checked&&!!document.querySelector('#companion-enabled')));
    });
    await check('notice receipt becomes a task and updates the other device selectively',async()=>{
      await nav(mobile,'tasks');await mobile.bringToFront();
      const calls=[],track=r=>{if(r.url().startsWith(origin+'/api/'))calls.push(new URL(r.url()).pathname);};
      mobile.on('request',track);
      const n=await intake('/notices',{title:'毕业论文选题流程核对 '+engine,
        body:'合成演练。题目申报、学院审核、学生选题分开记录。请核对你所负责的阶段和材料。',materials_complete:'true'},'notice: receive');
      const draft=await api(a,'/notices/'+n.id+'/manual','POST',{version:n.version},200,'notice: create manual draft');
      const title='核对本人选题材料 '+engine;
      await visibleAfter('task: other device visible',async()=>{
        const saved=await api(a,'/notices/'+n.id+'/confirm','POST',{version:draft.version,reviewed:true,tasks:[{title,materials:['签字页']}]},200,'notice: confirm task');
        tid=saved.task_ids[0];
      },()=>mobile.getByText(title,{exact:true}).waitFor());
      mobile.off('request',track);
      assert.ok(calls.includes('/api/tasks'));
      assert.ok(!calls.includes('/api/notices'),'A task list refresh must not download the notice library');
      task=(await api(a,'/tasks/'+tid+'/workflow')).task;
    });
    await check('an open notice receives a new source and the updated material count',async()=>{
      const n=await intake('/notices',{title:'来源补充核对 '+engine,body:'试点验收用的原始说明。'},'notice: receive for source update');
      await nav(mobile,'notice/'+n.id);await mobile.bringToFront();
      const summary=mobile.locator('.notice-originals>summary');
      assert.match(await summary.textContent(),/1 份/);
      await summary.click();
      await mobile.locator('.notice-context>summary').click();
      const body='试点验收用的更正说明，实际需要签字页。';
      await visibleAfter('notice: updated source visible',
        ()=>intake('/notices/'+n.id+'/supplement',{version:String(n.version),body},'notice: supplement source'),
        ()=>summary.getByText(/2 份/).waitFor());
      assert.equal(await mobile.locator('.notice-context').evaluate(node=>node.open),true);
      assert.equal(await mobile.locator('.notice-originals').evaluate(node=>node.open),true);
      await mobile.locator('.source-pane .source-section').filter({hasText:body}).waitFor();
    });
    await check('new arrangement and explicit calendar view synchronize without a reload',async()=>{
      await nav(desktop,'calendar');await nav(mobile,'calendar');await mobile.bringToFront();
      const [viewSaved]=await Promise.all([
        desktop.waitForResponse(r=>r.url()===origin+'/api/profile'&&r.request().method()==='PATCH'),
        desktop.locator('[data-calendar-view=day]').click(),
      ]);
      assert.equal(viewSaved.status(),200);
      await mobile.waitForFunction(()=>document.querySelector('[data-calendar-view=day]')?.getAttribute('aria-selected')==='true');
      const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
      const title='联动日程 '+engine;
      await visibleAfter('calendar: other device visible',()=>api(a,'/arrangements','POST',{data:{title,start_date:day,end_date:day,category:'personal'},request_id:randomUUID()},200,'calendar: create'),
        ()=>mobile.getByText(title,{exact:true}).first().waitFor());
    });
    await check('open workflow shows the latest receipt without overwriting a draft',async()=>{
      await nav(mobile,'tasks');await mobile.bringToFront();
      await mobile.locator('.task-primary[data-workflow-task="'+tid+'"]').click();
      await mobile.locator('#workflow-form').waitFor();
      const draft=mobile.locator('#workflow-form [name=outcome]');
      // The detailed fields may be collapsed until explicitly opened.
      while(await draft.locator('xpath=ancestor::details[not(@open)]').count()){
        await draft.locator('xpath=ancestor::details[not(@open)]').first().locator(':scope>summary').click();
      }
      await draft.fill('这段本人编辑要保留');
      const next='设备 A 已保存的跟进 '+engine;
      await visibleAfter('workflow: open detail visible',()=>api(a,'/tasks/'+tid+'/workflow','PUT',{
        version:task.workflow.version,task_version:task.version,data:{...task.workflow.data,next_step:next}
      },200,'workflow: save new progress'),()=>mobile.locator('[data-workflow-newer]').getByText('下一步 '+next,{exact:true}).waitFor());
      assert.equal(await draft.inputValue(),'这段本人编辑要保留');
    });
    await check('open workflow reflects material versions while retaining an unuploaded file',async()=>{
      const input=mobile.locator('#workflow-form [data-material-file]');
      await input.waitFor({state:'attached'});
      while(await input.locator('xpath=ancestor::details[not(@open)]').count()){
        await input.locator('xpath=ancestor::details[not(@open)]').first().locator(':scope>summary').click();
      }
      await input.setInputFiles({name:'未上传的本人文件.txt',mimeType:'text/plain',buffer:Buffer.from('尚未提交')});
      const latest=(await api(a,'/tasks/'+tid+'/workflow')).task;
      const upload=(name,text,prior={})=>intake('/tasks/'+tid+'/materials',{
        task_version:String(latest.version),requirement:'签字页',request_id:randomUUID(),
        file:{name,mimeType:'text/plain',buffer:Buffer.from(text)},...prior
      },'workflow: save material version');
      let first;
      const list=mobile.locator('#workflow-form .personal-file-list');
      await visibleAfter('workflow: material visible',async()=>{first=await upload('已提交材料.txt','第一版');},
        ()=>list.getByText('已提交材料.txt',{exact:true}).waitFor());
      await visibleAfter('workflow: new material version visible',()=>upload('已提交材料修订.txt','第二版',{
        material_id:first.materials[0].id,expected_version:'1'
      }),()=>list.getByText('已提交材料修订.txt',{exact:true}).waitFor());
      assert.equal(await input.evaluate(node=>node.files[0]?.name),'未上传的本人文件.txt');
      assert.equal(await mobile.locator('#workflow-form [name=outcome]').inputValue(),'这段本人编辑要保留');
      await mobile.keyboard.press('Escape');
    });
    await check('scoped collaboration is received, returned, supplemented and resolved across devices',async()=>{
      await nav(counselor,'collaboration');
      await mobile.bringToFront();
      await mobile.locator('.task-primary[data-workflow-task="'+tid+'"]').click();
      const currentForm=mobile.locator('#workflow-form');
      await currentForm.evaluate(node=>{window.pilotOpenWorkflow=node;});
      const previous=(await api(a,'/tasks/'+tid+'/workflow')).task;
      const firstNext='保持表单时更新进度 '+engine;
      await visibleAfter('workflow: open form stays in place',()=>api(a,'/tasks/'+tid+'/workflow','PUT',{
        version:previous.workflow.version,task_version:previous.version,data:{...previous.workflow.data,next_step:firstNext}
      },200,'workflow: save while form is open'),()=>mobile.locator('[data-workflow-newer]').getByText('下一步 '+firstNext,{exact:true}).waitFor());
      assert.equal(await currentForm.evaluate(node=>node===window.pilotOpenWorkflow),true);
      const optionsPath='/api/collaboration/tasks/'+tid+'/options';
      // Hold only this page's options read. The revision poll and the eventual
      // options response still use the real server without route interception.
      await mobile.evaluate(path=>{
        const fetchOptions=window.fetch;
        let release;
        const gate=new Promise(resolve=>{release=resolve;});
        window.pilotOptionsWaiting=false;
        window.releasePilotOptions=()=>{window.fetch=fetchOptions;release();};
        window.fetch=async function(input,init){
          if(input===path){window.pilotOptionsWaiting=true;await gate;}
          return fetchOptions.call(window,input,init);
        };
      },optionsPath);
      try{
        await mobile.locator('[data-collaboration-start]').click();
        await mobile.waitForFunction(()=>window.pilotOptionsWaiting);
        const latest=(await api(a,'/tasks/'+tid+'/workflow')).task;
        const next='接收人读取期间更新进度 '+engine;
        await visibleAfter('workflow: pending action remains available',()=>api(a,'/tasks/'+tid+'/workflow','PUT',{
          version:latest.workflow.version,task_version:latest.version,data:{...latest.workflow.data,next_step:next}
        },200,'workflow: save during recipient lookup'),()=>mobile.locator('[data-workflow-newer]').getByText('下一步 '+next,{exact:true}).waitFor());
        const response=mobile.waitForResponse(item=>item.url()===origin+optionsPath);
        await mobile.evaluate(()=>window.releasePilotOptions());
        assert.equal((await response).status(),200);
      }finally{await mobile.evaluate(()=>window.releasePilotOptions?.());}
      const form=mobile.locator('#dialog [data-workspace-form=collaboration]');
      await form.locator('[name=note]').fill('协助核对选题签字页');
      await form.getByRole('checkbox',{name:'已提交材料修订.txt · 第 2 版'}).check();
      const created=await submit(mobile,'/collaboration',()=>form.locator('[type=submit]').click(),'collaboration: send');
      caseId=created.id;
      await visibleAfter('collaboration: recipient inbox visible',async()=>{},()=>counselor.locator('a[href="#collaboration/'+caseId+'"]').waitFor());
      await counselor.locator('a[href="#collaboration/'+caseId+'"]').click();
      async function act(page,action,note=''){
        const editor=page.locator('#content [data-workspace-form=collaboration]');
        await editor.locator('[name=action]').selectOption(action);
        if(note)await editor.locator('[name=note]').fill(note);
        return submit(page,'/collaboration/'+caseId+'/actions',()=>editor.locator('[type=submit]').click(),'collaboration: '+action);
      }
      await nav(mobile,'collaboration/'+caseId);
      await act(counselor,'accept');
      await counselor.locator('[data-collaboration-status]').getByText('办理中',{exact:true}).waitFor();
      await visibleAfter('collaboration: supplement request visible',()=>act(counselor,'request_supplement','请补交签字页'),
        ()=>mobile.getByText('请补交签字页',{exact:true}).waitFor());
      await act(mobile,'resubmit','已补齐所需签字');
      await counselor.getByText('已补齐所需签字',{exact:true}).waitFor();
      await act(counselor,'accept');
      await counselor.getByText('办理中',{exact:true}).waitFor();
      await visibleAfter('collaboration: resolution receipt visible',()=>act(counselor,'resolve','回执：签字页已核对'),
        ()=>mobile.getByText('回执：签字页已核对',{exact:true}).waitFor());
      assert.equal((await api(a,'/tasks/'+tid+'/workflow')).task.status,'pending');
    });
    await check('disconnected device catches up and a local chat query uses the saved records',async()=>{
      await nav(mobile,'tasks');await b.setOffline(true);
      const old=(await api(a,'/tasks/'+tid+'/workflow')).task,title='断线后核对 '+engine;
      await api(a,'/tasks/'+tid,'PUT',{version:old.version,status:old.status,data:{...old.data,title},reason:'跨设备断线恢复验收'},200,'task: update while other device is offline');
      assert.equal(await mobile.getByText(title,{exact:true}).count(),0);
      await visibleAfter('offline recovery: latest task visible',()=>b.setOffline(false),()=>mobile.getByText(title,{exact:true}).waitFor());
      const chat=await api(a,'/conversations','POST',{title:'当前办理数据核对'},200,'chat: create');
      const sse=await api(a,'/conversations/'+chat.id+'/messages/stream','POST',{version:chat.version,request_id:randomUUID(),content:'我的待办一共有几条？',allow_external_processing:false},200,'chat: local count');
      const done=JSON.parse(sse.split('\n').find(line=>line.startsWith('data: ')).slice(6));
      assert.equal(done.conversation.messages.at(-1).grounding.planning_mode,'host_workspace_count');
      await nav(mobile,'chat/'+chat.id);
      await mobile.getByText(/你当前保存了 1 条待办记录/).first().waitFor();
    });
    await mobile.screenshot({path:path.join(out,engine+'-mobile.png')});
  }catch(error){
    report.errors.push({engine,error:error.message});
    console.error(engine,error.message);
    for(const [name,page] of [['desktop',desktop],['mobile',mobile],['counselor',counselor]]){
      await page.screenshot({path:path.join(out,engine+'-'+name+'-failure.png')}).catch(()=>{});
    }
  }finally{
    await site.dispose();await browser.close();
  }
  await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
}
console.log(JSON.stringify({checks:report.checks.length,failed:report.checks.filter(x=>!x.ok).length,errors:report.errors.length}));
if(report.errors.length||report.checks.some(x=>!x.ok))process.exitCode=1;
