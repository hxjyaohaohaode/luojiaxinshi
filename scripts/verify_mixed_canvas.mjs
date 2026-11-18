// Replay the separately measured MiMo completion without issuing a new model request.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium,firefox,webkit,request} from 'playwright';
import {browserOverride} from './browser-runtime.mjs';

const name=process.env.OPENUI_BROWSER||'chromium',engine={chromium,firefox,webkit}[name];
const out=process.env.OPENUI_ARTIFACT_DIR||'artifacts/mixed-canvas/'+name,origin='http://127.0.0.1:8794';
await mkdir(out,{recursive:true});
const api=await request.newContext({baseURL:origin,extraHTTPHeaders:{Origin:origin,'X-Requested-With':'campus-notice'}});
assert.equal((await api.post('/api/auth/login',{data:{username:'openui-preview',password:'OpenUIFixture2026!'}})).status(),200);
const response=await (await api.get('/api/conversations')).json();
const conversations=Array.isArray(response)?response:response.items||response.conversations;
assert.equal(conversations.length,1);
const browser=await engine.launch({headless:true,...browserOverride(engine),...(process.platform==='win32'&&name==='chromium'?{channel:'msedge'}:{})});
const checked=[];
try {
  const context=await browser.newContext({storageState:await api.storageState(),reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:width===390?844:950});
    await page.goto(origin+'/#chat/'+conversations[0].id);
    const host=page.locator('.message-assistant').last(),iframe=host.locator('iframe.openui-frame'),frame=iframe.contentFrame();
    const days=frame.getByRole('spinbutton');
    await days.waitFor();
    await days.fill('7');await days.press('Tab');
    await frame.getByText(/42\s*页/).first().waitFor();
    assert.ok(await frame.locator('svg').count());
    const bounds=await iframe.boundingBox();
    assert.ok(bounds.x>=0 && bounds.x+bounds.width<=width+1);
    const layout=await frame.locator('body').evaluate(el=>({background:getComputedStyle(el).backgroundColor,width:el.clientWidth,scroll:el.scrollWidth,
      outside:[...el.querySelectorAll('*')].filter(n=>n.getBoundingClientRect().right>el.clientWidth+1).slice(0,12).map(n=>[n.tagName,n.className?.baseVal||String(n.className),Math.round(n.getBoundingClientRect().width)])}));
    assert.equal(layout.background,'rgba(0, 0, 0, 0)');
    assert.ok(layout.scroll<=layout.width+1,JSON.stringify({width,layout}));
    await days.scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/reading-'+width+'.png',caret:'initial'});
    checked.push({width,canvas_width:Math.round(bounds.width),days:7,pages:42});
  }
  assert.deepEqual(errors,[]);
  await writeFile(out+'/report.json',JSON.stringify({browser:name,checks:checked},null,2));
} finally {await browser.close();await api.dispose();}
