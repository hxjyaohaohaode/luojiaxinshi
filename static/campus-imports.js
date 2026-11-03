import {captureUiContext,beginFormFeedback} from './ui-request.js';

export const WHU_TIMETABLE_URL='https://jwgl.whu.edu.cn/kbcx/xskbcx_cxXskbcxIndex.html?gnmkdm=N2151&layout=default';
export function publicSourceUrl(value){
  try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password&&(!u.port||['80','443'].includes(u.port))?u.href:'';}catch{return '';}
}
export function firstWeekMonday(value){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return '';
  const d=new Date(value+'T00:00:00Z');if(Number.isNaN(+d)||d.toISOString().slice(0,10)!==value)return '';
  d.setUTCDate(d.getUTCDate()-(d.getUTCDay()+6)%7);return d.toISOString().slice(0,10);
}
const rowKey=row=>JSON.stringify([row.name,row.wechat_id,row.institution]);
const weekdays=['','周一','周二','周三','周四','周五','周六','周日'];
const glyph=name=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${{upload:'<path d="M12 16V3m-4 4 4-4 4 4M5 15v5h14v-5"/>',document:'<path d="M14 3H6v18h12V7l-4-4Zm0 0v5h5M9 12h6M9 16h6"/>',arrow:'<path d="M7 17 17 7M7 7h10v10"/>',chevron:'<path d="m9 5 7 7-7 7"/>',check:'<path d="m5 12 4 4L19 6"/>'}[name]||''}</svg>`;
const progress=step=>`<ol class="import-steps" aria-label="导入进度">${['选择材料','核对内容','保存完成'].map((label,i)=>`<li ${i===step?'aria-current="step"':''} class="${i<step?'is-done':''}"><span>${i<step?glyph('check'):i+1}</span><b>${label}</b></li>`).join('')}</ol>`;
export function createCampusImports({state,api,esc,showDialog,toast,route}){
  let current=null,uploadController=null;
  const $=(s,root=document)=>root.querySelector(s);
  const input=(label,key,value='',attrs='')=>`<label class="field">${label}<input data-import-key="${key}" value="${esc(value??'')}" ${attrs}></label>`;
  function dispose(){uploadController?.abort();uploadController=null;for(const url of current?.urls||[])URL.revokeObjectURL(url);current=null;}
  function open(kind){
    dispose();if(!state.session?.user)return;
    const courses=kind==='courses';
    showDialog(courses?'导入课表':'导入公众号',`<form id="campus-import-upload" class="campus-import" data-kind="${kind}" data-no-history data-own-navigation>
      ${progress(0)}<div class="import-intro"><h3>${courses?'把本学期课表放进日历':'从关注列表开始'}</h3><p>${courses?'从学校导出课表，上传后核对一次即可。':'上传公众号列表截图，再选择适合的通知来源。'}</p></div>
      ${courses?`<a class="import-export-link" href="${WHU_TIMETABLE_URL.replaceAll('&','&amp;')}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"><span class="import-link-icon">${glyph('document')}</span><span><strong>前往教务系统导出课表</strong><small>在学校页面自行登录</small></span>${glyph('arrow')}</a>`:''}
      <label class="import-file-picker"><span class="import-upload-icon">${glyph('upload')}</span><strong>${courses?'选择导出的课表':'选择公众号列表截图'}</strong><span>${courses?'PDF、XLSX、CSV 或清晰截图':'PNG、JPG 或 WebP 图片'} · 每份最多 5 MB</span><input name="files" type="file" accept="${courses?'.pdf,.docx,.xlsx,.csv,.txt,.md,':''}.png,.jpg,.jpeg,.webp" multiple required aria-label="${courses?'选择课表文件':'选择公众号截图'}"></label><ul id="campus-selected-files" class="import-selected-files" aria-live="polite"></ul>
      <label class="check import-consent"><input type="checkbox" name="allow_external_processing" required><span>同意使用项目的 AI 服务识别所选文件${courses?'':'，并用公开账号名查找来源'}。</span></label>
      <p class="import-footnote">${courses?'不需要提供学校账号或密码。':'请裁去无关聊天与个人信息。'}原文件不在此入口留存；每次最多 4 份。</p>
      <p id="campus-import-status" class="import-status" role="status"></p><div class="form-footer"><button class="button" type="button" data-action="close-dialog">取消</button><button class="button primary" type="submit">下一步，核对内容</button></div></form>`);
  }
  function readRow(node){
    const original=current.rows[Number(node.dataset.importIndex)];const row={...original};
    for(const element of node.querySelectorAll('[data-import-key]'))row[element.dataset.importKey]=element.dataset.importKey==='weekday'?(element.value?Number(element.value):null):element.value;
    if(current.kind==='courses'){row.start_time=row.start_time||null;row.end_time=row.end_time||null;}
    return row;
  }
  function courseMarkup(row,i){
    const missing=!row.weekday||!row.weeks||!row.start_time||!row.end_time;
    return `<details class="import-review-row" data-import-index="${i}"><summary><span class="import-row-choice"><input type="checkbox" data-import-selected checked aria-label="选择 ${esc(row.title)}"><span><strong>${esc(row.title)}</strong><small>${esc([weekdays[row.weekday],row.start_time&&row.end_time?row.start_time+'–'+row.end_time:row.periods||'时间待补充',row.weeks].filter(Boolean).join(' · '))}</small></span></span>${missing?'<span class="import-tag needs-review">待补全</span>':''}<span class="import-edit-label">编辑</span>${glyph('chevron')}</summary><div class="import-row-fields">
      ${input('课程名称','title',row.title,'required maxlength="160"')}<div class="form-grid"><label class="field">星期<select data-import-key="weekday" required><option value="">请选择</option>${weekdays.slice(1).map((day,n)=>`<option value="${n+1}" ${row.weekday===n+1?'selected':''}>${day}</option>`).join('')}</select></label>${input('上课周次','weeks',row.weeks,'required maxlength="200" placeholder="如 1-16(单)"')}${input('开始时间','start_time',row.start_time,'type="time" required')}${input('结束时间','end_time',row.end_time,'type="time" required')}</div>
      ${row.periods?`<p class="import-footnote">原文：${esc(row.periods)}。请按学校作息核对时刻。</p>`:''}${input('教室或地点','location',row.location,'maxlength="300"')}${input('备注','notes',row.notes,'maxlength="1000"')}${row.evidence?`<details class="import-evidence"><summary>识别依据</summary><p>${esc(row.evidence)}</p></details>`:''}</div></details>`;
  }
  function accountMarkup(row,i){
    return `<details class="import-review-row" data-import-index="${i}"><summary><span class="import-row-choice"><input type="checkbox" data-import-selected checked aria-label="选择 ${esc(row.name)}"><span><strong>${esc(row.name)}</strong><small>${esc(row.wechat_id||row.institution||'未提供微信号')}</small></span></span><span class="import-tag" data-import-row-status>待配置</span>${glyph('chevron')}</summary><div class="import-row-fields">
      ${input('公众号名称','name',row.name,'required maxlength="100"')}${input('微信号','wechat_id',row.wechat_id,'maxlength="80" pattern="[a-zA-Z0-9_-]*" placeholder="原图没有可留空"')}${input('认证主体或发布机构','institution',row.institution,'maxlength="100" placeholder="选填"')}${row.evidence?`<details class="import-evidence"><summary>识别依据</summary><p>${esc(row.evidence)}</p></details>`:''}
      <button class="link-button import-lookup-action" type="button" data-campus-lookup="${i}">查找公开来源</button><div data-import-lookup="${i}" class="import-lookup" aria-live="polite"><p class="import-footnote">尚未检索。先核对微信号和认证主体。</p></div></div></details>`;
  }
  function review(){
    const courses=current.kind==='courses';
    showDialog(courses?'核对课表内容':'核对公众号清单',`<form id="campus-import-review" class="campus-import" novalidate data-no-history data-own-navigation>${progress(1)}
      <div class="import-intro"><h3>${courses?'核对你的课程':'确认想关注的账号'}</h3><p>${current.rows.length?`识别到 ${current.rows.length} ${courses?'组课程时段':'个公众号'}。点开可修改，取消勾选可跳过。`:'没有识别到可用内容，请换一份清晰的材料。'}</p></div>
      ${current.urls.length?`<details class="import-originals"><summary>对照所选原图</summary><div>${current.urls.map(url=>`<img src="${url}" alt="本次选择的原图">`).join('')}</div></details>`:''}
      ${current.warnings.length?`<details class="import-warnings"><summary>${current.warnings.length} 条识别提示，点开查看</summary><ul>${current.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:''}
      ${courses?`<div class="import-term">${input('第一教学周的周一日期','semester_start',current.semesterStart,'type="date" min="2000-01-01" max="2100-12-31" required')}<p>依据学校校历</p></div>`:'<div class="import-search-toolbar"><p>核对账号后，再查找可用的接收方式。</p><button class="button small" type="button" data-campus-lookup="all">查找公开来源</button></div>'}
      <div class="import-list">${current.rows.map((row,i)=>courses?courseMarkup(row,i):accountMarkup(row,i)).join('')}</div>
      <label class="check import-consent"><input type="checkbox" name="reviewed" required><span>${courses?'已核对课程、周次和时间，同意加入我的日历。':'已核对账号身份，同意保存来源与另行勾选的官网订阅。'}</span></label><p class="import-footnote">${courses?'按北京时间保存；本次不会自动设置课前提醒。':'公众号清单与文章自动同步分别配置。'}</p>
      <p id="campus-import-status" role="status" class="import-status"></p><div class="form-footer"><button class="button" type="button" data-campus-import="${current.kind}">重新上传</button><button type="submit" class="button primary" ${current.rows.length?'':'disabled'}>${courses?'确认导入日历':'保存所选来源'}</button></div></form>`);
  }
  async function searchOne(index,context){
    const node=$(`[data-import-index="${index}"]`),target=$(`[data-import-lookup="${index}"]`);if(!node||!target||!current)return;
    const active=current,row=readRow(node),key=rowKey(row);if(active.pending.has(index))return;
    active.pending.add(index);$('[data-import-row-status]',node).textContent='查找中';target.innerHTML='<p class="import-footnote" role="status">正在查找公开来源…</p>';
    try{
      const result=await api('/campus-imports/lookup',{method:'POST',json:{...row,allow_external_search:true}});
      if(!context.sameDialog()||!current||key!==rowKey(readRow(node)))return;
      current.lookups.set(index,{key,result});
      const status=$('[data-import-row-status]',node),presets=result.presets||[];
      status.textContent=presets.length?'可订阅官网':result.status==='unavailable'?'检索不可用':'文章导入';status.classList.toggle('can-subscribe',presets.length>0);
      target.innerHTML=`${presets.map(p=>`<label class="check import-consent"><input type="checkbox" data-import-preset="${esc(p.id)}"><span>已核对对应关系，订阅官网：${esc(p.name)}</span></label>`).join('')}
        ${result.items.length?`<details class="import-candidates"><summary>查看 ${result.items.length} 个候选依据</summary>${result.items.map(item=>{const url=publicSourceUrl(item.url);return url?`<div><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)} ↗</a><small>${item.read_original?'已读取公开网页':'仅搜索摘要'} · 账号对应关系需核对</small></div>`:'';}).join('')}</details>`:`<p class="import-footnote">${result.status==='unavailable'?'搜索服务暂不可用，可以先保存账号清单。':'暂未找到可靠的自动来源，之后可通过文章链接或原文导入。'}</p>`}`;
    }catch(error){if(context.sameDialog()&&current){$('[data-import-row-status]',node).textContent='待重试';target.innerHTML=`<p class="import-inline-error">${esc(error.message)}</p>`;}}
    finally{active.pending.delete(index);}
  }
  document.addEventListener('click',async event=>{
    const openButton=event.target.closest('[data-campus-import]');if(openButton){open(openButton.dataset.campusImport);return;}
    const lookupButton=event.target.closest('[data-campus-lookup]');if(lookupButton&&current){
      const context=captureUiContext(state,lookupButton),nodes=[...document.querySelectorAll('[data-import-index]')].filter(n=>$('[data-import-selected]',n).checked);
      const indexes=lookupButton.dataset.campusLookup==='all'?nodes.map(n=>Number(n.dataset.importIndex)):[Number(lookupButton.dataset.campusLookup)];
      const active=current;active.searching=true;lookupButton.disabled=true;
      try{for(let offset=0;offset<indexes.length&&context.sameDialog();offset+=2)await Promise.all(indexes.slice(offset,offset+2).map(i=>searchOne(i,context)));}
      finally{active.searching=false;if(lookupButton.isConnected)lookupButton.disabled=false;}return;
    }
    const view=event.target.closest('[data-campus-import-view]');if(view){$('#dialog').close();const target=view.dataset.campusImportView;if(location.hash===target)await route();else location.hash=target;}
  });
  document.addEventListener('input',event=>{
    const node=event.target.closest('[data-import-index]');if(!node||!current||!event.target.matches('[data-import-key]'))return;
    const row=readRow(node);$('.import-row-choice strong',node).textContent=current.kind==='courses'?row.title:row.name;
    $('.import-row-choice small',node).textContent=current.kind==='courses'?[weekdays[row.weekday],row.start_time&&row.end_time?row.start_time+'–'+row.end_time:row.periods||'时间待补充',row.weeks].filter(Boolean).join(' · '):row.wechat_id||row.institution||'未提供微信号';
    if(current.kind==='courses'){
      const missing=!row.weekday||!row.weeks||!row.start_time||!row.end_time,tag=$('.needs-review',node);
      if(!missing)tag?.remove();
      else if(!tag){const badge=document.createElement('span');badge.className='import-tag needs-review';badge.textContent='待补全';$('summary',node).insertBefore(badge,$('summary > svg',node));}
      return;
    }
    const index=Number(node.dataset.importIndex);current.lookups.delete(index);$('[data-import-row-status]',node).textContent='待配置';$('[data-import-lookup]',node).innerHTML='<p class="import-footnote">账号信息已修改，请重新查找来源。</p>';
  });
  document.addEventListener('change',event=>{
    if(event.target.matches('#campus-import-upload input[type="file"]'))$('#campus-selected-files').innerHTML=[...event.target.files].map(file=>`<li>${glyph('document')}<span><b>${esc(file.name)}</b><small>${file.size<1024*1024?Math.ceil(file.size/1024)+' KB':(file.size/1024/1024).toFixed(1)+' MB'}</small></span></li>`).join('');
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['campus-import-upload','campus-import-review'].includes(form.id))return;event.preventDefault();
    if(form.id==='campus-import-upload'){
      const files=[...form.elements.files.files],kind=form.dataset.kind,context=captureUiContext(state,form);
      if(!files.length||files.length>4||files.some(f=>!f.size||f.size>5*1024*1024)){toast('请选择 1 至 4 份文件，每份大于 0 字节且不超过 5 MB',true);return;}
      const finish=beginFormFeedback(form);if(!finish)return;form.inert=true;$('#campus-import-status').textContent='正在识别，完成后会显示待核对清单…';
      const body=new FormData(form);body.set('kind',kind);const controller=new AbortController();uploadController=controller;
      try{
        const result=await api('/campus-imports/preview',{method:'POST',body,signal:controller.signal});if(!context.sameDialog())return;
        current={kind,rows:result.rows,warnings:result.warnings,owner:state.session.user.id,requestId:crypto.randomUUID().replaceAll('-',''),lookups:new Map(),pending:new Set(),semesterStart:firstWeekMonday(state.session.user.profile.semester_start),urls:files.filter(f=>/^image\//.test(f.type)).map(f=>URL.createObjectURL(f))};review();
      }catch(error){if(context.sameDialog())$('#campus-import-status').textContent=error.message;}
      finally{form.inert=false;finish();if(uploadController===controller)uploadController=null;}
      return;
    }
    if(!current||current.owner!==state.session?.user?.id)return;
    if(current.searching||current.pending.size){toast('来源还在查找中，请稍等一下');return;}
    const selected=[...form.querySelectorAll('[data-import-index]')].filter(n=>$('[data-import-selected]',n).checked);
    if(!selected.length){toast('请至少选择一项需要保存的内容',true);return;}
    for(const element of [...form.querySelectorAll('input[name="reviewed"],input[data-import-key="semester_start"]'),...selected.flatMap(n=>[...n.querySelectorAll('input[data-import-key],select[data-import-key]')])])if(!element.checkValidity()){const details=element.closest('details');if(details)details.open=true;element.reportValidity();return;}
    const context=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;
    const kind=current.kind,requestId=current.requestId,payload={kind,request_id:requestId,reviewed:true,[kind==='courses'?'courses':'accounts']:selected.map(readRow)};
    if(kind==='courses')payload.semester_start=$('[data-import-key="semester_start"]',form).value;
    const presets=[...new Set(selected.flatMap(node=>[...node.querySelectorAll('[data-import-preset]:checked')].map(n=>n.dataset.importPreset)))];
    form.inert=true;$('#campus-import-status').textContent='正在保存，重复提交不会重复创建…';
    try{
      let result;
      try{result=await api('/campus-imports/commit',{method:'POST',json:payload});}
      catch(error){if(error.status!==0)throw error;result=await api('/campus-imports/receipts/'+requestId);if(result.state!=='saved')throw Error('暂未查到保存结果，保留当前页面后重试；相同提交不会重复创建。');}
      if(!context.sameDialog())return;
      const outcomes=[];
      for(const preset of presets){if(!context.sameDialog())break;try{await api('/source-presets/'+encodeURIComponent(preset)+'/subscribe',{method:'POST',json:{}});outcomes.push({id:preset,ok:true});}catch(error){outcomes.push({id:preset,ok:false,error:error.message});}}
      if(!context.sameDialog())return;
      showDialog('导入已保存',`<section class="campus-import import-complete"><span class="import-success-icon">${glyph('check')}</span><div class="import-intro"><h3>${kind==='courses'?'已经加入你的日历':'来源清单准备好了'}</h3><p>${kind==='courses'?`新增 ${Number(result.created)} 次课程安排`:`已添加 ${Number(result.created)} 个公众号`}${result.duplicates?`，跳过 ${Number(result.duplicates)} 项重复记录`:''}</p></div><p class="import-footnote">${kind==='courses'?'可在日历中继续修改课程，课前提醒需另行设置。':outcomes.some(x=>x.ok)?`${outcomes.filter(x=>x.ok).length} 个所选官网栏目已开启自动接收。`:'公众号清单已保存，尚未开启自动文章同步。'}</p>${outcomes.filter(x=>!x.ok).map(x=>`<p class="import-inline-error">官网订阅未完成：${esc(x.error)}。可在来源页重试。</p>`).join('')}<button class="button primary" type="button" data-campus-import-view="${kind==='courses'?'#calendar':'#sources'}">${kind==='courses'?'查看我的日历':'查看我的通知来源'}</button></section>`,{replaceHistory:true});dispose();
    }catch(error){if(context.sameDialog())$('#campus-import-status').textContent=error.message;}
    finally{form.inert=false;finish();}
  });
  document.querySelector('#dialog').addEventListener('close',dispose);
  document.querySelector('#dialog').addEventListener('dialog-back',dispose);
  window.addEventListener('hashchange',dispose);
  return {open};
}
