import {el,button,markdown,string} from './dom.js';

// These are content and interaction primitives, never complete page templates.
export function prose(p,options={}){
  const text=markdown(p.text||'',options);text.classList.add('gu-prose-text');
  const wrap=el(p.variant==='quote'?'figure':'div','gu-prose-content');wrap.dataset.variant=p.variant||'body';
  if(p.variant==='quote'){const quote=el('blockquote');quote.append(text);wrap.append(quote);if(p.attribution)wrap.append(el('figcaption','',p.attribution));}
  else wrap.append(text);
  return wrap;
}

export function choice(renderer,record){
  const {props:p,content:c}=record,values=new Set(),options=p.options||[];
  for(const option of options){const key=JSON.stringify(option.value);if(values.has(key))throw Error('duplicate_choice');values.add(key);}
  if(!options.length){c.append(el('p','gu-muted','暂无可选项'));return;}
  if(renderer.get(record)!==null&&!options.some(o=>o.value===renderer.get(record)))throw Error('invalid_choice_state');
  const field=el('fieldset','gu-choice-field'),legend=el('legend','',p.label),group=el('div','gu-choice-options');
  group.dataset.layout=p.layout||'inline';group.setAttribute('role','radiogroup');group.setAttribute('aria-label',p.label);field.append(legend,group);c.append(field);
  const controls=[];
  const select=(index,focus=false)=>{try{renderer.set(record,options[index].value);record.refresh();if(focus)controls[index].focus();renderer.action(record,'change');}catch{renderer.announce('这个选项暂不可用，请重试。');}};
  options.forEach((option,index)=>{
    const b=button('',()=>select(index),'gu-choice-option');b.setAttribute('role','radio');b.dataset.field='choice-'+index;
    b.append(el('span','gu-choice-label',option.label));if(option.description)b.append(el('span','gu-choice-description',option.description));
    b.addEventListener('keydown',event=>{
      let next;if(['ArrowRight','ArrowDown'].includes(event.key))next=(index+1)%options.length;
      else if(['ArrowLeft','ArrowUp'].includes(event.key))next=(index-1+options.length)%options.length;
      else if(event.key==='Home')next=0;else if(event.key==='End')next=options.length-1;else return;
      event.preventDefault();select(next,true);
    });group.append(b);controls.push(b);
  });
  record.refresh=()=>{const value=renderer.get(record),index=options.findIndex(o=>o.value===value);controls.forEach((b,i)=>{const selected=i===index;b.setAttribute('aria-checked',String(selected));b.tabIndex=selected||index<0&&i===0?0:-1;});};record.refresh();
}

export function comparison(p){
  if(!(p.items||[]).length)return el('p','gu-muted','暂无对比项');
  if(p.format==='columns'){
    const grid=el('div','gu-compare-grid');for(const item of p.items){const section=el('section','gu-compare-card');section.append(el('h4','',item.label));
      for(const dimension of p.dimensions||[]){const row=el('div','gu-compare-entry');row.append(el('strong','gu-compare-dimension',dimension),markdown(string(item.values[dimension]??'未提供')));section.append(row);}grid.append(section);}
    return grid;
  }
  const wrap=el('div','gu-compare-wrap'),table=el('table','gu-compare-matrix'),head=el('thead'),header=el('tr'),dimension=el('th','','比较维度');dimension.scope='col';header.append(dimension);
  table.append(el('caption','gu-visually-hidden',p.label||'内容对照'));
  for(const item of p.items){const th=el('th','',item.label);th.scope='col';header.append(th);}head.append(header);table.append(head);
  const body=el('tbody');for(const dimension of p.dimensions||[]){const row=el('tr'),title=el('th','',dimension);title.scope='row';row.append(title);
    for(const item of p.items){const cell=el('td'),label=el('span','gu-compare-source',item.label);label.setAttribute('aria-hidden','true');cell.append(label,markdown(string(item.values[dimension]??'未提供')));row.append(cell);}body.append(row);}
  table.append(body);wrap.append(table);return wrap;
}
