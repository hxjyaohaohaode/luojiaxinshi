import {el,button} from './genui/dom.js';
const images=new Set(['png','jpg','jpeg','webp']),videos=new Set(['mp4','webm']);
export function attachmentPreview(container,source,url){
 container.replaceChildren();container.classList.add('attachment-inline');
 const actions=el('div','preview-tabs'),download=el('a','button small','下载原件');download.href=url;download.download=source.name;actions.append(download);container.append(actions);
 if(images.has(source.kind)&&source.status!=='failed'){const image=el('img');image.src=url+'?preview=true';image.alt=source.name;container.append(image);return;}
 if(videos.has(source.kind)&&source.status!=='failed'){const video=el('video');video.src=url+'?preview=true';video.controls=true;video.playsInline=true;video.preload='none';video.setAttribute('aria-label',source.name);container.append(video);if(source.warning)container.append(el('p','small muted',source.warning));return;}
 const sections=source.sections||[];let page=0;const size=['xlsx','csv'].includes(source.kind)?20:6,pages=Math.max(1,Math.ceil(sections.length/size)),content=el('div'),status=el('span','small muted');
 const previous=button('上一页',()=>{page--;draw();},'button small'),next=button('下一页',()=>{page++;draw();},'button small');
 if(pages>1)actions.append(previous,status,next);
 if(['pdf','docx','xlsx'].includes(source.kind))container.append(el('p','small muted','文字预览 · 原始排版、图片和格式请查看下载的原件'));
 if(source.warning)container.append(el('p','small muted',source.warning));container.append(content);
 function draw(){content.replaceChildren();previous.disabled=page===0;next.disabled=page===pages-1;status.textContent=`${page+1} / ${pages}`;const part=sections.slice(page*size,(page+1)*size);if(!part.length){content.append(el('p','muted','暂无可预览文字，请下载原件或补充正文。'));return;}
  if(part.every(s=>s.table)){const wrap=el('div','preview-table-scroll'),table=el('table','preview-table'),caption=el('caption','sr-only',source.name),body=el('tbody');table.append(caption,body);for(const row of part){const tr=el('tr'),locator=el('th','',row.locator);locator.scope='row';tr.append(locator);for(const cell of row.text.split('\t'))tr.append(el('td','',cell));body.append(tr);}wrap.append(table);content.append(wrap);}
  else for(const section of part){const row=el('section','source-section');row.append(el('span','locator',section.locator),el('p','preserve-lines',section.text));content.append(row);}
 }draw();
}
export function installAttachmentPreviews({api,toast}){
 const requests=new WeakMap();
 document.addEventListener('click',async event=>{const b=event.target.closest('[data-preview-source]');if(!b)return;event.preventDefault();const host=b.closest('[data-attachment-notice]'),nid=host?.dataset.attachmentNotice;if(!nid)return;const target=b.closest('.task-attachments,details')||host;let pane=target.querySelector('.attachment-inline');if(!pane){pane=el('div','attachment-inline');target.append(pane);}const rid=(requests.get(target)||0)+1;requests.set(target,rid);b.disabled=true;pane.textContent='正在打开附件…';try{const notice=await api('/notices/'+encodeURIComponent(nid));if(rid!==requests.get(target)||!host.isConnected)return;const source=notice.sources.find(s=>s.id===b.dataset.previewSource);if(!source)throw Error('附件已移除，请刷新后查看。');attachmentPreview(pane,source,`/api/notices/${nid}/sources/${source.id}/download`);}catch(error){if(rid===requests.get(target)&&host.isConnected){pane.textContent=error.message;toast(error.message,true);}}finally{b.disabled=false;}});
}
