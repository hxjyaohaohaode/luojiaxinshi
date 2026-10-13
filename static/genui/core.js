import {CATALOG} from './catalog.js';
import {safeClone,safeKey,pathParts,readPath,matches,bytes} from './security.js';
import {parseExpression,evaluateExpression} from './expression.js';
export {CATALOG,evaluateExpression};
const textValue=value=>value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);
export function resolve(value,state,data,depth=0,limits=CATALOG.limits){
  if(depth>limits.depth)throw Error('value_too_deep');
  if(!value||typeof value!=='object')return value;
  if(Object.keys(value).length===1){if('$bind'in value)return readPath(state,value.$bind);if('$ref'in value)return readPath(data,value.$ref);if('$expr'in value)return evaluateExpression(value.$expr,state,limits);}
  if(Array.isArray(value))return value.map(v=>resolve(v,state,data,depth+1,limits));
  const out=Object.create(null);for(const [key,item]of Object.entries(value))out[key]=resolve(item,state,data,depth+1,limits);return out;
}
export function validateAction(action){
  const clean=safeClone(action),schema=Object.hasOwn(CATALOG.actions,clean?.kind)?CATALOG.actions[clean.kind]:null;
  if(!schema||!matches(clean,schema))throw Error('invalid_action');
  if(clean.kind==='state')pathParts(clean.key);
  if(clean.kind==='host'&&!matches(clean.params||{},CATALOG.hostActions[clean.name]))throw Error('invalid_host_params');
  return clean;
}
function expressions(value,limits){
  if(!value||typeof value!=='object')return;
  if(Object.hasOwn(value,'$expr'))parseExpression(value.$expr,limits);
  for(const item of Object.values(value))expressions(item,limits);
}
export function validateNode(input,limits=CATALOG.limits){
  const node=safeClone(input,limits);if(!safeKey(node.id)||typeof node.type!=='string')throw Error('invalid_node_id');
  if(Object.keys(node).some(k=>!['op','id','type','props','children','on'].includes(k)))throw Error('invalid_node_field');
  const definition=Object.hasOwn(CATALOG.components,node.type)?CATALOG.components[node.type]:null;
  if(!definition)return {id:node.id,type:'Unknown',props:{text:typeof node.props?.fallback==='string'?node.props.fallback:'这部分展示方式暂不支持，请以文字说明为准。'},children:[],error:'unknown_component'};
  if(node.props!==undefined&&(!node.props||typeof node.props!=='object'||Array.isArray(node.props)))throw Error('invalid_props');
  const props=Object.assign(Object.create(null),definition.defaults,node.props||{});
  if(!matches(props,{type:'object',properties:definition.properties,required:definition.required,additionalProperties:false}))throw Error('invalid_props');
  if(props.bind!==undefined)pathParts(props.bind);
  expressions(props,limits);
  const children=node.children||[];if(!Array.isArray(children)||children.length>limits.nodes||children.some(id=>!safeKey(id))||(!definition.children&&children.length))throw Error('invalid_children');
  const on=node.on||Object.create(null);if(typeof on!=='object'||Array.isArray(on)||Object.keys(on).some(k=>!['click','change','submit'].includes(k)))throw Error('invalid_event');
  for(const action of Object.values(on))validateAction(action);
  return {id:node.id,type:node.type,props,children:[...children],on};
}
export class StateStore{
  constructor(initial={},limits=CATALOG.limits){this.limits=limits;this.values=Object.create(null);this.dirty=new Set();this.listeners=new Set();this.defaults(initial);}
  defaults(values){const safe=safeClone(values,this.limits);if(!safe||typeof safe!=='object'||Array.isArray(safe))throw Error('invalid_state');const keys=Object.keys(safe);if(keys.some(key=>!safeKey(key)))throw Error('invalid_state_key');if(new Set([...Object.keys(this.values),...keys]).size>this.limits.stateKeys)throw Error('state_limit');for(const key of keys)if(!this.dirty.has(key))this.values[key]=safe[key];}
  get(path){return readPath(this.values,path);}
  set(path,value){const parts=pathParts(path);let target=this.values;for(const key of parts.slice(0,-1)){if(!target||typeof target!=='object'||!Object.hasOwn(target,key))throw Error('missing_state');target=target[key];}
    const key=parts.at(-1);if(!Object.hasOwn(target,key))throw Error('missing_state');const next=safeClone(value,this.limits),old=target[key];
    if((old===null)!==(next===null)||Array.isArray(old)!==Array.isArray(next)||typeof old!==typeof next)throw Error('state_type_changed');
    target[key]=next;this.dirty.add(parts[0]);for(const callback of this.listeners)callback(path,next);
  }
  subscribe(callback){this.listeners.add(callback);return()=>this.listeners.delete(callback);}
  snapshot(){return safeClone(this.values,this.limits);}
}
export function normalize(block,limits=CATALOG.limits){
  const nodes=Object.create(null);for(const [id,node]of block.nodes)nodes[id]=safeClone(node,{...limits,depth:limits.depth+4});
  const ids=Object.keys(nodes),referenced=new Set(ids.flatMap(id=>nodes[id].children||[])),roots=ids.filter(id=>!referenced.has(id)),visited=new Set();let edges=0;
  const errors=[...block.errors];const issue=(code,id)=>{if(errors.length<50&&!errors.some(e=>e.code===code&&e.id===id))errors.push({code,id});};
  function walk(id,path=[]){
    if(visited.has(id))return;visited.add(id);const node=nodes[id],children=[];
    for(const child of node.children||[]){
      if(++edges>limits.nodes){issue('reference_limit',id);continue;}
      if(path.includes(child)||child===id){issue('cycle',id);continue;}
      if(path.length+1>=limits.depth){issue('depth_limit',child);continue;}
      if(visited.has(child)){issue('shared_child',child);continue;}
      children.push(child);if(nodes[child])walk(child,[...path,id]);else if(block.ended)issue('missing_child',child);
    }node.children=children;
  }
  for(const id of roots)walk(id);for(const id of ids)if(!visited.has(id)){roots.push(id);walk(id);}
  return {v:1,roots,nodes,state:block.store.snapshot(),data:safeClone(block.data,limits),complete:!!(block.ended&&block.closed),errors};
}
export class Block{
  constructor(limits=CATALOG.limits,data={}){this.limits=limits;this.nodes=new Map();this.store=new StateStore({},limits);this.data=safeClone(data,limits);this.errors=[];this.begun=false;this.ended=false;this.closed=false;this.size=0;this.count=0;}
  error(code,id){if(this.errors.length<50&&!this.errors.some(e=>e.code===code&&e.id===id))this.errors.push({code,...(id?{id}:{})});}
  apply(input,{trusted=false}={}){
    if(this.ended){this.error('after_end');return;}
    if(++this.count>this.limits.operations){this.error('operation_limit');return;}
    try{
      const op=safeClone(input,this.limits);if(!op||typeof op!=='object'||Array.isArray(op))throw Error('invalid_operation');
      const allowed={begin:['op','v'],state:['op','set'],data:['op','id','value'],node:['op','id','type','props','children','on'],patch:['op','id','props','children','on'],end:['op']}[op.op];
      if(!allowed||Object.keys(op).some(k=>!allowed.includes(k)))throw Error('invalid_operation');
      if(op.op==='begin'){if(this.begun||op.v!==1)throw Error('unsupported_version');this.begun=true;return;}
      if(!this.begun)throw Error('missing_begin');
      if(op.op==='state'){if(!op.set||Array.isArray(op.set)||typeof op.set!=='object')throw Error('invalid_state');this.store.defaults(op.set);}
      else if(op.op==='data'){if(!trusted)throw Error('untrusted_data');if(!safeKey(op.id))throw Error('invalid_data_id');this.data[op.id]=op.value;}
      else if(op.op==='node'||op.op==='patch'){
        let inputNode=op;if(op.op==='patch'){const old=this.nodes.get(op.id);if(!old)throw Error('patch_missing_node');inputNode={...old,...op,props:{...old.props,...(op.props||{})}};delete inputNode.error;}
        if(!this.nodes.has(op.id)&&this.nodes.size>=this.limits.nodes)throw Error('node_limit');
        const node=validateNode(inputNode,this.limits);this.nodes.set(node.id,node);if(node.error)this.error(node.error,node.id);
      }else if(op.op==='end')this.ended=true;
    }catch(error){const id=safeKey(input?.id)?input.id:undefined;this.error(error.message,id);if(input?.op==='node'&&id&&(this.nodes.has(id)||this.nodes.size<this.limits.nodes))this.nodes.set(id,{id,type:'Unknown',props:{text:'此部分界面未能通过校验，请以回答中的文字说明为准。'},children:[],error:error.message});}
  }
  line(line){this.size+=bytes(line)+1;if(this.size>this.limits.blockBytes){this.error('block_limit');return;}try{this.apply(JSON.parse(line));}catch{this.error('malformed_line');}}
  spec(){return normalize(this,this.limits);}
}
export class StreamParser{
  constructor({limits={},data={}}={}){this.limits={...CATALOG.limits,...limits};this.data=data;this.decoder=new TextDecoder();this.buffer='';this.parts=[];this.block=null;this.fence=null;this.size=0;this.raw='';this.stopped=false;}
  text(value){const last=this.parts.at(-1);if(last?.kind==='text')last.text+=value;else this.parts.push({kind:'text',text:value});}
  push(chunk){
    if(this.stopped)return;const size=typeof chunk==='string'?bytes(chunk):chunk.byteLength;
    if(this.size+size>this.limits.messageBytes){this.stopped=true;this.text('\n回复超过显示上限，已保留可读部分。\n');if(this.block)this.block.error('message_limit');return;}
    this.size+=size;const value=typeof chunk==='string'?chunk:this.decoder.decode(chunk,{stream:true});this.raw+=value;this.buffer+=value;
    let newline;while((newline=this.buffer.indexOf('\n'))>=0){const line=this.buffer.slice(0,newline).replace(/\r$/,'');this.buffer=this.buffer.slice(newline+1);this.line(line,true);}
  }
  line(line,newline){
    if(this.block){if(/^\s*```\s*$/.test(line)){this.block.closed=true;if(!this.block.ended)this.block.error('missing_end');this.block=null;}else if(line.trim())this.block.line(line);return;}
    if(!this.fence&&/^\s*```genui\s*$/.test(line)){
      if(this.parts.filter(p=>p.kind==='ui').length>=this.limits.blocks){this.fence='overflow';this.text('交互区块数量已达上限，以下为原始说明。\n');return;}
      const block=new Block(this.limits,this.data);this.parts.push({kind:'ui',block});this.block=block;return;
    }
    if(/^\s*```/.test(line)){if(this.fence&&/^\s*```\s*$/.test(line))this.fence=null;else if(!this.fence)this.fence='code';}
    this.text(line+(newline?'\n':''));
  }
  finish(){if(!this.stopped){const tail=this.decoder.decode();this.raw+=tail;this.buffer+=tail;if(this.buffer)this.line(this.buffer,false);this.buffer='';}if(this.block)this.block.error('incomplete');return this.snapshot();}
  snapshot(){const parts=this.parts.map(p=>p.kind==='text'?{kind:'text',text:p.text}:{kind:'ui',spec:p.block.spec()});if(this.buffer&&!this.block&&!/^\s*`/.test(this.buffer)){if(parts.at(-1)?.kind==='text')parts.at(-1).text+=this.buffer;else parts.push({kind:'text',text:this.buffer});}return parts;}
}
export function parseMessage(raw,options){const parser=new StreamParser(options);parser.push(raw);return parser.finish();}
export function blockMarkdown(spec,state=spec.state){
  const lines=[],seen=new Set();let count=0;
  const value=v=>textValue(v),cell=v=>value(v).replace(/\|/g,'\\|').replace(/\n/g,' ');
  const table=(columns,rows)=>{lines.push('| '+columns.map(c=>cell(c.label)).join(' | ')+' |','| '+columns.map(()=> '---').join(' | ')+' |',...rows.map(row=>'| '+columns.map(c=>cell(row?.[c.key])).join(' | ')+' |'));};
  function visit(id){if(seen.has(id)||++count>CATALOG.limits.nodes)return;seen.add(id);const node=spec.nodes[id];if(!node){lines.push('内容尚未完整接收。');return;}
    let p;try{p=resolve(node.props,state,spec.data);}catch{p=node.props||{};}
    const t=node.type;let bound;if(p.bind)try{bound=readPath(state,p.bind);}catch{}
    if(t==='Divider')lines.push('---');
    else if(t==='Heading')lines.push('#'.repeat(p.level||3)+' '+value(p.text));
    else if(t==='Stat')lines.push(`${value(p.label)}：${value(p.value)} ${value(p.unit)}`);
    else if(t==='Table'){if(p.label)lines.push(p.label);table(Array.isArray(p.columns)?p.columns:[],Array.isArray(p.rows)?p.rows:[]);}
    else if(t.endsWith('Chart')){lines.push(value(p.label));table([{key:'x',label:p.xLabel||'项目'},{key:'y',label:(p.yLabel||'数值')+(p.unit?'（'+p.unit+'）':'')}],p.data||[]);}
    else if(t==='Compare'){table([{key:'label',label:'选项'},...(p.dimensions||[]).map(d=>({key:d,label:d}))],(p.items||[]).map(item=>({...item.values,label:item.label})));}
    else if(t==='Diagram'){for(const n of p.nodes||[])lines.push('- '+n.label);for(const e of p.edges||[])lines.push(`${p.nodes?.find(n=>n.id===e.from)?.label||e.from} → ${p.nodes?.find(n=>n.id===e.to)?.label||e.to}${e.label?'：'+e.label:''}`);}
    else if(t==='Image')lines.push(value(p.alt),value(p.caption));
    else if(t==='Code'){const fence='`'.repeat(Math.max(3,...(value(p.text).match(/`+/g)||[]).map(s=>s.length+1)));lines.push(fence+(p.language||''),value(p.text),fence);}
    else if(t==='Form'){lines.push(value(p.label));for(const f of p.fields||[])lines.push('- '+f.label+(f.required?'（必填）':'')+(f.options?'：'+f.options.map(o=>o.label).join(' / '):''));}
    else if(t==='Progress')lines.push(value(p.label)+'：'+value(p.value)+' / '+value(p.max));
    else if(t==='HostView')lines.push(value(p.title)||({campus_schedule:'查看工作台日程',material_index:'查看本次材料',messenger:'珞珈小信使'}[p.view]||'工作台入口'));
    else{
      if(p.title||p.label)lines.push(value(p.title||p.label));if(p.text)lines.push(value(p.text));if(p.description)lines.push(value(p.description));
      if(Array.isArray(p.items))lines.push(...p.items.map((item,index)=>{
        const mark=t==='Checklist'?(Array.isArray(bound)&&bound.includes(item.id)?'- [x] ':'- [ ] '):t==='Steps'?(index+1)+'. ':'- ';
        return mark+value(item.label||item.title||item.text)+(item.value!==undefined?'：'+value(item.value):'')+(item.description?' — '+value(item.description):'')+(item.date?' · '+value(item.date):'');
      }));
      if(bound!==undefined&&t!=='Checklist')lines.push(value(Array.isArray(p.options)?p.options.find(o=>o.value===bound)?.label??bound:bound)+(p.unit?' '+p.unit:''));
      if(p.labels)lines.push(p.labels.join(' / '));
    }
    for(const child of node.children||[])visit(child);
  }
  for(const root of spec.roots)visit(root);if(!spec.complete)lines.push('（界面未完整接收，以上为已收到的内容。）');return lines.filter(Boolean).join('\n\n');
}
export function messageMarkdown(parts){return parts.map(p=>p.kind==='text'?p.text:blockMarkdown(p.spec)).join('\n\n');}
