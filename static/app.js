import {bindProfileForm,saveProfileForm,applyProfileForm,patchProfile,profileUndoValues} from './profile-editor.js';
import {createDialogNavigation,installFormHistory} from './dialog-navigation.js';
import {syncPageNavigation,installPageNavigation} from './page-navigation.js';
import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {brandMotion,loadingState,beginRouteFeedback,initializeMotion,motionToggle} from './motion.js';
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
import {createNoticeIntakeUI,noticeState} from './notice-intake.js';
import {scheduledEditor,readScheduled,taskTimeLabel,installScheduledEditing,needsTimingReview,calendarReady,taskOnDay} from './notice-timing.js';
installScheduledEditing();
import {createOverview} from './overview.js';
import {initializeExperience,createToastPresenter,motionAllowed} from './experience-system.js';
import {initializeChoreography,choreograph} from './choreography.js';
import {createReminders} from './reminders.js';
import {createInsightsUI} from './insights.js';
import {legalMarkup} from './legal.js';
import {taskBoardMarkup} from './task-views.js';
import {createCommandSearch} from './command-search.js';
import {createWorkflowUI,taskMatchesFilter} from './workflow.js';
import {createMemoryUI} from './memory.js';
import {executionDialog} from './executions.js';
import {noticeProgressPanel,createNoticeProgress} from './notice-progress.js';
import {qualityPanel} from './notice-quality.js';
import {createReviewObserver,observationPanel} from './review-observation.js';
const reviewObserver=createReviewObserver();
import {readIssueDecisions,syncIssueControls,prepareQualityConfirmation,qualityReceipt,resizeQualityNotes} from './notice-resolution.js';
import {noticeModePicker,updateNoticeMode} from './notice-modes.js';
import {initializeDraftPlans,plainTask,taskIsPending,prepareConfirmation,draftPlanEditor,readDraftPlan,syncDraftPlanControls} from './action-plans.js';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const paths = {
  folder:'M3 6h6l2 2h10v12H3z M3 6V4h6l2 2h8v2',
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
  history:'M3 10a9 9 0 1 1 2 9 M3 3v7h7 M12 7v6l4 2',
  bell:'M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9 M10 20a2 2 0 0 0 4 0',
  chart:'M4 20V10 M10 20V4 M16 20v-7 M21 20H3'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.doc}"/></svg>`;
const button = (label, action, cls='', extra='') => `<button type="button" class="button ${cls}" data-action="${action}" ${extra}>${label}</button>`;
const pill = (label, cls='') => `<span class="pill ${cls}">${esc(label)}</span>`;
const dateText = n => new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(n*1000));
const timeInput = value => value ? new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,16) : '';
const toTime = value => value ? value+':00+08:00' : null;
const state = {session:null,notices:[],tasks:[],notice:null,drafts:[],filter:'pending',query:'',dateFilter:'',taskPage:1,taskView:'board',renderId:0,invite:''};
let dialogReturnTarget,lastDialogTrigger;
const dialogNavigation=createDialogNavigation({dialog:$('#dialog'),state,persist:persistCurrentForms});
document.addEventListener('click',event=>{if(!$('#dialog')?.open)lastDialogTrigger=event.target.closest('button,a,input,summary');},true);
const toast=createToastPresenter({esc,icon,owner:()=>state.session?.user?.id});
async function api(path, options={}) {
  const {json,blob,...opts}=options;
  const requestedSession=state.session;
  const headers = {'X-Requested-With':'campus-notice',...(opts.headers||{})};
  if(state.session)headers['X-CSRF-Token']=state.session.csrf;
  if(json!==undefined){headers['Content-Type']='application/json';opts.body=JSON.stringify(json);}
  let response;
  const readController=(opts.method||'GET')==='GET'&&!opts.signal?new AbortController():null;
  const readTimer=readController?setTimeout(()=>readController.abort(),25000):null;
  try{response=await fetch('/api'+path,{...opts,...(readController?{signal:readController.signal}:{}),headers,credentials:'same-origin'});}
  catch(error){clearTimeout(readTimer);const e=new Error(error.name==='AbortError'?'网络有点慢，已保存的内容都还在，稍后刷新一下就好。':'连接断开了，检查一下网络后再试。已保存的内容不会丢。');e.status=0;throw e;}
  try{if(!response.ok){let body;try{body=await response.json();}catch{body={detail:'服务暂时开小差了，请稍后再试'};}
    const d=body.detail;const message=typeof d==='string'?d:Array.isArray(d)?d.map(item=>String(item.msg||'请检查填写内容').replace(/^Value error, /,'')).join('；'):d?.message;const e=new Error(message||'没有成功，检查一下填写的内容再试试');e.status=response.status;e.detail=d;
    if(response.status===401&&requestedSession?.user?.id&&state.session===requestedSession){state.session=null;drafts.clear();state.tasks=[];state.notices=[];state.notice=null;authPage();location.hash='#login';}
    throw e;}
  return await (blob?response.blob():response.json());
  }catch(error){if(readController?.signal.aborted){const e=new Error('网络有点慢，已保存的内容都还在，稍后刷新一下就好。');e.status=0;throw e;}throw error;}
  finally{clearTimeout(readTimer);}
}
function showDialog(title,body){
  persistCurrentForms();dialogNavigation.remember(title);state.dialogRequest=(state.dialogRequest||0)+1;const request=state.dialogRequest,d=$('#dialog');
  if(!d.open)dialogReturnTarget=lastDialogTrigger?.isConnected?lastDialogTrigger:document.activeElement;
  d.setAttribute('aria-labelledby','dialog-title');
  const wasOpen=d.open,forward=dialogNavigation.hasParent();
  d.innerHTML=`<div class="dialog-head">${dialogNavigation.hasParent()?`<button type="button" class="icon-button" data-dialog-back aria-label="返回上一级" title="返回上一级">${icon('back')}</button>`:''}<h2 id="dialog-title" tabindex="-1">${esc(title)}</h2><button class="icon-button" data-action="close-dialog" aria-label="关闭">${icon('close')}</button></div><div class="dialog-body">${body}</div>`;
  if(!d.querySelector('form')&&!d.querySelector('.dialog-body [data-dialog-cancel],.dialog-body [data-action="close-dialog"]')){
    let footer=d.querySelector('.form-footer');
    if(!footer){footer=document.createElement('div');footer.className='form-footer dialog-dismiss';d.querySelector('.dialog-body').append(footer);}
    footer.insertAdjacentHTML('afterbegin',`<button type="button" class="button" data-dialog-cancel>${dialogNavigation.hasParent()?'返回上一级':'关闭'}</button>`);
  }
  if(!d.open)d.showModal();
  else if(wasOpen&&motionAllowed())d.querySelector('.dialog-body')?.animate([{opacity:0,transform:`translate3d(${forward?18:-18}px,0,0)`},{opacity:1,transform:'none'}],{duration:380,easing:'cubic-bezier(.22,1,.36,1)'});
  const openingFocus=document.activeElement;
  requestAnimationFrame(()=>{
    if(!d.open||request!==state.dialogRequest)return;
    // A user may already be typing before this frame runs on a busy device.
    if(document.activeElement!==openingFocus&&d.contains(document.activeElement))return;
    // Start with the heading in long forms. Opening a dialog should not summon
    // a phone keyboard or activate a native select before its context is read.
    const target=d.querySelector('[autofocus]')||d.querySelector('#dialog-title');
    target?.focus({preventScroll:true});d.querySelector('.dialog-body').scrollTop=0;
  });
}
function ask(title,text,confirmLabel='确认'){return new Promise(resolve=>{
  showDialog(title,`<p>${esc(text)}</p><div class="form-footer"><button type="button" class="button" data-dialog-cancel>取消</button>${button(confirmLabel,'accept-dialog','primary')}</div>`);
  const d=$('#dialog'),settle=value=>{d.removeEventListener('close',closed);d.removeEventListener('dialog-back',closed);resolve(value);};
  const closed=()=>settle(false),done=()=>{settle(true);d.close();};
  $('[data-action="accept-dialog"]',d).addEventListener('click',done,{once:true});d.addEventListener('close',closed,{once:true});d.addEventListener('dialog-back',closed,{once:true});
});}
function download(blob,name){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),15000);}
const empty=(title,text,action='',compact=false,visual='radar')=>`<div class="empty ${compact?'compact':''}">${visual==='static'?'<div class="empty-icon">'+icon('info')+'</div>':brandMotion(visual,'',{priority:2})}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
const field=(label,name,value='',type='text',opts='')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${opts}></label>`;
const area=(label,name,value='',rows=3,opts='')=>`<label class="field">${label}<textarea name="${name}" rows="${rows}" ${opts}>${esc(value)}</textarea></label>`;
function formError(form,message){let error=$('.form-error',form);if(!error){error=document.createElement('div');error.className='alert error form-error';error.setAttribute('role','alert');form.prepend(error);}error.textContent=message;error.scrollIntoView({block:'nearest'});}
function profileSaved(message,form,profile,values,view){
  const previous=profileUndoValues(form,values);
  toast(message,false,Object.keys(previous).length?{duration:15000,action:{label:'撤销',run:async()=>{if(!view.sameUser())throw Error('账号已变化，不能撤销原账号的设置。');const restored=await patchProfile(api,profile,previous);if(!view.sameUser())return;for(const key of Object.keys(previous))state.session.user.profile[key]=restored[key];updateAccount();if(view.sameRoute()&&location.hash==='#settings')settingsPage({preserveScroll:true});}}}:{});
}
function authPage(){noticeFiles=[];memoryUI.clearPrivate();authUI.render();}
const navs=[['dashboard','grid','办理工作台'],['chat','spark','和小信使聊聊'],['tasks','tasks','待办'],['notices','doc','通知资料'],['calendar','calendar','日历'],['insights','chart','数据看板'],['sources','history','通知来源'],['settings','settings','个人与账号']];
function shell(page){
  if($('.shell')){updateShell(page);return;}
  const u=state.session.user;
  $('#app').innerHTML=`<div class="shell"><a class="skip-link" href="#content">跳到主要内容</a><button type="button" class="menu-scrim" data-action="menu" aria-label="关闭导航菜单" tabindex="-1"></button><aside class="sidebar"><div class="sidebar-resize" role="separator" tabindex="0" aria-label="调整侧栏宽度，方向键可调节" aria-orientation="vertical" aria-valuemin="180" aria-valuemax="460" aria-valuenow="234"></div><a href="#dashboard" class="brand"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="50" height="50"><span><strong>珞珈信使</strong></span></a><a class="button primary sidebar-create" href="#new">${icon('plus')} 处理通知</a><nav aria-label="主导航">${navs.map(([id,i,l])=>`<a class="nav-item" href="#${id}">${icon(i)}<span>${l}</span>${id==='chat'?'<small>AI</small>':''}</a>`).join('')}</nav><div class="sidebar-bottom"><div class="account"><a href="#settings" class="avatar" aria-label="个人设置">${esc(u.display_name.slice(0,1))}</a><a href="#settings" class="spacer account-name">${esc(u.display_name)}<small>${{student:'学生',teacher:'教师',staff:'教职工',other:'个人'}[u.profile.campus_role]||'个人'}空间</small></a><button class="icon-button" title="退出登录" aria-label="退出登录" data-action="logout">${icon('logout')}</button></div></div></aside><div class="workspace"><button type="button" class="icon-button workspace-chrome-toggle" data-shell-toggle aria-label="收起侧栏" title="展开或收起侧栏 · Ctrl / ⌘ + \\">${icon('menu')}</button><header class="topbar"><div class="topbar-left"><a class="mobile-brand" href="#dashboard" aria-label="珞珈信使首页"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="40" height="40"></a><span>我的空间</span><span>/</span><b></b></div><div class="topbar-right">${motionToggle()}<button type="button" class="icon-button reminder-bell" data-action="reminders" aria-label="提醒" title="提醒">${icon('bell')}<span class="reminder-badge" hidden></span></button><button type="button" class="workspace-search" data-action="quick-search" aria-label="查找通知和待办">${icon('search')}<span>查找通知和待办</span><kbd>/</kbd></button><span class="date-text">${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'short'}).format(new Date())}</span><a href="#settings" class="service-indicator ${state.session.ai.configured?'configured':''}" title="${state.session.ai.configured?'AI 助手已接通':'AI 还没接通，可以先手动整理'}"><i class="dot"></i>${state.session.ai.configured?'AI 已就绪':'AI 未接通'}</a></div></header><main class="content" id="content" tabindex="-1">${loadingState()}</main></div><nav class="mobile-bottom-nav" aria-label="常用页面">${[['dashboard','grid','工作台'],['tasks','tasks','待办'],['chat','spark','助手'],['calendar','calendar','日历']].map(([id,i,l])=>`<a href="#${id}" class="nav-item">${icon(i)}<span>${l}</span></a>`).join('')}<button type="button" data-action="menu">${icon('menu')}<span>更多</span></button></nav></div>`;
}
function noticeStatus(n){return noticeState(n);}
function noticeRow(n){const [label,color]=noticeStatus(n);return `<a class="notice-row notice-row-link" href="#notice/${n.id}"><span class="notice-symbol">${icon('doc')}</span><span class="spacer"><strong>${esc(n.title)}</strong><small>${esc(n.source_label||'个人提交')} · ${n.task_count||0} 项待办</small></span>${pill(label,color)}<span class="date-col">${dateText(n.created_at)}</span></a>`;}
function taskAttachments(t){const files=t.attachments||(state.notice?.id===t.notice_id?state.notice.sources.filter(s=>s.active&&s.kind!=='text'):[]);if(!files.length)return '';return `<div class="task-attachments" data-attachment-notice="${t.notice_id}"><details class="attachment-peek"><summary>${icon('doc')} ${files.length} 份原文附件 · 点开预览</summary><div class="attachment-list">${files.map(s=>`<button type="button" class="attachment-tile" data-preview-source="${s.id}">${icon('doc')}<span><strong>${esc(s.name)}</strong><small>${esc(s.kind.toUpperCase())}${s.size?' · '+Math.ceil(s.size/1024)+' KB':''}</small></span>${icon('arrow')}</button>`).join('')}</div></details></div>`;}
function taskRow(t){
  const d=t.data;
  return `<div class="task-row ${t.status==='done'?'done':''}">
    <button class="task-check ${t.status==='done'?'checked':''}" data-action="toggle-task" data-id="${t.id}" aria-label="${t.status==='done'?'恢复待完成':'标记完成'}" aria-pressed="${t.status==='done'}" ${t.status==='cancelled'?'disabled':''}>${t.status==='done'?icon('check'):''}</button>
    <div class="task-main">
      <button type="button" class="task-title task-primary" data-workflow-task="${t.id}" aria-label="办理：${esc(d.title)}"><span class="task-label">${esc(d.title)}</span>
      <span class="task-meta task-timing"><span class="task-deadline">${icon('calendar')}${esc(taskTimeLabel(d))}</span>${t.overdue?pill('已逾期','red'):t.due_soon?pill('7 天内到期','orange'):''}${!d.deadline_confirmed&&d.due_date?pill('期限待确认','orange'):''}</span>
      <span class="task-meta task-statuses">${t.status==='cancelled'?pill('已取消'):''}${t.needs_calendar_sync?pill('日历需手动同步','orange'):''}${workflowUI.badges(t)}</span></button>
      <div class="task-meta task-source"><a class="small task-source-link" href="#notice/${t.notice_id}">${esc(t.notice_title||'查看原通知')}</a>${d.materials.length?`<span>${d.materials.length} 项材料</span>`:''}</div>
    </div>
    <div class="task-actions"><button class="task-open" title="办理与跟进" aria-label="办理与跟进" data-workflow-task="${t.id}">${icon('tasks')}<span>办理</span></button><button class="icon-button" title="导出日历" aria-label="导出日历" data-action="export-task" data-id="${t.id}">${icon('calendar')}</button><button class="icon-button" title="编辑待办" aria-label="编辑待办" data-action="edit-task" data-id="${t.id}">${icon('edit')}</button></div>
    ${taskAttachments(t)}
  </div>`;
}

