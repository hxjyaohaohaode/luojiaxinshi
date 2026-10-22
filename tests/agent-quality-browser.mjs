import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium} from 'playwright';

const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(String(e)));
try{
  await page.goto('http://127.0.0.1:8793/');
  const report=await page.evaluate(async()=>{
    const {ConversationView}=await import('/static/genui/chat-presenter.js');
    const host=document.createElement('div');document.body.append(host);
    const view=new ConversationView(host,{feature:{enabled:true},sources:[],arrangements:[],tasks:[]});
    const messages=[];
    for(let i=0;i<100;i++){
      messages.push({id:'u'+i,role:'user',content:'历史问题 '+i,created_at:100+i});
      messages.push({id:'a'+i,parent_id:'u'+i,role:'assistant',status:'complete',content:('历史内容 '+i+'\n').repeat(45),created_at:100+i});
    }
    const ops=[{op:'begin',v:1},{op:'state',set:{ready:[]}},
      {op:'node',id:'list',type:'Checklist',props:{label:'实际准备进度',bind:'ready',items:Array.from({length:100},(_,i)=>({id:'item'+i,label:'材料 '+i}))}},
      {op:'end'}];
    messages.push({id:'interactive',role:'assistant',status:'complete',content:'准备进度',genui:{v:1,tier:1,validated:true,raw:'```genui\n'+ops.map(op=>JSON.stringify(op)).join('\n')+'\n```',snapshots:{}}});
    const streaming={id:'streaming',role:'assistant',status:'processing',content:'',_preview:'正在回答'};messages.push(streaming);
    const started=performance.now();view.draw(messages);await new Promise(requestAnimationFrame);
    const firstPaintMs=performance.now()-started;
    const stable=host.querySelector('[data-message-id="a99"] .message-content');
    const originalNode=stable.firstChild,checkbox=host.querySelector('.gu-check input');
    checkbox.click();await new Promise(requestAnimationFrame);checkbox.focus();
    let mutations=0;const observer=new MutationObserver(records=>mutations+=records.length);observer.observe(stable,{subtree:true,childList:true,characterData:true});
    const durations=[];
    for(let i=0;i<40;i++){
      streaming._preview+='新增片段 '+i+'。';const before=performance.now();view.draw(messages);durations.push(performance.now()-before);
      await new Promise(requestAnimationFrame);
    }
    observer.disconnect();durations.sort((a,b)=>a-b);
    const result={messages:messages.length,checklist_items:100,stream_frames:40,first_paint_ms:+firstPaintMs.toFixed(2),
      median_update_ms:+durations[20].toFixed(2),p95_update_ms:+durations[38].toFixed(2),
      preserved_history_node:stable.firstChild===originalNode,history_content_mutations:mutations,
      preserved_focus:document.activeElement===checkbox,preserved_choice:checkbox.checked,
      renderer_errors:host.querySelectorAll('.gu-error').length};
    view.dispose();host.remove();return result;
  });
  assert.equal(report.preserved_history_node,true);assert.equal(report.history_content_mutations,0);
  assert.equal(report.preserved_focus,true);assert.equal(report.preserved_choice,true);assert.equal(report.renderer_errors,0);
  assert.deepEqual(errors,[]);
  await mkdir('artifacts/agent-quality-browser',{recursive:true});
  const checks=['历史 DOM 节点保留','历史正文没有重复变更','焦点保留','已勾选状态保留','渲染错误为零'];
  await writeFile('artifacts/agent-quality-browser/performance.json',JSON.stringify({...report,checks,errors,synthetic:true},null,2));
  console.log(JSON.stringify(report,null,2));
}finally{await browser.close();}
