import {installDataTransfer} from './data-transfer.js';
import {installAttachmentPreviews,attachmentPreview} from './attachments.js';
import {installChrome,syncChrome} from './chrome.js';
import {createAuthUI} from './auth.js';
import {createChatUI} from './chat.js';
import {createSourcesUI} from './sources.js';
import {createDraftStore,moveSelection} from './continuity.js';
import {companion,companionSetting,initializeCompanion,greeting,celebrateCompletion} from './companion.js';
import {calendarHelp} from './calendar-help.js';
import {createCalendarUI} from './calendar.js';
import {createLibraryUI} from './library.js';
import {speechDialog} from './speech.js';
import {createNoticeComposer} from './notice-compose.js';
import {createOverview} from './overview.js';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const paths = {
  mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0z M5 10v2a7 7 0 0 0 14 0v-2 M12 19v3 M8 22h8',
  search:'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  check:'m5 12 4 4L19 6', doc:'M14 2H5v20h14V7z M14 2v6h5 M8 12h8 M8 16h5',
  tasks:'M9 6h12 M9 12h12 M9 18h12 M3 6l1 1 2-3 M3 12l1 1 2-3 M3 18l1 1 2-3',
  calendar:'M4 5h16v16H4z M4 10h16 M8 3v4 M16 3v4 M8 14h2 M14 14h2 M8 18h2',
  settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3l-1 3-3 1-2 3 2 2-1 4 3 1 2 4h4l2-3 4-1 1-4-2-2 1-4-4-1-1-3z',
  plus:'M12 5v14 M5 12h14', arrow:'M5 12h14 m-5-5 5 5-5 5', clock:'M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  upload:'M12 16V3 m-5 5 5-5 5 5 M4 15v6h16v-6', down:'M12 3v13 m-5-5 5 5 5-5 M4 16v5h16v-5',
  logout:'M9 3H3v18h6 M9 12h12 m-5-5 5 5-5 5', close:'m6 6 12 12 M18 6 6 18',
  edit:'m4 16-1 5 5-1L21 7l-5-5z M13 5l5 5', info:'M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  spark:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',
  menu:'M4 6h16 M4 12h16 M4 18h16', trash:'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',
  back:'M19 12H5 m5-5-5 5 5 5', shield:'m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z m-5 9 4 4 6-7',
  history:'M3 10a9 9 0 1 1 2 9 M3 3v7h7 M12 7v6l4 2'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.doc}"/></svg>`;
const button = (label, action, cls='', extra='') => `<button type="button" class="button ${cls}" data-action="${action}" ${extra}>${label}</button>`;
const pill = (label, cls='') => `<span class="pill ${cls}">${esc(label)}</span>`;
const dateText = n => new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(n*1000));
const timeInput = value => value ? new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,16) : '';
const toTime = value => value ? value+':00+08:00' : null;
const state = {session:null,notices:[],tasks:[],notice:null,drafts:[],filter:'pending',query:'',dateFilter:'',taskPage:1,renderId:0,invite:''};
let toastTimer,dialogReturnTarget,lastDialogTrigger;
document.addEventListener('click',event=>{if(!$('#dialog')?.open)lastDialogTrigger=event.target.closest('button,a,input,summary');},true);
function toast(message,error=false){const e=$('#toast');e.textContent=message;e.className='visible'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>e.className='',error?9000:5000);}
async function api(path, options={}) {
  const {json,blob,...opts}=options;
  const headers = {'X-Requested-With':'campus-notice',...(opts.headers||{})};
  if(state.session)headers['X-CSRF-Token']=state.session.csrf;
  if(json!==undefined){headers['Content-Type']='application/json';opts.body=JSON.stringify(json);}
  let response;
  try{response=await fetch('/api'+path,{...opts,headers,credentials:'same-origin'});}
  catch{const e=new Error('连接暂时中断，请检查网络或确认工作台仍在运行，然后重试。');e.status=0;throw e;}
  if(!response.ok){let body;try{body=await response.json();}catch{body={detail:'服务暂时不可用，请稍后重试'};}
    const d=body.detail;const message=typeof d==='string'?d:Array.isArray(d)?d.map(item=>String(item.msg||'请检查填写内容').replace(/^Value error, /,'')).join('；'):d?.message;const e=new Error(message||'操作未完成，请检查填写内容后重试');e.status=response.status;e.detail=d;throw e;}
  return blob?response.blob():response.json();
}
function showDialog(title,body){persistCurrentForms();state.dialogRequest=(state.dialogRequest||0)+1;const d=$('#dialog');if(!d.open)dialogReturnTarget=lastDialogTrigger?.isConnected?lastDialogTrigger:document.activeElement;d.innerHTML=`<div class="dialog-head"><h2>${esc(title)}</h2><button class="icon-button" data-action="close-dialog" aria-label="关闭">${icon('close')}</button></div><div class="dialog-body">${body}</div>`;if(!d.open)d.showModal();requestAnimationFrame(()=>{if(d.open)(d.querySelector('[autofocus]')||[...d.querySelectorAll('.dialog-body input,.dialog-body select,.dialog-body textarea,.dialog-body button')].find(el=>el.getClientRects().length&&!el.disabled)||d.querySelector('button'))?.focus();});}
function ask(title,text,confirmLabel='确认'){return new Promise(resolve=>{showDialog(title,`<p>${esc(text)}</p><div class="form-footer">${button('返回','close-dialog')}${button(confirmLabel,'accept-dialog','primary')}</div>`);const d=$('#dialog');const done=()=>{d.removeEventListener('close',closed);resolve(true);d.close();};const closed=()=>resolve(false);$('[data-action="accept-dialog"]',d).addEventListener('click',done,{once:true});d.addEventListener('close',closed,{once:true});});}
function download(blob,name){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),15000);}
const empty=(title,text,action='',compact=false)=>`<div class="empty ${compact?'compact':''}">${compact?'<div class="empty-icon">'+icon('doc')+'</div>':companion('reading','empty-companion')}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
const field=(label,name,value='',type='text',opts='')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${opts}></label>`;
const area=(label,name,value='',rows=3,opts='')=>`<label class="field">${label}<textarea name="${name}" rows="${rows}" ${opts}>${esc(value)}</textarea></label>`;
function formError(form,message){let error=$('.form-error',form);if(!error){error=document.createElement('div');error.className='alert error form-error';form.prepend(error);}error.textContent=message;error.scrollIntoView({block:'nearest'});}
function authPage(){authUI.render();}
const navs=[['chat','spark','和小信使聊聊'],['dashboard','grid','今日安排'],['tasks','tasks','待办'],['notices','doc','通知资料'],['calendar','calendar','日历'],['sources','history','通知来源'],['settings','settings','个人与账号']];
function shell(page){
  if($('.shell')){updateShell(page);return;}
  const u=state.session.user;
  $('#app').innerHTML=`<div class="shell"><a class="skip-link" href="#content">跳到主要内容</a><button type="button" class="menu-scrim" data-action="menu" aria-label="关闭导航菜单" tabindex="-1"></button><aside class="sidebar"><div class="sidebar-resize" role="separator" tabindex="0" aria-label="调整侧栏宽度，方向键可调节" aria-orientation="vertical" aria-valuemin="180" aria-valuemax="460" aria-valuenow="234"></div><a href="#chat" class="brand"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="50" height="50"><span><strong>珞珈信使</strong><small>你的每一步，都算数</small></span></a><a class="button primary sidebar-create" href="#new">${icon('plus')} 处理一则通知</a><div class="nav-label">我的校园空间</div><nav aria-label="主导航">${navs.map(([id,i,l])=>`<a class="nav-item" href="#${id}">${icon(i)}<span>${l}</span>${id==='chat'?'<small>AI</small>':''}</a>`).join('')}</nav><div class="sidebar-bottom"><div class="account"><a href="#settings" class="avatar" aria-label="个人设置">${esc(u.display_name.slice(0,1))}</a><a href="#settings" class="spacer account-name">${esc(u.display_name)}<small>${{student:'学生',teacher:'教师',staff:'教职工',other:'个人'}[u.profile.campus_role]||'个人'}空间</small></a><button class="icon-button" title="退出登录" aria-label="退出登录" data-action="logout">${icon('logout')}</button></div></div></aside><div class="workspace"><button type="button" class="icon-button workspace-chrome-toggle" data-shell-toggle aria-label="收起侧栏" title="展开或收起侧栏 · Ctrl / ⌘ + \\">${icon('menu')}</button><header class="topbar"><div class="topbar-left"><a class="mobile-brand" href="#chat" aria-label="珞珈信使首页"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="40" height="40"></a><span>我的空间</span><span>/</span><b></b></div><div class="topbar-right"><button type="button" class="workspace-search" data-action="quick-search" aria-label="查找通知和待办">${icon('doc')}<span>查找通知和待办</span><kbd>/</kbd></button><span class="date-text">${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'short'}).format(new Date())}</span><a href="#settings" class="service-indicator ${state.session.ai.configured?'configured':''}" title="${state.session.ai.configured?'模型已配置，实际可用性以调用结果为准':'可以先保存材料；填写 API 后启用 AI'}"><i class="dot"></i>${state.session.ai.configured?'AI 已配置':'AI 待配置'}</a></div></header><main class="content" id="content" tabindex="-1"><div class="loading"><i class="spinner"></i>正在打开你的空间…</div></main></div><nav class="mobile-bottom-nav" aria-label="常用页面">${[['chat','spark','助手'],['tasks','tasks','待办'],['notices','doc','资料'],['calendar','calendar','日历']].map(([id,i,l])=>`<a href="#${id}" class="nav-item">${icon(i)}<span>${l}</span></a>`).join('')}<button type="button" data-action="menu">${icon('menu')}<span>更多</span></button></nav></div>`;
}
function noticeStatus(n){return ({received:['待整理',''],draft:['待确认','orange'],processing:['处理中','blue'],confirmed:['已转为待办','green'],failed:['处理失败','red']})[n.status]||['待整理',''];}
function noticeRow(n){const [label,color]=noticeStatus(n);return `<div class="notice-row"><div class="notice-symbol">${icon('doc')}</div><div class="spacer"><button class="link-button" data-action="open-notice" data-id="${n.id}">${esc(n.title)}</button><small>${esc(n.source_label||'个人提交')} · ${n.task_count||0} 项待办</small></div>${pill(label,color)}<span class="date-col">${dateText(n.created_at)}</span></div>`;}
function taskAttachments(t){const files=t.attachments||(state.notice?.id===t.notice_id?state.notice.sources.filter(s=>s.active&&s.kind!=='text'):[]);if(!files.length)return '';return `<div class="task-attachments" data-attachment-notice="${t.notice_id}"><details class="attachment-peek"><summary>${icon('doc')} ${files.length} 份原文附件 · 点开预览</summary><div class="attachment-list">${files.map(s=>`<button type="button" class="attachment-tile" data-preview-source="${s.id}">${icon('doc')}<span><strong>${esc(s.name)}</strong><small>${esc(s.kind.toUpperCase())}${s.size?' · '+Math.ceil(s.size/1024)+' KB':''}</small></span>${icon('arrow')}</button>`).join('')}</div></details></div>`;}
function taskRow(t){const d=t.data;return `<div class="task-row ${t.status==='done'?'done':''}"><button class="task-check ${t.status==='done'?'checked':''}" data-action="toggle-task" data-id="${t.id}" aria-label="${t.status==='done'?'恢复待完成':'标记完成'}" ${t.status==='cancelled'?'disabled':''}>${t.status==='done'?icon('check'):''}</button><div class="task-main"><button class="link-button task-title" data-action="edit-task" data-id="${t.id}">${esc(d.title)}</button><div class="task-meta"><span>${d.due_date?esc(d.due_date+' '+(d.due_time||'时刻未明确')):'期限待核实'}</span>${t.overdue?pill('已逾期','red'):t.due_soon?pill('7 天内到期','orange'):''}${!d.deadline_confirmed&&d.due_date?pill('期限待确认','orange'):''}${t.status==='cancelled'?pill('已取消'):''}${t.needs_calendar_sync?pill('日历需手动同步','orange'):''}${d.origin==='manual'?pill('手工整理'):''}</div><div class="task-meta"><button class="link-button small" data-action="open-notice" data-id="${t.notice_id}">${esc(t.notice_title||'查看原通知')}</button>${d.materials.length?`<span>· ${d.materials.length} 项材料</span>`:''}</div></div><div class="task-actions"><button class="icon-button" title="导出日历" aria-label="导出日历" data-action="export-task" data-id="${t.id}">${icon('calendar')}</button><button class="icon-button" title="编辑待办" aria-label="编辑待办" data-action="edit-task" data-id="${t.id}">${icon('edit')}</button></div>${taskAttachments(t)}</div>`;}
function dashboard(){overviewUI.render();}
function newNotice(){noticeUI.render();}

