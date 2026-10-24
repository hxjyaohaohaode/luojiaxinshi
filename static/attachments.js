import {readableSnapshot} from './record-preview.js';
import {el,button} from './genui/dom.js';
const images=new Set(['png','jpg','jpeg','webp']),videos=new Set(['mp4','webm']);
export function attachmentPreview(container,source,url,options={}){
 if(options.full)return fullAttachmentPreview(container,source,url,options.api);
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
  else for(const section of part){const row=el('section','source-section');row.append(el('span','locator',section.locator),el('p','preserve-lines',readableSnapshot(section.text,source.evidence_kind||source.kind,{multiline:true})));content.append(row);}
 }draw();
}
function fullAttachmentPreview(container,source,url,api){
 container.replaceChildren();container.classList.add('attachment-inline','full-preview');const actions=el('div','preview-tabs'),download=el('a','button small','下载原件');download.href=url;download.download=source.name;actions.append(download);container.append(actions);
 const visual=el('div','preview-original'),text=el('div','preview-full-text');container.append(visual,text);
 const imageKinds=new Set(['png','jpg','jpeg','webp','gif','bmp','tif','tiff']),audioKinds=new Set(['mp3','wav','m4a','ogg','flac']);
 if(imageKinds.has(source.kind)){const image=el('img');image.src=url+'?preview=true';image.alt=source.name;visual.append(image);
  if(['tif','tiff'].includes(source.kind))api(url.replace(/^\/api/,'').replace('/download','/preview')).then(result=>{if(!container.isConnected||result.frames<2)return;let frame=0;const count=el('span','small muted'),prev=button('上一页',()=>{frame--;drawFrame();},'button small'),next=button('下一页',()=>{frame++;drawFrame();},'button small');actions.append(prev,count,next);function drawFrame(){image.src=url+'?preview=true&frame='+frame;count.textContent=`${frame+1} / ${result.frames} 页`;prev.disabled=frame===0;next.disabled=frame===result.frames-1;}drawFrame();}).catch(error=>{if(container.isConnected)visual.append(el('p','small muted',error.message));});
 }
 if(videos.has(source.kind)){const video=el('video');video.src=url+'?preview=true';video.controls=true;video.playsInline=true;video.preload='metadata';visual.append(video);}
 if(audioKinds.has(source.kind)){const audio=el('audio');audio.src=url+'?preview=true';audio.controls=true;audio.preload='metadata';visual.append(audio);}
 if(source.kind==='pdf'){const frame=el('iframe','pdf-preview');frame.src=url+'?preview=true';frame.title=source.name+'完整 PDF';visual.append(frame);const native=button('原件预览',()=>{visual.hidden=false;text.hidden=true;},'button small'),plain=button('全文检索',()=>{visual.hidden=true;text.hidden=false;},'button small');actions.append(native,plain);text.hidden=true;}
 if(source.warning)container.append(el('p','small muted',source.warning));
 if(imageKinds.has(source.kind)||videos.has(source.kind)||audioKinds.has(source.kind))return;
 let page=1,sequence=0,timer;const search=el('input'),searchLabel=el('label','preview-search'),status=el('span','small muted'),content=el('div','preview-content'),pager=el('div','preview-pager');search.type='search';search.placeholder='查找全文中的文字';search.setAttribute('aria-label','搜索材料全文');searchLabel.append(search);text.append(searchLabel,content,pager);const previous=button('上一页',()=>{page--;draw();},'button small'),next=button('下一页',()=>{page++;draw();},'button small');pager.append(previous,status,next);
 search.addEventListener('input',()=>{clearTimeout(timer);sequence++;page=1;timer=setTimeout(draw,250);});
 async function draw(){const request=++sequence;status.textContent='正在读取…';try{const result=await api(url.replace(/^\/api/,'').replace('/download','/preview')+'?page='+page+'&q='+encodeURIComponent(search.value));if(request!==sequence||!container.isConnected)return;page=result.page;previous.disabled=page===1;next.disabled=page===result.pages;status.textContent=`${page} / ${result.pages} · ${result.matched} 个段落${search.value?'匹配':''}`;content.replaceChildren();
  if(!result.sections.length&&!result.resources?.length)content.append(el('p','muted',search.value?'全文中没有这个关键词，请换个词试试。':'暂无可读取文字。原件已保留，可从上方下载；扫描图片需另行识别。'));
  for(const section of result.sections){const row=el('section','source-section');row.append(el('span','locator',section.locator),el('p','preserve-lines',readableSnapshot(section.text,source.evidence_kind||source.kind,{multiline:true})));content.append(row);}
  if(!search.value)for(const resource of result.resources||[]){const image=el('img');image.src=resource.url;image.alt=resource.name;image.loading='lazy';content.append(image);}
  content.scrollTop=0;
 }catch(error){if(request===sequence&&container.isConnected){status.textContent=error.message;content.replaceChildren(button('重新读取',draw,'button small'));}}}draw();
}
export function installAttachmentPreviews({api,toast}){
 const requests=new WeakMap();
 document.addEventListener('click',async event=>{const b=event.target.closest('[data-preview-source]');if(!b)return;event.preventDefault();const host=b.closest('[data-attachment-notice]'),nid=host?.dataset.attachmentNotice;if(!nid)return;const target=b.closest('.task-attachments,details')||host;let pane=target.querySelector('.attachment-inline');if(!pane){pane=el('div','attachment-inline');target.append(pane);}const rid=(requests.get(target)||0)+1;requests.set(target,rid);b.disabled=true;pane.textContent='正在打开附件…';try{const notice=await api('/notices/'+encodeURIComponent(nid));if(rid!==requests.get(target)||!host.isConnected)return;const source=notice.sources.find(s=>s.id===b.dataset.previewSource);if(!source)throw Error('附件已移除，请刷新后查看。');attachmentPreview(pane,source,`/api/notices/${nid}/sources/${source.id}/download`);}catch(error){if(rid===requests.get(target)&&host.isConnected){pane.textContent=error.message;toast(error.message,true);}}finally{b.disabled=false;}});
}