function dashboard(){overviewUI.render();}
function newNotice(){noticeUI.render();}

function noticeList(){libraryUI.render();}
async function calendarPage(){await calendarUI.render(state.renderId);}

const factNames={theme:'主题',audience:'适用对象',dates:'关键时间',actions:'办理事项',materials:'材料清单',submission:'提交方式',location:'办理地点',contact:'联系方式'};
const blankTask=()=>({title:'',details:'',scope:'personal',due_date:null,due_time:null,deadline_text:'',planned_at:null,reminder_at:null,deadline_confirmed:false,materials:[],submission:'',location:'',contact:'',evidence:[],deadline_evidence:[],uncertainties:[],resolution_note:'',notes:'',origin:'manual'});
function taskEditor(t,index,editing=false){const d=t.data||t,existing=state.notice?.tasks||[];return `<section class="task-editor" data-editor="${index}"><div class="editor-head"><div class="row"><span class="number">${editing?'个人行动':'步骤 '+String(index+1).padStart(2,'0')}</span>${editing?'':`<label class="check"><input type="checkbox" name="include" aria-label="保存此步骤" ${t.include!==false&&d.scope!=='other'?'checked':''}> 保存</label>`}</div><div class="row">${pill(d.origin==='ai'?'AI 草稿':'手工整理')}${editing?'':`<button type="button" class="icon-button" data-action="move-step" data-index="${index}" data-direction="-1" aria-label="上移步骤" ${index===0?'disabled':''}>↑</button><button type="button" class="icon-button" data-action="move-step" data-index="${index}" data-direction="1" aria-label="下移步骤" ${index===state.drafts.length-1?'disabled':''}>↓</button><span class="step-drag-handle" draggable="true" data-step-drag="${index}" title="拖动调整步骤顺序">${icon('menu')}</span>`}</div></div>${field('要做的事','title',d.title,'text','maxlength="160" placeholder="写清具体行动"')}${scheduledEditor(d,field,esc)}<div class="form-grid">${field('截止日期','due_date',d.due_date||'','date')}${field('截止时间（可留空）','due_time',d.due_time||'','time')}</div><label class="check"><input type="checkbox" name="deadline_confirmed" ${d.deadline_confirmed?'checked':''}><span>截止时间我已对照原文确认</span></label><details class="details" ${d.planned_at||d.reminder_at?'open':''}><summary>个人计划与提醒</summary><div class="form-grid">${field('安排在哪天准备','planned_at',timeInput(d.planned_at),'datetime-local')}${field('提前提醒','reminder_at',timeInput(d.reminder_at),'datetime-local')}</div></details>${d.uncertainties.length?`<div class="alert"><strong>还需核实</strong><ul>${d.uncertainties.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}<details class="details" ${d.uncertainties.length?'open':''}><summary>办理要求、材料与联系方式</summary><div class="form-grid"><label class="field">办理责任<select name="scope">${[['personal','由本人办理'],['other','由学院或他人办理'],['uncertain','待核实']].map(([v,l])=>`<option value="${v}" ${d.scope===v?'selected':''}>${l}</option>`).join('')}</select></label>${field('原文期限表述','deadline_text',d.deadline_text,'text','maxlength="500"')}<div class="span-2">${area('办理说明','details',d.details,2,'maxlength="3000"')}</div><div class="span-2">${area('所需材料（每行一项）','materials',d.materials.join('\n'),2,'maxlength="10000"')}</div>${field('提交方式','submission',d.submission,'text','maxlength="1000"')}${field('地点','location',d.location,'text','maxlength="500"')}${field('联系方式','contact',d.contact,'text','maxlength="500"')}<div class="span-2">${area('核实依据（存在冲突时填写）','resolution_note',d.resolution_note,2,'maxlength="1500"')}</div></div></details><details class="details"><summary>个人备注与原文依据</summary>${area('个人备注','notes',d.notes,2,'maxlength="3000"')}${d.evidence.map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${e.source_id}" data-locator="${esc(e.locator)}">${esc(state.notice?.sources.find(s=>s.id===e.source_id)?.name||'原文')} · ${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</details>${editing?'':draftPlanEditor(d,index,state.drafts,esc)}${!editing&&existing.length?`<label class="field">保存到<select name="replacement"><option value="">新增待办</option>${existing.map(t=>`<option value="${t.id}" ${t.id===d.replacement?'selected':''}>更新：${esc(t.data.title)}</option>`).join('')}</select></label><p class="small muted">更新已有待办时，你写的备注、计划和提醒都会保留。</p>`:''}</section>`;}

function readEditor(el,base){const d={...base};const get=name=>$(`[name="${name}"]`,el);for(const key of ['title','scope','details','deadline_text','submission','location','contact','resolution_note','notes'])d[key]=get(key).value.trim();d.due_date=get('due_date').value||null;d.due_time=get('due_time').value||null;d.planned_at=toTime(get('planned_at').value);d.reminder_at=toTime(get('reminder_at').value);d.deadline_confirmed=get('deadline_confirmed').checked;d.scheduled=readScheduled(el,base);d.materials=get('materials').value.split('\n').map(x=>x.trim()).filter(Boolean);return plainTask(d);}
function captureDrafts(){const qualityForm=$('#draft-form');state.qualityDecisions=readIssueDecisions(qualityForm);state.manualQualityReviewed=!!$('[name=manual_quality_reviewed]',qualityForm)?.checked;state.qualityResolution=$('[name=quality_resolution]',$('#draft-form'))?.value||'';state.drafts=$$('[data-editor]',$('#draft-form')).map((el,i)=>({...readEditor(el,state.drafts[i]),...readDraftPlan(el,state.drafts[i]),include:$('[name=include]',el).checked,replacement:$('[name=replacement]',el)?.value||''}));}
function sourceCard(s){return `<details data-attachment-notice="${state.notice.id}" class="source-card ${s.active?'':'archived'}" data-source-card="${s.id}" ${s.kind==='text'&&s.active?'open':''}><summary>${esc(s.name)} <span class="source-state">${s.active?({ok:'已解析',review:'需核对',failed:'解析失败'}[s.status]):'历史材料'}</span></summary><div class="source-content">${s.origin?`<p class="small"><a href="${esc(s.origin.url)}" target="_blank" rel="noopener noreferrer">打开来源链接 ↗</a> · ${esc(s.origin.imported?'导入的材料快照':'读取于 '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short',hour12:false}).format(new Date(typeof s.origin.retrieved_at==='number'?s.origin.retrieved_at*1000:s.origin.retrieved_at)))}</p>`:''}${s.origin?.warnings?.length?`<div class="alert">${s.origin.warnings.map(esc).join('<br>')}</div>`:''}${s.warning?`<div class="alert">${esc(s.warning)}</div>`:''}${['png','jpg','jpeg','webp'].includes(s.kind)&&s.status!=='failed'?`<img class="source-image-preview" src="/api/notices/${state.notice.id}/sources/${s.id}/download?preview=true" alt="${esc(s.name)}">`:''}${s.sections.map(p=>`<div class="source-section" data-source="${s.id}" data-locator="${esc(p.locator)}"><span class="locator">${esc(p.locator)}</span>${esc(p.text)}</div>`).join('')||'<p class="small muted">这份材料里没有读到文字，可以补充一份可复制的文字版。</p>'}</div><div class="source-actions">${s.kind!=='text'?`<button type="button" class="button small" data-preview-source="${s.id}">预览附件</button><a class="button small plain" href="/api/notices/${state.notice.id}/sources/${s.id}/download">下载原件</a>`:''}${s.active&&s.status==='review'?button('记录已核实','source-resolve','small plain',`data-id="${s.id}"`):''}${s.active?button('移出当前材料','source-archive','small plain',`data-id="${s.id}"`):''}</div></details>`;}
function noticeDetail(n,keepDraft=false){state.notice=n;if(!keepDraft){const saved=drafts.peek('notice:'+n.id+':'+n.version).payload||{};state.qualityDecisions=saved.issue_resolutions||{};state.manualQualityReviewed=!!saved.manual_quality_reviewed;}if(!keepDraft)state.qualityResolution=drafts.peek('notice:'+n.id+':'+n.version).payload?.quality_resolution||'';if(!keepDraft)state.drafts=drafts.peek('notice:'+n.id+':'+n.version).payload?.tasks||n.draft?.tasks?.map(t=>({...t,include:t.scope!=='other',replacement:''}))||[];state.drafts=initializeDraftPlans(state.drafts,n.draft?.plans||{});const [status,color]=noticeStatus(n);$('#content').innerHTML=`<div class="notice-primary"><h1>${esc(n.title)}</h1><details class="notice-actions"><summary aria-label="通知操作" title="通知操作"><span aria-hidden="true">···</span></summary><div class="notice-actions-menu"><a class="button small plain" href="#notices">${icon('back')} 返回通知列表</a>${button(icon('spark')+' 带着材料继续问 AI','notice-chat','small plain')}${button(icon('history')+' 修改记录','history','small plain')}${button(icon('trash')+' 删除通知','delete-notice','small plain danger')}</div></details></div><ol class="notice-steps" aria-label="办理进度">${[['材料','received'],['核对行动','draft'],['保存办理','confirmed']].map(([label,key],i)=>`<li ${key===(n.status==='confirmed'?'confirmed':n.draft?'draft':'received')?'aria-current="step"':''}><b>${i+1}</b>${label}</li>`).join('')}</ol>${workflowUI.noticePanel(n)}<div class="review-grid"><section class="panel source-pane"><details class="notice-originals" ${!matchMedia('(max-width:1000px)').matches?'open':''}><summary class="between"><strong>原文与附件</strong><span class="small muted">${n.sources.filter(s=>s.active).length} 份 · ${n.character_count.toLocaleString()} 字</span></summary><div class="small muted">${esc(n.source_label||'本人提交')}${n.published_at?' · 发布于 '+esc(timeInput(n.published_at).replace('T',' ')):' · 未提供原发布时间'}</div>${n.source_url?`<a class="small" href="${esc(n.source_url)}" target="_blank" rel="noopener noreferrer">查看原文链接 ↗</a>`:''}${n.blockers.length?`<div class="alert"><strong>材料核对</strong><ul>${n.blockers.map(b=>`<li>${esc(b)}</li>`).join('')}</ul></div>`:'<div class="status-line muted">'+icon('shield')+' 材料已齐，可以开始整理。</div>'}${n.sources.map(sourceCard).join('')}<div class="form-footer">${button(icon('plus')+' 补充材料','supplement','small')}${button(n.materials_complete?'改为材料未齐':'确认材料齐全','materials','small')}</div></details></section><section id="draft-pane">${draftPane(n)}</section></div>`;intakeUI.decorateNotice(n);attachDraftForm();if(n.draft&&n.status!=='confirmed')syncIssueControls($('#draft-form'),n.draft.quality||{},state.drafts,state.qualityDecisions,esc);noticeProgress.watch(n);}
function draftPane(n){if(n.status==='processing')return noticeProgressPanel(n,{esc,brandMotion,button});if(n.status==='confirmed')return `<div class="panel"><div class="saved-notice-header">${companion('complete','saved-companion')}<div><div class="row">${brandMotion('seal','',{once:true})}<h2>已经转为个人待办</h2></div><p>${n.tasks.length} 项待办</p></div></div><div class="divider"></div>${qualityReceipt(n.quality_receipt,esc)}${n.tasks.map(taskRow).join('')}<div class="form-footer">${button('重新整理','regenerate','small')}<a class="button primary small" href="#tasks">管理我的待办</a></div></div>`;if(!n.draft)return `<div class="panel stack"><div><h2>把这则通知变成下一步</h2></div>${n.error?`<div class="alert error">${esc(n.error)}</div>`:''}<p class="muted small">小信使会找出和你有关的时间、材料和步骤，你看过没问题就能存成待办。</p><div class="alert ${state.session.ai.configured?'info':''}">${state.session.ai.configured?'小信使只读这则通知和整理需要的个人条件，结果由你确认后才会保存。':'AI 还没有接通，可以先手动整理。接通后，小信使就能帮你一键提取要点。'}</div>${noticeModePicker(state.session.ai,esc)}<label class="check"><input id="ai-consent" type="checkbox"><span>同意把这则通知和必要的个人条件发送给 AI 服务（小米 MiMo）整理</span></label>${state.session.ai.notice_review_enabled?'<p class="footnote">小信使会先整理，再自己复查一遍。没成功不会自动重试，你可以随时再试一次。</p>':''}<div class="row wrap">${button(icon('spark')+' AI 整理下一步','generate','primary',state.session.ai.configured?'':'disabled')}${button(icon('edit')+' 手工整理','manual')}</div><p class="footnote">整理结果只是草稿，你确认之后才会变成待办。</p></div>`;return `<form id="draft-form" class="panel"><div class="section-head"><h2>核对个人行动草稿</h2>${pill('等你确认','orange')}</div>${n.review_observation_contract===1?observationPanel():''}<div class="draft-review-intro"><p class="small muted">看看哪些步骤需要你自己做，勾选后保存。学院或别人负责的步骤默认不勾。</p><p class="small"><strong>${{matches_known:'看起来和你有关',not_matching:'可能不适用于你',needs_review:'需要你确认是否适用'}[n.draft.applicability]}</strong></p><details class="details draft-overview"><summary>通知概况，以及为什么这样判断</summary><p class="small muted">${esc(n.draft.summary)}</p><div class="alert info">${esc(n.draft.applicability_reason)}</div></details></div>${n.draft.warnings?.length?`<details class="alert draft-warnings" ${n.draft.warnings.length<=3?'open':''}><summary>${n.draft.warnings.length} 处值得留意<span class="small">展开查看</span></summary><ul>${n.draft.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:''}${Object.keys(n.draft.facts).length?`<details class="details"><summary>通知要点与原文出处</summary><div class="facts">${Object.entries(n.draft.facts).map(([key,f])=>`<div class="fact"><b>${esc(factNames[key]||key)}</b>${esc(f.value||'原文未明确')}${f.evidence.map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${e.source_id}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</div>`).join('')}</div></details>`:''}${qualityPanel(n.draft.quality,state.drafts,state.qualityResolution,esc,{structured:n.quality_resolution_contract===1,decisions:state.qualityDecisions,manualReviewed:state.manualQualityReviewed})}<div id="draft-editors">${state.drafts.map((t,i)=>taskEditor(t,i)).join('')}</div><div class="form-footer">${button(icon('plus')+' 增加本人步骤','add-task','small')}</div><div class="divider"></div><label class="check"><input name="reviewed" required type="checkbox"><span>我已对照原文看过这些步骤，确认保存。</span></label><p class="footnote">日期不确定可以先空着，之后再补。注意别把学院审核的时间当成自己的截止时间。</p><div class="form-footer"><button class="button primary" type="submit">${icon('check')} 确认并保存待办</button></div></form>`;}
function settingsPage({preserveScroll=false}={}){
  const content=$('#content'),scroll=content.scrollTop,p=state.session.user.profile,u=state.session.user;
  const selected=preserveScroll?content.querySelector('.settings-home')?.dataset.category||'personal':'personal';
  const groups=[['personal','个人资料'],['account','账号服务'],['display','显示与声音']];
  const item=(title,text,action,i='settings')=>`<button type="button" class="settings-item" data-action="${action}"><span class="settings-item-icon">${icon(i)}</span><span><strong>${title}</strong><small>${esc(text)}</small></span>${icon('arrow')}</button>`;
  const link=(title,text,href,i)=>`<a class="settings-item" href="${href}"><span class="settings-item-icon">${icon(i)}</span><span><strong>${title}</strong><small>${text}</small></span>${icon('arrow')}</a>`;
  const menus={
    personal:item('个人条件',[p.college,p.major,p.grade].filter(Boolean).join(' · ')||'身份、学期与联系方式','settings-profile','doc')+item('回答偏好',({concise:'简洁',balanced:'适中',detailed:'详细'}[p.response_detail]||'适中')+' · '+({warm:'温和自然',direct:'直接清楚',academic:'严谨规范'}[p.response_style]||'温和自然'),'settings-preferences','spark')+link('我的记忆与项目','偏好、项目与专题','#memory','history'),
    account:item('账号安全',u.username,'settings-security','shield')+item('模型与处理记录',state.session.ai.billing_label||'模型配置与处理状态','settings-model','spark')+link('通知来源','常用网站、公众号与群','#sources','history')+item('导入与导出','备份与迁移资料','settings-data','down')+link('隐私政策与用户协议','数据与服务条款','#privacy','shield'),
    display:item('语音播报','朗读回复与播放控制','settings-speech','mic')+(state.session.genui?item('互动回答',state.session.genui.enabled?'图表与互动内容':'使用文字回答','settings-genui','grid'):'')
  };
  content.innerHTML=`<h1 class="sr-only">个人与账号</h1><div class="settings-home" data-category="${selected}"><header class="settings-person"><span class="avatar avatar-${esc(p.avatar_tone||'forest')}">${esc((p.preferred_name||u.display_name).slice(0,1))}</span><div><h2>${esc(p.preferred_name||u.display_name)}</h2><p>${esc([p.school||'武汉大学',p.college,p.campus_area].filter(Boolean).join(' · '))}</p></div></header><div class="settings-layout"><nav class="settings-categories" role="tablist" aria-label="设置分类">${groups.map(([key,label])=>`<button type="button" role="tab" id="settings-category-${key}" data-settings-category="${key}" aria-controls="settings-panel-${key}" aria-selected="${key===selected}" tabindex="${key===selected?0:-1}">${label}</button>`).join('')}</nav><div class="settings-groups">${groups.map(([key,label])=>`<section class="settings-group" role="tabpanel" id="settings-panel-${key}" data-settings-panel="${key}" aria-labelledby="settings-category-${key}" ${key===selected?'':'hidden'}><h3>${label}</h3><div class="settings-menu">${menus[key]}</div>${key==='display'?`<details class="settings-usage"><summary>使用偏好</summary>${companionSetting()}</details>`:''}</section>`).join('')}</div></div></div>`;
  const nav=content.querySelector('.settings-categories');
  const choose=(key,focus=false)=>{content.querySelector('.settings-home').dataset.category=key;for(const tab of nav.children){const active=tab.dataset.settingsCategory===key;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;if(active&&focus)tab.focus();}for(const panel of content.querySelectorAll('[data-settings-panel]'))panel.hidden=panel.dataset.settingsPanel!==key;};
  nav.addEventListener('click',event=>{const tab=event.target.closest('[data-settings-category]');if(tab)choose(tab.dataset.settingsCategory);});
  nav.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;event.preventDefault();const index=groups.findIndex(([key])=>key===content.querySelector('.settings-home').dataset.category),next=event.key==='Home'?0:event.key==='End'?groups.length-1:(index+(['ArrowLeft','ArrowUp'].includes(event.key)?groups.length-1:1))%groups.length;choose(groups[next][0],true);});
  const usage=content.querySelector('.settings-usage');usage.querySelector('#companion-enabled+span').textContent='显示小信使问候';const notes=usage.querySelectorAll('p');if(notes[0])notes[0].textContent='仅保存在当前浏览器。';if(notes[1])notes[1].textContent='跟随系统的减少动态效果设置。';if(preserveScroll)content.scrollTop=scroll;
}
function preferencesDialog(){const p=state.session.user.profile;const select=(name,label,items,value)=>`<label class="field">${label}<select name="${name}">${Object.entries(items).map(([k,v])=>`<option value="${k}" ${k===value?'selected':''}>${v}</option>`).join('')}</select></label>`;showDialog('按你的习惯回答',`<form id="preferences-form" class="stack">${field('希望小信使怎么称呼你','preferred_name',p.preferred_name||'','text','maxlength="30" placeholder="留空使用账号昵称"')}<div class="form-grid">${select('response_detail','回答详细程度',{concise:'简洁 · 重点和下一步',balanced:'适中 · 解释关键原因',detailed:'详细 · 依据与完整步骤'},p.response_detail||'balanced')}${select('response_style','回答风格',{warm:'温和自然',direct:'直接清楚',academic:'严谨规范'},p.response_style||'warm')}${select('avatar_tone','头像颜色',{forest:'珞珈绿',blue:'湖水蓝',plum:'淡紫',amber:'暖杏'},p.avatar_tone||'forest')}</div>${area('还有哪些表达习惯','response_preferences',p.response_preferences||'',3,'maxlength="600" placeholder="例如：先给结论；解释缩写；计划分为今天和本周。"')}<p class="small muted">之后的回答会按这个习惯来，内容依据不受影响。</p><div class="form-footer"><button class="button primary" type="submit">保存偏好</button></div></form>`);bindProfileForm($('#preferences-form'),p);}
function dataDialog(){showDialog('导入与导出',`<div class="stack"><a class="button" href="/api/export">${icon('down')} 导出个人数据 JSON</a><p class="small muted">包括个人条件、通知、对话、待办和日程。附件原件请另行下载保留。</p><form id="data-import-form" data-workspace-form="data-transfer" class="stack"><label class="upload"><strong>选择此前导出的 JSON</strong><span class="small muted">先查看导入范围，再确认保存；不覆盖现有记录。</span><input id="data-import-file" name="backup" type="file" accept=".json,application/json" required></label><div id="data-import-preview" role="status"></div><button class="button" type="submit">查看导入内容</button></form></div>`);}

function profileDialog(){const p=state.session.user.profile;showDialog('个人条件',`<form id="profile-form" class="stack"><div class="tabs profile-tabs" role="tablist" aria-label="个人条件分组">${[['campus','身份'],['semester','学期'],['contacts','联系'],['goals','目标']].map(([key,label])=>`<button type="button" role="tab" id="profile-tab-${key}" aria-controls="profile-panel-${key}" tabindex="${key==='campus'?0:-1}" class="tab ${key==='campus'?'active':''}" aria-selected="${key==='campus'}" data-action="profile-section" data-section="${key}">${label}</button>`).join('')}</div><section role="tabpanel" id="profile-panel-campus" aria-labelledby="profile-tab-campus" data-profile-group="campus"><div class="form-grid"><label class="field">校园角色<select name="campus_role" aria-label="校园角色">${Object.entries({student:'学生',teacher:'教师',staff:'教职工',other:'其他'}).map(([k,v])=>`<option value="${k}" ${p.campus_role===k?'selected':''}>${v}</option>`).join('')}</select></label>${field('学校','school',p.school||'武汉大学','text','maxlength="80"')}${field('学院 / 单位','college',p.college||'','text','maxlength="80"')}${field('专业','major',p.major||'','text','maxlength="80"')}</div></section><section role="tabpanel" id="profile-panel-semester" aria-labelledby="profile-tab-semester" data-profile-group="semester" hidden><div class="form-grid">${field('常用校区','campus_area',p.campus_area||'','text','maxlength="80"')}${field('培养层次 / 职务','level',p.level||'','text','maxlength="40"')}${field('年级','grade',p.grade||'','text','maxlength="40"')}${field('当前学期','semester',p.semester||'','text','maxlength="40"')}${field('第一教学周内任意日期','semester_start',p.semester_start||'','date','min="2000-01-01" max="2100-12-31"')}</div></section><section role="tabpanel" id="profile-panel-contacts" aria-labelledby="profile-tab-contacts" data-profile-group="contacts" hidden><div class="form-grid">${field('学号（选填）','student_id',p.student_id||'','text','maxlength="40"')}${field('工号（选填）','employee_id',p.employee_id||'','text','maxlength="40"')}${field('手机号','phone',p.phone||'','tel','maxlength="30" autocomplete="tel"')}${field('微信号','wechat',p.wechat||'','text','maxlength="40"')}${field('QQ 号','qq',p.qq||'','text','maxlength="20" inputmode="numeric"')}</div><p class="small muted">这些资料字段不会自动发给 AI；自行粘贴到通知或对话中的内容仍可能发送。</p></section><section role="tabpanel" id="profile-panel-goals" aria-labelledby="profile-tab-goals" data-profile-group="goals" hidden>${area('近期想完成什么','goals',p.goals||'',4,'maxlength="1000" placeholder="例如：准备课程考试、申请项目。"')}${area('关注的方向','interests',p.interests||'',2,'maxlength="500" placeholder="课程、活动或希望提升的能力"')}${area('通常方便安排的时间','available_time',p.available_time||'',2,'maxlength="300" placeholder="例如：周三下午、工作日晚上"')}</section><p class="small muted">均可选填；修改不会改变已有待办。</p><div class="form-footer"><button class="button primary" type="submit">保存个人条件</button></div></form>`);bindProfileForm($('#profile-form'),p);moveSelection($('.profile-tabs'));}
function securityDialog(){showDialog('账号安全',`<form id="password-form" class="stack"><p class="small muted">登录账号：${esc(state.session.user.username)}</p>${field('原密码','old_password','','password','required autocomplete="current-password"')}${field('新密码 · 至少 12 个字符','new_password','','password','required minlength="12" maxlength="128" autocomplete="new-password"')}<div class="form-footer"><button class="button primary" type="submit">更新密码并退出其他设备</button></div></form><section class="account-danger"><h3>注销账号</h3><p class="small muted">账号和你保存的全部资料都会删除，无法恢复。</p><button type="button" class="button small danger" data-action="delete-account">注销账号…</button></section>`);}
async function legalInfo(){if(!state.legal)state.legal=await api('/legal');return state.legal;}
async function deleteAccountDialog(){const view=captureUiContext(state);const info=await legalInfo();if(!view.sameDialog())return;showDialog('注销账号',`<form id="delete-account-form" class="stack" data-no-history><div class="alert error"><strong>注销后无法恢复</strong><p>你的账号，以及全部通知、附件、对话、待办、日程和记忆会立即删除。已有备份不会立即改写。服务运行时会清理超过 ${Number(info.backup_retention_days)||7} 天的自动备份；停机期间暂停清理，手动备份请联系部署管理员处理。</p></div><p class="small muted">想留着这些资料的话，先导出一份。</p><a class="button small" href="/api/export">${icon('down')} 导出我的数据</a>${field('当前密码','password','','password','required autocomplete="current-password"')}${field('输入“注销账号”四个字确认','confirm','','text','required autocomplete="off" maxlength="20"')}<div class="form-footer"><button type="button" class="button" data-action="close-dialog">再想想</button><button class="button primary danger-fill" type="submit">永久注销</button></div></form>`);}
async function legalPage(kind,renderId){const info=await legalInfo();if(renderId!==state.renderId)return;$('#content').innerHTML=legalMarkup(kind,info,esc);}
async function standaloneLegal(kind){const info=await legalInfo();$('#app').innerHTML=`<main class="legal-standalone"><a class="legal-brand" href="#login"><img class="brand-mark" src="/static/assets/campus-notice-mark-v4.png" alt="" width="40" height="40"><strong>珞珈信使</strong></a>${legalMarkup(kind,info,esc)}<p class="legal-back"><a class="button" href="#login">${icon('back')} 返回登录</a></p></main>`;choreograph($('#app'));}
function modelDialog(){const service=state.session.ai;showDialog('模型服务',`<div class="stack"><div class="status-line">${pill(service.configured?'已填写配置':'等待配置',service.configured?'green':'orange')}<span class="mono small">${esc(service.model)}</span></div><p><strong>${esc(service.billing_label||'Xiaomi MiMo')}</strong></p><p class="small muted">${service.billing_channel==='token_plan'?'使用 Token Plan 专属通道，额度由小米套餐决定。当前适配器的语音功能需要普通 API 通道。':'当前调用走普通 API 按量通道，不代表扣除 Token Plan 或 Desktop 订阅额度。'}</p><p>通知提取：${esc(service.model)}<br>独立动作复核：${service.notice_review_enabled?esc(service.notice_review_model):'未启用'}<br>互动回答组织：${esc(service.composition_model||service.model)}</p><p>${state.session.user.role==='admin'?'模型和凭证在服务端 .env 中配置，修改后重启生效。可选 V2.6 Pro、Flash；普通 API 还适配 Pro UltraSpeed，其权限和费用由小米决定。':'模型服务由当前部署的管理员配置。你可以先保存材料，配置完成后继续对话。'}</p><p class="small muted">适配清单核对日期：${esc(service.catalog_verified_at||'未提供')}。配置状态不代表实时连通或账户模型权限，以实际调用结果为准。</p><button type="button" class="button" id="open-speech">语音播报</button><button type="button" class="button" id="open-executions">最近处理记录</button></div>`);$('#open-speech').addEventListener('click',()=>speechDialog({state,api,esc,toast,showDialog}).catch(e=>toast(e.message,true)));$('#open-executions').addEventListener('click',()=>executionDialog({state,api,esc,showDialog,toast}).catch(e=>toast(e.message,true)));}

function genuiDialog(){const g=state.session.genui;showDialog('互动回答',`<form id="genui-settings-form" class="stack"><label class="check"><input type="checkbox" name="enabled" ${g.enabled?'checked':''} ${g.available?'':'disabled'}><span>需要时，用图表、清单和可调参数帮助我理解</span></label><p class="small muted">简单问题仍用文字回答。调参数、排序和勾选在本地完成；需要保留时再点击“保存互动进度”。</p>${g.available?'':'<p class="alert">当前部署已关闭互动回答，仍可正常使用文字对话。</p>'}<div class="form-footer"><button type="submit" class="button primary">保存设置</button></div></form>`);}

async function refreshData(){const id=state.renderId;const [notices,tasks]=await Promise.all([api('/notices'),api('/tasks')]);if(id===state.renderId){state.notices=notices;state.tasks=tasks;document.dispatchEvent(new CustomEvent('campus:data-updated'));}reminders.refresh();}
async function route(){
  const id=++state.renderId;
  const previousContent=$('#content');if(previousContent){previousContent.inert=true;previousContent.setAttribute('aria-busy','true');previousContent.classList.add('route-pending');}
  reviewObserver.leave();
  clearTimeout(searchTimer);state.dialogRequest=(state.dialogRequest||0)+1;
  persistCurrentForms();
  if($('#dialog')?.open)$('#dialog').close();
  await drafts.flushAll().catch(error=>toast(error.message,true));
  if(id!==state.renderId)return;
  let page=location.hash.slice(1)||'dashboard';
  const recordTarget=/^(tasks|calendar|memory)\/([A-Za-z0-9_-]{1,100})$/.exec(page);
  const materialTarget=/^chat\/([A-Za-z0-9_-]{1,100})\/source\/([A-Za-z0-9_-]{1,100})$/.exec(page);
  const branchTarget=/^chat\/([a-f0-9]{32})\/branch\/([a-f0-9]{32})$/.exec(page);
  if(recordTarget)page=recordTarget[1];
  if(state.insightSelection&&(state.insightSelection.kind!==page||state.insightSelection.owner!==state.session?.user.id))state.insightSelection=null;
  if(page.startsWith('invite=')){state.invite=decodeURIComponent(page.slice(7));history.replaceState(null,'','#register');page='register';}
  if(page==='login')state.invite='';
  if(!state.session&&(page==='privacy'||page==='terms')){await standaloneLegal(page);return;}
  if(!state.session){authPage();return;}
  if(state.invite){await api('/auth/logout',{method:'POST'});state.session=null;drafts.clear();authPage();return;}
  shell(page.split('/')[0]);updateShell(page.split('/')[0]);reminders.start();
  const content=$('#content'),finishRouteFeedback=beginRouteFeedback(content);content.setAttribute('aria-busy','true');content.inert=true;content.classList.add('route-pending');
  try{
    content.dataset.page=page;
    if(page==='chat'||page.startsWith('chat/')){
      await chatUI.render(page.split('/')[1],id,branchTarget?.[2]);
      page=location.hash.slice(1)||'chat';
    }else if(page==='sources'){
      await sourcesUI.render(id);
    }else if(page==='memory'){
      await memoryUI.render();
    }else if(page==='insights'){
      await insightsUI.render(id);
    }else if(page==='privacy'||page==='terms'){
      await legalPage(page,id);
    }else if(page.startsWith('notice/')){
      const n=await api('/notices/'+encodeURIComponent(page.split('/')[1]));
      if(n.draft&&n.status!=='confirmed')await drafts.load('notice:'+n.id+':'+n.version);
      if(id!==state.renderId)return;noticeDetail(n);attachDraftForm();
    }else{
      await refreshData();
      if(page==='new')await drafts.load('new-notice');
      if(id!==state.renderId)return;
      await ({dashboard,tasks:taskList,notices:noticeList,new:newNotice,intake:()=>intakeUI.render(),calendar:calendarPage,settings:settingsPage}[page]||dashboard)();
      if(page==='new'){restoreNoticeForm();if(state.sourcePreset){const f=$('#notice-form');if(!f.elements.source_label.value)f.elements.source_label.value=state.sourcePreset.name;if(!f.elements.source_url.value)f.elements.source_url.value=state.sourcePreset.url;state.sourcePreset=null;persistCurrentForms();}}
    }
    if(id!==state.renderId)return;
    content.dataset.page=page;
    simplifyPageHeading();
    try{
      if(recordTarget?.[1]==='tasks')await workflowUI.openTask(recordTarget[2]);
      else if(recordTarget?.[1]==='calendar')calendarUI.openRecord(recordTarget[2]);
      else if(recordTarget?.[1]==='memory')await memoryUI.openRecord(recordTarget[2]);
    }catch(error){if(id===state.renderId)toast(error.message||'这项记录已移除或无法访问。',true);}
    if(materialTarget)await chatUI.preview(materialTarget[2]);
    choreograph(content);
  }catch(error){if(id!==state.renderId)return;if(error.status===401){state.session=null;drafts.clear();authPage();}else {if(!('status' in error))console.error('界面加载失败',error);content.innerHTML=empty('暂时未能打开',('status' in error)?error.message:'页面暂时未能显示，你的已保存内容仍然保留。请重新加载。',button('重新加载','refresh'),false,'static');}}
  finally{finishRouteFeedback();if(id===state.renderId&&$('#content')){content.inert=false;content.removeAttribute('aria-busy');content.classList.remove('route-pending');}}
}
function simplifyPageHeading(){
  for(const header of $$('#content .page-title')){
    header.classList.add('workspace-page-heading');
    for(const node of header.querySelectorAll(':scope > p,:scope > .eyebrow,:scope > div > p,:scope > div > .eyebrow'))node.remove();
    const title=header.querySelector('h1');
    if(title&&!$('#content').dataset.page.startsWith('notice/')){title.classList.add('sr-only');if(!header.querySelector('button,a,input,select'))header.classList.add('sr-only');}
  }
}

const noticeProgress=createNoticeProgress({state,api,refresh:()=>refreshNotice()});
async function refreshNotice(){const id=state.renderId,nid=state.notice.id;const n=await api('/notices/'+nid);if(id===state.renderId&&location.hash==='#notice/'+nid)noticeDetail(n);}
function showNoticeResult(n,id){if(id===state.renderId&&location.hash==='#notice/'+n.id)noticeDetail(n);}
function findTask(id){return state.tasks.find(t=>t.id===id)||state.notice?.tasks.find(t=>t.id===id);}
function actionableToast(message,label,action){
  toast(message,false,{duration:12000});const element=$('#toast');element.classList.add('has-action');
  const control=document.createElement('button');control.type='button';control.className='toast-action';control.textContent=label;
  control.addEventListener('click',async()=>{control.disabled=true;try{await action();}catch(error){toast(error.message,true);}},{once:true});
  element.querySelector('[data-toast-close]').before(control);
}
function displayTaskUpdate(updated){document.dispatchEvent(new CustomEvent('campus:data-updated'));state.tasks=state.tasks.map(t=>t.id===updated.id?updated:t);if(state.notice?.tasks)state.notice.tasks=state.notice.tasks.map(t=>t.id===updated.id?updated:t);const page=location.hash.slice(1).replace(/^(tasks|calendar|memory)\/.*/, '$1');if(page==='tasks')taskList();else if(page==='calendar')calendarUI.refresh();else if(page==='dashboard')dashboard();else if(page==='notice/'+updated.notice_id)noticeDetail(state.notice);}
async function toggleTask(id,routeId){
  const old=findTask(id);if(!old||old.status==='cancelled')return;
  const owner=state.session?.user?.id,next=old.status==='done'?'pending':'done';
  const controls=$$(`[data-action="toggle-task"][data-id="${CSS.escape(id)}"]`),focused=controls.includes(document.activeElement),disabledBefore=new Map(controls.map(b=>[b,b.disabled]));
  const paint=(status,busy)=>{for(const control of controls){
    if(!control.isConnected)continue;
    control.classList.toggle('checked',status==='done');control.setAttribute('aria-pressed',String(status==='done'));
    control.setAttribute('aria-label',status==='done'?'恢复待完成':'标记完成');control.innerHTML=status==='done'?icon('check'):'';
    control.disabled=busy||disabledBefore.get(control);busy?control.setAttribute('aria-busy','true'):control.removeAttribute('aria-busy');control.closest('.task-row')?.classList.toggle('is-saving',busy);control.closest('.task-row')?.classList.toggle('done',status==='done');
  }};
  paint(next,true);
  let updated;
  try{updated=await api('/tasks/'+id,{method:'PUT',json:{version:old.version,data:old.data,status:next,reason:next==='done'?'本人标记完成':'本人恢复为待完成'}});}
  catch(error){if(state.session?.user?.id===owner&&routeId===state.renderId)paint(old.status,false);throw error;}
  if(state.session?.user?.id!==owner)return;
  if(routeId===state.renderId){displayTaskUpdate(updated);if(focused)$(`[data-action="toggle-task"][data-id="${CSS.escape(id)}"]`)?.focus({preventScroll:true});}else await refreshData();
  actionableToast(updated.status==='done'?'已完成':'已恢复为待完成','撤回',async()=>{
    if(state.session?.user?.id!==owner)return;
    const restored=await api('/tasks/'+id,{method:'PUT',json:{version:updated.version,data:updated.data,status:old.status,reason:'本人撤回刚才的状态修改'}});
    if(state.session?.user?.id!==owner)return;
    const page=location.hash.slice(1);
    if(['tasks','dashboard','calendar'].includes(page)||page==='notice/'+old.notice_id)displayTaskUpdate(restored);else await refreshData();
    toast('已撤回');
  });
  if(updated.status==='done'&&!state.tasks.some(t=>taskIsPending(t)))celebrateCompletion();
}
async function editTask(id){const t=findTask(id);if(!t)return;const routeId=state.renderId,request=state.dialogRequest=(state.dialogRequest||0)+1;const n=await api('/notices/'+t.notice_id);if(routeId!==state.renderId||request!==state.dialogRequest)return;const current=n.tasks.find(x=>x.id===id);if(!current)return;const cacheKey='task:'+current.id+':'+current.version;const cached=await drafts.load(cacheKey);if(routeId!==state.renderId||request!==state.dialogRequest)return;persistCurrentForms();state.notice=n;state.editTask=current;drafts.activate(cacheKey);const shown=cached.payload?.data?{...current,data:cached.payload.data}:current;showDialog('编辑个人待办',`<form id="task-form" data-cache-key="${cacheKey}">${taskEditor(shown,0,true)}${taskAttachments(current)}<div class="form-grid"><label class="field">状态<select name="status" aria-label="状态">${[['pending','待完成'],['done','已完成'],['cancelled','已取消']].map(([v,l])=>`<option value="${v}" ${(cached.payload?.status||current.status)===v?'selected':''}>${l}</option>`).join('')}</select></label>${field('修改原因','reason',cached.payload?.reason||'','text','required maxlength="500" placeholder="例如：核对原文后更正截止日期"')}</div><p class="footnote">这里的“完成”是你自己的记录。改过已导出到手机日历的事项，记得在日历里同步一下。</p><div class="form-footer"><button class="button primary" type="submit">保存修改</button></div></form>`);}
async function exportTasks(tasks){if(!tasks.length)throw new Error('当前没有可导出的事项，请先核对条件、参加意愿和时间。');if(!tasks.length){toast('没有可导出的已核实事项',true);return;}const blob=await api('/calendar/export',{method:'POST',json:{task_ids:tasks.map(t=>t.id),versions:Object.fromEntries(tasks.map(t=>[t.id,t.version]))},blob:true});download(blob,'校园事项.ics');toast('日历文件已下载。导入手机或电脑日历后，记得看看提醒有没有打开。');await refreshData();if(location.hash==='#calendar')calendarPage();}
function supplementDialog(){showDialog('补充通知材料',`<form id="supplement-form" class="stack">${field('材料说明','label','','text','maxlength="80" placeholder="例如：正式更正通知、附件补充文字"')}${area('补充文字','body','',6,'maxlength="10000"')}<label class="upload">${icon('upload')}<strong>添加文件或图片</strong><input name="files" type="file" multiple accept=".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg,.webp,.mp4,.webm" aria-label="上传补充附件"></label><div class="files-list" id="files-list"></div><p class="small muted">补充之后需要重新整理一次，已有待办会保留。</p><div class="form-footer"><button class="button primary" type="submit">保存补充材料</button></div></form>`);}
async function handleClick(e){const target=e.target.closest('[data-action]');if(!target)return;const action=target.dataset.action,id=target.dataset.id;if(action==='accept-dialog'||target.disabled)return;if(!['menu','filter','clear-date','profile-section','quick-search','open-notice'].includes(action))target.disabled=true;const actionRoute=state.renderId,actionView=captureUiContext(state,target);try{
  if(action==='close-dialog')$('#dialog').close();
  else if(action==='menu')setMenu(!$('.shell').classList.contains('menu-open'),true,target);
  else if(action==='quick-search')quickSearch();
  else if(action==='reminders')await reminders.open();
  else if(action==='delete-account')await deleteAccountDialog();
  else if(action==='settings-profile')profileDialog();
  else if(action==='settings-preferences')preferencesDialog();
  else if(action==='settings-data')dataDialog();
  else if(action==='settings-security')securityDialog();
  else if(action==='settings-model')modelDialog();
  else if(action==='settings-speech')await speechDialog({state,api,esc,toast,showDialog});

  else if(action==='settings-genui')genuiDialog();
  else if(action==='profile-section'){$$('[data-profile-group]').forEach(node=>node.hidden=node.dataset.profileGroup!==target.dataset.section);$$('[data-action=profile-section]').forEach(node=>{const active=node===target;node.classList.toggle('active',active);node.setAttribute('aria-selected',String(active));node.tabIndex=active?0:-1;});moveSelection($('.profile-tabs'));}
  else if(action==='logout'){persistCurrentForms();await drafts.flushAll();await api('/auth/logout',{method:'POST'});state.session=null;state.invite='';drafts.clear();reminders.stop();state.tasks=[];state.notices=[];state.notice=null;location.hash='login';authPage();}
  else if(action==='open-notice')location.hash='notice/'+id;
  else if(action==='refresh')await route();
  else if(action==='refresh-notice')await refreshNotice();
  else if(action==='filter'){state.insightSelection=null;state.filter=target.dataset.filter;state.taskPage=1;taskList();}
  else if(action==='clear-task-filters'){state.insightSelection=null;state.filter='all';state.query='';state.dateFilter='';state.taskPage=1;$('#task-search').value='';$('#task-date').value='';taskList();$('#task-search').focus({preventScroll:true});}
  else if(action==='clear-date'){state.dateFilter='';state.taskPage=1;$('#task-date').value='';taskList();$('#task-search').focus({preventScroll:true});}
  else if(action==='task-page'){state.taskPage=Number(target.dataset.page);taskList();}
  else if(action==='download-draft'){const form=target.closest('form');persistCurrentForms();download(new Blob([JSON.stringify(drafts.peek(form.dataset.cacheKey).payload,null,2)],{type:'application/json'}),'未保存的编辑内容.json');}
  else if(action==='retry-draft'){persistCurrentForms();await drafts.flush(target.closest('form').dataset.cacheKey);}
  else if(action==='discard-missing-files'){const cached=drafts.peek('new-notice').payload;if(cached)drafts.stage('new-notice',{...cached,files:[]});noticeFiles=[];$('#missing-files')?.remove();persistCurrentForms();}
  else if(action==='manual'){showNoticeResult(await api(`/notices/${state.notice.id}/manual`,{method:'POST',json:{version:state.notice.version}}),actionRoute);}
  else if(action==='generate'){if(!$('#ai-consent')?.checked){toast('请先勾选同意，再让 AI 整理',true);return;}const n=state.notice,processingMode=$('#notice-processing-mode')?.value||'configured';$('#draft-pane').innerHTML=noticeProgressPanel(n,{esc,brandMotion,button});noticeProgress.watch(n,{pending:true});try{const result=await api(`/notices/${n.id}/generate`,{method:'POST',json:{version:n.version,allow_external_processing:true,...(state.session.ai.notice_modes?{processing_mode:processingMode}:{})}});showNoticeResult(result,actionRoute);}catch(error){if(actionRoute===state.renderId&&location.hash==='#notice/'+n.id)await refreshNotice();throw error;}}
  else if(action==='quality-step'){const index=state.drafts.findIndex(task=>task._source_index===Number(target.dataset.sourceIndex));const editor=$(`[data-editor="${index}"]`);editor?.scrollIntoView({block:'start',behavior:'smooth'});editor?.querySelector('[name=title]')?.focus({preventScroll:true});}
  else if(action==='regenerate'){if(await ask('重新整理','将以当前材料重新建立草稿，已有待办会保留。确认新草稿时可选择逐项更新。','继续')){state.notice.draft=null;state.notice.status='received';noticeDetail(state.notice);}}
  else if(action==='add-task'){captureDrafts();state.drafts.push(initializeDraftPlans([blankTask()])[0]);$('#draft-editors').innerHTML=state.drafts.map((t,i)=>taskEditor(t,i)).join('');const last=$$('[data-editor]').at(-1);last.scrollIntoView({block:'nearest'});$('[name=title]',last).focus();attachDraftForm();persistCurrentForms();}
  else if(action==='evidence'){const source=target.dataset.source,locator=target.dataset.locator;if($('#dialog').open)$('#dialog').close();const card=$$('[data-source-card]').find(el=>el.dataset.sourceCard===source);if(card){card.open=true;card.closest('.notice-originals').open=true;const section=$$('.source-section',card).find(el=>el.dataset.locator===locator);section?.scrollIntoView({block:'center',behavior:'smooth'});section?.animate([{background:'#fff1bb'},{background:'transparent'}],{duration:2500});}else{location.hash='notice/'+state.notice.id;}}
  else if(action==='supplement')supplementDialog();
  else if(action==='materials'){if(await ask('核对材料完整性',state.notice.materials_complete?'标记为材料未齐后，需重新核对草稿和相关期限。':'请确认正文提及的关键附件均已提交，解析异常已逐份核对。','确认'))showNoticeResult(await api(`/notices/${state.notice.id}/materials`,{method:'POST',json:{version:state.notice.version,complete:!state.notice.materials_complete}}),actionRoute);}
  else if(action==='source-resolve'||action==='source-archive'){state.sourceAction={id,action:action==='source-resolve'?'resolve':'archive'};showDialog(action==='source-resolve'?'记录材料核实结果':'移出当前材料',`<form id="source-form" class="stack"><p class="small muted">${action==='source-resolve'?'请对照原件检查表格、图片及未提取部分，补齐关键文字后再确认。':'原件和历史依据会保留，但不再送入新一轮 AI 处理。请确保当前材料仍完整。'}</p>${area('核实结果 / 原因','reason','',4,'required minlength="2" maxlength="500"')}<div class="form-footer"><button class="button primary" type="submit">确认并记录</button></div></form>`);}
  else if(action==='edit-task')await editTask(id);
  else if(action==='toggle-task')await toggleTask(id,actionRoute);
  else if(action==='export-task')await exportTasks([findTask(id)]);
  else if(action==='export-all'){const candidates=state.tasks.filter(t=>taskIsPending(t)&&!t.execution_issues?.length&&t.data.scope==='personal'&&calendarReady(t.data)&&(!t.data.uncertainties.length||t.data.resolution_note));await exportTasks(candidates);}
  else if(action==='notice-chat'){const result=await api('/notices/'+state.notice.id+'/conversation',{method:'POST',json:{version:state.notice.version}});if(actionView.sameDialog())location.hash='chat/'+result.conversation_id;else if(actionView.sameUser())toast('通知对话已准备好，可在助手中继续查看。');}
  else if(action==='move-step'){captureDrafts();const index=Number(target.dataset.index),next=index+Number(target.dataset.direction);if(next>=0&&next<state.drafts.length){const [item]=state.drafts.splice(index,1);state.drafts.splice(next,0,item);$('#draft-editors').innerHTML=state.drafts.map((t,i)=>taskEditor(t,i)).join('');persistCurrentForms();}}
  else if(action==='history'){const items=await api(`/notices/${state.notice.id}/history`);if(!actionView.sameDialog())return;const labels={create_notice:'保存通知',supplement:'补充材料',materials_review:'核对材料完整性',source_resolve:'核实材料',source_archive:'移出当前材料',ai_processing_consent:'确认模型外部处理',confirm_task:'确认新增待办',confirm_revision:'确认更新待办',confirm_draft:'确认草稿',update_task:'修改待办',calendar_export:'导出日历'};showDialog('修改与导出记录',items.length?items.map(item=>`<div class="history-entry"><div class="between"><strong class="small">${esc(labels[item.action]||item.action)}</strong><span class="history-badge">${dateText(item.created_at)}</span></div><details><summary>查看修改前后值</summary>${item.before_json?`<h4>修改前</h4><pre>${esc(JSON.stringify(JSON.parse(item.before_json),null,2))}</pre>`:''}<h4>修改后</h4><pre>${esc(JSON.stringify(JSON.parse(item.after_json||'null'),null,2))}</pre></details></div>`).join(''):'还没有修改记录');}
  else if(action==='delete-notice'){if(await ask('永久删除此通知','这会删除这则通知的正文、附件、草稿、待办和修改记录，删除后无法恢复。需要留存的话请先导出；手机日历里的副本需要你自己删除。','永久删除')){await api('/notices/'+state.notice.id,{method:'DELETE',json:{version:state.notice.version}});toast('通知及关联数据已删除');location.hash='notices';}}
  else if(action==='invite'){const result=await api('/admin/invites',{method:'POST'});if(!actionView.sameDialog())return;showDialog('成员邀请链接',`<p>将下方链接交给受邀成员。有效期 ${result.expires_in_days} 天，限注册一次。</p><div class="invitation" id="invite-link">${esc(result.url)}</div><div class="form-footer">${button('复制邀请链接','copy-invite','primary')}</div>`);}
  else if(action==='copy-invite'){try{await navigator.clipboard.writeText($('#invite-link').textContent);toast('已复制邀请链接');}catch{toast('请选中上方邀请链接并复制');}}
}catch(error){toast(error.message,true);if(error.status===401){state.session=null;authPage();}}finally{target.disabled=false;}}
document.addEventListener('click',handleClick);
document.addEventListener('submit',async e=>{if(e.target.dataset.workspaceForm)return;e.preventDefault();const form=e.target;if(!(form instanceof HTMLFormElement))return;if(form.id==='notice-form'&&noticeUI.advanceIfNeeded())return;const submit=$('[type=submit]',form);if(submit?.disabled)return;const submittedView=captureUiContext(state,form),finishFeedback=beginFormFeedback(form,form.id==='auth-form'?'正在验证账号…':'正在保存…');if(!finishFeedback)return;const submittedRoute=state.renderId,submittedNotice=state.notice,submittedTask=state.editTask,submittedDialog=state.dialogRequest,submittedSource=state.sourceAction;const fd=new FormData(form);persistCurrentForms();const submittedCache=form.dataset.cacheKey?drafts.checkpoint(form.dataset.cacheKey):null;const submittedDrafts=form.id==='draft-form'?structuredClone(state.drafts):null;const submittedQuality=form.id==='draft-form'?structuredClone(state.qualityDecisions):null;const submittedManualQuality=state.manualQualityReviewed;const submittedObservation=form.id==='draft-form'?reviewObserver.capture(form):null;const submittedTaskData=form.id==='task-form'?readEditor($('[data-editor]',form),submittedTask.data):null;form.inert=true;try{if(form.dataset.cacheKey)await drafts.flush(form.dataset.cacheKey);
  if(form.id==='auth-form'){await authUI.submit(form,fd);}
  else if(form.id==='notice-form'||form.id==='supplement-form'){const supplement=form.id==='supplement-form';fd.delete('rights');const files=fd.getAll('files').filter(f=>f.size);fd.delete('files');files.forEach(f=>fd.append('files',f));if(!supplement&&drafts.peek('new-notice').payload?.files?.length&&!files.length)throw new Error('已恢复文字草稿，请重新选择附件，或明确移除之前的附件记录');if(files.length>5||files.some(f=>f.size>5*1024*1024))throw new Error('最多 5 份附件，每份不超过 5 MB');if(supplement)fd.set('version',submittedNotice.version);else{fd.set('materials_complete',$('[name=materials_complete]',form).checked?'true':'false');fd.set('published_at',toTime(fd.get('published_at'))||'');}let n;try{n=await api(supplement?`/notices/${submittedNotice.id}/supplement`:'/notices',{method:'POST',body:fd});}catch(error){if(error.detail?.duplicate_id){if(!submittedView.sameDialog()){if(submittedView.sameUser())toast('已有相同通知，本次未另建；可在通知资料中查看。');return;}const existing=error.detail.duplicate_id;if(error.detail.reason==='request_changed')fd.set('request_id',crypto.randomUUID());showDialog('核对已有通知',`<p>${error.detail.reason==='request_changed'?'这次提交已保存，但当前草稿与已保存内容不同。请先核对已有通知，需要另建时再确认。':'当前账号已有相同内容。可复用原通知；不同学期或不同批次请明确另建。'}</p><div class="form-footer"><a class="button" href="#notice/${existing}" data-action="close-dialog">打开已有通知</a>${button('这是另一批次，另建','duplicate-create','primary')}</div>`);$('[data-action=duplicate-create]').addEventListener('click',async ev=>{const control=ev.currentTarget;if(control.disabled)return;const view=captureUiContext(state,control);control.disabled=true;try{fd.set('allow_duplicate','true');const r=await api('/notices',{method:'POST',body:fd});if(!view.sameUser())return;const retired=await retireAfterSave('new-notice',submittedCache);if(retired)noticeFiles=[];if(view.sameDialog()){$('#dialog').close();location.hash='notice/'+r.id;}toast('另一批次通知已保存，可在通知资料查看'+(retired===null?'；旧草稿清理未完成，请核对暂存状态':''),retired===null);}catch(err){if(view.sameUser())toast(err.message,true);}finally{control.disabled=false;}});return;}throw error;}if(!submittedView.sameUser())return;if(supplement){if(submittedView.sameDialog())$('#dialog').close();showNoticeResult(n,submittedRoute);toast('补充材料已保存，请重新整理一次');}else{const retired=await retireAfterSave('new-notice',submittedCache);if(retired)noticeFiles=[];if(submittedRoute===state.renderId){location.hash='notice/'+n.id;if(retired===null)toast('通知已保存；旧草稿清理未完成，重新提交前请核对通知资料',true);}else toast(retired===null?'通知已保存；暂存清理未完成，请核对新草稿的暂存状态':'通知已保存，可在通知资料查看',retired===null);}}
  else if(form.id==='draft-form'){const planned=prepareConfirmation(submittedDrafts,submittedNotice);await api(`/notices/${submittedNotice.id}/confirm`,{method:'POST',json:{version:submittedNotice.version,...planned,...prepareQualityConfirmation(submittedDrafts,submittedNotice,submittedQuality,submittedManualQuality),quality_resolution:String(fd.get('quality_resolution')||''),...(submittedNotice.review_observation_contract===1?{review_observation:submittedObservation}:{}),reviewed:true}});const retired=await retireAfterSave(form.dataset.cacheKey,submittedCache);toast('已保存到你的待办'+(retired===null?'；旧草稿清理未完成，请核对暂存状态':''),retired===null);document.dispatchEvent(new CustomEvent('campus:milestone',{detail:'notice-confirmed'}));await refreshData();if(submittedRoute===state.renderId)await refreshNotice();}
  else if(form.id==='task-form'){await drafts.flushAll();const old=submittedTask;const data=submittedTaskData;const updated=await api('/tasks/'+old.id,{method:'PUT',json:{version:old.version,data,status:fd.get('status'),reason:fd.get('reason')}});const retired=await retireAfterSave(form.dataset.cacheKey,submittedCache);if(submittedDialog===state.dialogRequest)$('#dialog').close();toast('修改已保存'+(retired===null?'；旧草稿清理未完成，请核对暂存状态':''),retired===null,{duration:15000,action:{label:'撤销',run:async()=>{if(!submittedView.sameUser())throw Error('账号已变化，不能撤销原账号的待办。');const restored=await api('/tasks/'+old.id,{method:'PUT',json:{version:updated.version,data:old.data,status:old.status,reason:'撤销上一次编辑'}});if(submittedView.sameRoute())displayTaskUpdate(restored);}}});if(submittedRoute===state.renderId)displayTaskUpdate(updated);}
  else if(form.id==='genui-settings-form'){const previous=structuredClone(state.session.genui),prefs=await api('/genui/preferences',{method:'PUT',json:{version:state.session.genui.version,enabled:fd.has('enabled'),theme:'light'}});if(!submittedView.sameUser())return;state.session.genui=prefs;toast('互动回答设置已保存',false,{duration:15000,action:{label:'撤销',run:async()=>{if(!submittedView.sameUser())throw Error('账号已变化，不能撤销原账号的设置。');const restored=await api('/genui/preferences',{method:'PUT',json:{version:prefs.version,enabled:previous.enabled,theme:previous.theme||'light'}});if(!submittedView.sameUser())return;state.session.genui=restored;if(submittedView.sameRoute()&&location.hash==='#settings')settingsPage({preserveScroll:true});}}});if(submittedView.sameDialog())$('#dialog').close();if(submittedView.sameRoute()&&location.hash==='#settings')settingsPage({preserveScroll:true});}
  else if(form.id==='preferences-form'){const profile=await saveProfileForm(api,form,Object.fromEntries(fd));if(!submittedView.sameUser())return;applyProfileForm(state,form,profile,Object.fromEntries(fd));if(submittedView.sameDialog())$('#dialog').close();updateAccount();if(submittedView.sameRoute()&&location.hash==='#settings')settingsPage({preserveScroll:true});profileSaved('偏好已保存，下一次回答会采用。',form,profile,Object.fromEntries(fd),submittedView);}
  else if(form.id==='profile-form'){const profile=await saveProfileForm(api,form,Object.fromEntries(fd));if(!submittedView.sameUser())return;applyProfileForm(state,form,profile,Object.fromEntries(fd));updateAccount();profileSaved('身份条件已保存',form,profile,Object.fromEntries(fd),submittedView);if(submittedView.sameDialog())$('#dialog').close();if(submittedView.sameRoute()&&location.hash==='#settings')settingsPage({preserveScroll:true});}
  else if(form.id==='delete-account-form'){const values=Object.fromEntries(fd);if(String(values.confirm).trim()!=='注销账号')throw new Error('请输入“注销账号”四个字确认');await api('/account/delete',{method:'POST',json:values});state.session=null;state.invite='';drafts.clear();reminders.stop();state.tasks=[];state.notices=[];state.notice=null;state.legal=null;if($('#dialog').open)$('#dialog').close();location.hash='login';authPage();toast('账号已经注销，谢谢你用过珞珈信使。');return;}
  else if(form.id==='password-form'){await api('/auth/password',{method:'POST',json:Object.fromEntries(fd)});if(!submittedView.sameUser())return;const session=await api('/session');if(!submittedView.sameUser())return;state.session=session;form.reset();toast('密码已更新，其他设备需要重新登录');}
  else if(form.id==='source-form'){const a=submittedSource;const n=await api(`/notices/${submittedNotice.id}/sources/${a.id}/review`,{method:'POST',json:{version:submittedNotice.version,action:a.action,reason:fd.get('reason')}});if(submittedDialog===state.dialogRequest)$('#dialog').close();showNoticeResult(n,submittedRoute);toast('已记下，请重新整理一次');}
}catch(error){if(submittedView.sameUser()){if(form.isConnected){if(!error.formHandled)formError(form,error.message);}else toast(error.message,true);if(error.status===401){state.session=null;authPage();}}}finally{form.inert=false;finishFeedback();if(form.id==='draft-form')reviewObserver.resume(form);}});
let searchTimer;
document.addEventListener('input',e=>{if(e.target.id==='task-search'){const pos=e.target.selectionStart;state.query=e.target.value;state.taskPage=1;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{if($('#task-results')&&$('#content')?.dataset.page==='tasks')taskList();},200);}if(e.target.name==='body'&&$('#char-count'))$('#char-count').textContent=e.target.value.length.toLocaleString()+' / 10,000 字';});
document.addEventListener('change',e=>{if(e.target.id==='task-date'){state.dateFilter=e.target.value;state.taskPage=1;taskList();}if(e.target.name==='files'&&e.target.closest('#notice-form')){noticeFiles=[...e.target.files];const cached=drafts.peek('new-notice').payload;if(cached)drafts.stage('new-notice',{...cached,files:noticeFiles.map(f=>f.name)});$('#missing-files')?.remove();}});
window.addEventListener('hashchange',()=>{if($('#dialog').open)$('#dialog').close();route();});
let noticeFiles=[];
const drafts=createDraftStore(api,(key,message,error)=>{
  const form=$$('form[data-cache-key]').find(f=>f.dataset.cacheKey===key);
  if(form){let label=$('.autosave-status',form);if(!label){label=document.createElement('div');label.className='autosave-status';label.setAttribute('role','status');form.prepend(label);}label.textContent=message;label.classList.toggle('save-error',error);if(error)label.insertAdjacentHTML('beforeend',button('重试暂存','retry-draft','small plain')+button('下载本页编辑','download-draft','small plain'));}
});
installFormHistory(document.body);
function updateShell(page){
  syncChrome(page);syncPageNavigation(state.session?.user?.id);updateAccount();
  const name=({memory:'我的记忆',privacy:'隐私政策',terms:'用户协议'})[page]||navs.find(n=>n[0]===page)?.[2]||'处理通知';
  $$('.nav-item').forEach(a=>{const active=a.hash==='#'+(['new','notice'].includes(page)?'notices':page);a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  const label=$('.topbar-left b');if(label)label.textContent=name;
  setMenu(false,false);
  moveSelection($('.sidebar nav'),'.nav-item.active');
}
function attachDraftForm(){
  const form=$('#draft-form');if(!form||!state.notice){reviewObserver.leave();return;}
  const key='notice:'+state.notice.id+':'+state.notice.version;
  form.dataset.cacheKey=key;drafts.activate(key);
  if(state.notice.review_observation_contract===1)reviewObserver.bind(form,state.session.user.id+':'+key);
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
  if(noticeFiles.length){const transfer=new DataTransfer();noticeFiles.forEach(f=>transfer.items.add(f));form.elements.files.files=transfer.files;}
  else if(data.files?.length){const message=document.createElement('div');message.id='missing-files';message.className='alert';message.innerHTML=`文字已经恢复。附件需要重新选一下：${data.files.map(esc).join('、')}。${button('本次不再使用这些附件','discard-missing-files','small plain')}`;form.prepend(message);}
  const label=document.createElement('div');label.className='autosave-status';label.textContent='上次没写完的内容已经帮你恢复';form.prepend(label);
  $('#char-count').textContent=form.elements.body.value.length.toLocaleString()+' / 10,000 字';
  noticeUI.restoreFiles(form);intakeUI.restoreSingle(form);
}
function persistCurrentForms(){
  workflowUI.persist();
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
      captureDrafts();syncIssueControls(form,state.notice.draft?.quality||{},state.drafts,state.qualityDecisions,esc);const snapshot={tasks:state.drafts,quality_resolution:state.qualityResolution,issue_resolutions:state.qualityDecisions,manual_quality_reviewed:state.manualQualityReviewed};if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,snapshot);
    }else if(form.id==='task-form'&&state.editTask){
      const snapshot={data:readEditor($('[data-editor]',form),state.editTask.data),status:form.elements.status.value,reason:form.elements.reason.value};
      if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,snapshot);
    }
  }
}
async function retireAfterSave(key,ticket){
  if(!key)return;
  try{return await drafts.retire(key,ticket);}catch(error){return null;}
}
function taskList(){
  const selected=state.insightSelection?.kind==='tasks'?state.insightSelection:null;
  const filtered=state.tasks.filter(t=>(!selected||selected.ids.includes(t.id))&&(state.filter==='all'||(taskMatchesFilter(t,state.filter)??(state.filter==='soon'?(t.due_soon||t.overdue)&&taskIsPending(t):state.filter==='unverified'?taskIsPending(t)&&t.data.scope==='personal'&&needsTimingReview(t):t.status===state.filter)))&&(!state.query||(t.data.title+' '+t.notice_title+' '+t.data.materials.join(' ')).toLowerCase().includes(state.query.toLowerCase()))&&(!state.dateFilter||taskOnDay(t.data,state.dateFilter)));
  if(!$('#task-results'))$('#content').innerHTML=`<div class="page-title between task-page-heading"><div><h1>我的待办</h1></div><div class="search"><input id="task-search" placeholder="搜索标题、通知或材料…" aria-label="搜索待办" value="${esc(state.query)}"></div><a href="#new" class="button primary">${icon('plus')} 处理通知</a></div><div class="toolbar"><div class="tabs" role="tablist" aria-label="待办状态">${[['pending','待完成'],['followup','待跟进'],['changes','变更待核实'],['soon','近期'],['unverified','时间待核对'],['sync','日历待同步'],['done','已完成'],['cancelled','已取消'],['all','全部']].map(([v,l])=>`<button role="tab" class="tab" data-action="filter" data-filter="${v}">${l}</button>`).join('')}</div></div><div class="task-filter-row"><div class="view-toggle" role="group" aria-label="待办展示方式"><button type="button" data-task-view="board" aria-label="看板视图">${icon('grid')}<span>看板</span></button><button type="button" data-task-view="list" aria-label="清单视图">${icon('menu')}<span>清单</span></button></div><details class="task-date-filter"><summary>${icon('calendar')}<span id="task-date-label">日期筛选</span></summary><div class="filters"><label for="task-date">按期限或活动日期</label><input id="task-date" type="date" value="${esc(state.dateFilter)}">${button('清除日期','clear-date','small plain')}</div></details><span class="small muted" id="task-count"></span></div><div class="divider"></div><div class="panel flush task-results" id="task-results" role="tabpanel" aria-live="polite"></div><div id="task-pages" class="pagination"></div>`;
  $$('[data-task-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.taskView===state.taskView)));
  $('#task-results').classList.toggle('board-view',state.taskView==='board');
  $$('[data-filter]').forEach(b=>{const active=b.dataset.filter===state.filter;b.classList.toggle('active',active);b.setAttribute('aria-selected',active?'true':'false');b.tabIndex=active?0:-1;});
  moveSelection($('.tabs'));
  let selectionNote=$('#task-insight-filter');if(!selectionNote){selectionNote=document.createElement('div');selectionNote.id='task-insight-filter';selectionNote.className='small muted';$('#task-results').before(selectionNote);}selectionNote.innerHTML=selected?`<span>数据看板 · ${esc(selected.label)}</span> ${button('清空筛选','clear-task-filters','small plain')}`:'';
  $('#task-count').textContent=filtered.length+' 项';$('#task-date-label').textContent=state.dateFilter||'日期筛选';
  const pages=Math.max(1,Math.ceil(filtered.length/20));state.taskPage=Math.min(state.taskPage,pages);
  const visible=filtered.slice((state.taskPage-1)*20,state.taskPage*20);
  $('#task-results').innerHTML=visible.length?(state.taskView==='board'?taskBoardMarkup(visible,taskRow,icon):visible.map(taskRow).join('')):(state.query||state.dateFilter||selected?empty('暂时没有匹配的事项','换一个关键词，或清空筛选。已经保存的事项可以从全部列表找回。',button('清空筛选，查看全部','clear-task-filters','small'),false,'search'):state.filter==='pending'&&state.tasks.some(t=>t.status==='done')?empty('已确认的待办，暂时都处理好了','给自己留一点松弛的时间，也可以去日历看看其他安排。','<a class="button small" href="#calendar">看看日历</a>',false,'serene'):state.filter==='unverified'?empty('没有待核对时间的事项','已确认的待完成事项中，暂时没有需要核对时间的步骤。已完成事项可从对应列表回看。',button('查看全部事项','clear-task-filters','small'),false,'serene'):empty(state.tasks.length?'当前状态下没有事项':'从清楚的一步开始',state.tasks.length?'切换到全部，可以查看其他状态的事项。':'先保存一则通知，核对后把属于自己的步骤转成待办。',state.tasks.length?button('查看全部事项','clear-task-filters','small'):'<a class="button small" href="#new">处理第一则通知</a>',false,'radar'));

  $('#task-pages').innerHTML=pages>1?`${button('上一页','task-page','small',`data-page="${state.taskPage-1}" ${state.taskPage===1?'disabled':''}`)}<span>第 ${state.taskPage} / ${pages} 页 · 每页 20 项</span>${button('下一页','task-page','small',`data-page="${state.taskPage+1}" ${state.taskPage===pages?'disabled':''}`)}`:'';
}
document.addEventListener('click',e=>{const view=e.target.closest('[data-task-view]');if(view){state.taskView=view.dataset.taskView;taskList();}});
document.addEventListener('input',e=>{if(e.target.closest('form[data-cache-key]'))persistCurrentForms();});
document.addEventListener('change',e=>{if(e.target.closest('form[data-cache-key]'))persistCurrentForms();});
$('#dialog').addEventListener('close',()=>{if($('#dialog').open)return;state.dialogRequest=(state.dialogRequest||0)+1;const closing=state.dialogRequest;persistCurrentForms();drafts.flushAll().catch(error=>toast(error.message,true));
  // 保留内容到淡出结束，避免关闭动画中出现空白框；期间重新打开则不清空。
  setTimeout(()=>{const d=$('#dialog');if(!d.open&&closing===state.dialogRequest)d.replaceChildren();},motionAllowed()?320:0);});
window.addEventListener('beforeunload',e=>{if(drafts.pending()){e.preventDefault();e.returnValue='';}});
window.addEventListener('resize',()=>{moveSelection($('.sidebar nav'),'.nav-item.active');$$('.tabs').forEach(group=>moveSelection(group));});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!$('#dialog').open&&$('.shell')?.classList.contains('menu-open'))setMenu(false);
  if(!event.target.matches('.tab')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=$$('.tab',event.target.parentElement),position=tabs.indexOf(event.target);
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(position+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();tabs[next].focus();tabs[next].click();
});

const authUI=createAuthUI({state,esc,field,api,icon,companion,showDialog,toast,download,route,moveSelection});
const memoryUI=createMemoryUI({state,api,esc,icon,showDialog,toast,ask});
const chatUI=createChatUI({state,api,esc,icon,companion,greeting,toast,showDialog,ask,field,area,drafts,route,memoryUI});
const sourcesUI=createSourcesUI({state,api,esc,icon,field,area,showDialog,ask,toast,route});
$('#dialog').addEventListener('close',()=>{
  const target=dialogReturnTarget,closingFocus=document.activeElement;
  // Safari may return native-dialog focus to the previously focused input,
  // because mouse clicks do not focus buttons there. Restore the real opener.
  // A new user focus change before the next frame still takes precedence.
  requestAnimationFrame(()=>{
    if(document.activeElement!==closingFocus&&document.activeElement!==document.body)return;
    const restored=target?.isConnected?target:target?.dataset.action?.startsWith('settings-')?document.querySelector(`[data-action="${target.dataset.action}"]`):null;
    if(!$('#dialog').open&&restored&&!restored.disabled)restored.focus({preventScroll:true});
  });
});
document.addEventListener('invalid',event=>{const group=event.target.closest('[data-profile-group]');if(group?.hidden)document.querySelector(`[data-action="profile-section"][data-section="${group.dataset.profileGroup}"]`)?.click();},true);
const libraryUI=createLibraryUI({state,esc,icon,noticeRow,empty,moveSelection});
const workflowUI=createWorkflowUI({state,api,esc,icon,showDialog,toast,field,area,timeInput,toTime,drafts,route,displayTaskUpdate,exportTasks});
const reminders=createReminders({state,api,esc,icon,toast,showDialog});
const insightsUI=createInsightsUI({state,api,esc,icon,companion});
const overviewUI=createOverview({state,esc,icon,companion,greeting,taskRow,noticeRow,moveSelection,reminders});
const commandSearch=createCommandSearch({state,api,esc,icon,showDialog,loadingState,empty});
const intakeUI=createNoticeIntakeUI({state,api,esc,icon,toast,showDialog,field,area,drafts,persist:persistCurrentForms,refreshData,onNotice:noticeDetail,toTime});
const noticeUI=createNoticeComposer({esc,field,area,icon,toast,showDialog,api,ask,persist:persistCurrentForms,onRender:form=>intakeUI.attachSingle(form)});
const calendarUI=createCalendarUI({state,api,esc,icon,companion,showDialog,ask,toast,field,area,download,moveSelection,calendarHelp,editTask,taskRow,drafts});
let menuFocusFrame=0,menuFocusTimer=0,menuRequest=0,menuReturnTarget=null;
function setMenu(open,focus=true,opener=null){
  const request=++menuRequest;cancelAnimationFrame(menuFocusFrame);clearTimeout(menuFocusTimer);
  menuFocusFrame=0;menuFocusTimer=0;
  const shell=$('.shell');if(!shell)return;
  const activeBefore=document.activeElement,routeId=state.renderId;
  if(open&&!shell.classList.contains('menu-open'))menuReturnTarget=opener||activeBefore;
  shell.classList.toggle('menu-open',open);$('.mobile-menu')?.setAttribute('aria-expanded',String(open));window.dispatchEvent(new Event('campus:menu'));
  const modal=open&&matchMedia('(max-width:850px)').matches;
  $('.workspace').inert=modal;$('.mobile-bottom-nav').inert=modal;
  if(focus){
    const focusMenu=()=>{
      if(request!==menuRequest||routeId!==state.renderId||!shell.isConnected||$('#dialog')?.open)return;
      const active=document.activeElement;
      if(modal&&matchMedia('(max-width:850px)').matches&&shell.classList.contains('menu-open')){
        if(!$('.sidebar').contains(active))$('.sidebar .nav-item')?.focus({preventScroll:true});
      }else if(!open&&!shell.classList.contains('menu-open')&&(active===activeBefore||active===document.body)){
        const origin=menuReturnTarget,target=origin?.isConnected&&!origin.disabled&&origin.getClientRects().length&&!origin.closest('[inert]')?origin:$('.workspace-chrome-toggle');
        target?.focus({preventScroll:true});
      }
    };
    menuFocusFrame=requestAnimationFrame(focusMenu);
    // A hidden drawer can reject focus until its visibility transition has finished.
    if(modal)menuFocusTimer=setTimeout(focusMenu,260);
  }
}
document.addEventListener('keydown',e=>{
  if(e.key!=='Tab'||$('#dialog').open||!$('.shell')?.classList.contains('menu-open')||!matchMedia('(max-width:850px)').matches)return;
  const focusable=$$('a[href],button:not(:disabled)',$('.sidebar')),first=focusable[0],last=focusable.at(-1);
  if(!$('.sidebar').contains(document.activeElement)){e.preventDefault();first.focus();}else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
});
document.addEventListener('click',e=>{if(e.target.closest('.skip-link')){e.preventDefault();$('#content')?.focus();}});
window.addEventListener('resize',()=>{if(!matchMedia('(max-width:850px)').matches)setMenu(false,false);});
function quickSearch(){commandSearch.open();}

document.addEventListener('click',e=>{const a=e.target.closest('[data-overview-filter]');if(a?.dataset.overviewFilter){state.insightSelection=null;state.filter=a.dataset.overviewFilter;state.query='';state.dateFilter='';state.taskPage=1;}});
initializeCompanion();
initializeMotion();
initializeExperience();
initializeChoreography();
const boot=$('#app .boot');if(boot)boot.innerHTML=brandMotion('stroke','',{once:true,priority:3})+'<p>正在打开个人工作台…</p>';
const [sessionResult,policyResult]=await Promise.allSettled([api('/session'),api('/auth/policy')]);
if(sessionResult.status==='fulfilled')state.session=sessionResult.value;else if(sessionResult.reason.status!==401)toast('无法连接服务：'+sessionResult.reason.message,true);
state.registrationMode=policyResult.status==='fulfilled'?policyResult.value.registration_mode:'unknown';
await route();

installChrome({setMenu});
installPageNavigation();

installAttachmentPreviews({api,toast});

function updateAccount(){const p=state.session.user.profile,u=state.session.user,name=p.preferred_name||u.display_name,avatar=$('.account .avatar'),account=$('.account-name');if(avatar){avatar.textContent=name.slice(0,1);avatar.className='avatar avatar-'+(p.avatar_tone||'forest');}if(account){account.replaceChildren(document.createTextNode(name));const small=document.createElement('small');small.textContent=p.college||({student:'学生',teacher:'教师',staff:'教职工',other:'个人'}[p.campus_role]||'个人')+'空间';account.append(small);}}

installDataTransfer({api,toast,onImported:async()=>{state.session=await api('/session');updateAccount();await refreshData();}});

let layoutFrame=0;window.addEventListener('campus:layout',()=>{cancelAnimationFrame(layoutFrame);layoutFrame=requestAnimationFrame(()=>{moveSelection($('.sidebar nav'),'.nav-item.active');$$('.tabs').forEach(group=>moveSelection(group));});});

let draggedStep=null;
document.addEventListener('dragstart',event=>{const handle=event.target.closest('[data-step-drag]');if(!handle)return;draggedStep=Number(handle.dataset.stepDrag);event.dataTransfer.setData('application/x-campus-step',String(draggedStep));event.dataTransfer.effectAllowed='move';});
document.addEventListener('dragover',event=>{if(draggedStep!==null&&event.target.closest('#draft-editors [data-editor]'))event.preventDefault();});
document.addEventListener('drop',event=>{const to=event.target.closest('#draft-editors [data-editor]');if(draggedStep===null||!to)return;event.preventDefault();captureDrafts();const index=Number(to.dataset.editor),[item]=state.drafts.splice(draggedStep,1);state.drafts.splice(index,0,item);draggedStep=null;$('#draft-editors').innerHTML=state.drafts.map((t,i)=>taskEditor(t,i)).join('');persistCurrentForms();});
document.addEventListener('dragend',()=>draggedStep=null);

document.addEventListener('click',event=>{for(const menu of $$('.notice-actions[open]'))if(!menu.contains(event.target)||event.target.closest('button,a'))menu.open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const menu of $$('.notice-actions[open]')){menu.open=false;menu.querySelector('summary').focus();}});

let backdropDown=false;$('#dialog').addEventListener('pointerdown',e=>{const r=e.currentTarget.getBoundingClientRect();backdropDown=e.target===e.currentTarget&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom);});$('#dialog').addEventListener('pointerup',e=>{const r=e.currentTarget.getBoundingClientRect();if(backdropDown&&e.target===e.currentTarget&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))e.currentTarget.close();backdropDown=false;});
document.addEventListener('click',e=>{for(const menu of document.querySelectorAll('.notice-actions[open],.library-date[open],.task-date-filter[open]'))if(!menu.contains(e.target))menu.open=false;});

document.addEventListener('change',event=>{if(event.target.closest('#draft-form'))syncDraftPlanControls(event.target);},true);
document.addEventListener('change',event=>{if(event.target.id==='notice-processing-mode')updateNoticeMode(document,state.session.ai);});

document.addEventListener('input',event=>{const form=event.target.closest('#draft-form');if(!form||event.target.name==='reviewed')return;const reviewed=form.querySelector('[name=reviewed]');if(reviewed)reviewed.checked=false;if(event.target.closest('[data-editor]')){const manual=form.querySelector('[name=manual_quality_reviewed]');if(manual)manual.checked=false;}},true);
let qualityResizeFrame=0;window.addEventListener('resize',()=>{cancelAnimationFrame(qualityResizeFrame);qualityResizeFrame=requestAnimationFrame(()=>resizeQualityNotes($('#draft-form')));});

document.addEventListener('campus:insight-selection',event=>{const {kind,ids,label}=event.detail||{};if(!['tasks','notices'].includes(kind)||!Array.isArray(ids)||!state.session)return;state.insightSelection={kind,ids:ids.filter(id=>typeof id==='string'),label:String(label||''),owner:state.session.user.id};state.filter='all';state.query='';state.dateFilter='';state.taskPage=1;libraryUI.resetFilters();location.hash=kind;});