function noticeList(){libraryUI.render();}
async function calendarPage(){await calendarUI.render(state.renderId);}

const factNames={theme:'主题',audience:'适用对象',dates:'关键时间',actions:'办理事项',materials:'材料清单',submission:'提交方式',location:'办理地点',contact:'联系方式'};
const blankTask=()=>({title:'',details:'',scope:'personal',due_date:null,due_time:null,deadline_text:'',planned_at:null,reminder_at:null,deadline_confirmed:false,materials:[],submission:'',location:'',contact:'',evidence:[],deadline_evidence:[],uncertainties:[],resolution_note:'',notes:'',origin:'manual'});
function taskEditor(t,index,editing=false){const d=t.data||t,existing=state.notice?.tasks||[];return `<section class="task-editor" data-editor="${index}"><div class="editor-head"><div class="row"><span class="number">${editing?'个人行动':'步骤 '+String(index+1).padStart(2,'0')}</span>${editing?'':`<label class="check"><input type="checkbox" name="include" aria-label="保存此步骤" ${t.include!==false&&d.scope!=='other'?'checked':''}> 保存</label>`}</div><div class="row">${pill(d.origin==='ai'?'AI 草稿':'手工整理')}${editing?'':`<button type="button" class="icon-button" data-action="move-step" data-index="${index}" data-direction="-1" aria-label="上移步骤" ${index===0?'disabled':''}>↑</button><button type="button" class="icon-button" data-action="move-step" data-index="${index}" data-direction="1" aria-label="下移步骤" ${index===state.drafts.length-1?'disabled':''}>↓</button><span class="step-drag-handle" draggable="true" data-step-drag="${index}" title="拖动调整步骤顺序">${icon('menu')}</span>`}</div></div>${field('要做的事','title',d.title,'text','maxlength="160" placeholder="写清具体行动"')}<div class="form-grid">${field('截止日期','due_date',d.due_date||'','date')}${field('截止时间（可留空）','due_time',d.due_time||'','time')}</div><label class="check"><input type="checkbox" name="deadline_confirmed" ${d.deadline_confirmed?'checked':''}><span>已对照原文核实本人的截止时间</span></label><details class="details" ${d.planned_at||d.reminder_at?'open':''}><summary>个人计划与提醒</summary><div class="form-grid">${field('安排在哪天准备','planned_at',timeInput(d.planned_at),'datetime-local')}${field('提前提醒','reminder_at',timeInput(d.reminder_at),'datetime-local')}</div></details>${d.uncertainties.length?`<div class="alert"><strong>还需核实</strong><ul>${d.uncertainties.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}<details class="details" ${d.uncertainties.length?'open':''}><summary>办理要求、材料与联系方式</summary><div class="form-grid"><label class="field">办理责任<select name="scope">${[['personal','由本人办理'],['other','由学院或他人办理'],['uncertain','待核实']].map(([v,l])=>`<option value="${v}" ${d.scope===v?'selected':''}>${l}</option>`).join('')}</select></label>${field('原文期限表述','deadline_text',d.deadline_text,'text','maxlength="500"')}<div class="span-2">${area('办理说明','details',d.details,2,'maxlength="3000"')}</div><div class="span-2">${area('所需材料（每行一项）','materials',d.materials.join('\n'),2,'maxlength="10000"')}</div>${field('提交方式','submission',d.submission,'text','maxlength="1000"')}${field('地点','location',d.location,'text','maxlength="500"')}${field('联系方式','contact',d.contact,'text','maxlength="500"')}<div class="span-2">${area('核实依据（存在冲突时填写）','resolution_note',d.resolution_note,2,'maxlength="1500"')}</div></div></details><details class="details"><summary>个人备注与原文依据</summary>${area('个人备注','notes',d.notes,2,'maxlength="3000"')}${d.evidence.map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${e.source_id}" data-locator="${esc(e.locator)}">${esc(state.notice?.sources.find(s=>s.id===e.source_id)?.name||'原文')} · ${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</details>${!editing&&existing.length?`<label class="field">保存到<select name="replacement"><option value="">新增待办</option>${existing.map(t=>`<option value="${t.id}" ${t.id===d.replacement?'selected':''}>更新：${esc(t.data.title)}</option>`).join('')}</select></label>`:''}</section>`;}

function readEditor(el,base){const d={...base};const get=name=>$(`[name="${name}"]`,el);for(const key of ['title','scope','details','deadline_text','submission','location','contact','resolution_note','notes'])d[key]=get(key).value.trim();d.due_date=get('due_date').value||null;d.due_time=get('due_time').value||null;d.planned_at=toTime(get('planned_at').value);d.reminder_at=toTime(get('reminder_at').value);d.deadline_confirmed=get('deadline_confirmed').checked;d.materials=get('materials').value.split('\n').map(x=>x.trim()).filter(Boolean);delete d.include;delete d.replacement;return d;}
function captureDrafts(){state.drafts=$$('[data-editor]',$('#draft-form')).map((el,i)=>({...readEditor(el,state.drafts[i]),include:$('[name=include]',el).checked,replacement:$('[name=replacement]',el)?.value||''}));}
function sourceCard(s){return `<details data-attachment-notice="${state.notice.id}" class="source-card ${s.active?'':'archived'}" data-source-card="${s.id}" ${s.kind==='text'&&s.active?'open':''}><summary>${esc(s.name)} <span class="source-state">${s.active?({ok:'已解析',review:'需核对',failed:'解析失败'}[s.status]):'历史材料'}</span></summary><div class="source-content">${s.warning?`<div class="alert">${esc(s.warning)}</div>`:''}${['png','jpg','jpeg','webp'].includes(s.kind)&&s.status!=='failed'?`<img class="source-image-preview" src="/api/notices/${state.notice.id}/sources/${s.id}/download?preview=true" alt="${esc(s.name)}">`:''}${s.sections.map(p=>`<div class="source-section" data-source="${s.id}" data-locator="${esc(p.locator)}"><span class="locator">${esc(p.locator)}</span>${esc(p.text)}</div>`).join('')||'<p class="small muted">没有可提取文字，请补充可读材料。</p>'}</div><div class="source-actions">${s.kind!=='text'?`<button type="button" class="button small" data-preview-source="${s.id}">预览附件</button><a class="button small plain" href="/api/notices/${state.notice.id}/sources/${s.id}/download">下载原件</a>`:''}${s.active&&s.status==='review'?button('记录已核实','source-resolve','small plain',`data-id="${s.id}"`):''}${s.active?button('移出当前材料','source-archive','small plain',`data-id="${s.id}"`):''}</div></details>`;}
function noticeDetail(n,keepDraft=false){state.notice=n;if(!keepDraft)state.drafts=drafts.peek('notice:'+n.id+':'+n.version).payload?.tasks||n.draft?.tasks?.map(t=>({...t,include:t.scope!=='other',replacement:''}))||[];const [status,color]=noticeStatus(n);$('#content').innerHTML=`<div class="notice-primary"><h1>${esc(n.title)}</h1><details class="notice-actions"><summary aria-label="通知操作" title="通知操作"><span aria-hidden="true">···</span></summary><div class="notice-actions-menu"><a class="button small plain" href="#notices">${icon('back')} 返回通知列表</a>${button(icon('spark')+' 带着材料继续问 AI','notice-chat','small plain')}${button(icon('history')+' 修改记录','history','small plain')}${button(icon('trash')+' 删除通知','delete-notice','small plain danger')}</div></details></div><ol class="notice-steps" aria-label="办理进度">${[['材料','received'],['核对行动','draft'],['保存办理','confirmed']].map(([label,key],i)=>`<li ${key===(n.status==='confirmed'?'confirmed':n.draft?'draft':'received')?'aria-current="step"':''}><b>${i+1}</b>${label}</li>`).join('')}</ol><div class="review-grid"><section class="panel source-pane"><details class="notice-originals" ${!n.draft&&!matchMedia('(max-width:850px)').matches?'open':''}><summary class="between"><strong>原文与附件</strong><span class="small muted">${n.sources.filter(s=>s.active).length} 份 · ${n.character_count.toLocaleString()} 字</span></summary><div class="small muted">${esc(n.source_label||'本人提交')}${n.published_at?' · 发布于 '+esc(timeInput(n.published_at).replace('T',' ')):' · 未提供原发布时间'}</div>${n.source_url?`<a class="small" href="${esc(n.source_url)}" target="_blank" rel="noopener noreferrer">查看原文链接 ↗</a>`:''}${n.blockers.length?`<div class="alert"><strong>材料核对</strong><ul>${n.blockers.map(b=>`<li>${esc(b)}</li>`).join('')}</ul></div>`:'<div class="status-line muted">'+icon('shield')+' 已确认材料齐全，仍请对照核对语义。</div>'}${n.sources.map(sourceCard).join('')}<div class="form-footer">${button(icon('plus')+' 补充材料','supplement','small')}${button(n.materials_complete?'改为材料未齐':'确认材料齐全','materials','small')}</div></details></section><section id="draft-pane">${draftPane(n)}</section></div>`;attachDraftForm();}
function draftPane(n){if(n.status==='processing')return `<div class="panel busy-panel"><div class="spinner"></div><h3>正在提取与核对依据</h3><p>本次只生成草稿。材料已保存，请稍候。<br>离开页面后可返回查看处理状态。</p>${button('刷新状态','refresh-notice','small')}</div>`;if(n.status==='confirmed')return `<div class="panel"><div class="row">${icon('check')}<h2>已经转为个人待办</h2></div><p class="small muted">${n.tasks.length} 项待办已保存。你可以管理进度，或补充材料后重新整理。</p><div class="divider"></div>${n.tasks.map(taskRow).join('')}<div class="form-footer">${button('重新整理','regenerate','small')}<a class="button primary small" href="#tasks">管理我的待办</a></div></div>`;if(!n.draft)return `<div class="panel stack"><div><h2>把这则通知变成下一步</h2></div>${n.error?`<div class="alert error">${esc(n.error)}</div>`:''}<p class="muted small">先提取与你有关的时间、材料和办理步骤，核对后保存。</p><div class="alert ${state.session.ai.configured?'info':''}">${state.session.ai.configured?'使用服务统一配置的 AI，只处理本通知与必要个人条件。':'AI 尚未配置。管理员在服务端填写 API 后重启即可启用；现在可使用完整的手工流程。'}</div><label class="check"><input id="ai-consent" type="checkbox"><span>允许 AI 处理本次材料与必要个人条件</span></label><div class="row wrap">${button(icon('spark')+' AI 整理下一步','generate','primary',state.session.ai.configured?'':'disabled')}${button(icon('edit')+' 手工整理','manual')}</div><p class="footnote">未经本人核对，草稿不会进入待办或触发任何外部操作。</p></div>`;return `<form id="draft-form" class="panel"><div class="section-head"><h2>核对个人行动草稿</h2>${pill('待本人确认','orange')}</div><p class="small muted">${esc(n.draft.summary)}</p><div class="alert info">${{matches_known:'符合已知条件',not_matching:'存在明确不符条件',needs_review:'适用条件待本人核实'}[n.draft.applicability]}：${esc(n.draft.applicability_reason)}</div>${n.draft.warnings?.length?`<div class="alert"><ul>${n.draft.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:''}${Object.keys(n.draft.facts).length?`<details class="details"><summary>查看八类事实与来源</summary><div class="facts">${Object.entries(n.draft.facts).map(([key,f])=>`<div class="fact"><b>${esc(factNames[key]||key)}</b>${esc(f.value||'原文未明确')}${f.evidence.map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${e.source_id}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</div>`).join('')}</div></details>`:''}<div id="draft-editors">${state.drafts.map((t,i)=>taskEditor(t,i)).join('')}</div><div class="form-footer">${button(icon('plus')+' 增加本人步骤','add-task','small')}</div><div class="divider"></div><label class="check"><input name="reviewed" required type="checkbox"><span>我已对照原文核实本人事项、日期、责任人及材料，确认保存所选步骤。</span></label><p class="footnote">提醒时间应设在未来。日期不明可留空，先保存待核实步骤；不要将他人的办理日期作为本人的截止日期。</p><div class="form-footer"><button class="button primary" type="submit">${icon('check')} 确认并保存待办</button></div></form>`;}
function settingsPage(){const p=state.session.user.profile,u=state.session.user;const item=(title,text,action,i='settings')=>`<button type="button" class="settings-item" data-action="${action}"><span class="settings-item-icon">${icon(i)}</span><span><strong>${title}</strong><small>${esc(text)}</small></span>${icon('arrow')}</button>`;$('#content').innerHTML=`<h1 class="sr-only">个人与账号</h1><div class="settings-home"><div class="settings-person"><span class="avatar avatar-${esc(p.avatar_tone||'forest')}">${esc((p.preferred_name||u.display_name).slice(0,1))}</span><div><h2>${esc(p.preferred_name||u.display_name)}</h2><p>${esc([p.school||'武汉大学',p.college,p.campus_area].filter(Boolean).join(' · '))}</p></div></div><div class="settings-menu">${item('个人条件',[p.college,p.major,p.grade].filter(Boolean).join(' · ')||'校园身份、联系信息与近期目标','settings-profile','doc')}${item('回答偏好',({concise:'简洁',balanced:'适中',detailed:'详细'}[p.response_detail]||'适中')+' · '+({warm:'温和自然',direct:'直接清楚',academic:'严谨规范'}[p.response_style]||'温和自然'),'settings-preferences','spark')}${item('账号安全',u.username,'settings-security','shield')}${item('语音播报','朗读文字、音色与播放','settings-speech','mic')}${state.session.genui?item('互动回答',state.session.genui.enabled?'按内容需要展示图表与可操作界面':'使用文字回答','settings-genui','grid'):''}<a class="settings-item" href="#sources"><span class="settings-item-icon">${icon('history')}</span><span><strong>通知来源</strong><small>常用网站、公众号与群</small></span>${icon('arrow')}</a>${item('导入与导出','迁移个人资料、通知、对话与安排','settings-data','down')}</div>${companionSetting()}</div>`;}
function preferencesDialog(){const p=state.session.user.profile;const select=(name,label,items,value)=>`<label class="field">${label}<select name="${name}">${Object.entries(items).map(([k,v])=>`<option value="${k}" ${k===value?'selected':''}>${v}</option>`).join('')}</select></label>`;showDialog('按你的习惯回答',`<form id="preferences-form" class="stack">${field('希望小信使怎么称呼你','preferred_name',p.preferred_name||'','text','maxlength="30" placeholder="留空使用账号昵称"')}<div class="form-grid">${select('response_detail','回答详细程度',{concise:'简洁 · 重点和下一步',balanced:'适中 · 解释关键原因',detailed:'详细 · 依据与完整步骤'},p.response_detail||'balanced')}${select('response_style','回答风格',{warm:'温和自然',direct:'直接清楚',academic:'严谨规范'},p.response_style||'warm')}${select('avatar_tone','头像颜色',{forest:'珞珈绿',blue:'湖水蓝',plum:'淡紫',amber:'暖杏'},p.avatar_tone||'forest')}</div>${area('还有哪些表达习惯','response_preferences',p.response_preferences||'',3,'maxlength="600" placeholder="例如：先给结论；解释缩写；计划分为今天和本周。"')}<p class="small muted">保存后用于后续回答。来源核对和事实准确性不会因风格改变。</p><div class="form-footer"><button class="button primary" type="submit">保存偏好</button></div></form>`);}
function dataDialog(){showDialog('导入与导出',`<div class="stack"><a class="button" href="/api/export">${icon('down')} 导出个人数据 JSON</a><p class="small muted">包括个人条件、通知、对话、待办和日程。附件原件请另行下载保留。</p><form id="data-import-form" data-workspace-form="data-transfer" class="stack"><label class="upload"><strong>选择此前导出的 JSON</strong><span class="small muted">先查看导入范围，再确认保存；不覆盖现有记录。</span><input id="data-import-file" name="backup" type="file" accept=".json,application/json" required></label><div id="data-import-preview" role="status"></div><button class="button" type="submit">查看导入内容</button></form></div>`);}

function profileDialog(){const p=state.session.user.profile;showDialog('个人条件',`<form id="profile-form" class="stack"><div class="tabs profile-tabs" role="tablist" aria-label="个人条件分组">${[['campus','校园条件'],['contacts','联系信息'],['goals','近期目标']].map(([key,label])=>`<button type="button" role="tab" class="tab ${key==='campus'?'active':''}" aria-selected="${key==='campus'}" data-action="profile-section" data-section="${key}">${label}</button>`).join('')}</div><section data-profile-group="campus"><div class="form-grid"><label class="field">校园角色<select name="campus_role" aria-label="校园角色">${Object.entries({student:'学生',teacher:'教师',staff:'教职工',other:'其他'}).map(([k,v])=>`<option value="${k}" ${p.campus_role===k?'selected':''}>${v}</option>`).join('')}</select></label>${field('学校','school',p.school||'武汉大学','text','maxlength="80"')}${field('学院 / 单位','college',p.college||'','text','maxlength="80"')}${field('专业','major',p.major||'','text','maxlength="80"')}${field('常用校区 / 校园区域','campus_area',p.campus_area||'','text','maxlength="80"')}${field('培养层次 / 职务','level',p.level||'','text','maxlength="40"')}${field('年级','grade',p.grade||'','text','maxlength="40"')}${field('当前学期','semester',p.semester||'','text','maxlength="40"')}${field('第一周内任意一天','semester_start',p.semester_start||'','date','min="2000-01-01" max="2100-12-31"')}</div></section><section data-profile-group="contacts" hidden><div class="form-grid">${field('学号（选填）','student_id',p.student_id||'','text','maxlength="40"')}${field('工号（选填）','employee_id',p.employee_id||'','text','maxlength="40"')}${field('手机号','phone',p.phone||'','tel','maxlength="30" autocomplete="tel"')}${field('微信号','wechat',p.wechat||'','text','maxlength="40"')}${field('QQ 号','qq',p.qq||'','text','maxlength="20" inputmode="numeric"')}</div><p class="small muted">仅由本人登记，不代表学校或平台验证；联系信息不加入 AI 上下文。</p></section><section data-profile-group="goals" hidden>${area('近期想完成什么','goals',p.goals||'',4,'maxlength="1000" placeholder="例如：准备课程考试、申请项目。"')}${area('关注的方向','interests',p.interests||'',2,'maxlength="500" placeholder="课程、活动或希望提升的能力"')}${area('通常方便安排的时间','available_time',p.available_time||'',2,'maxlength="300" placeholder="例如：周三下午、工作日晚上"')}</section><p class="small muted">按实际情况填写，选填项可留空。更新资料不会自动改动已有待办。</p><div class="form-footer"><button class="button primary" type="submit">保存个人条件</button></div></form>`);moveSelection($('.profile-tabs'));}
function securityDialog(){showDialog('账号安全',`<form id="password-form" class="stack"><p class="small muted">登录账号：${esc(state.session.user.username)}</p>${field('原密码','old_password','','password','required autocomplete="current-password"')}${field('新密码 · 至少 12 个字符','new_password','','password','required minlength="12" maxlength="128" autocomplete="new-password"')}<div class="form-footer"><button class="button primary" type="submit">更新密码并退出其他设备</button></div></form>`);}
function modelDialog(){showDialog('模型服务',`<div class="stack"><div class="status-line">${pill(state.session.ai.configured?'已填写配置':'等待配置',state.session.ai.configured?'green':'orange')}<span class="mono small">${esc(state.session.ai.model)}</span></div><p>${state.session.user.role==='admin'?'请在项目的 .env 中填写 MIMO_API_KEY；其余 MiMo 模型配置已预置，然后重启服务。密钥只保存在服务端。':'模型服务由当前部署的管理员配置。你可以先保存材料，配置完成后继续对话。'}</p><p class="small muted">填写配置后，以实际回复结果核对服务是否可用。</p><button type="button" class="button" id="open-speech">语音播报与音色</button></div>`);$('#open-speech').addEventListener('click',()=>speechDialog({api,esc,toast,showDialog}).catch(e=>toast(e.message,true)));}

function genuiDialog(){const g=state.session.genui;showDialog('互动回答',`<form id="genui-settings-form" class="stack"><label class="check"><input type="checkbox" name="enabled" ${g.enabled?'checked':''} ${g.available?'':'disabled'}><span>需要时，用图表、清单和可调参数帮助我理解</span></label><p class="small muted">简单问题仍用文字回答。调参数、排序和勾选在本地完成；需要保留时再点击“保存互动进度”。</p>${g.available?'':'<p class="alert">当前部署已关闭互动回答，仍可正常使用文字对话。</p>'}<label class="field">回答区域外观<select name="theme">${[['light','亮色'],['dark','暗色'],['auto','跟随系统']].map(([value,label])=>`<option value="${value}" ${g.theme===value?'selected':''}>${label}</option>`).join('')}</select></label><div class="form-footer"><button type="submit" class="button primary">保存设置</button></div></form>`);}

async function refreshData(){const id=state.renderId;const [notices,tasks]=await Promise.all([api('/notices'),api('/tasks')]);if(id===state.renderId){state.notices=notices;state.tasks=tasks;}}
async function route(){
  const id=++state.renderId;
  clearTimeout(searchTimer);state.dialogRequest=(state.dialogRequest||0)+1;
  persistCurrentForms();
  await drafts.flushAll().catch(error=>toast(error.message,true));
  if(id!==state.renderId)return;
  let page=location.hash.slice(1)||'chat';
  if(page.startsWith('invite=')){state.invite=decodeURIComponent(page.slice(7));history.replaceState(null,'','#register');page='register';}
  if(page==='login')state.invite='';
  if(!state.session){authPage();return;}
  if(state.invite){await api('/auth/logout',{method:'POST'});state.session=null;drafts.clear();authPage();return;}
  shell(page.split('/')[0]);updateShell(page.split('/')[0]);
  const content=$('#content');content.setAttribute('aria-busy','true');content.inert=true;content.classList.add('route-pending');
  try{
    content.dataset.page=page;
    if(page==='chat'||page.startsWith('chat/')){
      await chatUI.render(page.split('/')[1],id);
    }else if(page==='sources'){
      await sourcesUI.render(id);
    }else if(page.startsWith('notice/')){
      const n=await api('/notices/'+encodeURIComponent(page.split('/')[1]));
      if(n.draft&&n.status!=='confirmed')await drafts.load('notice:'+n.id+':'+n.version);
      if(id!==state.renderId)return;noticeDetail(n);attachDraftForm();
    }else{
      await refreshData();
      if(page==='new')await drafts.load('new-notice');
      if(id!==state.renderId)return;
      await ({dashboard,tasks:taskList,notices:noticeList,new:newNotice,calendar:calendarPage,settings:settingsPage}[page]||dashboard)();
      if(page==='new'){restoreNoticeForm();if(state.sourcePreset){const f=$('#notice-form');if(!f.elements.source_label.value)f.elements.source_label.value=state.sourcePreset.name;if(!f.elements.source_url.value)f.elements.source_url.value=state.sourcePreset.url;state.sourcePreset=null;persistCurrentForms();}}
    }
    content.dataset.page=page;
    simplifyPageHeading();
    content.animate([{opacity:.65},{opacity:1}],{duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:170});
  }catch(error){if(id!==state.renderId)return;if(error.status===401){state.session=null;drafts.clear();authPage();}else {if(!('status' in error))console.error('界面加载失败',error);content.innerHTML=empty('暂时未能打开',('status' in error)?error.message:'页面暂时未能显示，你的已保存内容仍然保留。请重新加载。',button('重新加载','refresh'));}}
  finally{if(id===state.renderId&&$('#content')){content.inert=false;content.removeAttribute('aria-busy');content.classList.remove('route-pending');}}
}
function simplifyPageHeading(){
  const header=$('#content .page-title');if(!header)return;
  const title=header.querySelector('h1');if(title)title.className='sr-only';
  header.querySelectorAll('p,.eyebrow').forEach(node=>node.remove());
  header.classList.add('quiet-page-heading');
  if(!header.querySelector('button,a,input'))header.classList.add('no-actions');
}
async function refreshNotice(){const id=state.renderId,nid=state.notice.id;const n=await api('/notices/'+nid);if(id===state.renderId&&location.hash==='#notice/'+nid)noticeDetail(n);}
function showNoticeResult(n,id){if(id===state.renderId&&location.hash==='#notice/'+n.id)noticeDetail(n);}
function findTask(id){return state.tasks.find(t=>t.id===id)||state.notice?.tasks.find(t=>t.id===id);}
function actionableToast(message,label,action){
  toast(message);const element=$('#toast');element.classList.add('has-action');
  const control=document.createElement('button');control.type='button';control.className='toast-action';control.textContent=label;
  control.addEventListener('click',async()=>{control.disabled=true;try{await action();}catch(error){toast(error.message,true);}},{once:true});
  element.append(control);clearTimeout(toastTimer);
  const dismiss=()=>{if(element.contains(document.activeElement))toastTimer=setTimeout(dismiss,5000);else element.className='';};
  toastTimer=setTimeout(dismiss,12000);
}
function displayTaskUpdate(updated){state.tasks=state.tasks.map(t=>t.id===updated.id?updated:t);if(state.notice?.tasks)state.notice.tasks=state.notice.tasks.map(t=>t.id===updated.id?updated:t);const page=location.hash.slice(1);if(page==='tasks')taskList();else if(page==='calendar')calendarUI.refresh();else if(page==='dashboard')dashboard();else if(page==='notice/'+updated.notice_id)noticeDetail(state.notice);}
async function toggleTask(id,routeId){
  const old=findTask(id);if(!old||old.status==='cancelled')return;
  const updated=await api('/tasks/'+id,{method:'PUT',json:{version:old.version,data:old.data,status:old.status==='done'?'pending':'done',reason:old.status==='done'?'本人恢复为待完成':'本人标记完成'}});
  if(routeId===state.renderId)displayTaskUpdate(updated);else await refreshData();
  actionableToast(updated.status==='done'?'已记录为完成。辛苦啦。':'已恢复为待完成，可以继续办理。','撤回',async()=>{
    const restored=await api('/tasks/'+id,{method:'PUT',json:{version:updated.version,data:updated.data,status:old.status,reason:'本人撤回刚才的状态修改'}});
    const page=location.hash.slice(1);
    if(['tasks','dashboard','calendar'].includes(page)||page==='notice/'+old.notice_id)displayTaskUpdate(restored);else await refreshData();
    toast('已撤回，原来的状态保留好了。');
  });
  if(updated.status==='done'&&!state.tasks.some(t=>t.status==='pending'))celebrateCompletion();
}
async function editTask(id){const t=findTask(id);if(!t)return;const routeId=state.renderId,request=state.dialogRequest=(state.dialogRequest||0)+1;const n=await api('/notices/'+t.notice_id);if(routeId!==state.renderId||request!==state.dialogRequest)return;const current=n.tasks.find(x=>x.id===id);if(!current)return;const cacheKey='task:'+current.id+':'+current.version;const cached=await drafts.load(cacheKey);if(routeId!==state.renderId||request!==state.dialogRequest)return;persistCurrentForms();state.notice=n;state.editTask=current;drafts.activate(cacheKey);const shown=cached.payload?.data?{...current,data:cached.payload.data}:current;showDialog('编辑个人待办',`<form id="task-form" data-cache-key="${cacheKey}">${taskEditor(shown,0,true)}${taskAttachments(current)}<div class="form-grid"><label class="field">状态<select name="status" aria-label="状态">${[['pending','待完成'],['done','已完成'],['cancelled','已取消']].map(([v,l])=>`<option value="${v}" ${(cached.payload?.status||current.status)===v?'selected':''}>${l}</option>`).join('')}</select></label>${field('修改原因','reason',cached.payload?.reason||'','text','required maxlength="500" placeholder="例如：核对原文后更正截止日期"')}</div><p class="footnote">标记完成不代表学校已受理。取消或修改已导出的事项后，请在外部日历同步处理。</p><div class="form-footer"><button class="button primary" type="submit">保存修改</button></div></form>`);}
async function exportTasks(tasks){if(!tasks.length){toast('没有可导出的已核实事项',true);return;}const blob=await api('/calendar/export',{method:'POST',json:{task_ids:tasks.map(t=>t.id),versions:Object.fromEntries(tasks.map(t=>[t.id,t.version]))},blob:true});download(blob,'校园事项.ics');toast('日历文件已导出，请在目标日历导入并验证提醒');await refreshData();if(location.hash==='#calendar')calendarPage();}
function supplementDialog(){showDialog('补充通知材料',`<form id="supplement-form" class="stack">${field('材料说明','label','','text','maxlength="80" placeholder="例如：正式更正通知、附件补充文字"')}${area('补充文字','body','',6,'maxlength="10000"')}<label class="upload">${icon('upload')}<strong>添加文件或图片</strong><input name="files" type="file" multiple accept=".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg,.webp,.mp4,.webm" aria-label="上传补充附件"></label><div class="files-list" id="files-list"></div><p class="small muted">补件后需要重新生成或手工整理草稿，已有待办不会被自动改动。</p><div class="form-footer"><button class="button primary" type="submit">保存补充材料</button></div></form>`);}
async function handleClick(e){const target=e.target.closest('[data-action]');if(!target)return;const action=target.dataset.action,id=target.dataset.id;if(action==='accept-dialog')return;if(!['menu','filter','clear-date','profile-section','quick-search','open-notice'].includes(action))target.disabled=true;const actionRoute=state.renderId;try{
  if(action==='close-dialog')$('#dialog').close();
  else if(action==='menu')setMenu(!$('.shell').classList.contains('menu-open'));
  else if(action==='quick-search')quickSearch();
  else if(action==='settings-profile')profileDialog();
  else if(action==='settings-preferences')preferencesDialog();
  else if(action==='settings-data')dataDialog();
  else if(action==='settings-security')securityDialog();
  else if(action==='settings-speech')await speechDialog({api,esc,toast,showDialog});

  else if(action==='settings-genui')genuiDialog();
  else if(action==='profile-section'){$$('[data-profile-group]').forEach(node=>node.hidden=node.dataset.profileGroup!==target.dataset.section);$$('[data-action=profile-section]').forEach(node=>{const active=node===target;node.classList.toggle('active',active);node.setAttribute('aria-selected',String(active));});moveSelection($('.profile-tabs'));}
  else if(action==='logout'){persistCurrentForms();await drafts.flushAll();await api('/auth/logout',{method:'POST'});state.session=null;state.invite='';drafts.clear();state.tasks=[];state.notices=[];state.notice=null;location.hash='login';authPage();}
  else if(action==='open-notice')location.hash='notice/'+id;
  else if(action==='refresh')await route();
  else if(action==='refresh-notice')await refreshNotice();
  else if(action==='filter'){state.filter=target.dataset.filter;state.taskPage=1;taskList();}
  else if(action==='clear-date'){state.dateFilter='';state.taskPage=1;$('#task-date').value='';taskList();}
  else if(action==='task-page'){state.taskPage=Number(target.dataset.page);taskList();}
  else if(action==='download-draft'){const form=target.closest('form');persistCurrentForms();download(new Blob([JSON.stringify(drafts.peek(form.dataset.cacheKey).payload,null,2)],{type:'application/json'}),'未保存的编辑内容.json');}
  else if(action==='retry-draft'){persistCurrentForms();await drafts.flush(target.closest('form').dataset.cacheKey);}
  else if(action==='discard-missing-files'){drafts.peek('new-notice').payload.files=[];$('#missing-files')?.remove();persistCurrentForms();}
  else if(action==='manual'){showNoticeResult(await api(`/notices/${state.notice.id}/manual`,{method:'POST',json:{version:state.notice.version}}),actionRoute);}
  else if(action==='generate'){if(!$('#ai-consent')?.checked){toast('请先确认本次材料允许发送到模型服务',true);return;}const n=state.notice;$('#draft-pane').innerHTML=`<div class="panel busy-panel"><div class="spinner"></div><h3>正在整理通知</h3><p>逐项提取事实并检查原文依据，请耐心等待。</p></div>`;try{const result=await api(`/notices/${n.id}/generate`,{method:'POST',json:{version:n.version,allow_external_processing:true}});showNoticeResult(result,actionRoute);}catch(error){if(actionRoute===state.renderId&&location.hash==='#notice/'+n.id)await refreshNotice();throw error;}}
  else if(action==='regenerate'){if(await ask('重新整理','将以当前材料重新建立草稿，已有待办会保留。确认新草稿时可选择逐项更新。','继续')){state.notice.draft=null;state.notice.status='received';noticeDetail(state.notice);}}
  else if(action==='add-task'){captureDrafts();state.drafts.push(blankTask());$('#draft-editors').innerHTML=state.drafts.map((t,i)=>taskEditor(t,i)).join('');const last=$$('[data-editor]').at(-1);last.scrollIntoView({block:'nearest'});$('[name=title]',last).focus();attachDraftForm();persistCurrentForms();}
  else if(action==='evidence'){const source=target.dataset.source,locator=target.dataset.locator;if($('#dialog').open)$('#dialog').close();const card=$$('[data-source-card]').find(el=>el.dataset.sourceCard===source);if(card){card.open=true;const section=$$('.source-section',card).find(el=>el.dataset.locator===locator);section?.scrollIntoView({block:'center',behavior:'smooth'});section?.animate([{background:'#fff1bb'},{background:'transparent'}],{duration:2500});}else{location.hash='notice/'+state.notice.id;}}
  else if(action==='supplement')supplementDialog();
  else if(action==='materials'){if(await ask('核对材料完整性',state.notice.materials_complete?'标记为材料未齐后，需重新核对草稿和相关期限。':'请确认正文提及的关键附件均已提交，解析异常已逐份核对。','确认'))showNoticeResult(await api(`/notices/${state.notice.id}/materials`,{method:'POST',json:{version:state.notice.version,complete:!state.notice.materials_complete}}),actionRoute);}
  else if(action==='source-resolve'||action==='source-archive'){state.sourceAction={id,action:action==='source-resolve'?'resolve':'archive'};showDialog(action==='source-resolve'?'记录材料核实结果':'移出当前材料',`<form id="source-form" class="stack"><p class="small muted">${action==='source-resolve'?'请对照原件检查表格、图片及未提取部分，补齐关键文字后再确认。':'原件和历史依据会保留，但不再送入新一轮 AI 处理。请确保当前材料仍完整。'}</p>${area('核实结果 / 原因','reason','',4,'required minlength="2" maxlength="500"')}<div class="form-footer"><button class="button primary" type="submit">确认并记录</button></div></form>`);}
  else if(action==='edit-task')await editTask(id);
  else if(action==='toggle-task')await toggleTask(id,actionRoute);
  else if(action==='export-task')await exportTasks([findTask(id)]);
  else if(action==='export-all'){const candidates=state.tasks.filter(t=>t.status==='pending'&&t.data.scope==='personal'&&(t.data.due_date?t.data.deadline_confirmed:!!t.data.planned_at)&&(!t.data.uncertainties.length||t.data.resolution_note));await exportTasks(candidates);}
  else if(action==='notice-chat'){const result=await api('/notices/'+state.notice.id+'/conversation',{method:'POST',json:{version:state.notice.version}});location.hash='chat/'+result.conversation_id;}
  else if(action==='move-step'){captureDrafts();const index=Number(target.dataset.index),next=index+Number(target.dataset.direction);if(next>=0&&next<state.drafts.length){const [item]=state.drafts.splice(index,1);state.drafts.splice(next,0,item);$('#draft-editors').innerHTML=state.drafts.map((t,i)=>taskEditor(t,i)).join('');persistCurrentForms();}}
  else if(action==='history'){const items=await api(`/notices/${state.notice.id}/history`);const labels={create_notice:'保存通知',supplement:'补充材料',materials_review:'核对材料完整性',source_resolve:'核实材料',source_archive:'移出当前材料',ai_processing_consent:'确认模型外部处理',confirm_task:'确认新增待办',confirm_revision:'确认更新待办',confirm_draft:'确认草稿',update_task:'修改待办',calendar_export:'导出日历'};showDialog('修改与导出记录',items.length?items.map(item=>`<div class="history-entry"><div class="between"><strong class="small">${esc(labels[item.action]||item.action)}</strong><span class="history-badge">${dateText(item.created_at)}</span></div><details><summary>查看修改前后值</summary>${item.before_json?`<h4>修改前</h4><pre>${esc(JSON.stringify(JSON.parse(item.before_json),null,2))}</pre>`:''}<h4>修改后</h4><pre>${esc(JSON.stringify(JSON.parse(item.after_json||'null'),null,2))}</pre></details></div>`).join(''):'还没有修改记录');}
  else if(action==='delete-notice'){if(await ask('永久删除此通知','这将删除本通知的正文、全部附件、草稿、待办和修改记录。请先导出需要保留的资料，并自行删除外部日历副本。','永久删除')){await api('/notices/'+state.notice.id,{method:'DELETE',json:{version:state.notice.version}});toast('通知及关联数据已删除');location.hash='notices';}}
  else if(action==='invite'){const result=await api('/admin/invites',{method:'POST'});showDialog('成员邀请链接',`<p>将下方链接交给受邀成员。有效期 ${result.expires_in_days} 天，限注册一次。</p><div class="invitation" id="invite-link">${esc(result.url)}</div><div class="form-footer">${button('复制邀请链接','copy-invite','primary')}</div>`);}
  else if(action==='copy-invite'){try{await navigator.clipboard.writeText($('#invite-link').textContent);toast('已复制邀请链接');}catch{toast('请选中上方邀请链接并复制');}}
}catch(error){toast(error.message,true);if(error.status===401){state.session=null;authPage();}}finally{target.disabled=false;}}
document.addEventListener('click',handleClick);
document.addEventListener('submit',async e=>{if(e.target.dataset.workspaceForm)return;e.preventDefault();const form=e.target;if(!(form instanceof HTMLFormElement))return;if(form.id==='notice-form'&&noticeUI.advanceIfNeeded())return;const submit=$('[type=submit]',form);if(submit?.disabled)return;if(submit)submit.disabled=true;const submittedRoute=state.renderId,submittedNotice=state.notice;const fd=new FormData(form);persistCurrentForms();form.inert=true;try{if(form.dataset.cacheKey)await drafts.flush(form.dataset.cacheKey);
  if(form.id==='auth-form'){await authUI.submit(form,fd);}
  else if(form.id==='notice-form'||form.id==='supplement-form'){const supplement=form.id==='supplement-form';fd.delete('rights');const files=fd.getAll('files').filter(f=>f.size);fd.delete('files');files.forEach(f=>fd.append('files',f));if(!supplement&&drafts.peek('new-notice').payload?.files?.length&&!files.length)throw new Error('已恢复文字草稿，请重新选择附件，或明确移除之前的附件记录');if(files.length>5||files.some(f=>f.size>5*1024*1024))throw new Error('最多 5 份附件，每份不超过 5 MB');if(supplement)fd.set('version',submittedNotice.version);else{fd.set('materials_complete',$('[name=materials_complete]',form).checked?'true':'false');fd.set('published_at',toTime(fd.get('published_at'))||'');}let n;try{n=await api(supplement?`/notices/${submittedNotice.id}/supplement`:'/notices',{method:'POST',body:fd});}catch(error){if(error.detail?.duplicate_id){const existing=error.detail.duplicate_id;showDialog('发现相同的通知',`<p>当前账号已有相同内容。可复用原通知；不同学期或不同批次请明确另建。</p><div class="form-footer"><a class="button" href="#notice/${existing}" data-action="close-dialog">打开已有通知</a>${button('这是另一批次，另建','duplicate-create','primary')}</div>`);$('[data-action=duplicate-create]').addEventListener('click',async ev=>{ev.target.disabled=true;try{fd.set('allow_duplicate','true');const r=await api('/notices',{method:'POST',body:fd});await retireAfterSave('new-notice');noticeFiles=[];$('#dialog').close();location.hash='notice/'+r.id;}catch(err){toast(err.message,true);ev.target.disabled=false;}},{once:true});return;}throw error;}if(supplement){$('#dialog').close();showNoticeResult(n,submittedRoute);toast('补充材料已保存，请重新整理');}else{await retireAfterSave('new-notice');noticeFiles=[];if(submittedRoute===state.renderId)location.hash='notice/'+n.id;else toast('通知已保存，可在通知资料查看');}}
  else if(form.id==='draft-form'){captureDrafts();const tasks=[],replacements={},target_versions={};for(const d of state.drafts){if(d.include===false)continue;const data={...d};delete data.include;delete data.replacement;if(d.replacement){replacements[tasks.length]=d.replacement;target_versions[d.replacement]=state.notice.tasks.find(t=>t.id===d.replacement).version;}tasks.push(data);}if(!tasks.length)throw new Error('请至少选择一个本人步骤');await api(`/notices/${state.notice.id}/confirm`,{method:'POST',json:{version:state.notice.version,tasks,replacements,target_versions,reviewed:true}});await retireAfterSave(form.dataset.cacheKey);toast('待办已保存，重复提交不会重复建项');document.dispatchEvent(new CustomEvent('campus:milestone',{detail:'notice-confirmed'}));await refreshData();if(submittedRoute===state.renderId)await refreshNotice();}
  else if(form.id==='task-form'){const old=state.editTask;const data=readEditor($('[data-editor]',form),old.data);const updated=await api('/tasks/'+old.id,{method:'PUT',json:{version:old.version,data,status:fd.get('status'),reason:fd.get('reason')}});await retireAfterSave(form.dataset.cacheKey);$('#dialog').close();toast('修改已保存，历史记录可回查');if(submittedRoute===state.renderId)displayTaskUpdate(updated);}
  else if(form.id==='genui-settings-form'){const prefs=await api('/genui/preferences',{method:'PUT',json:{version:state.session.genui.version,enabled:fd.has('enabled'),theme:fd.get('theme')}});state.session.genui=prefs;toast('互动回答设置已保存');$('#dialog').close();if(location.hash==='#settings')settingsPage();}
  else if(form.id==='preferences-form'){await api('/profile',{method:'PUT',json:{...state.session.user.profile,...Object.fromEntries(fd)}});state.session=await api('/session');$('#dialog').close();updateAccount();settingsPage();toast('偏好已保存，下一次回答会采用。');}
  else if(form.id==='profile-form'){await api('/profile',{method:'PUT',json:{...state.session.user.profile,...Object.fromEntries(fd)}});state.session=await api('/session');updateAccount();toast('身份条件已保存');$('#dialog').close();if(location.hash==='#settings')settingsPage();}
  else if(form.id==='password-form'){await api('/auth/password',{method:'POST',json:Object.fromEntries(fd)});state.session=await api('/session');form.reset();toast('密码已更新，其他设备会话已退出');}
  else if(form.id==='source-form'){const a=state.sourceAction;const n=await api(`/notices/${state.notice.id}/sources/${a.id}/review`,{method:'POST',json:{version:state.notice.version,action:a.action,reason:fd.get('reason')}});$('#dialog').close();showNoticeResult(n,submittedRoute);toast('材料变更已记录，请重新整理');}
}catch(error){formError(form,error.message);if(error.status===401){state.session=null;authPage();}}finally{form.inert=false;if(submit)submit.disabled=false;}});
let searchTimer;
document.addEventListener('input',e=>{if(e.target.id==='task-search'){const pos=e.target.selectionStart;state.query=e.target.value;state.taskPage=1;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{if($('#task-results')&&$('#content')?.dataset.page==='tasks')taskList();},200);}if(e.target.name==='body'&&$('#char-count'))$('#char-count').textContent=e.target.value.length.toLocaleString()+' / 10,000 字';});
document.addEventListener('change',e=>{if(e.target.id==='task-date'){state.dateFilter=e.target.value;state.taskPage=1;taskList();}if(e.target.name==='files'){if(e.target.closest('#notice-form')){noticeFiles=[...e.target.files];const cached=drafts.peek('new-notice').payload;if(cached)cached.files=noticeFiles.map(f=>f.name);$('#missing-files')?.remove();}const list=$('#files-list',e.target.closest('form'));if(list)list.innerHTML=[...e.target.files].map(f=>`<div class="file-chip"><span>${esc(f.name)}</span><span>${(f.size/1024).toFixed(0)} KB</span></div>`).join('');}});
window.addEventListener('hashchange',()=>{if($('#dialog').open)$('#dialog').close();route();});
let noticeFiles=[];
const drafts=createDraftStore(api,(key,message,error)=>{
  const form=$$('form[data-cache-key]').find(f=>f.dataset.cacheKey===key);
  if(form){let label=$('.autosave-status',form);if(!label){label=document.createElement('div');label.className='autosave-status';label.setAttribute('role','status');form.prepend(label);}label.textContent=message;label.classList.toggle('save-error',error);if(error)label.insertAdjacentHTML('beforeend',button('重试暂存','retry-draft','small plain')+button('下载本页编辑','download-draft','small plain'));}
});
function updateShell(page){
  syncChrome(page);updateAccount();
  const name=navs.find(n=>n[0]===page)?.[2]||'处理通知';
  $$('.nav-item').forEach(a=>{const active=a.hash==='#'+(['new','notice'].includes(page)?'notices':page);a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  const label=$('.topbar-left b');if(label)label.textContent=name;
  setMenu(false,false);
  moveSelection($('.sidebar nav'),'.nav-item.active');
}
function attachDraftForm(){
  const form=$('#draft-form');if(!form||!state.notice)return;
  const key='notice:'+state.notice.id+':'+state.notice.version;
  form.dataset.cacheKey=key;drafts.activate(key);
}
function restoreNoticeForm(){
  const form=$('#notice-form');if(!form)return;
  const cached=drafts.peek('new-notice');drafts.activate('new-notice');form.dataset.cacheKey='new-notice';
  const data=cached.payload;
  if(!data)return;
  for(const [name,value] of Object.entries(data.fields||{})){
    const el=form.elements.namedItem(name);if(!el||el.type==='file')continue;
    if(el.type==='checkbox')el.checked=!!value;else el.value=String(value??'');
  }
  if(noticeFiles.length){const transfer=new DataTransfer();noticeFiles.forEach(f=>transfer.items.add(f));form.elements.files.files=transfer.files;$('#files-list').innerHTML=noticeFiles.map(f=>`<div class="file-chip">${esc(f.name)}</div>`).join('');}
  else if(data.files?.length){const message=document.createElement('div');message.id='missing-files';message.className='alert';message.innerHTML=`文字草稿已恢复。刷新后需重新选择附件：${data.files.map(esc).join('、')}。${button('本次不再使用这些附件','discard-missing-files','small plain')}`;form.prepend(message);}
  const label=document.createElement('div');label.className='autosave-status';label.textContent='已恢复尚未提交的文字草稿';form.prepend(label);
  $('#char-count').textContent=form.elements.body.value.length.toLocaleString()+' / 10,000 字';
}
function persistCurrentForms(){
  chatUI.persist();
  calendarUI.persist();
  for(const form of $$('form[data-cache-key]')){
    const key=form.dataset.cacheKey;if(drafts.peek(key).retired)continue;
    if(form.id==='notice-form'){
      const fields={};for(const el of form.elements){if(!el.name||el.type==='file'||el.type==='submit')continue;fields[el.name]=el.type==='checkbox'?el.checked:el.value;}
      const actual=[...form.elements.files.files];if(actual.length)noticeFiles=actual;
      const files=actual.length?actual.map(f=>f.name):(drafts.peek(key).payload?.files||[]);
      const snapshot={fields,files};if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,snapshot);
    }else if(form.id==='draft-form'){
      captureDrafts();const snapshot={tasks:state.drafts};if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,snapshot);
    }else if(form.id==='task-form'&&state.editTask){
      const snapshot={data:readEditor($('[data-editor]',form),state.editTask.data),status:form.elements.status.value,reason:form.elements.reason.value};
      if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,snapshot);
    }
  }
}
async function retireAfterSave(key){
  if(!key)return;
  try{await drafts.retire(key);}catch(error){drafts.peek(key).retired=true;toast('正式内容已保存；旧编辑草稿清理未完成，请刷新核对',true);}
}
function taskList(){
  const filtered=state.tasks.filter(t=>(state.filter==='all'||(state.filter==='soon'?(t.due_soon||t.overdue)&&t.status==='pending':t.status===state.filter))&&(!state.query||(t.data.title+' '+t.notice_title+' '+t.data.materials.join(' ')).toLowerCase().includes(state.query.toLowerCase()))&&(!state.dateFilter||t.data.due_date===state.dateFilter));
  if(!$('#task-results'))$('#content').innerHTML=`<div class="page-title between"><div><h1>我的待办</h1><p>已核对的个人行动，按你的节奏逐项完成。</p></div><a href="#new" class="button primary">${icon('plus')} 处理通知</a></div><div class="toolbar"><div class="tabs" role="tablist" aria-label="待办状态">${[['pending','待完成'],['soon','近期'],['done','已完成'],['cancelled','已取消'],['all','全部']].map(([v,l])=>`<button role="tab" class="tab" data-action="filter" data-filter="${v}">${l}</button>`).join('')}</div><div class="search"><input id="task-search" placeholder="搜索标题、通知或材料…" aria-label="搜索待办" value="${esc(state.query)}"></div></div><div class="task-filter-row"><details class="task-date-filter"><summary>${icon('calendar')}<span id="task-date-label">日期筛选</span></summary><div class="filters"><label for="task-date">按截止日期</label><input id="task-date" type="date" value="${esc(state.dateFilter)}">${button('清除日期','clear-date','small plain')}</div></details><span class="small muted" id="task-count"></span></div><div class="divider"></div><div class="panel flush task-results" id="task-results" role="tabpanel" aria-live="polite"></div><div id="task-pages" class="pagination"></div>`;
  $$('.tab').forEach(b=>{const active=b.dataset.filter===state.filter;b.classList.toggle('active',active);b.setAttribute('aria-selected',active?'true':'false');});
  moveSelection($('.tabs'));
  $('#task-count').textContent=filtered.length+' 项事项';$('#task-date-label').textContent=state.dateFilter||'日期筛选';
  const pages=Math.max(1,Math.ceil(filtered.length/20));state.taskPage=Math.min(state.taskPage,pages);
  const visible=filtered.slice((state.taskPage-1)*20,state.taskPage*20);
  $('#task-results').innerHTML=visible.length?visible.map(taskRow).join(''):empty('没有符合条件的事项','调整筛选或提交一则通知，已保存的事项始终可以从全部列表查看。');
  $('#task-results').animate([{opacity:.6},{opacity:1}],{duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:150});
  $('#task-pages').innerHTML=pages>1?`${button('上一页','task-page','small',`data-page="${state.taskPage-1}" ${state.taskPage===1?'disabled':''}`)}<span>第 ${state.taskPage} / ${pages} 页 · 每页 20 项</span>${button('下一页','task-page','small',`data-page="${state.taskPage+1}" ${state.taskPage===pages?'disabled':''}`)}`:'';
}
document.addEventListener('input',e=>{if(e.target.closest('form[data-cache-key]'))persistCurrentForms();});
document.addEventListener('change',e=>{if(e.target.closest('form[data-cache-key]'))persistCurrentForms();});
$('#dialog').addEventListener('close',()=>{if($('#dialog').open)return;state.dialogRequest=(state.dialogRequest||0)+1;persistCurrentForms();drafts.flushAll().catch(error=>toast(error.message,true));$('#dialog').replaceChildren();});
window.addEventListener('beforeunload',e=>{if(drafts.pending()){e.preventDefault();e.returnValue='';}});
window.addEventListener('resize',()=>{moveSelection($('.sidebar nav'),'.nav-item.active');moveSelection($('.tabs'));});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&$('.shell')?.classList.contains('menu-open'))setMenu(false);
  if(!event.target.matches('.tab')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=$$('.tab',event.target.parentElement),position=tabs.indexOf(event.target);
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(position+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();tabs[next].focus();tabs[next].click();
});

const authUI=createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,download,route,moveSelection});
const chatUI=createChatUI({state,api,esc,icon,companion,greeting,toast,showDialog,ask,field,area,drafts,route});
const sourcesUI=createSourcesUI({state,api,esc,icon,field,area,showDialog,ask,toast,route});
$('#dialog').addEventListener('close',()=>{const target=dialogReturnTarget;requestAnimationFrame(()=>{const restored=target?.isConnected?target:target?.dataset.action?.startsWith('settings-')?document.querySelector(`[data-action="${target.dataset.action}"]`):null;if(!$('#dialog').open&&restored&&!restored.disabled)restored.focus({preventScroll:true});});});
document.addEventListener('invalid',event=>{const group=event.target.closest('[data-profile-group]');if(group?.hidden)document.querySelector(`[data-action="profile-section"][data-section="${group.dataset.profileGroup}"]`)?.click();},true);
const libraryUI=createLibraryUI({state,esc,icon,noticeRow,empty,moveSelection});
const overviewUI=createOverview({state,esc,icon,companion,greeting,taskRow,noticeRow,moveSelection});
const noticeUI=createNoticeComposer({esc,field,area,icon,toast,showDialog,api,ask,persist:persistCurrentForms});
const calendarUI=createCalendarUI({state,api,esc,icon,companion,showDialog,ask,toast,field,area,download,moveSelection,calendarHelp,editTask,taskRow,drafts});
function setMenu(open,focus=true){
  const shell=$('.shell');if(!shell)return;
  shell.classList.toggle('menu-open',open);$('.mobile-menu')?.setAttribute('aria-expanded',String(open));window.dispatchEvent(new Event('campus:menu'));
  const modal=open&&matchMedia('(max-width:850px)').matches;
  $('.workspace').inert=modal;$('.mobile-bottom-nav').inert=modal;
  if(focus){
    const focusMenu=()=>{if(!shell.isConnected)return;if(modal&&shell.classList.contains('menu-open')){if(!$('.sidebar').contains(document.activeElement))$('.sidebar .nav-item')?.focus();}else if(!shell.classList.contains('menu-open'))$('.workspace-chrome-toggle')?.focus();};
    requestAnimationFrame(focusMenu);
    // A hidden drawer can reject focus until its visibility transition has finished.
    if(modal)setTimeout(focusMenu,260);
  }
}
document.addEventListener('keydown',e=>{
  if(e.key!=='Tab'||!$('.shell')?.classList.contains('menu-open')||!matchMedia('(max-width:850px)').matches)return;
  const focusable=$$('a[href],button:not(:disabled)',$('.sidebar')),first=focusable[0],last=focusable.at(-1);
  if(!$('.sidebar').contains(document.activeElement)){e.preventDefault();first.focus();}else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
});
document.addEventListener('click',e=>{if(e.target.closest('.skip-link')){e.preventDefault();$('#content')?.focus();}});
window.addEventListener('resize',()=>{if(!matchMedia('(max-width:850px)').matches)setMenu(false,false);});
function quickSearch(){
  showDialog('查找通知和待办',`<div class="stack"><label class="field">输入标题或材料关键词<input id="global-search" type="search" placeholder="搜索当前账号的全部已存内容" autofocus></label><div id="global-results" class="global-results"></div></div>`);
  Promise.all([api('/tasks'),api('/notices')]).then(([tasks,notices])=>{if(!$('#global-search'))return;state.tasks=tasks;state.notices=notices;searchAll('');}).catch(e=>toast(e.message,true));
}
function searchAll(value){
  const q=value.toLowerCase(),items=[...state.tasks.filter(t=>(t.data.title+' '+t.data.materials.join(' ')).toLowerCase().includes(q)).map(t=>({title:t.data.title,label:'待办',url:'#notice/'+t.notice_id})),...state.notices.filter(n=>n.title.toLowerCase().includes(q)).map(n=>({title:n.title,label:'通知',url:'#notice/'+n.id}))];
  $('#global-results').innerHTML=items.length?items.map(x=>`<a class="history-chat" href="${x.url}"><span class="pill">${x.label}</span><strong>${esc(x.title)}</strong>${icon('arrow')}</a>`).join(''):'<p class="muted">没有匹配的内容。试试更短的关键词。</p>';
}
document.addEventListener('input',e=>{if(e.target.id==='global-search')searchAll(e.target.value);});
document.addEventListener('click',e=>{const a=e.target.closest('[data-overview-filter]');if(a?.dataset.overviewFilter){state.filter=a.dataset.overviewFilter;state.taskPage=1;}});
document.addEventListener('keydown',e=>{if(e.key==='/'&&!e.target.closest('input,textarea,select,[contenteditable]')&&state.session&&!$('#dialog').open){e.preventDefault();quickSearch();}});
initializeCompanion();
try{state.session=await api('/session');}catch(e){if(e.status!==401)toast('无法连接服务：'+e.message,true);}
await route();

installChrome({setMenu});

installAttachmentPreviews({api,toast});

function updateAccount(){const p=state.session.user.profile,u=state.session.user,name=p.preferred_name||u.display_name,avatar=$('.account .avatar'),account=$('.account-name');if(avatar){avatar.textContent=name.slice(0,1);avatar.className='avatar avatar-'+(p.avatar_tone||'forest');}if(account){account.replaceChildren(document.createTextNode(name));const small=document.createElement('small');small.textContent=p.college||({student:'学生',teacher:'教师',staff:'教职工',other:'个人'}[p.campus_role]||'个人')+'空间';account.append(small);}}

installDataTransfer({api,toast,onImported:async()=>{state.session=await api('/session');updateAccount();await refreshData();}});

let layoutFrame=0;window.addEventListener('campus:layout',()=>{cancelAnimationFrame(layoutFrame);layoutFrame=requestAnimationFrame(()=>moveSelection($('.sidebar nav'),'.nav-item.active'));});

let draggedStep=null;
document.addEventListener('dragstart',event=>{const handle=event.target.closest('[data-step-drag]');if(!handle)return;draggedStep=Number(handle.dataset.stepDrag);event.dataTransfer.setData('application/x-campus-step',String(draggedStep));event.dataTransfer.effectAllowed='move';});
document.addEventListener('dragover',event=>{if(draggedStep!==null&&event.target.closest('#draft-editors [data-editor]'))event.preventDefault();});
document.addEventListener('drop',event=>{const to=event.target.closest('#draft-editors [data-editor]');if(draggedStep===null||!to)return;event.preventDefault();captureDrafts();const index=Number(to.dataset.editor),[item]=state.drafts.splice(draggedStep,1);state.drafts.splice(index,0,item);draggedStep=null;$('#draft-editors').innerHTML=state.drafts.map((t,i)=>taskEditor(t,i)).join('');persistCurrentForms();});
document.addEventListener('dragend',()=>draggedStep=null);

document.addEventListener('click',event=>{for(const menu of $$('.notice-actions[open]'))if(!menu.contains(event.target)||event.target.closest('button,a'))menu.open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const menu of $$('.notice-actions[open]')){menu.open=false;menu.querySelector('summary').focus();}});
