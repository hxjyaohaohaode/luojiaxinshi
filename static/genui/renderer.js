import {CATALOG,StateStore,resolve,validateAction,blockMarkdown,StreamParser} from './core.js';
import {matches,safeClone,safeKey,safeUrl,readPath} from './security.js';
import {el,button,replaceInOrder,markdown,dataTable,download,string} from './dom.js';
let nextInstance=0,chartsModule;
const numeric=value=>{if(typeof value!=='number'||!Number.isFinite(value))throw Error('数值暂不可用');return value;};
const errorText='这部分暂时无法显示，其余内容仍可使用。';

export class UIRenderer{
  constructor(container,spec,options={}){
    this.container=container;this.options=options;this.instance='genui-'+(++nextInstance);this.records=new Map();this.view=safeClone(options.snapshot?.view||{});this.store=new StateStore(spec.state||{});this.frame=0;this.disposed=false;
    if(options.snapshot?.state)for(const [key,value]of Object.entries(options.snapshot.state)){try{this.store.set(key,value);}catch{/* Outdated snapshots cannot override the current schema. */}}
    this.root=el('section','genui');this.root.setAttribute('aria-label','互动回答');this.root.dataset.genuiVersion='1';this.body=el('div','gu-body');this.footer=el('div','gu-footer');this.status=el('span','gu-status');this.feedback=el('span','gu-feedback');this.feedback.setAttribute('role','status');this.feedback.setAttribute('aria-live','polite');
    this.copy=button('复制为文字',async()=>{try{await navigator.clipboard.writeText(blockMarkdown(this.spec,this.store.values));this.announce('已复制');}catch{this.announce('复制失败，可选择回答文字后复制。');}});
    this.save=button('保存互动进度',async()=>{if(!this.options.onSave)return;this.save.disabled=true;try{await this.options.onSave(this.snapshot());this.announce('互动进度已保存');this.root.dataset.dirty='false';}catch(error){this.announce(error.message||'暂未保存，请重试。');}finally{this.save.disabled=false;}});
    this.save.hidden=!options.onSave;this.footer.append(this.status,this.copy,this.save,this.feedback);this.root.append(this.body,this.footer);container.append(this.root);
    this.unsubscribe=this.store.subscribe(()=>{this.changed();this.schedule();});this.update(spec,true);
  }
  changed(){this.root.dataset.dirty='true';this.options.onChange?.(this.snapshot());}
  announce(text){this.feedback.textContent=text;}
  snapshot(){return {state:this.store.snapshot(),view:safeClone(this.view)};}
  update(spec,immediate=false){this.spec=spec;try{this.store.defaults(spec.state||{});}catch{this.announce('状态更新超出限制，已保留当前值。');}if(immediate)this.paint();else this.schedule();}
  schedule(){if(!this.frame&&!this.disposed)this.frame=requestAnimationFrame(()=>{this.frame=0;this.paint();});}
  dispose(){this.disposed=true;cancelAnimationFrame(this.frame);this.unsubscribe?.();this.records.clear();this.root.remove();}
  node(id,depth=0){
    if(depth>CATALOG.limits.depth)return el('p','gu-error','内容层级过多，请查看文字。');
    const model=this.spec.nodes[id];let record=this.records.get(id);
    if(!record){record={id,element:el('div','gu-node'),content:el('div'),children:el('div','gu-children'),local:this.view[id]??=Object.create(null),signature:null};record.element.dataset.nodeId=id;record.element.append(record.content,record.children);this.records.set(id,record);}
    try{
      if(!model){record.content.replaceChildren(el('p','gu-skeleton','正在接收这部分内容…'));record.children.replaceChildren();return record.element;}
      const definition=CATALOG.components[model.type],props=resolve(model.props,this.store.values,this.spec.data||{});
      if(model.type!=='Unknown'&&(!definition||!matches(props,{type:'object',properties:definition.properties,required:definition.required,additionalProperties:false},false)))throw Error('数据尚未完整或不符合组件要求');
      this.paintItems+=(props.items?.length||0)+(props.data?.length||0)+Math.min(props.rows?.length||0,50)+(props.edges?.length||0)+1;
      if(this.paintItems>(CATALOG.limits.renderItems||5000))throw Error('render_limit');
      delete record.element.dataset.error;record.model=model;record.props=props;const signature=JSON.stringify([model.type,props,model.on,model.children]);
      if(signature!==record.signature){
        const focused=record.content.contains(document.activeElement)?document.activeElement:null,field=focused?.dataset.field,selection=focused&&'selectionStart'in focused?focused.selectionStart:null;
        record.signature=signature;record.refresh=null;record.mount=null;record.content.className='';record.content.replaceChildren();record.children.replaceChildren();record.element.className='gu-node gu-'+model.type.toLowerCase();
        if(model.type==='Unknown')record.content.append(el('p','gu-error',props.text||errorText));
        else if(props.status==='loading')record.content.append(el('p','gu-skeleton','正在准备…'));
        else if(props.status==='empty')record.content.append(el('p','gu-muted',props.fallback||'暂时没有内容'));
        else if(props.status==='error')record.content.append(el('p','gu-error',props.error||props.fallback||errorText));
        else this.build(record);
        if(field){const replacement=[...record.content.querySelectorAll('[data-field]')].find(e=>e.dataset.field===field);replacement?.focus({preventScroll:true});if(selection!==null&&replacement?.setSelectionRange)try{replacement.setSelectionRange(selection,selection);}catch{/* Numeric fields have no text selection. */}}
      }
      record.refresh?.();
      if(definition?.children&&(!props.status||props.status==='ready')){
        const children=(model.children||[]).map(child=>this.node(child,depth+1));if(record.mount)record.mount(children);else replaceInOrder(record.children,children);
      }
    }catch(error){record.signature=null;record.refresh=null;record.mount=null;record.content.replaceChildren(el('p','gu-error',model?.props?.fallback&&typeof model.props.fallback==='string'?model.props.fallback:errorText));record.children.replaceChildren();record.element.dataset.error='true';}
    return record.element;
  }
  paint(){
    if(this.disposed)return;this.paintItems=0;const start=performance.now();replaceInOrder(this.body,this.spec.roots.map(id=>this.node(id)));
    const label=this.options.aiLabel===false?'':typeof this.options.aiLabel==='string'?this.options.aiLabel:'AI 生成内容';this.status.textContent=[label,!this.spec.complete?'未完整接收':this.spec.errors?.length?'部分内容已降级':''].filter(Boolean).join(' · ');
    this.root.dataset.complete=String(!!this.spec.complete);this.options.onRender?.(performance.now()-start);
  }
  set(record,value){const bind=record.props.bind;if(!bind)throw Error('此控件尚未绑定状态');this.store.set(bind,value);}
  get(record){return this.store.get(record.props.bind);}
  local(record,key,value){record.local[key]=value;this.changed();}
  async action(record,eventName,values={},explicit=false){
    try{
      const raw=record.model.on?.[eventName];if(!raw)return;
      const action=validateAction(resolve(raw,this.store.values,this.spec.data||{}));
      if(action.kind==='state'){this.store.set(action.key,action.value);return;}
      if(!explicit||!['click','submit'].includes(eventName))throw Error('此操作需要点击确认。');
      if(action.kind==='open_url'){const url=safeUrl(action.url,{hosts:this.options.urlHosts||CATALOG.policy.urlHosts});if(!url)throw Error('此链接不在允许范围内。');window.open(url,'_blank','noopener,noreferrer');}
      else if(action.kind==='host'){
        if(action.name==='export_csv'||action.name==='export_json'){download(action.params?.data||[],action.name==='export_csv'?'csv':'json');this.announce('导出文件已生成');return;}
        const registered=this.options.hostActions?.[action.name];if(!registered)throw Error('此操作暂不可用。');
        if(registered.highRisk&&!(await this.options.confirm?.('确认执行此操作？')))return;
        await registered.run(action.params||{});
      }else if(action.kind==='ask_model'){
        if(!this.options.askModel)throw Error('请在对话中继续提问。');await this.options.askModel({v:1,node_id:record.id,event:eventName,prompt:action.prompt||'',values:{...(action.values||{}),...safeClone(values)}});
      }
    }catch(error){this.announce(error.message||'操作未完成，请重试。');}
  }
  build(record){
    const {model,props:p,content:c,children:child,local:v}=record,t=model.type;
    if(['Stack','Row','Grid','Card'].includes(t)){
      record.element.dataset.gap=p.gap||'md';record.element.dataset.columns=p.columns||2;record.element.dataset.tone=p.tone||'neutral';if(p.title||p.label)c.append(el('h3','gu-heading',p.title||p.label));if(p.description)c.append(el('p','gu-muted',p.description));return;
    }
    if(['Tabs','Carousel','Accordion'].includes(t)){this.groups(record);return;}
    if(t==='Divider'){c.append(el('hr','gu-divider'));return;}
    if(t==='Markdown'){v.markdown??={};c.append(markdown(p.text,{view:v.markdown,changed:()=>this.changed()}));return;}
    if(t==='Heading'){c.append(el('h'+p.level,'gu-heading',p.text));return;}
    if(t==='Callout'||t==='Badge'){const node=el(t==='Badge'?'span':'aside',t==='Badge'?'gu-badge':'gu-callout');node.dataset.tone=p.tone||'info';if(p.label)node.append(el('strong','',p.label));node.append(el('span','',p.text));c.append(node);return;}
    if(t==='Stat'){const value=el('strong','gu-stat-value',string(p.value)+(p.unit?' '+p.unit:''));value.setAttribute('aria-live','polite');c.append(el('span','gu-muted',p.label),value);if(p.description)c.append(el('p','gu-muted',p.description));return;}
    if(t==='KeyValue'){const dl=el('dl','gu-kv');for(const item of p.items||[]){const row=el('div');row.append(el('dt','',item.label),el('dd','',item.value));dl.append(row);}if(!dl.childNodes.length)c.append(el('p','gu-muted','暂无信息'));else c.append(dl);return;}
    if(['List','Steps','Checklist','Timeline'].includes(t)){this.items(record);return;}
    if(t==='Table'){c.append(dataTable(p,{view:v,changed:()=>this.changed()}));return;}
    if(t==='Code'){const pre=el('pre'),code=el('code','',p.text);pre.append(code);const copy=button('复制代码',async()=>{try{await navigator.clipboard.writeText(p.text);this.announce('代码已复制');}catch{this.announce('请选中文字后复制。');}});c.className='gu-code';c.append(el('span','gu-muted',p.language||'文本'),copy,pre);return;}
    if(t==='Progress'){const label=el('div','gu-control-label',p.label),progress=el('progress');progress.max=p.max;progress.value=Math.min(p.max,Math.max(0,p.value));progress.setAttribute('aria-label',p.label||'进度');label.append(el('span','gu-numeric',`${Math.round(progress.value/p.max*100)}%`));c.append(label,progress);return;}
    if(['Slider','Stepper','Select','Toggle','TextInput','ButtonGroup'].includes(t)){this.input(record);return;}
    if(t==='Button'){const b=button(p.label,()=>this.action(record,'click',{},true),'gu-button gu-'+p.variant);b.disabled=p.disabled||!model.on?.click;c.append(b);return;}
    if(t.endsWith('Chart')){
      c.append(el('div','gu-skeleton','正在绘制图表…'));const signature=record.signature;
      (chartsModule??=import('./charts.js')).then(module=>{if(!this.disposed&&record.signature===signature)try{c.replaceChildren(module.chart(t,p,{view:v,changed:()=>this.changed()}));}catch{c.replaceChildren(el('p','gu-error',errorText));}}).catch(()=>{if(!this.disposed)c.replaceChildren(el('p','gu-error','图表暂不可用，请复制为文字查看数据。'));});return;
    }
    if(t==='Compare'){const grid=el('div','gu-compare-grid');for(const item of p.items||[]){const card=el('section','gu-compare-card');card.append(el('h4','',item.label));const dl=el('dl','gu-kv');for(const dimension of p.dimensions||[]){const row=el('div');row.append(el('dt','',dimension),el('dd','',item.values[dimension]??'未提供'));dl.append(row);}card.append(dl);grid.append(card);}c.append(grid.childNodes.length?grid:el('p','gu-muted','暂无对比项'));return;}
    if(t==='Math'){const math=document.createElementNS('http://www.w3.org/1998/Math/MathML','math');math.setAttribute('display','block');math.setAttribute('aria-label',p.text);const text=document.createElementNS(math.namespaceURI,'mtext');text.textContent=p.text;math.append(text);c.append(math);if(p.label)c.append(el('p','gu-muted',p.label));return;}
    if(t==='Diagram'){const diagram=el('ol','gu-diagram');for(const n of p.nodes||[]){const li=el('li');li.append(el('strong','',n.label));const edges=(p.edges||[]).filter(e=>e.from===n.id);for(const edge of edges){const dest=p.nodes.find(n=>n.id===edge.to);if(dest)li.append(el('div','gu-muted','→ '+(edge.label?edge.label+'：':'')+dest.label));}diagram.append(li);}c.append(diagram.childNodes.length?diagram:el('p','gu-muted','暂无流程'));return;}
    if(t==='Form'){this.form(record);return;}
    if(t==='Image'){
      const url=safeUrl(p.src,{hosts:this.options.imageHosts||[]}),permitted=url&&(new URL(url).origin!==location.origin||this.options.imageResources?.some(src=>new URL(src,location.origin).href===url));
      if(!permitted){c.append(el('p','gu-muted',p.alt+'（图片未获授权加载）'));return;}
      const img=el('img','gu-image');img.alt=p.alt;img.loading='lazy';img.referrerPolicy='no-referrer';img.addEventListener('error',()=>{img.replaceWith(el('p','gu-error',p.alt+'（图片加载失败）'));},{once:true});img.src=url;c.append(img);if(p.caption)c.append(el('p','gu-muted',p.caption));return;
    }
    if(t==='HostView'){const host=this.options.hostViews?.[p.view];if(!host){c.append(el('p','gu-muted',p.title||'请在工作台查看此内容'));return;}const result=host(p);if(!(result instanceof Node))throw Error('invalid_host_view');c.append(result);return;}
    throw Error('unknown_component');
  }
  groups(record){
    const {model,props:p,content:c,children:container,local:v}=record,accordion=model.type==='Accordion';const keys=model.children||[],labels=keys.map((_,i)=>p.labels?.[i]||'第 '+(i+1)+' 项');
    if(!keys.length){c.append(el('p','gu-muted','暂无分组内容'));return;}
    if(accordion){const details=keys.map((key,i)=>{const d=el('details','gu-accordion'),summary=el('summary','',labels[i]),slot=el('div','gu-group-panel');d.open=!!v[key];d.append(summary,slot);d.addEventListener('toggle',()=>{if(v[key]!==d.open)this.local(record,key,d.open);});container.append(d);return slot;});record.mount=children=>children.forEach((node,i)=>replaceInOrder(details[i],[node]));return;}
    const nav=el('div','gu-tabs');nav.setAttribute('role','tablist');nav.setAttribute('aria-label',p.label||'内容分组');c.append(nav);const panels=[],buttons=[];
    const choose=index=>{if(p.bind){try{this.set(record,index);}catch{this.announce('标签状态暂不可用');return;}}else this.local(record,'selected',index);refresh();};
    keys.forEach((key,i)=>{const panel=el('div','gu-group-panel');panel.id=this.instance+'-'+record.id+'-panel-'+i;panel.setAttribute('role','tabpanel');const b=button(labels[i],()=>choose(i),'gu-tab');b.id=this.instance+'-'+record.id+'-tab-'+i;b.setAttribute('role','tab');b.setAttribute('aria-controls',panel.id);panel.setAttribute('aria-labelledby',b.id);b.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?keys.length-1:(i+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length;choose(next);buttons[next].focus();});buttons.push(b);panels.push(panel);nav.append(b);container.append(panel);});
    const refresh=()=>{const selected=Math.max(0,Math.min(keys.length-1,Number(p.bind?this.get(record):v.selected)||0));buttons.forEach((b,i)=>{b.setAttribute('aria-selected',String(i===selected));b.tabIndex=i===selected?0:-1;panels[i].hidden=i!==selected;});};
    if(model.type==='Carousel'){const controls=el('div','gu-carousel-controls');controls.append(button('上一项',()=>{const n=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');choose((n-1+keys.length)%keys.length);}),button('下一项',()=>{const n=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');choose((n+1)%keys.length);}));c.append(controls);}
    record.refresh=refresh;record.mount=children=>children.forEach((node,i)=>replaceInOrder(panels[i],[node]));refresh();
  }
  items(record){
    const {model,props:p,content:c,local:v}=record,check=model.type==='Checklist',list=el(model.type==='Steps'?'ol':'ul','gu-'+model.type.toLowerCase()+'-items');if(p.label)c.append(el('strong','',p.label));c.append(list);
    const controls=[];for(const [i,item]of (p.items||[]).entries()){
      const li=el('li'),text=el('span');text.append(el('strong','',item.label));if(item.text||item.description)text.append(el('span','gu-muted',item.text||item.description));
      if(check){const id=item.id||'item'+i,label=el('label','gu-check'),input=el('input');input.type='checkbox';input.dataset.field=id;input.addEventListener('change',()=>{try{const current=p.bind?this.get(record):(v.checked??[]);if(!Array.isArray(current))throw Error('清单状态无效');const next=current.filter(key=>key!==id);if(input.checked)next.push(id);if(p.bind)this.set(record,next);else this.local(record,'checked',next);this.action(record,'change');}catch(error){this.announce(error.message);record.refresh();}});label.append(input,text);li.append(label);controls.push({input,id,item});}else li.append(text);list.append(li);
    }
    if(!list.childNodes.length)c.append(el('p','gu-muted','暂无条目'));
    if(check){record.refresh=()=>{const checked=p.bind?this.get(record):v.checked;if(checked!==undefined&&!Array.isArray(checked))throw Error('invalid_checklist_state');controls.forEach(({input,id,item})=>{input.checked=checked?checked.includes(id):!!item.done;});};record.refresh();}
  }
  input(record){
    const {model,props:p,content:c}=record,t=model.type,current=this.get(record),id=this.instance+'-'+record.id;const label=el('label','gu-control-label',p.label);label.htmlFor=id;c.append(label);
    const change=value=>{try{this.set(record,value);this.action(record,'change');}catch(error){this.announce(error.message);record.refresh?.();}};
    if(t==='ButtonGroup'){
      const group=el('div','gu-button-group');group.setAttribute('role','group');group.setAttribute('aria-label',p.label||'选项');const controls=(p.options||[]).map(option=>{const b=button(option.label,()=>change(option.value));group.append(b);return {b,value:option.value};});c.append(group);record.refresh=()=>{const value=this.get(record);controls.forEach(({b,value:option})=>b.setAttribute('aria-pressed',String(value===option)));};return;
    }
    const input=el(t==='Select'?'select':t==='TextInput'&&p.multiline?'textarea':'input');input.id=id;input.dataset.field='value';
    if(t==='Select'){
      for(const [index,option]of (p.options||[]).entries()){const item=el('option','',option.label);item.value=String(index);input.append(item);}input.addEventListener('change',()=>change(p.options[Number(input.value)]?.value));record.refresh=()=>{input.value=String((p.options||[]).findIndex(option=>option.value===this.get(record)));};
    }else if(t==='Toggle'){
      if(typeof current!=='boolean')throw Error('invalid_toggle_state');input.type='checkbox';input.setAttribute('role','switch');input.addEventListener('change',()=>change(input.checked));record.refresh=()=>{input.checked=!!this.get(record);};label.classList.add('gu-switch');label.prepend(input);return;
    }else if(t==='TextInput'){
      if(typeof current!=='string')throw Error('invalid_text_state');if(!p.multiline)input.type='text';input.placeholder=p.placeholder||'';input.maxLength=p.maxLength;input.autocomplete='off';input.addEventListener('input',()=>change(input.value));record.refresh=()=>{const value=this.get(record);if(input.value!==value)input.value=value;};
    }else{
      numeric(current);const min=numeric(p.min),max=numeric(p.max),step=numeric(p.step);if(max<min||step<=0)throw Error('invalid_range');input.type=t==='Slider'?'range':'number';input.min=min;input.max=max;input.step=step;
      const value=el('output','gu-numeric');value.htmlFor=id;label.append(value);const bounded=number=>Math.min(max,Math.max(min,Number((Math.round((number-min)/step)*step+min).toFixed(10))));
      input.addEventListener(t==='Slider'?'input':'change',()=>{if(input.value===''||!Number.isFinite(input.valueAsNumber)){record.refresh();return;}change(bounded(input.valueAsNumber));});
      record.refresh=()=>{const n=numeric(this.get(record));input.value=String(n);value.textContent=n+(p.unit?' '+p.unit:'');};
      if(t==='Stepper'){const row=el('div','gu-stepper'),minus=button('−',()=>change(bounded(numeric(this.get(record))-step))),plus=button('+',()=>change(bounded(numeric(this.get(record))+step)));minus.setAttribute('aria-label',p.label+' 减少');plus.setAttribute('aria-label',p.label+' 增加');row.append(minus,input,plus);c.append(row);const update=record.refresh;record.refresh=()=>{update();minus.disabled=this.get(record)<=min;plus.disabled=this.get(record)>=max;};return;}
    }
    c.append(input);
  }
  form(record){
    const {props:p,content:c,local:v}=record,form=el('form','gu-form'),inputs=[];form.setAttribute('aria-label',p.label||'补充信息');if(p.label)form.append(el('h4','',p.label));v.fields??=Object.create(null);
    const names=new Set();for(const field of p.fields||[]){if(!safeKey(field.name)||names.has(field.name))throw Error('invalid_form_field');names.add(field.name);const label=el('label','gu-form-field'),span=el('span','',field.label+(field.required?' *':'')),input=el(field.type==='select'?'select':'input');input.name=field.name;input.dataset.field=field.name;input.required=!!field.required;
      if(field.type==='select')for(const [index,option]of (field.options||[]).entries()){const o=el('option','',option.label);o.value=String(index);input.append(o);}else input.type=field.type==='checkbox'?'checkbox':field.type;
      if(field.type==='number'){if(field.min!==undefined)input.min=field.min;if(field.max!==undefined)input.max=field.max;input.step='any';}else if(field.type==='text'){input.maxLength=500;input.autocomplete='off';}
      if(field.type==='checkbox')input.checked=!!v.fields[field.name];else input.value=v.fields[field.name]??'';
      input.addEventListener('input',()=>{v.fields[field.name]=field.type==='checkbox'?input.checked:input.value;this.changed();});label.append(span,input);form.append(label);inputs.push({input,field});
    }
    const submit=button(p.submitLabel||'继续提问');submit.type='submit';submit.disabled=!this.options.askModel;form.append(submit,el('p','gu-muted','提交后，这些信息将作为一条新问题发送。'));
    form.addEventListener('submit',async event=>{event.preventDefault();if(!form.reportValidity())return;const values=Object.create(null);for(const {input,field}of inputs)values[field.name]=field.type==='checkbox'?input.checked:field.type==='number'?input.value===''?null:input.valueAsNumber:field.type==='select'?field.options[Number(input.value)]?.value??null:input.value;
      submit.disabled=true;try{const action=record.model.on?.submit;if(action&&action.kind!=='ask_model')throw Error('表单只能用于继续提问。');if(action)await this.action(record,'submit',values,true);else await this.options.askModel({v:1,node_id:record.id,event:'submit',prompt:p.label||'根据补充信息继续',values});}catch(error){this.announce(error.message);}finally{submit.disabled=false;}});c.append(form);
  }
}

