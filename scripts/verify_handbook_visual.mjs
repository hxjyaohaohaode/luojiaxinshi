import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
import {artifactPath} from './mvp_check_runtime.mjs';

const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const origin='http://127.0.0.1:8780',report={checks:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()});
try{
  const context=await browser.newContext({reducedMotion:'reduce'});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  const check=(route,width,detail,passed,actual)=>report.checks.push({route,width,detail,passed,...(actual===undefined?{}:{actual})});
  // Auth screens are checked signed out, including short landscape.
  for(const [width,height] of [[1440,900],[390,844],[320,740],[844,390]]){
    await page.setViewportSize({width,height});
    for(const route of ['login','register','recover']){
      await page.goto(origin+'/?visual-auth='+Date.now()+'#'+route);await page.waitForSelector('#auth-form');
      check(route,width,'No document overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      const box=await page.locator('.auth-form').boundingBox();
      check(route,width,'Auth form remains in viewport columns',box.x>=0&&box.x+box.width<=width+1,box);
      if(route==='login'&&width===1440)check(route,width,'Confirmation badge stays above mascot',await page.evaluate(()=>Number(getComputedStyle(document.querySelector('.auth-tag-two')).zIndex)>Number(getComputedStyle(document.querySelector('.auth-companion')).zIndex)));
      if(route==='register'){
        await page.locator('[name=display_name]').fill('虚构视觉验收');
        await page.locator('[name=username]').fill('visual.fixture');
        await page.locator('[data-auth-next]').click();
        check(route,width,'Registration password stage is reachable',await page.locator('[data-auth-step=password]').isVisible());
        check(route,width,'Hidden account stage does not occupy space',!(await page.locator('[data-auth-step=account]').isVisible()));
      }
      if(route==='login'||width===390)await page.screenshot({path:artifactPath(`${route}-${width}.png`),fullPage:true});
    }
  }
  const response=await context.request.post(origin+'/api/auth/login',{headers:{Origin:origin,'X-Requested-With':'campus-notice'},data:{username:'workflow.demo',password:'Mvp-Verification-Only-2026'}});
  if(!response.ok())throw Error('Synthetic login failed');
  const mappings=[
    ['dashboard','.overview-letter','.overview-launch'],
    ['tasks','.page-title h1','.toolbar'],
    ['notices','.page-title h1','.library-toolbar'],
    ['new','.notice-welcome h1','.notice-stepper'],
    ['sources','.page-title h1','.source-toolbar'],
    ['memory','.page-heading h1','.memory-note'],
  ];
  for(const width of [1920,1440,768,390,320]){
    await page.setViewportSize({width,height:width<850?844:1000});
    for(const [route,title,frame] of mappings){
      await page.goto(origin+'/?visual-align='+Date.now()+'#'+route);
      await page.waitForSelector(title);await page.locator('#content[aria-busy=true]').waitFor({state:'detached'});
      const metrics=await page.evaluate(({title,frame})=>{
        const h=document.querySelector(title),f=document.querySelector(frame),c=document.querySelector('#content'),a=h.getBoundingClientRect(),b=f.getBoundingClientRect(),s=getComputedStyle(c);
        const left=c.getBoundingClientRect().left+parseFloat(s.paddingLeft),right=c.getBoundingClientRect().right-parseFloat(s.paddingRight);
        return {titleLeft:a.left,frameLeft:b.left,frameRight:b.right,contentLeft:left,contentRight:right,titleSize:parseFloat(getComputedStyle(h).fontSize),font:getComputedStyle(h).fontFamily,overflow:document.documentElement.scrollWidth>innerWidth+1};
      },{title,frame});
      check(route,width,'Title and primary frame share a left edge',Math.abs(metrics.titleLeft-metrics.frameLeft)<=1,metrics);
      check(route,width,'Primary frame fills the page content column',Math.abs(metrics.frameLeft-metrics.contentLeft)<=1&&Math.abs(metrics.frameRight-metrics.contentRight)<=1,metrics);
      check(route,width,'No horizontal overflow',!metrics.overflow);
      if(route==='new')await page.screenshot({path:artifactPath(`new-aligned-${width}.png`),fullPage:true});
    }
    await page.goto(origin+'/?visual-settings='+Date.now()+'#settings');await page.waitForSelector('.settings-home');
    const cards=await page.locator('.settings-menu').first().locator('.settings-item').evaluateAll(items=>items.slice(0,2).map(el=>({top:el.getBoundingClientRect().top,height:el.getBoundingClientRect().height})));
    check('settings',width,'Settings cards align within each row',cards.length===2&&(Math.abs(cards[0].top-cards[1].top)>2||Math.abs(cards[0].height-cards[1].height)<=1),cards);
  }
  await context.close();
}catch(error){report.errors.push(error.stack);}
finally{await browser.close();}
await writeFile(artifactPath('handbook-visual-alignment.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:report.checks.filter(c=>c.passed).length,total:report.checks.length,errors:report.errors,failed:report.checks.filter(c=>!c.passed)},null,2));
if(report.errors.length||report.checks.some(c=>!c.passed))process.exitCode=1;
