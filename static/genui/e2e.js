// Explicit developer test. Real endpoints + renderer; synthetic server only.
import {ConversationView} from './chat-presenter.js';
import {StreamParser} from './core.js';
import {streamChat} from './transport.js';
import {el} from './dom.js';
const frame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
const assert=(value,message)=>{if(!value)throw Error(message);};

export async function runE2E(container){
  const response=await fetch('/api/session',{credentials:'same-origin'}),session=await response.json();
  if(session.ai?.model!=='offline-genui-fixture')throw Error('此测试只允许在 scripts/genui_test_server.py 的隔离合成环境运行。');
  const results=[],start=performance.now();let chat,view,saveTask;
  async function api(path,method='GET',json){
    const r=await fetch('/api'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Requested-With':'campus-notice','X-CSRF-Token':session.csrf},...(json?{body:JSON.stringify(json)}:{})});
    const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'HTTP '+r.status);return data;
  }
  async function test(name,run){try{await run();results.push({name,passed:true});}catch(error){results.push({name,passed:false,error:error.message});}}
  const original=await api('/genui/preferences');let feature=original;
  try{
    if(!feature.enabled)feature=await api('/genui/preferences','PUT',{version:feature.version,enabled:true,theme:feature.theme});
    chat=await api('/conversations','POST',{title:'生成式界面自动验收（合成）'});
    const host=el('div');container.replaceChildren(host);
    const options={feature,sources:[],arrangements:[],tasks:[],preview:()=>{},openCalendar:()=>{},openSources:()=>{},askModel:async()=>{},
      save:(mid,snapshots)=>saveTask=(async()=>{const m=chat.messages.find(m=>m.id===mid);const result=await api(`/conversations/${chat.id}/messages/${mid}/ui-state`,'PUT',{version:m.genui.snapshot_version,snapshots});m.genui.snapshot_version=result.snapshot_version;m.genui.snapshots=result.snapshots;})()};
    function display(){if(!view)view=new ConversationView(host,options);view.draw(chat.messages);}
    async function send(question){let parser,mid,raw='',sawText=false,sawPartial=false;
      await streamChat(chat.id,{version:chat.version,content:question,request_id:crypto.randomUUID(),allow_external_processing:true},{csrf:session.csrf,onEvent:(type,data)=>{
        if(type==='start'){chat=data.conversation;mid=data.message_id;parser=new StreamParser({limits:data.limits,data:data.data});}
        if(type==='delta'){raw+=data.text;parser.push(data.text);const m=chat.messages.find(m=>m.id===mid);m.genui.raw=raw;m._liveParts=parser.snapshot();sawText||=m._liveParts.some(p=>p.kind==='text'&&p.text);sawPartial||=m._liveParts.some(p=>p.kind==='ui'&&!p.spec.complete);}
        if(type==='done')chat=data.conversation;display();
      }});await frame();return {sawText,sawPartial,raw};
    }
    await test('SSE text first, partial UI, final canonical history',async()=>{
      const r=await send('工程验收：计算每天2小时，连续7天');assert(r.sawText&&r.sawPartial,'incremental parts missing');assert(chat.messages.at(-1).status==='complete','message incomplete');assert(host.querySelector('input[type=range]'),'slider missing');const saved=await api('/conversations/'+chat.id);assert(JSON.stringify(saved.messages.at(-1).parts)===JSON.stringify(chat.messages.at(-1).parts),'history normalization differs');
    });
    await test('local parameter update has zero fetch calls and keeps focus',async()=>{
      const input=host.querySelector('input[type=range]'),fetchOriginal=window.fetch;let calls=0;assert(input,'missing input');window.fetch=()=>{calls++;throw Error('unexpected fetch');};
      try{input.focus();input.value='4';input.dispatchEvent(new Event('input',{bubbles:true}));await frame();assert(host.querySelector('.gu-stat-value')?.textContent==='28 小时','dependent result not updated');assert(calls===0,'local update used network');assert(document.activeElement===input,'focus lost');}finally{window.fetch=fetchOriginal;}
    });
    await test('explicit snapshot save and fresh history restore',async()=>{
      const save=[...host.querySelectorAll('button')].find(b=>b.textContent==='保存互动进度');assert(save,'save missing');save.click();await saveTask;await frame();chat=await api('/conversations/'+chat.id);view.dispose();view=null;display();await frame();assert(host.querySelector('input[type=range]').value==='4','snapshot value lost');assert(host.querySelector('.gu-stat-value').textContent==='28 小时','history result lost');assert(view.copy(chat.messages.at(-1)).includes('28'),'copy not equivalent');
    });
    await test('invalid operation and unknown component degrade locally',async()=>{
      await send('工程故障注入');const last=host.querySelector('.message-assistant:last-child');assert(last.textContent.includes('这一块暂不支持'),'fallback missing');assert(last.querySelector('input[type=range]'),'valid sibling lost');assert(last.textContent.includes('正式截止时间'),'text after UI lost');
    });
    await test('provider failure keeps partial response and retry',async()=>{
      await send('工程中断验收');assert(chat.messages.at(-1).status==='failed','failure not preserved');assert(chat.messages.at(-1).genui.raw.length>0,'partial raw lost');assert(host.querySelector('[data-chat-action=retry]'),'retry missing');
    });
    await test('feature disabled preserves legacy endpoint and readable history',async()=>{
      feature=await api('/genui/preferences','PUT',{version:feature.version,enabled:false,theme:feature.theme});
      chat=await api('/conversations/'+chat.id+'/messages','POST',{version:chat.version,content:'纯文字工程验收',request_id:crypto.randomUUID(),allow_external_processing:true});
      assert(chat.messages.at(-1).status==='complete','legacy send failed');view.configure({feature});display();await frame();assert(!host.querySelector('.genui'),'UI remains when disabled');assert(host.textContent.includes('工程夹具回复'),'legacy text missing');
    });
  }finally{
    view?.dispose();const latest=await api('/genui/preferences');if(latest.enabled!==original.enabled)await api('/genui/preferences','PUT',{version:latest.version,enabled:original.enabled,theme:original.theme});
  }
  return {mode:'isolated synthetic provider; real HTTP and SQLite',passed:results.filter(r=>r.passed).length,failed:results.filter(r=>!r.passed).length,durationMs:performance.now()-start,results};
}
