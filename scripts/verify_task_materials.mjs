// Synthetic application workflow; no real school submission or model calls.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const out=path.resolve('artifacts/task-materials-browser'),root=path.resolve('.');await fs.mkdir(out,{recursive:true});
const require=createRequire(path.join(root,'package.json')),{chromium}=require('playwright');
const seed={username:'workflow.demo',password:'Mvp-Verification-Only-2026'};
const browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()});
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN',timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
const report={synthetic_data:true,external_calls:false,checks:[],errors:[]};page.on('pageerror',e=>report.errors.push(e.message));
const api=(url,method='GET',data=null,form=false)=>page.evaluate(async({url,method,data,form})=>{
 const session=await fetch('/api/session').then(r=>r.json());const headers={'X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf};
 let body;if(data){if(form){body=new FormData();for(const[k,v]of Object.entries(data))body.set(k,v);}else{headers['Content-Type']='application/json';body=JSON.stringify(data);}}
 const r=await fetch('/api'+url,{method,headers,body});if(!r.ok)throw Error(await r.text());return r.json();
},{url,method,data,form});
const open=async()=>{await page.goto('http://127.0.0.1:8786/#notice/'+seed.notice_id);await page.locator('[data-workflow-task="'+seed.task_id+'"]').first().click();await page.locator('[data-upload-material]').waitFor();};
const upload=async(requirement,filename,text)=>{await page.locator('[data-material-requirement]').selectOption(requirement);await page.locator('[data-material-file]').setInputFiles({name:filename,mimeType:'text/plain',buffer:Buffer.from(text)});await page.locator('[data-upload-material]').click();await page.getByText('本人材料已保存',{exact:true}).waitFor();};
try{
 await page.goto('http://127.0.0.1:8786/#login');await page.locator('[name=username]').fill(seed.username);await page.locator('[name=password]').fill(seed.password);await page.locator('#auth-form [type=submit]').click();await page.locator('#content:not([inert])').waitFor();
 const template={...(await api('/tasks'))[0].data,materials:['申请表（本人填写并签字）','成绩单（教务系统导出）'],submission:'学院办公室',uncertainties:[],resolution_note:'合成测试材料已核对'};
 let fresh=await api('/notices','POST',{title:'合成材料验收通知',body:'合成申请通知 '+Date.now(),materials_complete:'true'},true);fresh=await api('/notices/'+fresh.id+'/manual','POST',{version:fresh.version});
 const freshTasks=await api('/notices/'+fresh.id+'/confirm','POST',{version:fresh.version,reviewed:true,tasks:[template],plans:{0:{execution_mode:'submission',action_kind:'required',depends_on:[],conditions:[]}}});seed.notice_id=fresh.id;seed.task_id=freshTasks.task_ids[0];
 const original=await api('/notices/'+seed.notice_id);
 await page.goto('http://127.0.0.1:8786/#notice/'+seed.notice_id);await page.locator('[data-action=toggle-task][data-id="'+seed.task_id+'"]').first().click();await page.locator('[data-upload-material]').waitFor();
 assert.equal((await api('/tasks/'+seed.task_id+'/workflow')).task.status,'pending');report.checks.push('Completing an unsubmitted application opens its handling workspace and leaves the task pending');
 await upload('申请表（本人填写并签字）','application-v1.txt','合成申请表：已填写并签字。');
 assert.equal(await page.locator('.personal-file').count(),1);report.checks.push('Uploaded personal file appears immediately in its requirement group');
 const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载材料包',exact:true}).click();const downloaded=await downloading;assert.ok(downloaded.suggestedFilename().endsWith('.zip'));assert.equal((await fs.readFile(await downloaded.path())).subarray(0,2).toString(),'PK');report.checks.push('The package link downloads an actual ZIP through the authenticated API');
 await page.locator('.personal-submission-editor>summary').click();await page.locator('[data-submission-channel]').fill('合成场景：学院办公室');await page.locator('[data-submission-receipt]').fill('合成回执编号 RECEIPT-001');
 await upload('成绩单（教务系统导出）','transcript.txt','合成成绩单：本人课程记录。');
 assert.equal(await page.locator('[data-submission-receipt]').inputValue(),'合成回执编号 RECEIPT-001');report.checks.push('Adding another file preserves an in-progress submission draft');
 assert.equal(await page.locator('.personal-file').count(),2);
 await page.locator('[data-submission-confirm]').check();await page.locator('[data-record-submission]').click();await page.locator('#dialog').waitFor({state:'hidden'});
 const after=await api('/notices/'+seed.notice_id);assert.equal(after.version,original.version);assert.equal(after.status,original.status);assert.deepEqual(after.sources,original.sources);report.checks.push('Personal uploads and submission do not change notice evidence, status, or version');
 const flow=await api('/tasks/'+seed.task_id+'/workflow');assert.equal(flow.task.workflow.data.stage,'submitted');assert.equal(flow.task.status,'pending');
 let files=await api('/tasks/'+seed.task_id+'/materials');assert.equal(files.submissions.length,1);assert.equal(files.submissions[0].data.files.length,2);report.checks.push('One UI action atomically records fixed file versions and self-reported submitted state, without completing or accepting the task');
 await open();const application=files.materials.find(m=>m.requirement==='申请表（本人填写并签字）');
 await page.locator('[data-replace-material="'+application.id+'"]').click();await page.locator('[data-material-file]').setInputFiles({name:'application-v2.txt',mimeType:'text/plain',buffer:Buffer.from('合成修订申请表：更正说明。')});await page.locator('[data-upload-material]').click();await page.getByText('本人材料已保存',{exact:true}).waitFor();
 files=await api('/tasks/'+seed.task_id+'/materials');assert.equal(files.materials.find(m=>m.id===application.id).version,2);assert.equal(files.submissions[0].data.files.find(f=>f.material_id===application.id).version,1);report.checks.push('Uploading version 2 keeps the prior submission snapshot on version 1');
 await page.screenshot({path:path.join(out,'implemented-personal-materials-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'implemented-personal-materials-mobile.png'),fullPage:true});
 assert.equal(await page.locator('#dialog').evaluate(n=>n.scrollWidth>n.clientWidth+2),false);report.checks.push('390px dialog has no horizontal overflow');
 await page.keyboard.press('Escape');await page.locator('#dialog').waitFor({state:'hidden'});
 let reading=await api('/notices','POST',{title:'合成阅读通知',body:'合成阅读通知 '+Date.now(),materials_complete:'true'},true);reading=await api('/notices/'+reading.id+'/manual','POST',{version:reading.version});
 const base={...flow.task.data,title:'合成阅读事项',materials:[],due_date:null,due_time:null,deadline_confirmed:false,deadline_text:'',planned_at:null,reminder_at:null};
 const created=await api('/notices/'+reading.id+'/confirm','POST',{version:reading.version,reviewed:true,tasks:[base],plans:{0:{execution_mode:'reading',action_kind:'required',depends_on:[],conditions:[]}}});
 await page.goto('http://127.0.0.1:8786/#notice/'+reading.id);await page.locator('[data-workflow-task="'+created.task_ids[0]+'"]').first().click();await page.locator('#workflow-form').waitFor();
 assert.equal(await page.locator('.personal-materials').isVisible(),false);report.checks.push('A reading task without required materials does not show the application-file workflow');
}catch(e){report.errors.push(e.stack);process.exitCode=1;await page.screenshot({path:path.join(out,'implemented-materials-failure.png'),fullPage:true});}
finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report,null,2));}
