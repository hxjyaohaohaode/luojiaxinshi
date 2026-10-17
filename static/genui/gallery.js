import {CATALOG,Block,parseMessage} from './core.js';
import {SAMPLES} from './fixtures.js';
import {SCENARIOS} from './scenarios.js';
import {UIRenderer,MessageRenderer} from './renderer.js';
import {el} from './dom.js';
import {CitationView} from './citations.js';
export const galleryOptions={aiLabel:"工程示例",mediaResources:['/static/assets/genui-demo.webm'],imageResources:['/static/assets/luojia-messenger-planning.png'],hostViews:{messenger:p=>{const card=el('div','gu-messenger'),img=el('img');img.src='/static/assets/luojia-messenger-'+(p.pose||'planning')+'.png';img.alt='原创珞珈小信使';card.append(img,el('span','',p.title));return card;},campus_schedule:()=>el('p','','日程入口（工程示例）'),material_index:()=>el('p','','材料目录（工程示例）')},hostActions:{open_calendar:{run:()=>{document.querySelector('#gallery-status').textContent='已触发白名单日程入口（工程测试）';}}},askModel:async event=>{document.querySelector('#gallery-log').textContent=JSON.stringify(event,null,2);document.querySelector('#gallery-status').textContent='已生成结构化事件；画廊不会调用模型。';},onSave:async value=>{document.querySelector('#gallery-log').textContent=JSON.stringify(value,null,2);}};
export function sampleSpec(name,variant='ready'){
  const block=new Block();for(const original of SAMPLES[name]){const op=JSON.parse(JSON.stringify(original));if(op.op==='node'&&op.id==='demo'){
    if(['loading','empty','error'].includes(variant)){op.props.status=variant;if(variant==='error')op.props.error='示例：这一项暂未获取成功，请重试。';}
    if(variant==='long'){if('text'in op.props)op.props.text='需要完整保留并自动换行的长内容。'.repeat(24);if('label'in op.props)op.props.label='这是一个需要自动换行的较长标签，用来检查窄屏对齐';if('title'in op.props)op.props.title='这是一项较长标题，检查完整显示和布局';}
  }block.apply(op);}block.closed=true;return block.spec();
}
const select=document.querySelector('#component'),result=document.querySelector('#gallery-result'),variant=document.querySelector('#variant');let renderers=[],timer,sourceView;
const group=el('optgroup');group.label='组合示例 · 可以自由改写';for(const [key,scene]of Object.entries(SCENARIOS)){const option=el('option','',scene.title);option.value='scene:'+key;group.append(option);}select.append(group);
for(const name of Object.keys(CATALOG.components)){const option=el('option','',name);option.value=name;select.append(option);}
function clearRender(){clearInterval(timer);sourceView?.dispose();sourceView=null;renderers.forEach(r=>r.dispose());renderers=[];result.replaceChildren();}
function render(){clearRender();for(const button of document.querySelectorAll('[data-scene]'))button.setAttribute('aria-pressed',String(select.value==='scene:'+button.dataset.scene));if(select.value.startsWith('scene:')){const scene=SCENARIOS[select.value.slice(6)],content=el('div'),footer=el('div','gu-gallery-evidence');result.append(content,footer);const decorate=()=>sourceView?.decorate(),r=new MessageRenderer(content,{...galleryOptions,aiLabel:false,externalActions:true,onRender:decorate,afterRender:decorate});renderers.push(r);sourceView=new CitationView(content,footer,{sources:[]});sourceView.update({id:select.value,citations:scene.citations||[],evidence_sources:scene.evidence_sources||[]},{sources:[]});r.push(scene.intro+'\n\n```genui\n'+scene.ops.map(op=>JSON.stringify(op)).join('\n')+'\n```');r.finish();return;}const names=select.value==='all'?Object.keys(SAMPLES):[select.value];
  for(const name of names){const section=el('section');section.append(el('h2','',name));result.append(section);if(variant.value==='stream'){
      const text='先展示说明，再逐步补充界面。\n```genui\n'+SAMPLES[name].map(op=>JSON.stringify(op)).join('\n')+'\n```';const renderer=new MessageRenderer(section,galleryOptions);renderers.push(renderer);let offset=0;const id=setInterval(()=>{renderer.push(text.slice(offset,offset+80));offset+=80;if(offset>=text.length){clearInterval(id);renderer.finish();}},40);timer=id;if(names.length>1){clearInterval(id);renderer.push(text);renderer.finish();}
    }else renderers.push(new UIRenderer(section,sampleSpec(name,variant.value),galleryOptions));
  }
}
select.addEventListener('change',render);variant.addEventListener('change',render);document.querySelector('#theme').addEventListener('change',event=>{document.querySelector('main').dataset.genuiTheme=event.target.value;});document.querySelector('#width').addEventListener('change',event=>{document.querySelector('main').dataset.narrow=String(event.target.value==='narrow');});
document.querySelector('#run-tests').addEventListener('click',async event=>{const b=event.currentTarget;b.disabled=true;document.querySelector('#run-e2e').disabled=true;clearRender();document.querySelector('#gallery-status').textContent='正在验证组件、状态、交互和性能…';try{const {run}=await import('./gallery-tests.js');const report=await run(result,galleryOptions,sampleSpec);document.querySelector('#gallery-log').textContent=JSON.stringify(report,null,2);document.querySelector('#gallery-status').textContent=report.failed?'有 '+report.failed+' 项未通过':'组件验证通过：'+report.passed+' 项';}catch(error){document.querySelector('#gallery-status').textContent='测试中断：'+error.message;}finally{b.disabled=false;document.querySelector('#run-e2e').disabled=false;}});
select.value='scene:news';render();
const editor=document.querySelector('#composition-source');
function loadEditor(){const scene=SCENARIOS[select.value.slice(6)];if(scene)editor.value=scene.intro+'\n\n```genui\n'+scene.ops.map(op=>JSON.stringify(op)).join('\n')+'\n```';}
select.addEventListener('change',loadEditor);loadEditor();
for(const button of document.querySelectorAll('[data-scene]'))button.addEventListener('click',()=>{select.value='scene:'+button.dataset.scene;render();loadEditor();});
document.querySelector('#render-composition').addEventListener('click',()=>{
  const parts=parseMessage(editor.value),errors=parts.filter(p=>p.kind==='ui').flatMap(p=>p.spec.errors);
  if(errors.length){document.querySelector('#gallery-status').textContent='结构需要修正：'+errors.map(e=>e.code+(e.id?'（'+e.id+'）':'')).join('、');return;}
  clearRender();const renderer=new MessageRenderer(result,galleryOptions);renderers=[renderer];renderer.update(parts);document.querySelector('#gallery-status').textContent='已按当前内容重新编排，可直接操作。';
});

document.querySelector('#run-e2e').addEventListener('click',async event=>{const b=event.currentTarget;b.disabled=true;document.querySelector('#run-tests').disabled=true;clearRender();document.querySelector('#gallery-status').textContent='正在验证真实传输、保存、重载与降级…';try{const {runE2E}=await import('./e2e.js');const report=await runE2E(result);document.querySelector('#gallery-log').textContent=JSON.stringify(report,null,2);document.querySelector('#gallery-status').textContent=report.failed?'对话验收有 '+report.failed+' 项未通过':'对话验收通过：'+report.passed+' 项';}catch(error){document.querySelector('#gallery-status').textContent=error.message;}finally{b.disabled=false;document.querySelector('#run-tests').disabled=false;}});

document.querySelector('#record-demo').addEventListener('click',async event=>{const b=event.currentTarget;b.disabled=true;try{const {recordDemo}=await import('./media-demo.js');document.querySelector('#gallery-status').textContent='正在生成本地视频验收素材…';await recordDemo();document.querySelector('#gallery-status').textContent='工程视频已生成，仅用于播放验收。';}catch(error){document.querySelector('#gallery-status').textContent=error.message;}finally{b.disabled=false;}});
