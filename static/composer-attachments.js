const imageKinds=new Set(['png','jpg','jpeg','webp','gif','bmp']);
const kindOf=name=>name.split('.').at(-1).toLowerCase();

// Three independent uploads at a time. Only transport bytes drive percentages;
// parsing remains a separate state, and one failure never cancels its siblings.
export class ComposerAttachments{
  constructor(host,{upload,remove,onChange,open,sources=[],ids=[]}){
    Object.assign(this,{host,upload,remove,onChange,open});this.items=[];this.running=0;this.disposed=false;
    for(const source of sources.filter(s=>ids.includes(s.id)))this.items.push({name:source.name,kind:source.kind,ids:[source.id],source,state:'ready'});
    this.draw();
  }
  get ids(){return [...new Set(this.items.flatMap(i=>i.ids||[]))];}
  get busy(){return this.items.some(i=>['queued','uploading','parsing','removing'].includes(i.state));}
  get failed(){return this.items.some(i=>i.state==='error');}
  adopt(sources,ids){for(const source of sources.filter(s=>ids.includes(s.id)&&!this.ids.includes(s.id)))this.items.push({name:source.name,kind:source.kind,ids:[source.id],source,state:'ready'});this.draw();}
  add(files){
    files=[...files];
    if(this.items.length+files.length>100)throw Error('每次最多添加 100 份附件。');
    for(const file of files){
      if(this.items.some(i=>i.file&&i.file.name===file.name&&i.file.size===file.size&&i.file.lastModified===file.lastModified))continue;
      const item={file,name:file.name,kind:kindOf(file.name),state:'queued',ids:[]};
      if(!file.size||file.size>20*1024*1024){item.state='error';item.error='文件须大于 0 字节且不超过 20 MB';}
      if(imageKinds.has(item.kind))item.url=URL.createObjectURL(file);
      this.items.push(item);
    }
    this.draw();this.pump();
  }
  pump(){
    while(!this.disposed&&this.running<3){
      const item=this.items.find(i=>i.state==='queued');if(!item)break;
      this.running++;item.state='uploading';item.progress=0;item.controller=new AbortController();this.draw();
      item.promise=this.upload(item.file,progress=>{if(this.disposed)return;item.progress=progress;item.state=progress===100?'parsing':'uploading';this.draw();},item.controller.signal)
        .then(result=>{if(this.disposed)return;item.ids=result.ids||[];item.source=result.sources.find(s=>item.ids.includes(s.id));if(!item.ids.length)throw Error('未收到附件确认，请重试。');item.state='ready';item.file=null;})
        .catch(error=>{if(this.disposed)return;item.state='error';item.error=error.message||'上传失败';})
        .finally(()=>{this.running--;if(!this.disposed){this.draw();this.pump();}});
    }
  }
  clear(){for(const item of this.items)if(item.url)URL.revokeObjectURL(item.url);this.items=[];this.draw();}
  dispose(){this.disposed=true;for(const item of this.items){item.controller?.abort();if(item.url)URL.revokeObjectURL(item.url);}}
  draw(){
    this.host.hidden=!this.items.length;
    for(const [index,item] of this.items.entries()){
      if(!item.node){
      const card=document.createElement('div');item.node=card;
      const body=document.createElement('button');body.type='button';body.className='attachment-preview';body.title=item.name;body.setAttribute('aria-label','查看附件 '+item.name);
      body.onclick=()=>this.open(item.source);
      const name=document.createElement('span');name.className='attachment-name';name.textContent=item.name;
      const status=document.createElement('span');status.className='attachment-state';
      status.setAttribute('role','status');card.append(body,name,status);
      const remove=document.createElement('button');remove.type='button';remove.className='attachment-remove';remove.textContent='×';remove.setAttribute('aria-label','移除附件 '+item.name);
      remove.onclick=async()=>{try{if(item.ids.length){item.state='removing';this.draw();await this.remove(item.ids);}this.items=this.items.filter(i=>i!==item);if(item.url)URL.revokeObjectURL(item.url);}catch(error){item.state='error';item.error=error.message;}this.draw();};card.append(remove);
      const retry=document.createElement('button');retry.type='button';retry.className='attachment-retry';retry.textContent='重试';retry.onclick=()=>{item.state='queued';item.error='';this.pump();};card.append(retry);
      item.elements={body,status,remove,retry};
      }
      const {body,status,remove,retry}=item.elements;
      item.node.className='composer-attachment '+(imageKinds.has(item.kind)?'is-image ':'')+item.state;
      const url=item.url||(item.source&&imageKinds.has(item.kind)?this.open(item.source,true):null);
      if(item.previewUrl!==url||!body.firstChild){item.previewUrl=url;body.replaceChildren();if(url){const img=document.createElement('img');img.src=url;img.alt=item.name;body.append(img);}else{const badge=document.createElement('span');badge.className='attachment-kind';badge.textContent=item.kind.toUpperCase()||'FILE';body.append(badge);}}
      body.disabled=item.state!=='ready';remove.disabled=this.running>0||this.items.some(i=>i.state==='removing');retry.hidden=item.state!=='error'||!item.file;
      const label=item.state==='uploading'?`上传 ${item.progress}%`:item.state==='queued'?'等待上传':item.state==='parsing'?'读取中':item.state==='removing'?'移除中':item.state==='error'?item.error:item.source?.status==='failed'?'读取失败 · 原件已保留':'已添加';
      if(status.textContent!==label)status.textContent=label;
      if(this.host.children[index]!==item.node)this.host.insertBefore(item.node,this.host.children[index]||null);
    }
    while(this.host.children.length>this.items.length)this.host.lastChild.remove();
    this.host.closest('form')?.classList.toggle('has-attachments',!!this.items.length);this.onChange?.(this);
  }
}

export function uploadAttachment(cid,version,file,{csrf,signal,onProgress}){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest(),data=new FormData();data.set('version',version);data.set('append_only','true');data.append('files',file);data.set('paths',JSON.stringify([file.webkitRelativePath||file._relativePath||file.name]));
    xhr.open('POST',`/api/conversations/${encodeURIComponent(cid)}/sources`);xhr.setRequestHeader('X-Requested-With','campus-notice');xhr.setRequestHeader('X-CSRF-Token',csrf);xhr.responseType='json';xhr.timeout=120000;
    const abort=()=>xhr.abort(),cleanup=()=>signal?.removeEventListener('abort',abort);
    xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded/e.total*100));};
    xhr.onload=()=>{cleanup();if(xhr.status>=200&&xhr.status<300)resolve(xhr.response);else reject(Error(typeof xhr.response?.detail==='string'?xhr.response.detail:'上传失败，请重试。'));};
    xhr.onerror=xhr.ontimeout=()=>{cleanup();reject(Error('上传连接中断，请重试；已成功的附件会保留。'));};xhr.onabort=()=>{cleanup();reject(new DOMException('上传已取消','AbortError'));};
    if(signal?.aborted){reject(new DOMException('上传已取消','AbortError'));return;}signal?.addEventListener('abort',abort,{once:true});xhr.send(data);
  });
}
