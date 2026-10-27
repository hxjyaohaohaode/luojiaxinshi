import {copyCode} from '../reference-interactions.js';
import {safeUrl,safeClone} from './security.js';
export const string=value=>value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);
export function el(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=string(text);return node;}
export function button(label,run,className='gu-button'){const node=el('button',className,label);node.type='button';if(run)node.addEventListener('click',run);return node;}
export function replaceInOrder(parent,children){const wanted=new Set(children);for(const child of [...parent.childNodes])if(!wanted.has(child))child.remove();children.forEach((child,index)=>{if(parent.childNodes[index]!==child)parent.insertBefore(child,parent.childNodes[index]||null);});}
export function download(data,format='json'){
  const clean=safeClone(data);let body,type;
  if(format==='csv'){
    if(!Array.isArray(clean)||clean.some(row=>!row||Array.isArray(row)||typeof row!=='object'))throw Error('导出内容不是表格。');
    const keys=[...new Set(clean.flatMap(row=>Object.keys(row)))].slice(0,40);
    const cell=value=>{let text=string(value);if(/^[\s]*[=+\-@]/.test(text)||/^[\t\r]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';};
    body='\uFEFF'+[keys,...clean.map(row=>keys.map(key=>row[key]))].map(row=>row.map(cell).join(',')).join('\r\n');type='text/csv;charset=utf-8';
  }else{body=JSON.stringify(clean,null,2);type='application/json';}
  const url=URL.createObjectURL(new Blob([body],{type})),link=el('a');link.href=url;link.download='campus-answer.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function linkedText(text,parent){
  const pattern=/https?:\/\/[^\s<>"'`\[\]，。；！？、（）]+/g;let cursor=0;
  for(const match of text.matchAll(pattern)){
    let value=match[0].replace(/[.,;:!?]+$/,'');
    // Keep balanced parentheses in URLs, but leave sentence punctuation outside.
    while(value.endsWith(')')&&(value.match(/\)/g)||[]).length>(value.match(/\(/g)||[]).length)value=value.slice(0,-1);
    parent.append(document.createTextNode(text.slice(cursor,match.index)));
    const url=safeUrl(value,{hosts:null});
    if(url){const link=el('a','',value);link.href=url;link.rel='noopener noreferrer';link.target='_blank';parent.append(link);}
    else parent.append(document.createTextNode(value));
    parent.append(document.createTextNode(match[0].slice(value.length)));cursor=match.index+match[0].length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}
export function inline(text,parent){
  text=string(text);
  const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g;let cursor=0;
  for(const match of text.matchAll(pattern)){
    linkedText(text.slice(cursor,match.index),parent);const raw=match[0];let node;
    if(raw.startsWith('`'))node=el('code','gu-inline-code',raw.slice(1,-1));
    else if(raw.startsWith('**')){node=el('strong');linkedText(raw.slice(2,-2),node);}
    else{const cut=raw.indexOf(']('),url=safeUrl(raw.slice(cut+2,-1),{hosts:null,mailto:true});node=el(url?'a':'span','',raw.slice(1,cut));if(url){node.href=url;node.rel='noopener noreferrer';node.target='_blank';}}
    parent.append(node);cursor=match.index+raw.length;
  }
  linkedText(text.slice(cursor),parent);
}
export function dataTable(props,{view={},changed=()=>{}}={}){
  const box=el('div','gu-table-wrap'),table=el('table','gu-table'),caption=el('caption','',props.label||'数据'),head=el('thead'),body=el('tbody'),row=el('tr');
  const columns=props.columns||[],source=props.rows||[];table.append(caption,head,body);head.append(row);box.append(table);
  const pager=el('div','gu-pager'),status=el('span','gu-muted');let sortButtons=[];
  function paint(){
    const pageSize=props.pageSize||10;view.page=Math.max(0,Math.min(Number(view.page)||0,Math.max(0,Math.ceil(source.length/pageSize)-1)));
    const rows=source.map((value,index)=>({value,index}));if(view.sort)rows.sort((a,b)=>{const av=a.value[view.sort],bv=b.value[view.sort];return ((typeof av==='number'&&typeof bv==='number'?av-bv:string(av).localeCompare(string(bv),'zh-CN',{numeric:true}))*(view.desc?-1:1))||a.index-b.index;});
    body.replaceChildren();for(const {value} of rows.slice(view.page*pageSize,(view.page+1)*pageSize)){const tr=el('tr');for(const col of columns){const td=el('td');inline(value[col.key],td);td.dataset.label=col.label;tr.append(td);}body.append(tr);}
    if(!rows.length){const td=el('td','gu-muted','暂无数据');td.colSpan=Math.max(1,columns.length);body.append(el('tr'));body.firstChild.append(td);}
    sortButtons.forEach(({th,b,col})=>{th.setAttribute('aria-sort',view.sort===col.key?(view.desc?'descending':'ascending'):'none');b.textContent=col.label+(col.unit?' · '+col.unit:'')+(view.sort===col.key?(view.desc?' ↓':' ↑'):' ↕');});
    status.textContent=`${source.length} 条 · ${view.page+1}/${Math.max(1,Math.ceil(source.length/pageSize))} 页`;previous.disabled=view.page===0;next.disabled=(view.page+1)*pageSize>=source.length;pager.hidden=source.length<=pageSize;
  }
  for(const col of columns){const th=el('th');th.scope='col';if(col.sortable!==false){const b=button(col.label,()=>{view.desc=view.sort===col.key?!view.desc:false;view.sort=col.key;view.page=0;paint();changed();},'gu-sort');th.append(b);sortButtons.push({th,b,col});}else th.textContent=col.label;row.append(th);}
  const previous=button('上一页',()=>{view.page--;paint();changed();}),next=button('下一页',()=>{view.page++;paint();changed();});pager.append(previous,status,next);box.append(pager);paint();return box;
}
export function markdown(text,{enhance=true,streaming=false,view={},changed=()=>{}}={}){
  const host=el('div','gu-markdown'),lines=String(text).split('\n');let i=0,count=0;
  const cellLine=line=>line.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(v=>v.trim().replace(/\\\|/g,'|'));
  while(i<lines.length&&count++<1000){
    const line=lines[i];if(!line.trim()){i++;continue;}
    if(/^\s*```/.test(line)){
      const language=line.trim().slice(3),code=[];i++;while(i<lines.length&&!/^\s*```\s*$/.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;
      const box=el('div','gu-code'),pre=el('pre'),content=el('code','',code.join('\n'));pre.append(content);const copy=button('复制代码',event=>copyCode(event.currentTarget,content.textContent));copy.disabled=streaming;copy.dataset.codeCopy='';box.append(el('span','gu-muted',language),copy,pre);host.append(box);continue;
    }
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i+1])){
      const labels=cellLine(line),rows=[];i+=2;while(i<lines.length&&lines[i].includes('|')&&rows.length<1000){const cells=cellLine(lines[i++]);rows.push(Object.fromEntries(labels.map((_,n)=>['c'+n,cells[n]||''])));}
      const key='table'+count;view[key]??=Object.create(null);host.append(dataTable({columns:labels.map((label,n)=>({label,key:'c'+n,sortable:enhance})),rows,pageSize:streaming?1000:10},{view:view[key],changed}));continue;
    }
    if(/^\s*[-*] \[[ xX]\] /.test(line)){
      const list=el('ul','gu-checklist');while(i<lines.length&&/^\s*[-*] \[[ xX]\] /.test(lines[i])){const match=lines[i].match(/^\s*[-*] \[([ xX])\] (.*)$/),key='check'+i,input=el('input'),label=el('label','gu-check'),li=el('li');input.type='checkbox';input.checked=view[key]??(match[1].toLowerCase()==='x');input.disabled=!enhance;input.addEventListener('change',()=>{view[key]=input.checked;changed();});const span=el('span');inline(match[2],span);label.append(input,span);li.append(label);list.append(li);i++;}host.append(list);continue;
    }
    if(/^\s*(?:\d+\.|[-*]) /.test(line)){
      const ordered=/^\s*\d+\./.test(line),list=el(ordered?'ol':'ul',ordered&&enhance?'gu-steps':'gu-list');
      while(i<lines.length&&(ordered?/^\s*\d+\. /:/^\s*[-*] /).test(lines[i])){const li=el('li');inline(lines[i++].replace(/^\s*(?:\d+\.|[-*]) /,''),li);list.append(li);}host.append(list);continue;
    }
    const heading=line.match(/^(#{1,4}) (.*)$/),node=el(heading?'h'+Math.min(4,heading[1].length+1):line.startsWith('> ')?'blockquote':'p');inline(heading?heading[2]:line.replace(/^> /,''),node);host.append(node);i++;
  }
  if(i<lines.length){const more=button('展开剩余内容',()=>{const rest=markdown(lines.slice(i).join('\n'),{enhance,view:view.rest??(view.rest={}),changed});more.replaceWith(rest);changed();});host.append(more);}return host;
}
