import {browserExecutable} from './browser-runtime.mjs';
// Real app, signed synthetic webhooks and a loopback fixture for the QQ file response.
import assert from 'node:assert/strict';
import {createPrivateKey,sign} from 'node:crypto';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium,firefox,webkit} from 'playwright';

const origin='http://127.0.0.1:8786';
const folder=path.resolve('artifacts/qq-group-intake-browser');
await mkdir(folder,{recursive:true});
const report={synthetic:true,external_requests:0,checks:[],errors:[]};
const seed=Buffer.from('qq-browser-signing-fixture'.repeat(2)).subarray(0,32);
const key=createPrivateKey({key:Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),seed]),format:'der',type:'pkcs8'});
const original='合成群通知原件，请核对课程资料。';

for(const engine of [chromium,firefox,webkit]){
  const name=engine.name();
  let browser,page;
  const check=async(title,fn)=>{await fn();report.checks.push({browser:name,title,passed:true});};
  try{
    browser=await engine.launch({headless:true,executablePath:browserExecutable(engine)});
    page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
    page.setDefaultTimeout(12000);
    page.on('pageerror',error=>report.errors.push(name+': '+error.message));
    await page.route('**/*',route=>{
      if(new URL(route.request().url()).origin===origin)return route.continue();
      report.external_requests++;
      return route.abort();
    });
    const api=(endpoint,method='GET',json)=>page.evaluate(async({endpoint,method,json})=>{
      const {csrf}=await fetch('/api/session').then(r=>r.json());
      const response=await fetch('/api'+endpoint,{method,headers:{'X-Requested-With':'campus-notice',
        'X-CSRF-Token':csrf,'Content-Type':'application/json'},body:json===undefined?undefined:JSON.stringify(json)});
      if(!response.ok)throw Error(await response.text());
      return response.json();
    },{endpoint,method,json});
    const group='qq-fixture-'+name,alias='课程资料群 '+name;
    const intake='/integrations/qq/groups/'+group+'/intake';
    async function event(content,id,extra={}){
      const payload=JSON.stringify({op:0,t:'GROUP_MESSAGE_CREATE',d:{id,content,group_openid:group,
        author:{member_openid:'owner-'+name,member_role:'owner'},...extra}});
      const stamp=String(Math.floor(Date.now()/1000));
      const response=await page.request.post(origin+'/api/integrations/qq/webhook',{
        data:payload,headers:{'Content-Type':'application/json','X-Bot-Appid':'qq-browser-synthetic',
          'X-Signature-Timestamp':stamp,'X-Signature-Ed25519':sign(null,Buffer.from(stamp+payload),key).toString('hex')}});
      assert.equal(response.status(),200,await response.text());
    }
    const sources=()=>page.locator('[data-source-action=platforms]').click();
    const groupButton=page.locator('[data-source-action=qq-group-intake][data-id="'+group+'"]');
    const open=async()=>{
      await groupButton.click();
      await page.locator('[data-workspace-form=qq-group-intake]').waitFor();
    };
    const filter=page.getByLabel('筛选收件记录');
    const items=page.locator('[data-qq-intake-record]');
    const waitCount=count=>page.waitForFunction(n=>document.querySelectorAll('[data-qq-intake-record]').length===n,count);
    let quietId;

    await page.goto(origin+'/#login');
    await page.locator('[name=username]').fill('workflow.demo');
    await page.locator('[name=password]').fill('Mvp-Verification-Only-2026');
    await page.locator('#auth-form [type=submit]').click();
    await page.waitForURL(/#dashboard/);
    await api('/fixture/qq-enable','POST',{});
    const code=await api('/integrations/qq/group-code','POST',{receive_group_notices:true});
    await event(code.authorize_command,'authorize-'+name);
    await page.goto(origin+'/#sources');
    await sources();
    await check('save real per-group rules and update the parent dialog',async()=>{
      await open();
      const form=page.locator('[data-workspace-form=qq-group-intake]');
      assert.equal(await page.locator('.dialog-dismiss').count(),0);
      await form.getByLabel('群显示名').fill(alias);
      await form.getByLabel('关注词').fill('实验实践，' + name);
      const response=page.waitForResponse(r=>r.url().endsWith(intake)&&r.request().method()==='PUT');
      await form.getByRole('button',{name:'保存群设置'}).click();
      assert.equal((await response).status(),200);
      assert.deepEqual((await api(intake)).settings,{name:alias,mode:'notices',keywords:['实验实践',name],version:1});
      await page.locator('[data-dialog-back]').click();
      await page.locator('[data-qq-group-name]').filter({hasText:alias}).waitFor();
    });

    await event('收到','ack');
    for(let i=0;i<25;i++)await event(name+' 第 '+i+' 项实践请提交证明','practice-'+i);
    await event('','file',{attachments:[{url:'https://multimedia.nt.qq.com.cn/download?fileid=browser-synthetic',
      filename:'合成原件.txt',content_type:'text/plain'}]});
    await check('filter, page and refresh the real history without horizontal overflow',async()=>{
      await open();
      await waitCount(25);
      await filter.selectOption('discussion');
      await waitCount(1);
      assert.match(await items.first().innerText(),/普通讨论默认收起/);
      const quiet=(await api(intake+'?category=discussion')).items[0];
      quietId=quiet.notice_id;
      await filter.selectOption('all');
      await waitCount(25);
      await page.getByRole('button',{name:'下一页'}).click();
      await waitCount(2);
      await page.getByRole('button',{name:'上一页'}).click();
      await waitCount(25);
      for(const [width,height] of [[320,680],[390,844],[768,1024],[1440,900]]){
        await page.setViewportSize({width,height});
        const overflowing=await page.evaluate(()=>{
          const dialog=document.querySelector('#dialog'),body=dialog.querySelector('.dialog-body');
          return document.documentElement.scrollWidth>innerWidth+2||dialog.scrollWidth>dialog.clientWidth+2||
            body.scrollWidth>body.clientWidth+2;
        });
        assert.equal(overflowing,false,name+' at '+width+' × '+height);
      }
      await page.screenshot({path:path.join(folder,name+'-desktop.png')});
    });
    await check('open the received file and retrieve it from the real notice route',async()=>{
      const start=Date.now();
      while((await api(intake)).items[0].media_state!=='complete'){
        assert.ok(Date.now()-start<16000,'group attachment worker did not finish');
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      await page.getByRole('button',{name:'刷新',exact:true}).click();
      const received=items.filter({hasText:'原件已保存'});
      await received.waitFor();
      await page.setViewportSize({width:390,height:844});
      await page.screenshot({path:path.join(folder,name+'-phone.png')});
      await received.getByRole('link',{name:'查看原文'}).click();
      await page.waitForURL(/#notice\//);
      assert.equal(await page.locator('#dialog').evaluate(d=>d.open),false);
      const nid=new URL(page.url()).hash.split('/')[1];
      const n=await api('/notices/'+nid);
      const file=n.sources.find(s=>s.name==='合成原件.txt');
      assert.equal(file.sections[0].text,original);
      const download=await page.request.get(origin+'/api/notices/'+nid+'/sources/'+file.id+'/download');
      assert.equal(await download.text(),original);
    });
    await check('the library can recover archived group discussion',async()=>{
      await page.goto(origin+'/#notices');
      await page.getByLabel('按办理状态查看').selectOption('discussion');
      await page.locator('a[href="#notice/'+quietId+'"]').waitFor();
    });
  }catch(error){
    report.errors.push(name+': '+error.stack);
    if(page)await page.screenshot({path:path.join(folder,name+'-failure.png')}).catch(()=>{});
  }finally{
    if(browser)await browser.close();
  }
}
await writeFile(path.join(folder,'report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
if(report.errors.length||report.external_requests)process.exitCode=1;
