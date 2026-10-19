import {el,button} from './genui/dom.js';
export function installDataTransfer({api,toast,onImported}){
 document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='data-import-form')return;event.preventDefault();const submit=form.querySelector('[type=submit]'),file=form.elements.backup.files[0],preview=form.querySelector('#data-import-preview');if(!file||submit.disabled)return;submit.disabled=true;preview.replaceChildren();try{
  if(file.size>10*1024*1024)throw Error('请选择不超过 10 MB 的本系统 JSON 备份。');
  const data=JSON.parse(await file.text()),result=await api('/import',{method:'POST',json:{data}});if(!form.isConnected)return;
  const labels={notices:'通知',conversations:'对话',arrangements:'日程',source_catalog:'来源',memory_projects:'记忆项目',memories:'个人记忆'};preview.append(el('p','',Object.entries(result.counts).map(([key,value])=>`${value} 份${labels[key]}`).join(' · ')));
  const list=el('ul','small muted');for(const text of result.warnings)list.append(el('li','',text));preview.append(list);
  const label=el('label','check'),apply=el('input');apply.type='checkbox';label.append(apply,document.createTextNode('同时应用备份中的个人条件与回答偏好（替换当前设置）'));preview.append(label);
  const confirm=button('确认导入',async()=>{confirm.disabled=true;submit.disabled=true;try{const saved=await api('/import',{method:'POST',json:{data,digest:result.digest,confirm:true,apply_profile:apply.checked}});if(form.isConnected){preview.replaceChildren(el('p','',`已新增 ${saved.added} 份记录，跳过 ${saved.skipped} 份重复记录。`));}toast('导入已完成，现有记录保留。');await onImported();}catch(error){toast(error.message,true);confirm.disabled=false;}finally{submit.disabled=false;}},'button primary');preview.append(confirm);
 }catch(error){preview.textContent=error instanceof SyntaxError?'文件不是有效 JSON，请重新选择本系统导出的文件。':error.message;}finally{submit.disabled=false;}});
 document.addEventListener('change',event=>{if(event.target.id==='data-import-file')document.querySelector('#data-import-preview')?.replaceChildren();});
}
