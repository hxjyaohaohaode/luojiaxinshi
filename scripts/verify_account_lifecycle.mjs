/** Account lifecycle through the real UI and APIs; delivery is an isolated local capture. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
import {browserExecutable} from './browser-runtime.mjs';

const require=createRequire(import.meta.url),pw=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8786',out=path.resolve('artifacts/account-lifecycle-browser');
const engines=(process.env.UI_ENGINES||'chromium,firefox,webkit').split(','),timeout=12000;
const names=[
  'mobile signup retains a rejected code and verifies normalized six-digit input only after explicit submission',
  'the three signup stages create the verified owner and open the workspace',
  'a rejected password keeps the same accessible form and a corrected retry signs in',
  'verification-code login returns to the same owner through the real proof endpoint',
  'a private notice and edited personal conditions persist through real workspace forms',
  'a delayed successful password response cannot replace a newer dialog and invalidates the older device',
  'verified password recovery renews the same owner without losing private records',
  'a rejected account deletion retains the account and does not request remote push detachment',
  'confirmed account deletion clears the session and denies the previous private record',
  'registering the same contact and account name again creates an empty distinct owner',
  'the complete account lifecycle has no uncaught browser errors',
];
const report={fixture:'Loopback-only real application APIs and synthetic phone numbers. Codes come from the explicitly enabled local capture; no real SMS, email, school, or deployment acceptance is claimed.',network_fixture:{service_workers:'block',reason:'The password response is held after the real server commits; PWA behavior remains covered independently.'},cooldown_fixture:'Only the captured challenge destination cooldown is expired by an opt-in fixture endpoint. This is not a claim of waiting sixty seconds or disabling other limits.',clipboard_fixture:'The native input receives a synthetic ClipboardEvent carrying full-width digits and spaces; this exercises the real paste handler, not an operating-system clipboard integration.',observation_scope:'HTTP projections retain only owner identity, profile fields under test, record IDs, list totals, synthetic cooldown scope and presence of a verification proof. Tokens, passwords and the original verification digits are never recorded.',expected_checks:engines.length*names.length,names,status:'running',complete:false,passed:false,checks:[],errors:[],receipts:[],api_observations:[],authentication:[],otp:[],geometry:[],password_delays:[],deletions:[],requests:[]};
await fs.mkdir(out,{recursive:true});
async function save(){const file=path.join(out,'report.json');await fs.writeFile(file+'.tmp',JSON.stringify(report,null,2));await fs.rename(file+'.tmp',file);}
async function bounded(promise,label){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+' exceeded '+timeout+' ms')),timeout);})]);}finally{clearTimeout(timer);}}
const sha=value=>createHash('sha256').update(value).digest('hex');
function safeProjection(route,value){
  if(!value||typeof value!=='object')return null;
  const result={},user=value.session?.user||(route==='/session'?value.user:null);
  if(user)result.owner={id:user.id,username:user.username,profile:{school:user.profile?.school,college:user.profile?.college}};
  if(route==='/auth/challenges')Object.assign(result,{challenge_id:value.challenge_id,retry_after:value.retry_after});
  if(route==='/auth/verify')result.verification_proof_present=typeof value.verification_token==='string'&&value.verification_token.length>0;
  if(['/notices/page','/tasks/page'].includes(route))Object.assign(result,{total:value.total,item_ids:(value.items||[]).map(item=>item.id)});
  if(/^\/notices\/[^/]+$/.test(route)&&value.id)result.record_id=value.id;
  if(route==='/fixture/account-otp-cooldown')for(const key of ['synthetic','challenge_id','cooldown_rows_removed','scope'])result[key]=value[key];
  if(route.startsWith('/fixture/pilot-otp/'))result.synthetic=value.synthetic;
  return result;
}
await save();

for(const [engineIndex,engine] of engines.entries()){
  const browser=await pw[engine].launch({headless:true,executablePath:browserExecutable(pw[engine])});
  const context=await browser.newContext({viewport:{width:320,height:800},serviceWorkers:'block',locale:'zh-CN'}),page=await context.newPage();
  const otherContext=await browser.newContext({viewport:{width:1280,height:850},serviceWorkers:'block'}),other=await otherContext.newPage();
  const pageErrors=[],password='AccountFixtureOnly2026!',nextPassword='AccountUpdatedOnly2026!',recoveredPassword='AccountRecoveredOnly2026!';
  const username='account-'+engine+'-'+randomUUID().slice(0,8),phone='1399900'+String(8100+engineIndex);
  const identity={engine,username,phone,original_owner:null,new_owner:null};report.authentication.push(identity);
  let oldOwner,noticeId,initialOtp,lastChallenge;
  for(const p of [page,other]){p.setDefaultTimeout(timeout);p.setDefaultNavigationTimeout(45000);p.on('pageerror',error=>{const item={engine,page:p===page?'primary':'other',error:error.message};pageErrors.push(item);report.errors.push(item);process.exitCode=1;});}
  page.on('request',request=>{const url=new URL(request.url());if(url.origin!==origin)return;report.requests.push({engine,at:Date.now(),method:request.method(),path:url.pathname+url.search});if(report.requests.length>240)report.requests.splice(0,report.requests.length-240);});
  const responseFor=(p,pathname,method='POST')=>p.waitForResponse(response=>response.url()===origin+'/api'+pathname&&response.request().method()===method);
  const request=async(route,{method='GET',data,expected=200,ctx=context}={})=>{
    const headers={Origin:origin,'X-Requested-With':'campus-notice'};
    if(method!=='GET'){const sessionResponse=await ctx.request.get(origin+'/api/session');if(sessionResponse.ok()){const session=await sessionResponse.json();headers['X-CSRF-Token']=session.csrf;headers['X-Workspace-Owner']=session.user.id;}}
    const response=await ctx.request.fetch(origin+'/api'+route,{method,headers,timeout,...(data===undefined?{}:{data})}),text=await response.text();
    let value;try{value=text?JSON.parse(text):null;}catch{}
    report.api_observations.push({engine,context:ctx===context?'primary':'other',check_index:names.indexOf(report.active?.name),route,method,status:response.status(),body_sha256:sha(text),projection:safeProjection(route,value)});
    assert.equal(response.status(),expected,text);return {status:response.status(),headers:response.headers(),data:text?JSON.parse(text):null};
  };
  const session=async(ctx=context)=>(await request('/session',{ctx})).data;
  async function submit(p,route,action,expected=200){const [response]=await Promise.all([responseFor(p,route),action()]);const text=await response.text();let value;try{value=JSON.parse(text);}catch{}const receipt={engine,context:p===page?'primary':'other',check_index:names.indexOf(report.active?.name),route,method:'POST',status:response.status(),body_sha256:sha(text),projection:safeProjection(route,value)};report.receipts.push(receipt);await save();assert.equal(response.status(),expected,text);return JSON.parse(text);}
  const check=async(index,work)=>{const name=names[index];report.active={engine,name};await save();try{await work();report.checks.push({engine,name,ok:true});}catch(error){report.checks.push({engine,name,ok:false,error:error.stack||String(error)});throw error;}finally{await save();}};
  const ready=()=>page.waitForFunction(()=>{const node=document.querySelector('#content');return node&&!node.inert;});
  const nav=async target=>{await page.evaluate(target=>{location.hash='#'+target;},target);await page.waitForFunction(target=>document.querySelector('#content')?.dataset.page===target&&!document.querySelector('#content')?.inert,target);};
  const closeDialog=async()=>{await page.locator('#dialog').getByRole('button',{name:'关闭',exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});};
  async function settings(kind){await nav('settings');await page.locator('[data-settings-category="'+(kind==='profile'?'personal':'account')+'"]').click();await page.locator('[data-action="settings-'+(kind==='profile'?'profile':'security')+'"]').click();await page.locator(kind==='profile'?'#profile-form':'#password-form').waitFor();}
  async function logout(){await page.setViewportSize({width:1280,height:850});await submit(page,'/auth/logout',()=>page.locator('.sidebar [data-action=logout]').click());await page.locator('#auth-form').waitFor();assert.equal((await request('/session',{expected:401})).status,401);}
  async function passwordLogin(p,secret){await p.goto(origin+'/#login');await p.locator('[data-login-method=password]').click();await p.locator('[name=username]').fill(username);await p.locator('[name=password]').fill(secret);const value=await submit(p,'/auth/login',()=>p.locator('#auth-form [type=submit]').click());await p.locator('#content:not([inert])').waitFor();return value.session.user.id;}
  async function expireCooldown(){assert.ok(lastChallenge,'A real captured challenge must precede fixture cooldown expiration');const value=await request('/fixture/account-otp-cooldown',{method:'POST',data:{challenge_id:lastChallenge}});assert.equal(value.data.synthetic,true);report.otp.push({engine,phase:'synthetic cooldown expiration',challenge_id:lastChallenge,receipt:value.data});await save();}
  async function issue(group,{destination=phone,consent=false,checkCooldown=false}={}){
    if(await group.locator('[data-otp-destination]').count())await group.locator('[data-otp-destination]').fill(destination);
    if(consent)await page.locator('[name=verification_consent]').check();
    const challenge=await submit(page,'/auth/challenges',()=>group.locator('[data-otp-send]').click());assert.ok(challenge.challenge_id);assert.ok(Number.isInteger(challenge.retry_after)&&challenge.retry_after>=1&&challenge.retry_after<=60);lastChallenge=challenge.challenge_id;
    await page.waitForFunction(({id,max})=>{const group=document.querySelector('[data-verification="'+id+'"]'),button=group?.querySelector('[data-otp-send]'),seconds=Number(button?.textContent.match(/^(\d+) 秒后重发$/)?.[1]);return button?.disabled&&Number.isInteger(seconds)&&seconds>=1&&seconds<=max;},{id:await group.getAttribute('data-verification'),max:challenge.retry_after});
    const captured=(await request('/fixture/pilot-otp/'+challenge.challenge_id)).data;assert.equal(captured.synthetic,true);assert.match(captured.code,/^\d{6}$/);
    const evidence={engine,purpose:await group.getAttribute('data-purpose'),challenge_id:challenge.challenge_id,status:'issued',retry_after:challenge.retry_after,button_text:await group.locator('[data-otp-send]').innerText(),button_disabled:await group.locator('[data-otp-send]').isDisabled(),code_sha256:sha(captured.code)};report.otp.push(evidence);
    if(checkCooldown){const denied=await request('/auth/challenges',{method:'POST',expected:429,data:{channel:'sms',destination:phone,purpose:'register',username:'',invite:''}});assert.ok(Number(denied.headers['retry-after'])>0);evidence.cooldown_denial={status:denied.status,retry_after:Number(denied.headers['retry-after'])};}
    // The real password/recovery/delete endpoints retire challenge rows. Expire
    // this isolated contact's cooldown while its captured challenge still exists.
    await expireCooldown();await save();return {challenge,code:captured.code,evidence};
  }
  async function pasteCode(group,code){
    const input=group.locator('[data-otp-code]'),fullWidth=[...code].map(d=>String.fromCharCode(d.charCodeAt(0)+0xfee0)).join(' ');
    const observation=await input.evaluate((node,text)=>{node.focus();const transfer=new DataTransfer();transfer.setData('text/plain',text);const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:transfer});node.dispatchEvent(event);return {value:node.value,prevented:event.defaultPrevented,selection_start:node.selectionStart,selection_end:node.selectionEnd};},fullWidth);
    assert.equal(observation.value,code);assert.equal(observation.prevented,true);assert.equal(observation.selection_start,6);assert.equal(observation.selection_end,6);assert.equal(await input.getAttribute('autocomplete'),'one-time-code');
    assert.equal(await group.locator('[data-otp-slot]').count(),6);assert.equal(await group.locator('.verification-code-slots').getAttribute('aria-hidden'),'true');assert.equal(await group.locator('[data-otp-shell]').getAttribute('data-state'),'ready');assert.equal(await input.evaluate(node=>node.readOnly),false);
    assert.equal((await group.locator('[data-otp-slot]').allTextContents()).join(''),code);const {value,...safe}=observation;return {...safe,normalized_length:value.length,normalized_code_sha256:sha(value)};
  }
  async function touchTarget(locator,label){await locator.scrollIntoViewIfNeeded();const value=await locator.evaluate(node=>{const r=node.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {rect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height},viewport:{width:innerWidth,height:innerHeight},document_width:document.documentElement.scrollWidth,hit:!!hit&&(node===hit||node.contains(hit)),font_size:parseFloat(getComputedStyle(node).fontSize)};});report.geometry.push({engine,label,...value});await save();assert.ok(value.rect.width>=43.9&&value.rect.height>=43.9,label+' must provide at least a 44px target');assert.ok(value.rect.left>=-1&&value.rect.right<=value.viewport.width+1);assert.ok(value.document_width<=value.viewport.width+1);assert.equal(value.hit,true);return value;}
  async function completeSignup(secret,displayName,phase='signup'){await page.locator('[name=display_name]').fill(displayName);await page.locator('[name=username]').fill(username);await page.screenshot({path:path.join(out,engine+'-'+phase+'-account.png'),fullPage:true});await page.locator('[data-signup-next="2"]').click();await page.locator('[data-signup-step="3"]').waitFor();await page.locator('[name=password]').fill(secret);await page.locator('[name=confirm_password]').fill(secret);await page.locator('[name=accepted_terms]').check();await touchTarget(page.locator('[data-auth-show]'),'signup password eye at '+(await page.viewportSize()).width);await page.locator('[data-auth-show]').click();assert.equal(await page.locator('[name=password]').getAttribute('type'),'text');await page.locator('[data-auth-show]').click();assert.equal(await page.locator('[name=password]').getAttribute('type'),'password');await page.screenshot({path:path.join(out,engine+'-'+phase+'-password.png'),fullPage:true});const registered=await submit(page,'/auth/register',()=>page.locator('#auth-form [type=submit]').click());await ready();return registered.session;}
  try{
    console.log('Account lifecycle: '+engine);
    await check(0,async()=>{
      await page.goto(origin+'/#register');const group=page.locator('[data-verification=auth]');await group.waitFor();initialOtp=await issue(group,{consent:true,checkCooldown:true});
      const wrong=(initialOtp.code[0]==='0'?'1':'0')+initialOtp.code.slice(1);await group.locator('[data-otp-code]').fill(wrong);await submit(page,'/auth/verify',()=>page.locator('[data-signup-next="1"]').click(),400);
      await page.waitForFunction(()=>document.querySelector('[data-otp-shell]')?.dataset.state==='error');const rejectedCode=await group.locator('[data-otp-code]').inputValue(),invalidCode=await group.locator('[data-otp-code]').getAttribute('aria-invalid'),rejectedStage=await page.locator('#auth-form').getAttribute('data-signup-current');assert.equal(rejectedCode,wrong);assert.equal(invalidCode,'true');assert.equal(rejectedStage,'1');
      const description=await group.locator('[data-otp-code]').getAttribute('aria-describedby'),statusId=await group.locator('[data-otp-status]').getAttribute('id');assert.ok(description?.split(/\s+/).includes(statusId));initialOtp.evidence.rejected_code={value_sha256:sha(rejectedCode),length:rejectedCode.length,aria_invalid:invalidCode,signup_stage:rejectedStage,described_by:description,status_id:statusId};await page.screenshot({path:path.join(out,engine+'-signup-code-error.png'),fullPage:true});
      const posts=report.requests.filter(item=>item.engine===engine&&item.path==='/api/auth/verify'&&item.method==='POST').length;initialOtp.evidence.paste=await pasteCode(group,initialOtp.code);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const afterPastePosts=report.requests.filter(item=>item.engine===engine&&item.path==='/api/auth/verify'&&item.method==='POST').length;initialOtp.evidence.paste_submission={before_posts:posts,after_posts:afterPastePosts};assert.equal(afterPastePosts,posts);assert.equal(await page.locator('#auth-form').getAttribute('data-signup-current'),'1');
      await touchTarget(group.locator('[data-otp-send]'),'signup send-code at 320');await page.screenshot({path:path.join(out,engine+'-signup-code-ready.png'),fullPage:true});
      const proof=await submit(page,'/auth/verify',()=>page.locator('[data-signup-next="1"]').click());assert.ok(proof.verification_token);await page.locator('[data-signup-step="2"]').waitFor();await page.locator('[data-signup-back="1"]').click();
      const verifiedState=await group.locator('[data-otp-shell]').getAttribute('data-state'),verifiedReadonly=await group.locator('[data-otp-code]').evaluate(node=>node.readOnly),verifiedText=await group.locator('[data-otp-status]').innerText();assert.equal(verifiedState,'verified');assert.equal(verifiedReadonly,true);assert.match(verifiedText,/已验证/);initialOtp.evidence.verified_ui={state:verifiedState,readonly:verifiedReadonly,status_text:verifiedText};await page.screenshot({path:path.join(out,engine+'-signup-code-verified.png'),fullPage:true});
      initialOtp.evidence.status='verified';await page.locator('[data-signup-next="1"]').click();await page.locator('[data-signup-step="2"]').waitFor();
    });
    await check(1,async()=>{const value=await completeSignup(password,'账号全流程 '+engine);oldOwner=value.user.id;identity.original_owner=oldOwner;assert.equal(value.user.username,username);assert.ok(value.user.verified_contacts.some(contact=>contact.value===phone));assert.equal((await session()).user.id,oldOwner);assert.equal(await page.locator('#auth-form').count(),0);});
    await check(2,async()=>{
      await logout();await page.setViewportSize({width:320,height:800});for(const method of ['password','code'])await touchTarget(page.locator('[data-login-method='+method+']'),'login '+method+' at 320');await page.locator('[data-login-method=password]').click();await page.locator('[name=username]').fill(username);await page.locator('[name=password]').fill('WrongPassword2026!');
      const retained=await page.locator('#auth-form').elementHandle();await submit(page,'/auth/login',()=>page.locator('#auth-form [type=submit]').click(),401);
      await page.locator('#auth-form .form-error').waitFor();const retainedPassword=await page.locator('[name=password]').inputValue(),rejectedLogin={same_form:await retained.evaluate(node=>node.isConnected&&node===document.querySelector('#auth-form')),username:await page.locator('[name=username]').inputValue(),password_sha256:sha(retainedPassword),aria_invalid:await page.locator('[name=password]').getAttribute('aria-invalid'),error_text:await page.locator('#auth-form .form-error').innerText()};identity.rejected_login=rejectedLogin;assert.equal(rejectedLogin.same_form,true);assert.equal(rejectedLogin.username,username);assert.equal(retainedPassword,'WrongPassword2026!');assert.equal(rejectedLogin.aria_invalid,'true');assert.match(rejectedLogin.error_text,/账号|密码/);
      await page.screenshot({path:path.join(out,engine+'-login-password-error.png'),fullPage:true});await page.locator('[name=password]').fill(password);const value=await submit(page,'/auth/login',()=>page.locator('#auth-form [type=submit]').click());assert.equal(value.session.user.id,oldOwner);await ready();assert.equal(await page.locator('#auth-form').count(),0);
    });
    await check(3,async()=>{
      await logout();await page.setViewportSize({width:390,height:844});await page.locator('[data-login-method=code]').click();const group=page.locator('[data-verification=auth]'),otp=await issue(group);await pasteCode(group,otp.code);
      const [proof,value]=await Promise.all([responseFor(page,'/auth/verify'),submit(page,'/auth/verified-login',()=>page.locator('#auth-form [type=submit]').click())]);assert.equal(proof.status(),200);otp.evidence.proof_status=proof.status();assert.equal(value.session.user.id,oldOwner);otp.evidence.status='consumed by verified login';await ready();
    });
    await check(4,async()=>{
      await page.setViewportSize({width:390,height:844});await nav('new');await page.locator('.intake-metadata>summary').click();const title='本人生命周期资料 '+username;
      await page.locator('#notice-form [name=title]').fill(title);await page.locator('#notice-form [name=body]').fill('这是 '+username+' 的独立合成原文，用来验证注销与重新注册之间不复用个人资料。');await page.locator('[name=rights]').check();await page.locator('[name=materials_complete]').check();
      const [created]=await Promise.all([responseFor(page,'/notices'),page.locator('#notice-form [type=submit]').click()]);assert.equal(created.status(),200);await page.waitForURL(/#notice\//);noticeId=new URL(page.url()).hash.split('/')[1];identity.notice_id=noticeId;identity.notice_created={status:created.status(),record_id:noticeId};assert.equal((await request('/notices/'+noticeId)).data.title,title);
      await settings('profile');const college='合成学院 '+engine;await page.locator('#profile-form [name=school]').fill('');await page.locator('#profile-form [name=college]').fill(college);const [saved]=await Promise.all([responseFor(page,'/profile','PATCH'),page.locator('#profile-form [type=submit]').click()]);assert.equal(saved.status(),200);identity.profile_save_status=saved.status();await page.locator('#dialog').waitFor({state:'hidden'});const profile=(await session()).user.profile;assert.equal(profile.college,college);assert.equal(profile.school,'');identity.profile_saved={school:profile.school,college:profile.college};
      await page.locator('[data-action=settings-profile]').click();const reopenedProfile={college:await page.locator('#profile-form [name=college]').inputValue(),school:await page.locator('#profile-form [name=school]').inputValue()};identity.profile_reopened=reopenedProfile;assert.equal(reopenedProfile.college,college);assert.equal(reopenedProfile.school,'');await page.screenshot({path:path.join(out,engine+'-profile-mobile.png'),fullPage:true});await closeDialog();
    });
    await check(5,async()=>{
      assert.equal(await passwordLogin(other,password),oldOwner);await page.setViewportSize({width:1280,height:850});await settings('security');const form=page.locator('#password-form');await form.locator('[name=old_password]').fill(password);await form.locator('[name=new_password]').fill(nextPassword);const otp=await issue(form.locator('[data-verification]'));await pasteCode(form.locator('[data-verification]'),otp.code);
      let release,enteredResolve,enteredReject,heldTask;const gate=new Promise(resolve=>{release=resolve;}),entered=new Promise((resolve,reject)=>{enteredResolve=resolve;enteredReject=reject;});
      const evidence={engine,status:'running',original_owner:oldOwner,held_response:null};report.password_delays.push(evidence);const oldForm=await form.elementHandle();
      const handler=route=>{heldTask=(async()=>{const response=await route.fetch({timeout}),body=await response.body();let value;try{value=JSON.parse(body.toString());}catch{}evidence.held_response={status:response.status(),body_sha256:sha(body),projection:safeProjection('/auth/password',value)};enteredResolve();await gate;await route.fulfill({response,body});})().catch(error=>{enteredReject(error);throw error;});heldTask.catch(()=>{});return heldTask;};
      await page.route(origin+'/api/auth/password',handler);let primary;
      try{
        await Promise.all([bounded(entered,'real password response'),form.locator('[type=submit]').click()]);await save();assert.equal(evidence.held_response.status,200);assert.equal(await form.getAttribute('aria-busy'),'true');await closeDialog();await page.locator('[data-settings-category=personal]').click();await page.locator('[data-action=settings-profile]').click();const replacement=await page.locator('#profile-form').elementHandle(),unsaved='尚未保存 '+engine;await page.locator('#profile-form [name=college]').fill(unsaved);
        const [response]=await Promise.all([responseFor(page,'/auth/password'),(async()=>{release();await heldTask;})()]);assert.equal(response.status(),200);await page.waitForFunction(node=>node.getAttribute('aria-busy')!=='true'&&!node.inert,oldForm);
        await page.waitForFunction(()=>{const node=document.querySelector('#toast.visible .toast-copy');return node?.textContent.includes('账号安全信息已更新');});
        const afterDelay={same_dialog_node:await replacement.evaluate(node=>node.isConnected&&node===document.querySelector('#profile-form')&&node.closest('dialog').open),college:await page.locator('#profile-form [name=college]').inputValue(),password_form_count:await page.locator('#password-form').count(),owner:(await session()).user.id,old_device_status:(await request('/session',{ctx:otherContext,expected:401})).status};evidence.after=afterDelay;assert.equal(afterDelay.same_dialog_node,true);assert.equal(afterDelay.college,unsaved);assert.equal(afterDelay.password_form_count,0);assert.equal(afterDelay.owner,oldOwner);assert.equal(afterDelay.old_device_status,401);evidence.status='passed';evidence.new_dialog_preserved=afterDelay.same_dialog_node;evidence.old_device_status=afterDelay.old_device_status;otp.evidence.status='consumed by password update';await closeDialog();
      }catch(error){primary=error;throw error;}finally{
        release();const cleanup=await Promise.allSettled([bounded(page.unrouteAll({behavior:'wait'}),'password route cleanup'),...(heldTask?[bounded(heldTask,'held password response cleanup')]:[])]);
        evidence.cleanup=cleanup.map(result=>({status:result.status,...(result.status==='rejected'?{error:String(result.reason)}:{})}));await save();
        if(!primary){const failed=cleanup.find(result=>result.status==='rejected');if(failed)throw failed.reason;}
      }
    });
    await check(6,async()=>{
      await logout();await page.locator('a[href="#recover"]').click();await page.locator('#auth-form[data-auth-mode=recover]').waitFor();await page.locator('[name=password]').fill(recoveredPassword);await page.locator('[name=confirm_password]').fill(recoveredPassword);const group=page.locator('[data-verification=auth]'),otp=await issue(group);await pasteCode(group,otp.code);
      const value=await submit(page,'/auth/recover',()=>page.locator('#auth-form [type=submit]').click());assert.equal(value.session.user.id,oldOwner);await ready();assert.equal((await request('/notices/'+noticeId)).data.id,noticeId);otp.evidence.status='consumed by recovery';
    });
    await check(7,async()=>{
      await settings('security');await page.locator('[data-action=delete-account]').click();const form=page.locator('#delete-account-form');await form.waitFor();await form.locator('[name=password]').fill('WrongDeletePassword2026!');await form.locator('[name=confirm]').fill('注销账号');const retained=await form.elementHandle(),requests=[];
      const record=request=>{if(new URL(request.url()).pathname==='/api/push/subscriptions'&&request.method()==='DELETE')requests.push(request.url());};page.on('request',record);
      try{await submit(page,'/account/delete',()=>form.locator('[type=submit]').click(),400);await form.locator('.form-error').waitFor();const retainedDeleteForm=await retained.evaluate(node=>node.isConnected&&node.closest('dialog').open),retainedDeletePassword=await form.locator('[name=password]').inputValue(),retainedConfirmation=await form.locator('[name=confirm]').inputValue();assert.equal(retainedDeleteForm,true);assert.equal(retainedDeletePassword,'WrongDeletePassword2026!');assert.equal(retainedConfirmation,'注销账号');assert.equal(requests.length,0);assert.equal((await session()).user.id,oldOwner);assert.equal((await request('/notices/'+noticeId)).data.id,noticeId);report.deletions.push({engine,phase:'rejected',status:400,remote_push_deletes:requests.length,owner:oldOwner,form_retained:retainedDeleteForm,password_sha256:sha(retainedDeletePassword),confirmation:retainedConfirmation});}finally{page.off('request',record);}
    });
    await check(8,async()=>{
      const form=page.locator('#delete-account-form');await form.locator('[name=password]').fill(recoveredPassword);const requests=[];const record=request=>{if(new URL(request.url()).pathname==='/api/push/subscriptions'&&request.method()==='DELETE')requests.push(request.url());};page.on('request',record);
      try{await submit(page,'/account/delete',()=>form.locator('[type=submit]').click());await page.locator('#auth-form').waitFor();await page.waitForFunction(()=>!document.querySelector('#content')&&!document.querySelector('#dialog')?.open);const clearedUi=await page.evaluate(()=>({auth_form_present:!!document.querySelector('#auth-form'),content_present:!!document.querySelector('#content'),dialog_open:!!document.querySelector('#dialog')?.open}));assert.equal((await request('/session',{expected:401})).status,401);assert.equal((await request('/notices/'+noticeId,{expected:401})).status,401);assert.equal(requests.length,0);report.deletions.push({engine,phase:'confirmed',status:200,remote_push_deletes:requests.length,old_owner:oldOwner,cleared_ui:clearedUi});await page.screenshot({path:path.join(out,engine+'-deleted-account.png'),fullPage:true});}finally{page.off('request',record);}
    });
    await check(9,async()=>{
      await page.setViewportSize({width:320,height:800});await page.locator('a[href="#register"]').click();await page.locator('#auth-form[data-auth-mode=register]').waitFor();const group=page.locator('[data-verification=auth]'),otp=await issue(group,{consent:true});await pasteCode(group,otp.code);await submit(page,'/auth/verify',()=>page.locator('[data-signup-next="1"]').click());await page.locator('[data-signup-step="2"]').waitFor();const value=await completeSignup(password,'重新注册 '+engine,'reregister');identity.new_owner=value.user.id;assert.notEqual(value.user.id,oldOwner);assert.equal(value.user.username,username);assert.ok(value.user.verified_contacts.some(contact=>contact.value===phone));assert.equal(value.user.profile.college,'');assert.equal((await request('/notices/page')).data.total,0);assert.equal((await request('/tasks/page')).data.total,0);assert.equal((await request('/notices/'+noticeId,{expected:404})).status,404);otp.evidence.status='consumed by new-owner registration';await page.screenshot({path:path.join(out,engine+'-reregistered-mobile.png'),fullPage:true});
    });
    await check(10,async()=>{assert.deepEqual(pageErrors,[]);assert.equal(identity.original_owner,oldOwner);assert.notEqual(identity.new_owner,oldOwner);assert.equal(report.checks.filter(check=>check.engine===engine&&check.ok).length,names.length-1);});
  }catch(error){process.exitCode=1;report.errors.push({engine,error:error.stack||String(error),kind:'suite failure'});await page.screenshot({path:path.join(out,engine+'-failure.png'),fullPage:true}).catch(()=>{});}
  finally{await save();await Promise.allSettled([context.close(),otherContext.close()]);await browser.close();}
}
report.active=null;report.complete=report.checks.length===report.expected_checks;report.passed=report.complete&&report.checks.every(check=>check.ok)&&report.errors.length===0;report.status=report.passed?'passed':'failed';if(!report.passed)process.exitCode=1;await save();console.log(JSON.stringify({checks:report.checks.length,expected:report.expected_checks,passed:report.checks.filter(check=>check.ok).length,errors:report.errors.length,status:report.status}));
