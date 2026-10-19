import {artifactPath} from './mvp_check_runtime.mjs';
// Exercise the existing synthetic component gallery; no model request is made.
import {createRequire} from 'node:module';
import {writeFile} from 'node:fs/promises';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const report={views:[],suites:[],errors:[]},browser=await chromium.launch({headless:true,executablePath:chromium.executablePath()});
const page=await browser.newPage({reducedMotion:'reduce'});
page.on('pageerror',e=>report.errors.push(e.message));
try{
  for(const width of [1440,320]){
    await page.setViewportSize({width,height:width===320?740:900});
    await page.goto('http://127.0.0.1:8780/static/genui/gallery.html');await page.waitForSelector('#gallery-result .gu-message');
    for(const scene of ['news','brief','notice','review']){
      await page.locator(`[data-scene=${scene}]`).click();
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      report.views.push({scene,width,overflow});
      await page.screenshot({path:artifactPath(`content-${scene}-${width}.png`),fullPage:true,animations:'disabled'});
    }
    const suite=await page.evaluate(async()=>{
      const {run}=await import('/static/genui/gallery-tests.js');
      const {galleryOptions,sampleSpec}=await import('/static/genui/gallery.js');
      return run(document.querySelector('#gallery-result'),galleryOptions,sampleSpec);
    });
    report.suites.push(suite);
    console.log(JSON.stringify({width,passed:suite.passed,failed:suite.failed,failures:suite.results.filter(x=>!x.passed)},null,2));
  }
  if(report.errors.length||report.views.some(v=>v.overflow)||report.suites.some(s=>s.failed))process.exitCode=1;
}catch(e){report.failure=e.stack;console.error(e);process.exitCode=1;}
finally{await writeFile(artifactPath('content-report.json'),JSON.stringify(report,null,2));await browser.close();}