export class MessageRenderer{
  constructor(container,options={}){this.container=container;this.options=options;this.parser=new StreamParser({limits:options.limits,data:options.data});this.parts=[];this.frame=0;this.markdownView=Object.create(null);this.container.classList.add('gu-message');}
  push(chunk){this.parser.push(chunk);this.parts=this.parser.snapshot();this.schedule();}
  finish(){this.parts=this.parser.finish();this.schedule();return this.parts;}
  update(parts){this.parts=parts;this.schedule();}
  schedule(){if(!this.frame)this.frame=requestAnimationFrame(()=>{this.frame=0;this.paint();});}
  paint(){
    const follow=this.options.beforeRender?.(),elements=[];this.rendered??=[];
    this.parts.forEach((part,index)=>{let r=this.rendered[index];if(!r||r.kind!==part.kind){r?.ui?.dispose();r={kind:part.kind,element:el('div',part.kind==='text'?'gu-text-part':'gu-ui-part')};this.rendered[index]=r;}
      if(part.kind==='text'&&r.text!==part.text){this.markdownView[index]??={};r.element.replaceChildren(markdown(part.text,{view:this.markdownView[index],changed:()=>this.options.onChange?.()}));r.text=part.text;}
      else if(part.kind==='ui'){if(r.ui)r.ui.update(part.spec,true);else r.ui=new UIRenderer(r.element,part.spec,{...this.options,snapshot:this.options.snapshots?.[index],onSave:this.options.onSave?value=>this.options.onSave(index,value):null});}
      elements.push(r.element);
    });
    while(this.rendered.length>this.parts.length)this.rendered.pop().ui?.dispose();replaceInOrder(this.container,elements);this.options.afterRender?.(follow);
  }
  snapshots(){return Object.fromEntries((this.rendered||[]).flatMap((r,i)=>r.ui?[[i,r.ui.snapshot()]]:[]));}
  dispose(){cancelAnimationFrame(this.frame);for(const r of this.rendered||[])r.ui?.dispose();this.container.replaceChildren();}
}
