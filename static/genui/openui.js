import {el,button} from './dom.js';
import {openUIPlainText} from './openui-codec.js';

const clone=value=>JSON.parse(JSON.stringify(value));
function boundedControls(value){
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length>40)throw Error('互动输入过多，请减少到 40 项以内。');
  if(new TextEncoder().encode(JSON.stringify(value)).length>16000)throw Error('互动内容过长，请精简后保存。');
  const clean=Object.create(null);
  for(const [key,item]of Object.entries(value)){
    if(!key||key.length>100||['__proto__','prototype','constructor'].includes(key)||!['string','boolean'].includes(typeof item)||typeof item==='string'&&item.length>4000)throw Error('互动输入未通过检查。');
    clean[key]=item;
  }
  return clean;
}
export class SandboxRenderer{
  constructor(container,spec,options={}){
    this.container=container;this.options=options;this.spec=spec;this.controls={};this.initial={};this.records=new Map();this.view={};
    this.token=crypto.randomUUID();this.status=el('p','openui-status','正在生成界面…');this.status.setAttribute('role','status');
    this.frame=el('iframe','openui-frame');this.frame.title=spec.sandbox?.title||'互动回答';this.frame.setAttribute('sandbox','allow-scripts');this.frame.setAttribute('allow','camera \'none\'; microphone \'none\'; geolocation \'none\'; clipboard-read \'none\'; clipboard-write \'none\'');this.frame.setAttribute('referrerpolicy','no-referrer');this.frame.setAttribute('scrolling','no');
    this.frame.src='/static/genui/sandbox.html';this.frame.height=String(spec.sandbox?.initialHeight||160);this.frame.hidden=!spec.complete&&!spec.sandbox?.html?.join('').trim();
    this.toolbar=el('div','openui-toolbar');this.reset=button('重置选择',()=>this.post('restore',{controls:this.initial}),'button small plain');this.toolbar.append(this.reset);this.toolbar.hidden=true;
    this.fallback=el('details','openui-fallback');this.fallback.append(el('summary','','文字内容'),el('div','openui-readable'));
    this.message=event=>this.receive(event);window.addEventListener('message',this.message);
    this.load=()=>this.initialize();this.frame.addEventListener('load',this.load);
    this.container.classList.add('openui-surface');this.container.replaceChildren(this.status,this.frame,this.toolbar,this.fallback);
    this.timer=setTimeout(()=>{if(!this.ready)this.error('互动界面未能连接，可查看文字内容或重新生成。');},12000);
    this.update(spec);
  }
  initialize(){if(this.disposed||this.initialized)return;this.initialized=true;this.frame.contentWindow?.postMessage({channel:'campus-openui',token:this.token,type:'init'},'*');}
  post(type,data={}){if(!this.disposed)this.frame.contentWindow?.postMessage({channel:'campus-openui',type,...data},'*');}
  update(spec){
    const revision=spec.sandbox?.revision;
    if(revision&&this.revision&&revision!==this.revision&&this.localInteractive)this.restart();
    if(revision)this.revision=revision;
    this.spec=spec;
    const ui=spec.sandbox;
    if(!ui){if(spec.errors?.length)this.error('界面内容未完整接收，请查看文字或重新生成。');return;}
    this.frame.title=ui.title||'互动回答';
    this.frame.hidden=!spec.complete&&(!ui.cssComplete||!ui.html?.join('').trim());
    const signature=JSON.stringify([ui,spec.complete]);if(signature===this.signature)return;this.signature=signature;
    this.fallback.lastChild.textContent=openUIPlainText(ui).replace(/\[E\d+\]/g,'');
    this.fallback.hidden=!this.fallback.lastChild.textContent.trim();
    if(!spec.complete)this.status.textContent=ui.localReady?'正在核对内容…':ui.htmlComplete?'正在生成交互…':ui.cssComplete?'正在生成界面…':'正在生成样式…';
    this.render();
  }
  render(){if(this.ready&&this.spec.sandbox)this.post('render',{content:this.spec.sandbox,complete:!!this.spec.complete&&!this.spec.errors?.length,snapshot:this.pendingRestore||this.options.snapshot});}
  restart(){const edited=Object.fromEntries(Object.entries(this.controls).filter(([key,value])=>JSON.stringify(value)!==JSON.stringify(this.initial[key])));this.pendingRestore={state:{controls:edited},view:{},contract:this.controlContract||{}};this.token=crypto.randomUUID();this.initialized=false;this.ready=false;this.interactive=false;this.localInteractive=false;this.lastAction=0;this.controls={};this.initial={};this.status.hidden=false;const old=this.frame;this.frame=old.cloneNode(false);this.frame.addEventListener('load',this.load);old.removeEventListener('load',this.load);old.replaceWith(this.frame);old.src='about:blank';this.signature=null;}
  schedule(){this.render();}
  receive(event){
    if(this.disposed||event.source!==this.frame.contentWindow||event.data?.channel!=='campus-openui')return;
    const data=event.data;
    if(data.type==='boot'){this.initialize();return;}
    if(data.token!==this.token)return;
    if(data.type==='ready'){this.ready=true;clearTimeout(this.timer);this.render();return;}
    if(data.type==='resize'){
      if(typeof data.height==='number'&&Number.isFinite(data.height)&&data.height>=0&&data.height<=200000){const height=Math.max(1,Math.ceil(data.height));if(this.frame.height!==String(height)){const follow=this.options.beforeRender?.();this.frame.height=String(height);this.options.afterRender?.(follow);}}
    }else if(data.type==='reading'&&Number.isFinite(data.delta)&&Math.abs(data.delta)<=240){
      this.frame.dispatchEvent(new CustomEvent('campus:reading',{bubbles:true,detail:{delta:data.delta}}));
    }else if(data.type==='runtime_error'){
      this.interactive=false;this.error('此界面的交互未能完成，可查看文字内容或重新生成。');
    }else if(data.type==='text'&&typeof data.text==='string'&&data.text.length<=80000){
      this.readableText=data.text;this.fallback.lastChild.textContent=data.text;
    }else if(data.type==='local_ready'){
      this.localInteractive=true;this.status.textContent='正在核对内容…';
    }else if(data.type==='interactive'){
      this.localInteractive=true;this.interactive=true;this.status.hidden=true;this.toolbar.hidden=!Object.keys(this.controls).length;
    }else if(data.type==='state'&&(this.spec.complete||this.spec.sandbox?.localReady)){
      try{const next=boundedControls(data.controls);if(data.initial)this.initial=boundedControls(data.initial);if(data.contract&&typeof data.contract==='object'&&JSON.stringify(data.contract).length<=16000)this.controlContract=data.contract;const changed=JSON.stringify(this.controls)!==JSON.stringify(next);this.controls=next;this.toolbar.hidden=!this.interactive||!Object.keys(next).length;if(changed)this.options.onChange?.();}catch(error){this.error(error.message);}
    }else if(data.type==='action')this.action(data);
  }
  async action(data){
    if(!this.spec.complete||!this.interactive||!Number.isSafeInteger(data.id)||data.id<=this.lastAction)return;
    this.lastAction=data.id;
    try{
      const args=data.args;
      if(!args||typeof args!=='object'||Array.isArray(args)||JSON.stringify(args).length>6000)throw Error('操作内容无效或过长。');
      if(data.name==='sendPrompt'){
        if(Object.keys(args).some(k=>!['text','values'].includes(k))||typeof args.text!=='string'||!args.text.trim()||args.text.length>4000)throw Error('请填写要继续分析的问题。');
        if(!this.options.askModel)throw Error('请回到原对话继续提问。');
        await this.options.askModel({v:1,node_id:'sandbox',event:'submit',prompt:args.text.trim(),values:args.values||{}});
      }else if(data.name==='openLink'){
        if(Object.keys(args).some(k=>k!=='url')||typeof args.url!=='string'||!this.options.linkResources?.includes(args.url))throw Error('此链接未登记为本回答来源。');
        const url=new URL(args.url);if(url.protocol!=='https:')throw Error('此链接无法安全打开。');
        window.open(url.href,'_blank','noopener,noreferrer');
      }else if(data.name==='hostAction'){
        const shapes={open_calendar:[],open_sources:[],upload_material:[],review_material:['source_id']};
        if(Object.keys(args).some(k=>!['name','params'].includes(k))||!Object.hasOwn(shapes,args.name)||!args.params||typeof args.params!=='object'||Array.isArray(args.params)||Object.keys(args.params).some(k=>!shapes[args.name].includes(k))||args.name==='review_material'&&typeof args.params.source_id!=='string')throw Error('此工作台操作暂不支持。');
        const action=this.options.hostActions?.[args.name];if(!action?.run)throw Error('请回到工作台执行此操作。');await action.run(args.params);
      }else if(data.name==='citation'){
        if(!Number.isInteger(args.number)||args.number<1)throw Error('依据编号无效。');
        if(this.options.openCitation)this.options.openCitation(args.number);else await this.options.hostActions?.open_sources?.run({});
      }else throw Error('此操作暂不支持。');
      this.post('result',{id:data.id,result:{ok:true}});
    }catch(error){this.post('result',{id:data.id,error:error.message||'操作未完成，请重试。'});}
  }
  error(text){this.status.hidden=false;this.status.textContent=text;this.status.classList.add('is-error');}
  snapshot(){return {state:{controls:clone(this.controls)},view:{}};}
  snapshots(){return this.snapshot();}
  markdown(){return this.readableText||openUIPlainText(this.spec.sandbox);}
  interaction(){const different=JSON.stringify(this.controls)!==JSON.stringify(this.initial);return {available:Object.keys(this.controls).length>0,changed:different,block:{inputs:{controls:clone(this.controls)},view:{}}};}
  markSaved(){}
  dispose(){this.disposed=true;clearTimeout(this.timer);window.removeEventListener('message',this.message);this.frame.removeEventListener('load',this.load);this.frame.src='about:blank';this.container.replaceChildren();}
}
