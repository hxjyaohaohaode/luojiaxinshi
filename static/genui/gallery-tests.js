// Runs only when the developer explicitly clicks the gallery test button.
import {CATALOG,Block,parseMessage} from './core.js';
import {UIRenderer,MessageRenderer} from './renderer.js';
import {markdown,el} from './dom.js';
const frame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
const assert=(value,message)=>{if(!value)throw Error(message);};
const equal=(a,b,message)=>assert(JSON.stringify(a)===JSON.stringify(b),message);
export async function run(host,options,sampleSpec){
  const results=[],timings={},begin=performance.now();host.replaceChildren();const testArea=el('div');host.append(testArea);
  async function test(name,fn){try{await fn();results.push({name,passed:true});}catch(error){results.push({name,passed:false,error:error.message});}testArea.replaceChildren();}
  for(const name of Object.keys(CATALOG.components))for(const variant of ['ready','loading','empty','error','long'])await test(name+' / '+variant,async()=>{
    const r=new UIRenderer(testArea,sampleSpec(name,variant),options);await frame();assert(!r.root.querySelector('[data-error=true]'),'component render failure');assert(r.root.textContent.length>0,'readable content missing');assert(r.root.scrollWidth<=r.root.clientWidth+1,'component width overflow');r.dispose();
  });
  await test('local controls update dependants without fetch; input keeps focus',async()=>{
    const b=new Block();b.apply({op:'begin',v:1});b.apply({op:'state',set:{hours:2,checked:[],choice:'a',toggle:false,text:'原文'}});b.apply({op:'node',id:'slider',type:'Slider',props:{label:'准备时长',bind:'hours',min:0,max:8,step:.5}});b.apply({op:'node',id:'stat',type:'Stat',props:{label:'每周',value:{$expr:'hours*7'}}});b.apply({op:'end'});b.closed=true;
    const r=new UIRenderer(testArea,b.spec(),options),input=r.root.querySelector('input');input.focus();const original=window.fetch;let requests=0;window.fetch=()=>{requests++;throw Error('unexpected network');};
    try{const start=performance.now();input.value='4';input.dispatchEvent(new Event('input',{bubbles:true}));await frame();timings.localUpdateMs=performance.now()-start;assert(r.root.querySelector('.gu-stat-value').textContent==='28','dependent value did not update');assert(document.activeElement===input,'focus was lost');assert(requests===0,'local control sent a request');assert(timings.localUpdateMs<100,'interaction exceeded 100ms');}finally{window.fetch=original;r.dispose();}
  });
  await test('dirty local state survives streaming patch and history recreation',async()=>{
    const spec=sampleSpec('Slider'),r=new UIRenderer(testArea,spec,options);r.store.set('hours',4);r.update(spec);await frame();assert(r.store.get('hours')===4,'stream reset control');const snapshot=r.snapshot();r.dispose();const history=new UIRenderer(testArea,spec,{...options,snapshot});assert(history.root.querySelector('input').value==='4','history did not restore');equal(history.snapshot(),snapshot,'snapshot mismatch');history.dispose();
  });
  await test('table sorts numerically and persists its view',async()=>{
    const r=new UIRenderer(testArea,sampleSpec('Table'),options),buttons=r.root.querySelectorAll('.gu-sort');buttons[1].click();const values=[...r.root.querySelectorAll('tbody tr')].map(row=>row.children[1].textContent);equal(values,['1','2','3'],'numeric sorting');const snapshot=r.snapshot();r.dispose();const h=new UIRenderer(testArea,sampleSpec('Table'),{...options,snapshot});equal([...h.root.querySelectorAll('tbody tr')].map(row=>row.children[1].textContent),values,'sort history');h.dispose();
  });
  await test('tabs keyboard selection and checklist local state',async()=>{
    const r=new UIRenderer(testArea,sampleSpec('Tabs'),options),tabs=r.root.querySelectorAll('[role=tab]');tabs[0].focus();tabs[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert(tabs[1].getAttribute('aria-selected')==='true','keyboard tab did not change');const checkbox=r.root.querySelector('input[type=checkbox]');checkbox.click();await frame();assert(r.store.get('checked').includes('one'),'checklist state');r.dispose();
  });
  await test('host side effects cannot execute from a change event',async()=>{
    let calls=0;const spec=sampleSpec('Slider');spec.nodes.demo.on={change:{kind:'host',name:'open_calendar',params:{}}};const r=new UIRenderer(testArea,spec,{...options,hostActions:{open_calendar:{run:()=>calls++}}}),input=r.root.querySelector('input');input.value='3';input.dispatchEvent(new Event('input',{bubbles:true}));await frame();assert(calls===0,'side effect escaped click gate');r.dispose();
  });
  await test('hostile Markdown stays text, unsafe links and images do not load',()=>{
    const node=markdown('<script>window.bad=1</script>\n[x](javascript:alert)\n![x](https://evil.invalid/pixel)\n<a onclick="bad()">x</a>');testArea.append(node);assert(!node.querySelector('script,img,[onclick]'),'unsafe markup created');assert(![...node.querySelectorAll('a')].some(a=>a.protocol==='javascript:'),'unsafe link');assert(node.textContent.includes('<script>'),'plain fallback lost content');
    const spec=sampleSpec('Image');spec.nodes.demo.props.src='https://evil.invalid/pixel';const r=new UIRenderer(testArea,spec,options);assert(!r.root.querySelector('img'),'remote image was loaded');r.dispose();
  });
  await test('faulty node does not interrupt its sibling',()=>{
    const raw='说明\n```genui\n{"op":"begin","v":1}\n{"op":"node","id":"bad","type":"Stat","props":{"label":"坏的","value":{"$expr":"1/0"}}}\n{"op":"node","id":"good","type":"Markdown","props":{"text":"仍然可读"}}\n{"op":"end"}\n```';const r=new MessageRenderer(testArea,options);r.update(parseMessage(raw));r.paint();assert(testArea.textContent.includes('仍然可读'),'sibling disappeared');assert(testArea.querySelector('[data-error=true]'),'fault did not degrade');r.dispose();
  });
  await test('streaming and historical renders are equivalent',async()=>{
    const raw='先核对。\n```genui\n'+[{op:'begin',v:1},{op:'state',set:{hours:2}},{op:'node',id:'stat',type:'Stat',props:{label:'小时',value:{$expr:'hours*7'}}},{op:'end'}].map(o=>JSON.stringify(o)).join('\n')+'\n```\n之后再安排。';const r=new MessageRenderer(testArea,options),bytes=new TextEncoder().encode(raw);for(let i=0;i<bytes.length;i+=7)r.push(bytes.slice(i,i+7));const parts=r.finish();await frame();const text=testArea.textContent;r.dispose();const h=new MessageRenderer(testArea,options);h.update(parts);await frame();assert(testArea.textContent===text,'live/history mismatch');h.dispose();
  });
  await test('300 nodes render and update within frame budgets',async()=>{
    const b=new Block();b.apply({op:'begin',v:1});b.apply({op:'state',set:{hours:2}});for(let i=0;i<300;i++)b.apply({op:'node',id:'n'+i,type:'Stat',props:{label:'项目 '+i,value:{$expr:'hours*7'}}});b.apply({op:'end'});b.closed=true;
    let latest=0;const start=performance.now(),r=new UIRenderer(testArea,b.spec(),{...options,onRender:ms=>latest=ms});timings.render300Ms=performance.now()-start;await frame();const startUpdate=performance.now();r.store.set('hours',3);await frame();timings.update300Ms=performance.now()-startUpdate;timings.update300PaintMs=latest;
    assert(r.root.querySelectorAll('.gu-stat-value').length===300,'nodes missing');assert(latest<100,'300-node update paint exceeded 100ms');assert(timings.render300Ms<200,'300-node first render exceeded 200ms');r.dispose();
  });
  const report={passed:results.filter(r=>r.passed).length,failed:results.filter(r=>!r.passed).length,timings,elapsedMs:Math.round(performance.now()-begin),viewport:{width:innerWidth,height:innerHeight},theme:document.querySelector('main').dataset.genuiTheme,results};testArea.remove();return report;
}
