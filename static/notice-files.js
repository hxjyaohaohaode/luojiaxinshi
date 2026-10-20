// Local selection queue inspired by the handbook's Kokonut File Upload pattern.
// Files are only uploaded when the enclosing form is submitted.
export const noticeFileExtensions = ['pdf','docx','xlsx','csv','md','txt','png','jpg','jpeg','webp','mp4','webm'];
const fileKey = file => [file.name,file.size,file.lastModified].join('\0');
export function selectNoticeFiles(previous, incoming) {
  const files = [...previous], keys = new Set(files.map(fileKey));
  let duplicates = 0;
  for (const file of incoming) {
    const extension = file.name.split('.').pop().toLowerCase();
    if (!file.name.includes('.') || !noticeFileExtensions.includes(extension))
      return {files:previous,error:`“${file.name}”的格式暂不支持，请选择列出的文档、图片或视频。`};
    if (file.size > 5 * 1024 * 1024)
      return {files:previous,error:`“${file.name}”超过 5 MB，请压缩后重新选择。`};
    if (keys.has(fileKey(file))) { duplicates++; continue; }
    files.push(file); keys.add(fileKey(file));
  }
  if (files.length > 5) return {files:previous,error:'最多选择 5 份附件，请先移除不需要的文件。'};
  return {files,duplicates,error:''};
}
export function formatFileSize(size) {
  return size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${Math.ceil(size/1024)} KB` : `${(size/1024/1024).toFixed(1)} MB`;
}

export function installNoticeFiles({esc,icon,toast,onChange=()=>{}}) {
  const selected = new WeakMap(), managed = new WeakSet();
  const thumbnails = new WeakMap();
  const selector = '#notice-form input[name=files],#supplement-form input[name=files]';
  function draw(input, message='', error=false) {
    const form=input.closest('form'), list=form?.querySelector('.files-list');
    if(!list)return;
    const files=[...input.files];
    list.innerHTML=files.map((file,index)=>`<div class="file-chip selected-file">
      <span class="selected-file-type" aria-hidden="true">${esc(file.name.split('.').pop().slice(0,4).toUpperCase())}</span>
      <div class="selected-file-info"><strong>${esc(file.name)}</strong><small>${formatFileSize(file.size)} <span>· 待保存</span></small></div>
      <button type="button" class="icon-button" data-notice-file-remove="${index}" aria-label="移除附件 ${esc(file.name)}">${icon('close')}</button>
    </div>`).join('');
    // Local image previews use CSP-permitted data URLs, and never leave the form.
    files.forEach((file,index)=>{
      if(!/\.(png|jpe?g|webp)$/i.test(file.name))return;
      const placeholder=list.children[index]?.querySelector('.selected-file-type');
      if(!thumbnails.has(file))thumbnails.set(file,new Promise(resolve=>{
        const reader=new FileReader();
        reader.onload=()=>resolve(reader.result);reader.onerror=()=>resolve(null);
        reader.readAsDataURL(file);
      }));
      thumbnails.get(file).then(url=>{
        if(!url||!placeholder?.isConnected)return;
        const image=new Image();image.className='selected-file-preview';image.alt='';
        image.src=url;
        image.decode().then(()=>{if(placeholder.isConnected&&image.naturalWidth>0)placeholder.replaceWith(image);}).catch(()=>{/* A damaged image keeps its readable file-type tile. */});
      });
    });
    let status=form.querySelector('.file-queue-status');
    if(!status){status=document.createElement('p');status.className='file-queue-status';status.setAttribute('role','status');list.after(status);}
    status.classList.toggle('error',error);
    status.textContent=message||(files.length?`已选择 ${files.length} / 5 份附件 · 点击保存后上传`:'');
    onChange();
  }
  function assign(input,files) {
    const transfer=new DataTransfer(); files.forEach(file=>transfer.items.add(file));
    input.files=transfer.files; selected.set(input,[...files]);
  }
  function dispatch(input) {
    const event=new Event('change',{bubbles:true}); managed.add(event); input.dispatchEvent(event);
  }
  function add(input,incoming,emit=true) {
    if(input.disabled||input.closest('[inert]'))return;
    const result=selectNoticeFiles(selected.get(input)||[],incoming);
    assign(input,result.files);
    if(result.error)toast(result.error,true);
    const message=result.error||(result.duplicates?`已跳过 ${result.duplicates} 份重复附件 · 当前 ${result.files.length} / 5 份`:'');
    draw(input,message,!!result.error);
    if(emit&&!result.error)dispatch(input);
    return result;
  }
  // Browsers emit input before change for a file chooser. Draft listeners must
  // only see the validated queue published by the change handler below.
  document.addEventListener('input',event=>{
    if(event.target.matches(selector))event.stopImmediatePropagation();
  },true);
  document.addEventListener('change',event=>{
    if(!event.target.matches(selector)||managed.has(event))return;
    const result=add(event.target,[...event.target.files],false);
    if(result?.error)event.stopImmediatePropagation();
  },true);
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-notice-file-remove]');
    if(!button)return;
    const form=button.closest('form'),input=form?.querySelector('input[name=files]');
    if(!input||form.inert)return;
    const files=[...input.files],index=Number(button.dataset.noticeFileRemove),removed=files[index];
    if(!removed)return;
    files.splice(index,1);assign(input,files);draw(input,`已移除 ${removed.name} · 当前 ${files.length} / 5 份`);dispatch(input);
    const buttons=[...form.querySelectorAll('[data-notice-file-remove]')];
    (buttons[Math.min(index,buttons.length-1)]||input).focus({preventScroll:true});
  });
  const zoneFor=event=>event.target.closest?.('#notice-form .upload,#supplement-form .upload');
  document.addEventListener('dragover',event=>{
    const zone=zoneFor(event);if(!zone||!event.dataTransfer?.types.includes('Files'))return;
    event.preventDefault();event.dataTransfer.dropEffect='copy';zone.classList.add('is-dragging');
  });
  document.addEventListener('dragleave',event=>{const zone=zoneFor(event);if(zone&&!zone.contains(event.relatedTarget))zone.classList.remove('is-dragging');});
  document.addEventListener('drop',event=>{
    const zone=zoneFor(event);if(!zone)return;event.preventDefault();zone.classList.remove('is-dragging');
    const input=zone.querySelector('input[name=files]');if(input)add(input,[...event.dataTransfer.files]);
  });
  document.addEventListener('paste',event=>{
    const form=event.target.closest?.('#notice-form,#supplement-form');
    if(!form||!event.clipboardData?.files.length)return;
    event.preventDefault();add(form.querySelector('input[name=files]'),[...event.clipboardData.files]);
  });
  return {
    restore(form) {const input=form?.querySelector('input[name=files]');if(input){selected.set(input,[...input.files]);draw(input);}},
  };
}
