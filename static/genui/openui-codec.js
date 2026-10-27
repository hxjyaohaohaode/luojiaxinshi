// Authored code is data here. Execution belongs exclusively to sandbox-runtime.js.
export function validateOpenUI(value){
  if(!value||typeof value!=='object'||Array.isArray(value)||value.renderer!=='open_generative_ui')throw Error('openui_renderer');
  const allowed=['renderer','title','initialHeight','placeholderMessages','css','html','jsFunctions','jsExpressions'];
  if(Object.keys(value).some(k=>!allowed.includes(k))||typeof value.title!=='string'||!value.title.trim()||value.title.length>100)throw Error('openui_fields');
  const ui={initialHeight:240,placeholderMessages:[],css:'',jsFunctions:'',jsExpressions:[],...value};
  if(!Number.isInteger(ui.initialHeight)||ui.initialHeight<80||ui.initialHeight>1600)throw Error('openui_height');
  if(!Array.isArray(ui.html)||!ui.html.length||ui.html.length>100||ui.html.some(s=>typeof s!=='string')||!ui.html.join('').trim())throw Error('openui_html');
  if(typeof ui.css!=='string'||ui.css.length>24000||typeof ui.jsFunctions!=='string'||ui.jsFunctions.length>32000)throw Error('openui_code');
  if(!Array.isArray(ui.jsExpressions)||ui.jsExpressions.length>40||ui.jsExpressions.some(s=>typeof s!=='string'||s.length>16000))throw Error('openui_expressions');
  if(!Array.isArray(ui.placeholderMessages)||ui.placeholderMessages.length>4||ui.placeholderMessages.some(s=>typeof s!=='string'||s.length>160))throw Error('openui_placeholders');
  if(new TextEncoder().encode(JSON.stringify(ui)).length>131072)throw Error('openui_size_limit');
  return ui;
}
export function openUIPlainText(ui){
  return (ui?.html||[]).join('').replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,'').replace(/<[^>]+>/g,'\n').replace(/&#(x[0-9a-f]+|\d+);/gi,(_,s)=>{const n=s[0].toLowerCase()==='x'?parseInt(s.slice(1),16):Number(s);return n<=0x10ffff?String.fromCodePoint(n):'';}).replace(/&(amp|lt|gt|quot|apos|nbsp);/g,(_,s)=>({amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '})[s]).split('\n').map(s=>s.trim()).filter(Boolean).join('\n');
}
export function previewSpec(content){return {v:1,roots:[],nodes:{},state:{controls:{}},data:{},complete:false,errors:[],sandbox:content,preview:true};}
export function applyPreview(previous,patch){
  if(!patch||typeof patch!=='object')throw Error('openui_preview');
  const next=previous?{...previous,html:[...previous.html],jsExpressions:[...(previous.jsExpressions||[])]}:{renderer:'open_generative_ui',css:'',html:[],jsFunctions:'',jsExpressions:[],generating:true};
  if(patch.reset){next.revision=(previous?.revision||0)+1;next.css='';next.html=[];next.jsFunctions='';next.jsExpressions=[];next.cssComplete=false;next.htmlComplete=false;next.localReady=false;next.jsFunctionsComplete=false;next.jsExpressionsComplete=false;}
  if(patch.css!==undefined){if(typeof patch.css!=='string'||patch.css.length>24000)throw Error('openui_preview_css');next.css+=patch.css;}
  if(patch.html!==undefined){
    if(!Array.isArray(patch.html)||patch.html.length>100)throw Error('openui_preview_html');
    for(const item of patch.html){if(!item||!Number.isInteger(item.index)||item.index<0||item.index>=100||typeof item.text!=='string'||item.text.length>131072)throw Error('openui_preview_html');while(next.html.length<=item.index)next.html.push('');next.html[item.index]+=item.text;}
  }
  if(patch.jsFunctions!==undefined){if(typeof patch.jsFunctions!=='string'||patch.jsFunctions.length>32000)throw Error('openui_preview_js');next.jsFunctions=patch.jsFunctions;}
  if(patch.jsExpressions!==undefined){if(!Array.isArray(patch.jsExpressions)||patch.jsExpressions.length>40)throw Error('openui_preview_js');for(const item of patch.jsExpressions){if(!item||!Number.isInteger(item.index)||item.index<0||item.index>=40||typeof item.text!=='string'||item.text.length>16000)throw Error('openui_preview_js');next.jsExpressions[item.index]=item.text;}}
  for(const key of ['cssComplete','htmlComplete','jsFunctionsComplete','jsExpressionsComplete','localReady'])if(patch[key]!==undefined){if(typeof patch[key]!=='boolean')throw Error('openui_preview_flags');next[key]=patch[key];}
  if(patch.title!==undefined){if(typeof patch.title!=='string'||patch.title.length>100)throw Error('openui_preview_title');next.title=patch.title;}
  if(patch.initialHeight!==undefined){if(!Number.isInteger(patch.initialHeight)||patch.initialHeight<80||patch.initialHeight>1600)throw Error('openui_preview_height');next.initialHeight=patch.initialHeight;}
  if(new TextEncoder().encode(JSON.stringify(next)).length>150000)throw Error('openui_preview_limit');
  return next;
}
export class OpenUIBlock{
  constructor(){this.lines=[];this.errors=[];this.size=0;this.closed=false;this.ended=true;}
  error(code){if(!this.errors.some(e=>e.code===code))this.errors.push({code});}
  line(line){this.size+=new TextEncoder().encode(line).length;if(this.size>131072)this.error('openui_size_limit');else this.lines.push(line);}
  spec(){let sandbox=null;const errors=[...this.errors];try{sandbox=validateOpenUI(JSON.parse(this.lines.join('\n')));}catch{if(this.closed)errors.push({code:'openui_invalid_document'});}return {...previewSpec(sandbox),preview:false,complete:this.closed&&!!sandbox&&!errors.length,errors};}
}
