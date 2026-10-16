// Runs only when the developer explicitly clicks the gallery test button.
import {CATALOG,Block,parseMessage} from './core.js';
import {UIRenderer,MessageRenderer} from './renderer.js';
import {SCENARIOS} from './scenarios.js';
import {markdown,el} from './dom.js';
import {WorkSummaryView} from './work-view.js';
import {CitationView} from './citations.js';
import {ConversationView} from './chat-presenter.js';
const frame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
const assert=(value,message)=>{if(!value)throw Error(message);};
const equal=(a,b,message)=>assert(JSON.stringify(a)===JSON.stringify(b),message);
export async function run(host,options,sampleSpec){
  const results=[],timings={},begin=performance.now();host.replaceChildren();const testArea=el('div');host.append(testArea);
  async function test(name,fn){try{await fn();results.push({name,passed:true});}catch(error){results.push({name,passed:false,error:error.message});}testArea.replaceChildren();}
  await test('gallery controls stay within the actual viewport',()=>assert(document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,'gallery controls overflow narrow viewport'));
  await test('plain and table URLs are clickable, punctuation and code remain intact',()=>{
    const content=markdown('官网 https://uc.whu.edu.cn/tzgg.htm。\n[官网](https://www.whu.edu.cn/)\n`https://code.invalid/`\n括号 (https://example.com/a(b)).\n\n| 网站 |\n| --- | --- |\n| https://uc.whu.edu.cn/ |');testArea.append(content);
    const links=[...content.querySelectorAll('a')];assert(links.length===4,'missing links or code turned into a link');
    assert(links.every(a=>a.target==='_blank'&&a.rel.includes('noopener')),'external navigation unsafe');
    assert(links[0].href==='https://uc.whu.edu.cn/tzgg.htm','sentence punctuation included in URL');
    assert(links[2].href==='https://example.com/a(b)','unbalanced sentence parenthesis included');
    assert(content.querySelector('td a'),'table URL missing');assert(content.querySelector('code').textContent==='https://code.invalid/','code changed');
  });
  await test('long prose can expand its remaining paragraphs without losing the ending',()=>{
    const text=Array.from({length:1200},(_,i)=>'第'+i+'段：中文长回复。').join('\n'),content=markdown(text);testArea.append(content);
    const more=[...content.querySelectorAll('button')].find(b=>b.textContent==='展开剩余内容');assert(more,'remaining content control absent');more.click();
    assert(content.textContent.includes('第1199段'),'long answer ending inaccessible');
  });
  await test('work summary preserves manual collapse and auto-collapses at completion',()=>{
    const content=el('div');testArea.append(content);const view=new WorkSummaryView(testArea,content),step={id:'step-1',stage:'planning',title:'确认范围',state:'running',summary:'确认问题范围',tools:['范围规划'],started_at:10},message={status:'processing',_work:[step]};view.update(message);assert(view.root.open,'initial progress must open');view.root.open=false;view.update({...message,_work:[{...step,summary:'新说明'}]});assert(!view.root.open,'manual collapse lost');view.root.open=true;view.update({status:'complete',grounding:{started_at:10,checked_at:20,steps:[{...step,state:'complete',finished_at:20}]}});assert(!view.root.open,'completed summary must collapse');
    view.update({status:'processing',_work:[{...step,stage:'retrieving',title:'查找资料与日程',summary:'本账号资料检索',tools:['资料与日程检索']}],grounding:{retrieval:{local_scope:'message',selected_sources:1},web:{status:'not_needed',reason:'限定材料'},coverage_check:{items:[{requirement:'限定规则',status:'supported',gap:''}]}}});
    assert(view.root.querySelector('.work-audit')&&!view.root.querySelector('.work-audit').open,'audit detail should start collapsed');assert(view.root.textContent.includes('核对限定消息材料')&&!view.root.textContent.includes('资料与日程检索'),'scoped work claimed an account search');view.dispose();
  });
  await test('inline citations are numbered from evidence and do not decorate code or unknown numbers',()=>{
    const content=markdown('结论。[1] 未登记[9]。`代码[1]`'),footer=el('div');testArea.append(content,footer);const view=new CitationView(content,footer,{sources:[]});view.update({id:'test',citations:[{source_id:'one',locator:'第1段',quote:'真实原句'}],evidence_sources:[{id:'one',name:'<script>unsafe</script>',url:'https://uc.whu.edu.cn',evidence_kind:'web_page'}]},{sources:[]});assert(content.querySelectorAll('.citation-mark').length===1,'incorrect citation matching');assert(content.querySelector('code').textContent==='代码[1]','code was changed');assert(footer.textContent.includes('1 个网页'),'incorrect web count');view.dispose();
  });
  await test('source panel preserves the selected citation across responsive rebuilds',()=>{
    const workspace=el('div'),content=markdown('结论。[1]'),footer=el('div');workspace.id='chat-workspace';workspace.append(content,footer);testArea.append(workspace);
    const view=new CitationView(content,footer,{sources:[]});view.update({id:'resize-test',citations:[{source_id:'web',locator:'标题','quote':'通知公告'}],evidence_sources:[{id:'web',name:'通知公告',url:'https://uc.whu.edu.cn/tzgg.htm',evidence_kind:'web_page'}]},{sources:[]});
    content.querySelector('.citation-mark').click();const previous=view.panel;view.resize();assert(view.panel&&view.panel!==previous,'responsive change lost the source panel');assert(view.panel.querySelector('.source-quote.selected'),'selected citation lost');assert(view.panel.querySelector('.source-quote-details').open,'selected evidence must expand');view.dispose();
  });
  await test('conversation citations decorate newly revealed interactive content',async()=>{
    const raw='```genui\n'+[
      {op:'begin',v:1},{op:'state',set:{lens:'facts'}},
      {op:'node',id:'lens',type:'Choice',props:{label:'阅读视角',bind:'lens',options:[{value:'facts',label:'事实'},{value:'impact',label:'影响'}]}},
      {op:'node',id:'body',type:'Prose',props:{text:{$expr:'lens == "facts" ? "登记事实。[1]" : "切换后显示的内容。[1]"'}}},
      {op:'node',id:'replySources',type:'Button',props:{label:'查看本回答来源'},on:{click:{kind:'host',name:'open_sources',params:{}}}},
      {op:'end'}].map(op=>JSON.stringify(op)).join('\n')+'\n```';
    let materialOpens=0;const view=new ConversationView(testArea,{...options,openSources:()=>{materialOpens++;},feature:{enabled:true},sources:[]});
    try{view.draw([{id:'live-citations',role:'assistant',status:'complete',content:'',genui:{v:1,tier:1,validated:true,raw},citations:[{source_id:'one',locator:'第1段',quote:'登记事实。'}],evidence_sources:[{id:'one',name:'测试网页原文',evidence_kind:'web_page',url:'https://library.example.edu.cn/rules'}]}]);await frame();
      const body=testArea.querySelector('[data-node-id=body]');assert(body.querySelectorAll('.citation-mark').length===1,'initial citation absent');
      testArea.querySelectorAll('[role=radio]')[1].click();await frame();
      assert(body.textContent.includes('切换后显示的内容'),'content did not change');assert(body.querySelectorAll('.citation-mark').length===1,'new content retained a raw citation');assert(body.querySelector('.citation-mark').dataset.citation==='1','citation numbering changed');
      testArea.querySelector('[data-node-id=replySources] button').click();await frame();assert(materialOpens===0,'answer sources opened an unrelated attachment drawer');assert(document.querySelector('.reply-sources-panel a[href="https://library.example.edu.cn/rules"]'),'answer source link missing');
    }finally{view.dispose();}
  });
  await test('conversation follow-ups carry current edited records and explain the attached selections',async()=>{
    const raw='```genui\n'+SCENARIOS.review.ops.map(op=>JSON.stringify(op)).join('\n')+'\n```',view=new ConversationView(testArea,{...options,feature:{enabled:true},sources:[]}),message={id:'context-origin',role:'assistant',status:'complete',content:'',genui:{v:1,tier:1,validated:true,raw}};
    try{view.draw([message]);await frame();assert(view.interactionContext()===null,'unchanged defaults were treated as user confirmation');
      const input=testArea.querySelector('[data-node-id=items] textarea');input.value='这条材料还缺预约方式';input.dispatchEvent(new Event('input',{bubbles:true}));await frame();
      const context=view.interactionContext();assert(context.message_id==='context-origin','wrong origin reply');assert(context.blocks[0].inputs['records.0.note']==='这条材料还缺预约方式','record note missing');assert(!('records' in context.blocks[0].inputs),'raw source records sent as user selections');
      const copied=view.copyHTML(message);assert(copied.includes('这条材料还缺预约方式')&&copied.includes('尚未判断'),'rich copy lost edited notes or the selected decision');
      view.draw([message,{id:'plain-answer',role:'assistant',status:'complete',content:'继续说明',genui:{v:1,tier:1,validated:true,raw:'继续说明'}}]);await frame();assert(view.interactionContext()?.message_id==='context-origin','a later text reply lost the active workspace');
      view.markContextSubmitted(context);assert(view.interactionContext()===null,'already acknowledged selections were sent again');assert(view.interactionContext('context-origin',true)?.message_id==='context-origin','explicit continuation omitted its workspace');
      const followup={id:'context-user',role:'user',content:'继续核查',status:'complete',interaction:{selections:[{label:'<img src=x>批注',value:'这条材料还缺预约方式'}]}};view.draw([message,followup]);await frame();
      const detail=testArea.querySelector('.message-selection-context');assert(detail&&detail.textContent.includes('这条材料还缺预约方式'),'attached choices not inspectable');assert(!detail.querySelector('img'),'selection label became HTML');detail.open=true;view.draw([message,followup]);assert(detail.open&&detail.isConnected,'redraw collapsed submitted selections');
    }finally{view.dispose();}
  });
  for(const name of Object.keys(CATALOG.components))for(const variant of ['ready','loading','empty','error','long'])await test(name+' / '+variant,async()=>{
    const r=new UIRenderer(testArea,sampleSpec(name,variant),options);await frame();assert(!r.root.querySelector('[data-error=true]'),'component render failure');assert(r.root.textContent.length>0,'readable content missing');assert(r.root.scrollWidth<=r.root.clientWidth+1,'component width overflow');r.dispose();
  });
  for(const [name,scene]of Object.entries(SCENARIOS))await test('composition / '+name,async()=>{
    const b=new Block();for(const op of scene.ops)b.apply(op);b.closed=true;assert(!b.errors.length,'invalid composition');
    const r=new UIRenderer(testArea,b.spec(),options);await frame();assert(!r.root.querySelector('[data-error=true]'),'composition render failed');assert(r.root.scrollWidth<=r.root.clientWidth+1,'composition overflow');r.dispose();
  });
  const editorialSpec=name=>{const b=new Block();for(const op of SCENARIOS[name].ops)b.apply(op);b.closed=true;return b.spec();};
  await test('per-record notes survive filtering and keep their own source identity',async()=>{
    const spec=editorialSpec('review'),r=new UIRenderer(testArea,spec,options);await frame();
    const initialRows=r.root.querySelectorAll('[data-node-id=items] [data-item-index]');assert(Math.abs(initialRows[0].getBoundingClientRect().x-initialRows[1].getBoundingClientRect().x)<1,'declared single-column review became a narrow multi-column layout');
    const original=JSON.stringify(r.store.get('records').map(row=>row.excerpt));
    const second=r.root.querySelector('[data-node-id=items] [data-item-index="1"]');const note=second.querySelector('textarea');note.focus();note.value='这是展望，尚未正式决定。';note.setSelectionRange(4,4);note.dispatchEvent(new Event('input',{bubbles:true}));await frame();assert(document.activeElement===note&&note.selectionStart===4,'typing replaced the focused record or lost its caret');
    r.root.querySelector('[data-node-id=items] [data-item-index="1"]').querySelectorAll('[role=radio]')[1].click();await frame();
    r.root.querySelectorAll('[data-node-id=filter] [role=radio]')[1].click();await frame();
    const rows=r.root.querySelectorAll('[data-node-id=items] [data-item-index]');assert(rows.length===1,'filter did not narrow the review');assert(rows[0].textContent.includes('校园报道'),'note moved to a different record');assert(rows[0].querySelector('textarea').value==='这是展望，尚未正式决定。','filtered note lost');
    assert(r.interaction().block.inputs['records.1.note']==='这是展望，尚未正式决定。','follow-up lost concrete record binding');assert(JSON.stringify(r.store.get('records').map(row=>row.excerpt))===original,'source text changed');assert(!r.root.querySelector('[data-error=true]'),'item binding failed');r.dispose();
  });
  await test('undo, redo and reset cover choices and drafts without a model call',async()=>{
    let calls=0;const r=new UIRenderer(testArea,editorialSpec('review'),{...options,askModel:async()=>{calls++;}});await frame();
    const first=r.root.querySelector('[data-node-id=items] textarea');first.value='待核实';first.dispatchEvent(new Event('input',{bubbles:true}));await frame();
    assert(r.store.get('records.0.note')==='待核实','draft not updated');r.undoButton.click();await frame();assert(r.store.get('records.0.note')==='','undo did not restore draft');r.redoButton.click();await frame();assert(r.store.get('records.0.note')==='待核实','redo lost draft');
    r.resetButton.click();await frame();assert(r.store.get('records.0.note')==='','reset did not restore initial choices');assert(r.interaction().block.inputs['records.0.note']===''&&r.interaction().changed,'reset left a stale note in the next model context');r.undoButton.click();await frame();assert(r.store.get('records.0.note')==='待核实','reset was not reversible');assert(calls===0,'local edit invoked a model');r.dispose();
  });
  await test('resetting forms, unbound tabs and local checklists supersedes earlier choices',async()=>{
    const ops=[{op:'begin',v:1},{op:'node',id:'form',type:'Form',props:{fields:[{name:'note',label:'补充判断',type:'text'}]}},{op:'node',id:'tabs',type:'Tabs',props:{labels:['甲','乙']},children:['a','b']},{op:'node',id:'a',type:'Prose',props:{text:'第一组'}},{op:'node',id:'b',type:'Prose',props:{text:'第二组'}},{op:'node',id:'checks',type:'Checklist',props:{label:'本地选择',items:[{id:'one',label:'保留问题'}]}},{op:'end'}],b=new Block();for(const op of ops)b.apply(op);b.closed=true;
    const r=new UIRenderer(testArea,b.spec(),options);await frame();const input=r.root.querySelector('input[name=note]');input.value='曾经填写';input.dispatchEvent(new Event('input',{bubbles:true}));r.root.querySelectorAll('[role=tab]')[1].click();const check=r.root.querySelector('input[type=checkbox]');check.checked=true;check.dispatchEvent(new Event('change',{bubbles:true}));await frame();
    r.resetButton.click();await frame();const context=r.interaction();assert(context.changed,'reset was omitted from context');assert(context.block.view.form.fields.note===''&&context.block.view.tabs.selected===0&&context.block.view.checks.checked.length===0,'old view values survived reset');r.dispose();
  });
  await test('draft editing updates readable output and context while retaining evidence',async()=>{
    const r=new UIRenderer(testArea,editorialSpec('review'),options);await frame();r.root.querySelectorAll('[role=tab]')[1].click();await frame();
    const draft=r.root.querySelector('[data-node-id=draftEditor] textarea');draft.value='我保留试点范围，将未来扩大保留为未知。[1]';draft.dispatchEvent(new Event('input',{bubbles:true}));await frame();
    assert(r.root.querySelector('[data-node-id=draftText]').textContent.includes('将未来扩大保留为未知'),'draft preview did not change');assert(r.interaction().block.inputs.draft===draft.value,'context omitted draft');assert(draft.clientHeight>=100&&draft.scrollHeight<=draft.clientHeight+2,'short editable prose was clipped in a tiny input');assert(r.root.scrollWidth<=r.root.clientWidth+1,'writing layout overflow');
    testArea.style.width='180px';await frame();await frame();assert(draft.scrollHeight<=draft.clientHeight+2||draft.clientHeight>=350,'resizing clipped the editor before its next keystroke');testArea.style.width='';r.dispose();
  });
  await test('model actions show a pending state, reject duplicate clicks and retain drafts on failure',async()=>{
    let calls=0,reject;const r=new UIRenderer(testArea,editorialSpec('review'),{...options,askModel:()=>{calls++;return new Promise((_,fail)=>{reject=fail;});}});await frame();
    const textarea=r.root.querySelector('[data-node-id=items] textarea');textarea.value='保留我的疑问';textarea.dispatchEvent(new Event('input',{bubbles:true}));await frame();
    let action=r.root.querySelector('[data-node-id=recordFollowup] button');action.click();action.click();await frame();assert(calls===1&&action.disabled,'duplicate model request');assert(action.textContent==='分析中…','pending label absent');
    reject(Error('测试：暂时连接失败'));await frame();action=r.root.querySelector('[data-node-id=recordFollowup] button');assert(!action.disabled&&action.textContent==='围绕这条材料继续分析','action did not recover');assert(r.store.get('records.0.note')==='保留我的疑问','error erased draft');assert(r.feedback.textContent.includes('连接失败'),'error not announced');r.dispose();
  });
  await test('an unanswered top-level choice restores only a declared selection',async()=>{
    const spec=sampleSpec('Choice');spec.state.perspective=null;const r=new UIRenderer(testArea,spec,options);await frame();assert(r.root.querySelectorAll('[aria-checked=true]').length===0,'unanswered choice preselected');
    r.root.querySelectorAll('[role=radio]')[1].click();await frame();const snapshot=r.snapshot();r.dispose();const h=new UIRenderer(testArea,spec,{...options,snapshot});await frame();assert(h.store.get('perspective')==='impact','nullable choice snapshot was not restored');assert(h.root.querySelectorAll('[aria-checked=true]').length===1,'restored choice not reflected in UI');h.dispose();
  });
  await test('news reading lens changes qualitative evidence and preserves its source records',async()=>{
    const spec=editorialSpec('news'),r=new UIRenderer(testArea,spec,options),before=JSON.stringify(r.store.get('reports'));await frame();
    const facts=r.root.querySelector('[data-node-id=lens] [role=radio]:nth-child(2)');facts.focus();facts.click();await frame();
    assert(r.root.querySelector('[data-node-id=matrix]').textContent.includes('已经明确'),'comparison lens did not change');assert(JSON.stringify(r.store.get('reports'))===before,'reading lens rewrote evidence');
    assert(document.activeElement===facts&&facts.getAttribute('aria-checked')==='true','choice lost focus or selection');
    facts.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));await frame();assert(r.store.get('focus')==='perspective','keyboard did not change perspective');
    r.dispose();
  });
  await test('scenario answer, feedback, reset, restoration and explicit follow-up work together',async()=>{
    const spec=editorialSpec('notice');let sent;const r=new UIRenderer(testArea,spec,{...options,askModel:async event=>sent=event});await frame();
    assert(r.root.querySelector('[data-node-id=checkAnswer] button').disabled,'unanswered exercise can be graded');
    r.root.querySelector('[data-node-id=answerChoice] [role=radio]:nth-child(2)').click();await frame();assert(!sent,'selecting an answer sent a model request');
    r.root.querySelector('[data-node-id=checkAnswer] button').click();await frame();assert(!r.root.querySelector('[data-node-id=feedback]').hidden,'feedback did not open');assert(r.root.textContent.includes('这个判断守住了原文边界'),'feedback does not match answer');
    const snapshot=r.snapshot();r.dispose();const restored=new UIRenderer(testArea,spec,{...options,snapshot,askModel:async event=>sent=event});await frame();assert(restored.store.get('exercise.answer')==='b'&&restored.store.get('exercise.revealed'),'exercise progress was lost');
    restored.root.querySelector('[data-node-id=caseChoice] [role=radio]:nth-child(2)').click();await frame();assert(restored.store.get('exercise.answer')===null&&!restored.store.get('exercise.revealed'),'new scenario retained an old grade');assert(restored.root.querySelector('[data-node-id=feedback]').hidden,'new scenario exposed feedback');
    restored.root.querySelector('[data-node-id=noticeContinue] button').click();await frame();assert(sent?.values.scenario.id==='rumor','follow-up lost the active scenario');restored.dispose();
  });
  await test('editorial composition has no enclosing frame and qualitative columns fit their container',async()=>{
    const r=new UIRenderer(testArea,editorialSpec('news'),options);await frame();const s=getComputedStyle(r.root);assert(parseFloat(s.borderTopWidth)===0&&parseFloat(s.borderLeftWidth)===0,'enclosing frame returned');
    const wrap=r.root.querySelector('.gu-compare-wrap');assert(wrap.scrollWidth<=wrap.clientWidth+1,'qualitative comparison overflows');r.dispose();
  });
  await test('free composition filters repeated subtrees and keeps scoped actions, hidden branches and restored state correct',async()=>{
    const b=new Block();for(const op of SCENARIOS.compose.ops)b.apply(op);b.closed=true;let sent;
    const r=new UIRenderer(testArea,b.spec(),{...options,askModel:async value=>sent=value});await frame();
    r.store.set('category','表达');r.store.set('showDetail',false);await frame();
    assert(r.root.querySelectorAll('.gu-collection-item').length===2,'filter did not update collection');assert(r.root.querySelector('[data-node-id=hours]').textContent.includes('5.5'),'derived total is stale');assert(r.root.querySelector('[data-node-id=method]').hidden,'conditional branch stayed visible');
    r.root.querySelector('[data-node-id=itemAction] button').click();await frame();assert(sent.node_id==='itemAction'&&sent.values.project.id==='c','scoped action selected the wrong item');
    const snapshot=r.snapshot();r.dispose();const history=new UIRenderer(testArea,b.spec(),{...options,snapshot});assert(history.root.querySelectorAll('.gu-collection-item').length===2,'collection state was not restored');history.store.set('query','不存在');await frame();assert(history.root.querySelector('.gu-collection').textContent.includes('没有匹配项'),'empty branch is missing');history.dispose();
  });
  await test('semantic text colors meet AA on both surfaces',()=>{
    const r=new UIRenderer(testArea,sampleSpec('Callout'),options),style=getComputedStyle(r.root);
    const rgb=value=>{let s=value.trim();if(s[0]==='#'&&s.length===4)s='#'+[...s.slice(1)].map(v=>v+v).join('');return s[0]==='#'?s.slice(1).match(/../g).map(v=>parseInt(v,16)):s.match(/[\d.]+/g).slice(0,3).map(Number);};
    const luminance=value=>rgb(value).map(c=>{c/=255;return c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4);}).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
    for(const bg of ['--gu-bg','--gu-surface'])for(const text of ['--gu-ink','--gu-muted','--gu-accent','--gu-error','--gu-warning']){
      const a=luminance(style.getPropertyValue(bg)),b=luminance(style.getPropertyValue(text));
      assert((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,text+' on '+bg+' below AA');
    }r.dispose();
  });
  await test('chart axes stay readable at container width and resize cleanly',async()=>{
    const r=new UIRenderer(testArea,sampleSpec('BarChart'),options);await frame();await frame();
    const svg=r.root.querySelector('.gu-chart svg');assert(svg,'chart not loaded');
    const width=svg.getBoundingClientRect().width,units=svg.viewBox.baseVal.width;
    assert(width/units>=.98,'axis labels shrunk with the chart');
    assert(svg.querySelector('.gu-chart-axis')&&getComputedStyle(svg.querySelector('.gu-chart-axis')).fontSize==='12px','axis label scale');r.dispose();
  });
  await test('interactive controls retain 44px targets',()=>{
    for(const type of ['Button','ButtonGroup','Choice','Slider','Stepper','Toggle','Select','TextInput','Checklist','Tabs','Accordion']){
      const r=new UIRenderer(testArea,sampleSpec(type),options);
      for(const element of r.root.querySelectorAll('button,input,select,textarea,summary')){
        const target=element.type==='checkbox'?element.closest('label'):element,rect=target?.getBoundingClientRect();
        if(!rect?.height)continue;
        assert(rect.height>=43.9&&rect.width>=43.9,type+' touch target below 44px');
      }r.dispose();
    }
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
  await test('tab navigation sits above a full-width panel at every container width',()=>{
    const r=new UIRenderer(testArea,sampleSpec('Tabs'),options),nav=r.root.querySelector('[role=tablist]'),panel=r.root.querySelector('[role=tabpanel]:not([hidden])');
    const a=nav.getBoundingClientRect(),b=panel.getBoundingClientRect(),wrapper=nav.closest('.gu-node').getBoundingClientRect();
    assert(b.top>=a.bottom-1,'tab content is squeezed alongside its navigation');assert(b.width>=wrapper.width-2,'tab panel does not use the content width');r.dispose();
  });
  await test('host side effects cannot execute from a change event',async()=>{
    let calls=0;const spec=sampleSpec('Slider');spec.nodes.demo.on={change:{kind:'host',name:'open_calendar',params:{}}};const r=new UIRenderer(testArea,spec,{...options,hostActions:{open_calendar:{run:()=>calls++}}}),input=r.root.querySelector('input');input.value='3';input.dispatchEvent(new Event('input',{bubbles:true}));await frame();assert(calls===0,'side effect escaped click gate');r.dispose();
  });
  await test('hostile Markdown stays text, unsafe links and images do not load',()=>{
    const node=markdown('<script>window.bad=1</script>\n[x](javascript:alert)\n![x](https://evil.invalid/pixel)\n<a onclick="bad()">x</a>');testArea.append(node);assert(!node.querySelector('script,img,[onclick]'),'unsafe markup created');assert(![...node.querySelectorAll('a')].some(a=>a.protocol==='javascript:'),'unsafe link');assert(node.textContent.includes('<script>'),'plain fallback lost content');
    const spec=sampleSpec('Image');spec.nodes.demo.props.src='https://evil.invalid/pixel';const r=new UIRenderer(testArea,spec,options);assert(!r.root.querySelector('img'),'remote image was loaded');r.dispose();
  });
  await test('linked plot updates geometry without a network request',async()=>{
    const b=new Block();for(const op of SCENARIOS.explore.ops)b.apply(op);b.closed=true;
    const r=new UIRenderer(testArea,b.spec(),options);await frame();await frame();
    const input=r.root.querySelector('input[type=range]'),before=r.root.querySelector('polyline').getAttribute('points'),fetchOriginal=window.fetch;let calls=0;
    window.fetch=()=>{calls++;throw Error('unexpected network');};
    try{input.focus();input.value='-1';input.dispatchEvent(new Event('input',{bubbles:true}));await frame();assert(r.root.querySelector('polyline').getAttribute('points')!==before,'curve did not change');assert(document.activeElement===input,'plot input lost focus');assert(calls===0,'plot used network');}finally{window.fetch=fetchOriginal;r.dispose();}
  });
  await test('media requires current authorization and never autoplays',()=>{
    const spec=sampleSpec('Video'),r=new UIRenderer(testArea,spec,{...options,mediaResources:[]});assert(!r.root.querySelector('video'),'unauthorized video created');r.dispose();
    const allowed=new UIRenderer(testArea,spec,options),video=allowed.root.querySelector('video');assert(video&&video.controls&&!video.autoplay&&video.preload==='none','unsafe or missing video controls');allowed.dispose();
    spec.nodes.demo.props.src='https://evil.invalid/movie.mp4';const remote=new UIRenderer(testArea,spec,options);assert(!remote.root.querySelector('video'),'remote video loaded');remote.dispose();
  });
  await test('image preview opens original with keyboard accessible close',()=>{
    const r=new UIRenderer(testArea,sampleSpec('Image'),options),preview=r.root.querySelector('.gu-image-open');assert(preview,'preview missing');preview.click();const dialog=document.querySelector('.gu-media-dialog');assert(dialog?.open&&dialog.querySelector('img').alt,'image dialog missing');assert(document.activeElement?.textContent==='关闭预览','focus not on close');dialog.close();r.dispose();
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
