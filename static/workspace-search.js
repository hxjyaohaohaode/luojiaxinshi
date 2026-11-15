import {brandMotion} from './motion.js';
import {setDisclosureVisible} from './reference-interactions.js';
export const materialFormats='.pdf,.docx,.xlsx,.pptx,.odt,.ods,.odp,.doc,.xls,.ppt,.txt,.md,.csv,.tsv,.json,.jsonl,.xml,.yaml,.yml,.log,.ini,.toml,.sql,.py,.js,.ts,.css,.c,.cpp,.h,.java,.tex,.ics,.eml,.html,.htm,.svg,.rtf,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.mp4,.webm,.mov,.avi,.wmv,.mp3,.wav,.m4a,.ogg,.flac,.zip';
export function searchControls({id,esc,icon,scope='materials',kinds=[]}){
 const history=scope==='history';
 const label=history?'搜索历史对话':scope==='sources'?'搜索通知来源':'搜索本次材料';
 const placeholder=history?'搜标题、消息或材料':scope==='sources'?'搜索来源':'搜索材料';
 const filterIcon='<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M7 12h10M10 17h4"/></svg>';
 const kindOptions=history?[['with-materials','有材料'],['without-materials','无材料']]:kinds;
 const kindTitle=history?'材料':'类型';
 const kindDefault=history?'不限材料':'全部类型';
 return `<div class="record-search" data-search-host="${id}">
   <div class="record-search-line">
     <label class="search-input-wrap">${icon('search')}<input id="${id}-search" type="search" placeholder="${placeholder}" aria-label="${label}" autocomplete="off" maxlength="200"><button type="button" data-search-clear aria-label="清空关键词">${icon('close')}</button></label>
     <button type="button" class="search-tool" data-search-mode="file" aria-label="用图片或文件检索" title="用图片或文件检索" aria-pressed="false" aria-expanded="false" aria-controls="${id}-reference">${icon('upload')}</button>
     <button type="button" class="search-tool" data-search-mode="filter" aria-label="筛选" title="筛选" aria-pressed="false" aria-expanded="false" aria-controls="${id}-filters">${filterIcon}<span data-filter-count hidden></span></button>
   </div>
   <div class="search-reference" id="${id}-reference" hidden>
     <button type="button" class="button small" data-search-pick>${icon('upload')} 选择图片或文字文件</button>
     <input type="file" data-search-file accept="${materialFormats.replace(',.zip','')}" hidden><span class="search-file-name small muted"></span>
   </div>
   <div class="search-filters" id="${id}-filters" hidden>
     <label>${kindTitle}<select data-search-kind aria-label="${label}${kindTitle}"><option value="">${kindDefault}</option>${kindOptions.map(([v,t])=>`<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></label>
     <label>时间<select data-search-period aria-label="${label}时间"><option value="all">全部时间</option><option value="week">最近 7 天</option><option value="month">最近 30 天</option>${history?'<option value="quarter">最近 90 天</option>':''}</select></label>
     ${scope==='materials'?'<label>读取状态<select data-search-status aria-label="材料读取状态"><option value="">全部状态</option><option value="ok">已读取</option><option value="review">需核对</option><option value="failed">读取失败</option></select></label>':''}
     ${history?`<label>范围<select data-search-field aria-label="关键词匹配范围"><option value="">全部内容</option><option value="title">对话标题</option><option value="messages">消息正文</option><option value="materials">材料名称与内容</option></select></label>
       <label>排序<select data-search-sort aria-label="对话排序"><option value="">匹配优先</option><option value="recent">最近更新</option><option value="oldest">最早更新</option></select></label>`:''}
   </div>
   <div class="search-feedback small muted" role="status" aria-live="polite"></div>
 </div>`;
}
const filterKeys=['kind','period','status','field','sort'];
export class WorkspaceSearch{
 constructor(host,{api,scope,conversationId,onResult,onError}){
  this.host=host;this.options={api,scope,conversationId,onResult,onError};this.sequence=0;this.file=null;this.mode='text';this.reference=null;this.pendingReference=null;
  this.disposed=false;this.request=null;this.syncControls();
  host.addEventListener('input',e=>{if(!e.isComposing&&e.target.matches('input[type=search]'))this.schedule();});
  host.addEventListener('compositionend',e=>{if(e.target.matches('input[type=search]'))this.schedule();});
  host.addEventListener('change',e=>{if(e.target.matches('[data-search-file]')){this.file=e.target.files[0]||null;host.querySelector('.search-file-name').textContent=this.file?.name||'';this.run();}else if(e.target.matches('select'))this.run();});
  host.addEventListener('click',e=>{
   const control=e.target.closest('[data-search-mode]');
   if(control){
    const kind=control.dataset.searchMode,panel=host.querySelector(kind==='file'?'.search-reference':'.search-filters'),open=control.getAttribute('aria-expanded')!=='true';
    setDisclosureVisible(panel,open);control.setAttribute('aria-expanded',String(open));control.setAttribute('aria-pressed',String(open));
    if(kind==='file'){this.mode=open?'file':'text';if(this.file)this.run();}
   }
   if(e.target.closest('[data-search-clear]'))this.clearQuery();
   if(e.target.closest('[data-search-reset]'))this.clear();
   if(e.target.closest('[data-search-retry]'))this.run();
   if(e.target.closest('[data-search-pick]'))host.querySelector('[data-search-file]').click();
   const remove=e.target.closest('[data-search-remove]');
   if(remove){
    const key=remove.dataset.searchRemove,keys=[...host.querySelectorAll('[data-search-remove]')].map(b=>b.dataset.searchRemove),index=keys.indexOf(key);
    if(key==='file')this.clearFile();else host.querySelector(`[data-search-${key}]`).selectedIndex=0;
    this.syncControls();const remaining=[...host.querySelectorAll('[data-search-remove]')];(remaining[Math.min(index,remaining.length-1)]||host.querySelector('[data-search-mode=filter]')).focus({preventScroll:true});this.run();
   }
  });
  host.addEventListener('keydown',e=>{
   if(e.isComposing||e.keyCode===229)return;
   if(e.target.matches('input[type=search]')&&e.key==='Enter'){e.preventDefault();this.run();}
   else if(e.target.matches('input[type=search]')&&e.key==='Escape'&&e.target.value){e.preventDefault();e.stopPropagation();this.clearQuery();}
  });
 }
 syncControls(){
  const host=this.host,clear=host.querySelector('[data-search-clear]');clear.hidden=!host.querySelector('input[type=search]').value;clear.setAttribute('aria-label','清空关键词');
  let tags=host.querySelector('[data-search-tags]');if(!tags){tags=document.createElement('div');tags.className='search-active-filters';tags.dataset.searchTags='';tags.setAttribute('aria-label','已选筛选条件');host.querySelector('.search-feedback').before(tags);}
  const values=filterKeys.flatMap(key=>{
   const select=host.querySelector('[data-search-'+key+']');
   return select?.value&&select.value!=='all'?[{key,text:select.selectedOptions[0].textContent}]:[];
  });
  if(this.mode==='file'&&this.file)values.push({key:'file',text:this.file.name});
  const signature=JSON.stringify(values);if(tags.dataset.signature===signature)return;tags.dataset.signature=signature;tags.hidden=!values.length;tags.replaceChildren();
  for(const {key,text} of values){const button=document.createElement('button');button.type='button';button.className='search-filter-chip';button.dataset.searchRemove=key;button.setAttribute('aria-label','移除筛选：'+text);button.title=text;const label=document.createElement('span');label.textContent=text;const close=document.createElement('span');close.textContent='×';close.setAttribute('aria-hidden','true');button.append(label,close);tags.append(button);}
  if(values.length){const reset=document.createElement('button');reset.type='button';reset.className='search-filter-reset';reset.dataset.searchReset='';reset.textContent='清空全部';tags.append(reset);}
 }
 schedule(){clearTimeout(this.timer);this.sequence++;this.request?.abort();this.syncControls();this.timer=setTimeout(()=>this.run(),250);}
 hasFilters(){return !!this.host.querySelector('input[type=search]').value.trim()||[...this.host.querySelectorAll('select')].some(s=>s.value&&s.value!=='all')||this.mode==='file'&&!!this.file;}
 clearFile(){this.file=null;this.reference=null;this.host.querySelector('[data-search-file]').value='';this.host.querySelector('.search-file-name').textContent='';}
 clearQuery(){this.host.querySelector('input[type=search]').value='';this.run();this.host.querySelector('input[type=search]').focus();}
 clear(){this.host.querySelector('input[type=search]').value='';this.clearFile();this.host.querySelectorAll('select').forEach(s=>s.selectedIndex=0);this.run();this.host.querySelector('input[type=search]').focus();}
 async run(){
  clearTimeout(this.timer);if(this.disposed||!this.host.isConnected)return;
  this.request?.abort();const controller=new AbortController();this.request=controller;this.syncControls();const sequence=++this.sequence,feedback=this.host.querySelector('.search-feedback');
  const {api,scope,conversationId,onResult,onError}=this.options,data=new FormData();
  data.set('scope',scope);data.set('query',this.host.querySelector('input[type=search]').value);
  for(const key of filterKeys){
   const select=this.host.querySelector('[data-search-'+key+']');
   if(select)data.set(key,select.value);
  }
  const count=[...this.host.querySelectorAll('select')].filter(s=>s.value&&s.value!=='all').length,badge=this.host.querySelector('[data-filter-count]');badge.textContent=count;badge.hidden=!count;
  const cid=conversationId?.();if(scope==='materials'&&!cid){feedback.textContent='';this.host.removeAttribute('aria-busy');onResult({items:[],query:'',total:0});return;}if(cid)data.set('conversation_id',cid);
  this.host.setAttribute('aria-busy','true');
  feedback.innerHTML=brandMotion('search','search-progress')+'<span>正在检索…</span>';
  try{
   let reference=null;
   if(this.mode==='file'&&this.file){
    const file=this.file;if(file.size>5*1024*1024)throw Error('检索文件最多 5 MB，请换一份更小的文件。');
    if(this.reference?.file===file)reference=this.reference.result;
    else{
     if(this.pendingReference?.file!==file){const request=new FormData();for(const [key,value]of data)request.set(key,value);request.set('query','');request.set('file',file);this.pendingReference={file,promise:api('/workspace-search',{method:'POST',body:request})};}
     const pending=this.pendingReference;
     try{reference=await pending.promise;if(this.file===file)this.reference={file,result:reference};}finally{if(this.pendingReference===pending)this.pendingReference=null;}
    }
    if(sequence!==this.sequence||!this.host.isConnected)return;
    data.set('query',(data.get('query')+' '+reference.query).trim());
   }
   const result=await api('/workspace-search',{method:'POST',body:data,signal:controller.signal});if(sequence!==this.sequence||!this.host.isConnected)return;
   feedback.textContent=this.hasFilters()?`${result.total} 项匹配`:'';if(reference?.query)feedback.textContent+=` · ${reference.query.slice(0,80)}`;onResult(result);
  }
  catch(error){if(sequence!==this.sequence||!this.host.isConnected||controller.signal.aborted)return;feedback.textContent=error.message+' ';const retry=document.createElement('button');retry.type='button';retry.className='search-filter-reset';retry.dataset.searchRetry='';retry.textContent='重试';feedback.append(retry);onError?.(error.message);}
  finally{if(sequence===this.sequence&&this.host.isConnected)this.host.removeAttribute('aria-busy');}
 }
 dispose(){clearTimeout(this.timer);this.sequence++;this.disposed=true;this.request?.abort();}
}
export function materialTree(sources,{esc,icon,sourceStatus,cid,processing=false,matches=null}){
 const root={folders:new Map(),files:[],path:''};
 for(const source of sources){const parts=(source.path||source.name).split('/');let node=root;for(const part of parts.slice(0,-1)){if(!node.folders.has(part))node.folders.set(part,{folders:new Map(),files:[],path:node.path?node.path+'/'+part:part});node=node.folders.get(part);}node.files.push(source);}
 function file(source){
  const {id,name,kind,status,path,size}=source;
  const image=status!=='failed'&&['png','jpg','jpeg','webp','gif','bmp','tif','tiff'].includes(kind);
  const title=esc(path||name),snippet=matches?.get(id)?.snippet;
  const preview=image
   ?`<img class="material-thumbnail" src="/api/conversations/${encodeURIComponent(cid)}/sources/${encodeURIComponent(id)}/download?preview=true" alt="" loading="lazy" decoding="async">
     <span class="material-thumbnail-fallback" hidden>${icon('doc')} 打开图片原件</span>`
   :`<span class="material-file-icon" aria-hidden="true">${icon(kind==='zip'?'folder':'doc')}</span>
     <span class="material-file-meta"><strong>${esc(name)}</strong><small class="${status==='failed'?'text-error':''}">${esc(kind==='text'?'文字':kind.toUpperCase())} · ${sourceStatus(source)}${size?` · ${formatSize(size)}`:''}</small></span>`;
  return `<div class="material-item${image?' material-image':''}">
   <button type="button" class="material-open" data-chat-action="preview" data-id="${esc(id)}" aria-label="预览 ${esc(name)}" title="${title}">${preview}</button>
   <button type="button" class="icon-button material-remove" data-chat-action="remove-source" data-id="${esc(id)}" aria-label="移除 ${esc(name)}" title="移除材料" ${processing?'disabled':''}>${icon('close')}</button>
   ${snippet?`<small class="material-snippet">${esc(snippet)}</small>`:''}
  </div>`;
 }
 function draw(node,depth=0){
  return [...node.folders].map(([name,child])=>`<details class="material-folder" data-folder-path="${esc(child.path)}" ${depth===0?'open':''}><summary>${icon('folder')}<span>${esc(name)}</span><small>${count(child)} 份</small></summary><div class="material-folder-children">${draw(child,depth+1)}</div></details>`).join('')+node.files.map(file).join('');
 }
 function count(n){return n.files.length+[...n.folders.values()].reduce((a,c)=>a+count(c),0);}return draw(root);
}
export function formatSize(size){return size>=1024*1024?(size/1024/1024).toFixed(1)+' MB':size?Math.max(1,Math.ceil(size/1024))+' KB':'文字材料';}
