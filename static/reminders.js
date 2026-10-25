// Read/archive state belongs to the account; task completion stays independent.
import {captureUiContext} from './ui-request.js';
const LEVEL_TEXT = {urgent:'要紧', attention:'留意', info:'其他'};
const KIND_ICON = {overdue:'clock', due:'calendar', reminder:'bell', followup:'history', change:'shield', arrangement:'calendar', notice:'doc'};
const NOTIFIED_KEY = 'campus.reminders.notified', ENABLED_KEY = 'campus.reminders.browser';

export function createReminders({state, api, esc, icon, toast, showDialog, push=null}) {
  let data=null, owner=null, timers=[], poll=0, loading=null, generation=0;
  let filter='unread', managing=false, selected=new Set(), saving=false, lastError='';
  const $ = selector => document.querySelector(selector);
  const supported = () => typeof Notification === 'function';
  const browserEnabled = () => { try { return localStorage.getItem(ENABLED_KEY)==='on'; } catch { return false; } };
  const current = (uid,epoch) => uid===owner && uid===state.session?.user.id && epoch===generation;
  const activeItems = () => (data?.items||[]).filter(item=>!item.is_archived);
  const unreadItems = () => activeItems().filter(item=>!item.is_read);
  const visibleItems = () => (data?.items||[]).filter(item=>filter==='archived'?item.is_archived:!item.is_archived&&(filter==='all'||(filter==='read'?item.is_read:!item.is_read)));
  function notified() { try { return new Set(JSON.parse(localStorage.getItem(NOTIFIED_KEY)||'[]')); } catch { return new Set(); } }
  function remember(key) { const seen=notified();seen.add(key);try { localStorage.setItem(NOTIFIED_KEY,JSON.stringify([...seen].slice(-200))); } catch {} }
  function target(item) {
    if(item.task_id)return '#tasks/'+encodeURIComponent(item.task_id);
    if(item.arrangement_id)return '#calendar/'+encodeURIComponent(item.arrangement_id);
    if(item.notice_id)return '#notice/'+encodeURIComponent(item.notice_id);
    return item.kind==='notice'?'#notices':'#tasks';
  }
  function itemLink(item,compact=false) {
    return `<a class="reminder-item level-${item.level}" href="${target(item)}" data-reminder-link="${esc(item.id)}"><span class="reminder-icon" aria-hidden="true">${icon(KIND_ICON[item.kind]||'info')}</span><span class="reminder-copy"><strong>${esc(item.title)}</strong><span>${esc(item.text)}</span>${item.note?`<small class="reminder-note">${esc(item.note)}</small>`:''}${!compact&&item.notice_title?`<small class="reminder-source">${esc(item.notice_title)}</small>`:''}</span>${compact?'':`<span class="reminder-go" aria-hidden="true">${icon('arrow')}</span>`}</a>`;
  }
  function itemMarkup(item) {
    const command=item.is_archived||item.is_read?'unread':'read',label=item.is_archived?'恢复为未读':item.is_read?'标为未读':'标为已读';
    return `<article class="reminder-entry ${item.is_read?'is-read':''}">${managing?`<label class="reminder-select"><input type="checkbox" data-reminder-select="${esc(item.id)}" aria-label="选择：${esc(item.title)}" ${selected.has(item.id)?'checked':''} ${saving?'disabled':''}></label>`:''}${itemLink(item)}<div class="reminder-item-actions"><span class="small muted">${item.is_archived?'已归档':item.is_read?'已读':'未读'}</span><button type="button" class="button small plain" data-reminder-command="${command}" data-reminder-id="${esc(item.id)}" ${saving?'disabled':''}>${label}</button>${managing&&!item.is_archived?`<button type="button" class="button small plain" data-reminder-command="archived" data-reminder-id="${esc(item.id)}" ${saving?'disabled':''}>归档</button>`:''}</div></article>`;
  }
  function updateBadge() {
    const button=$('[data-action="reminders"]');if(!button)return;
    const items=unreadItems(),count=items.length,badge=button.querySelector('.reminder-badge');
    if(badge){badge.textContent=count>99?'99+':String(count);badge.hidden=!count;}
    button.classList.toggle('has-urgent',items.some(item=>item.level==='urgent'));
    button.setAttribute('aria-label',count?`提醒，${count} 条未读`:'提醒，无未读');
  }
  function schedule() {
    timers.forEach(clearTimeout);timers=[];
    if(!data||push?.enabled()||!supported()||Notification.permission!=='granted'||!browserEnabled())return;
    const seen=notified(),now=Date.now(),uid=owner;
    for(const entry of data.upcoming){
      const at=Date.parse(entry.at),key=`${uid}:${entry.task_id||entry.arrangement_id}:${entry.at}`;
      if(seen.has(key)||at-now>24*3600e3)continue;
      timers.push(setTimeout(()=>{
        if(owner!==uid||state.session?.user.id!==uid||notified().has(key))return;
        remember(key);
        try { const notice=new Notification('珞珈信使 · '+entry.title,{body:entry.text,tag:key,icon:'/static/assets/campus-notice-icon-v4-64.png'});notice.onclick=()=>{if(state.session?.user.id===uid){window.focus();location.hash=target(entry);}notice.close();}; } catch {}
      },Math.max(0,at-now)));
    }
  }
  function publish(result) { data=result;lastError='';updateBadge();schedule();renderCenter();document.dispatchEvent(new CustomEvent('campus:reminders',{detail:result})); }
  async function refresh() {
    if(!state.session||owner!==state.session.user.id)return null;
    if(saving)return data;if(loading)return loading;
    const uid=owner,epoch=generation;
    const request=api('/reminders').then(result=>{if(!current(uid,epoch))return null;publish(result);return result;}).catch(error=>{if(current(uid,epoch)){lastError=error.message;renderCenter();}return null;}).finally(()=>{if(loading===request)loading=null;});
    loading=request;return request;
  }
  function stop() { generation++;owner=null;data=null;loading=null;saving=false;lastError='';selected.clear();clearInterval(poll);timers.forEach(clearTimeout);timers=[]; }
  function start() { push?.start();const uid=state.session?.user.id;if(owner===uid){refresh();return;}stop();owner=uid;filter='unread';managing=false;if(!uid)return;poll=setInterval(()=>{if(!document.hidden)refresh();},60e3);refresh(); }
  function browserControl() {
    if(!supported())return '<p class="small muted">当前浏览器不支持网页通知。</p>';
    if(Notification.permission==='denied')return '<p class="small muted">浏览器已拒绝通知，可在网站设置中开启。</p>';
    const on=Notification.permission==='granted'&&browserEnabled();
    return `<label class="check reminder-toggle"><input type="checkbox" data-reminder-browser ${on?'checked':''}><span>页面打开时提醒<small>只在当前页面保持打开时生效。</small></span></label>`;
  }
  function centerMarkup() {
    const items=visibleItems(),ids=new Set(items.map(item=>item.id));selected=new Set([...selected].filter(id=>ids.has(id)));
    const disabled=saving?'disabled':'',bulkDisabled=saving||!selected.size?'disabled':'';
    const counts={unread:unreadItems().length,read:activeItems().filter(item=>item.is_read).length,all:activeItems().length,archived:(data?.items||[]).filter(item=>item.is_archived).length};
    const groups=Object.keys(LEVEL_TEXT).map(level=>[level,items.filter(item=>item.level===level)]).filter(([,list])=>list.length);
    return `<div class="reminder-toolbar"><strong role="status">${saving?'正在保存…':`${counts.unread} 条未读`}</strong><div class="row wrap"><button type="button" class="button small" data-reminder-all ${saving||!counts.unread?'disabled':''}>全部已读</button><button type="button" class="button small ${managing?'primary':''}" data-reminder-manage aria-pressed="${managing}" ${disabled}>${managing?'完成管理':'管理'}</button></div></div>
    ${lastError?`<div class="alert error" role="alert">${esc(lastError)} <button type="button" class="button small" data-reminder-refresh>重试</button></div>`:''}
    <div class="tabs reminder-filters" role="tablist" aria-label="提醒状态">${Object.entries({unread:'未读',all:'全部',read:'已读',archived:'已归档'}).map(([key,label])=>`<button type="button" class="tab ${filter===key?'active':''}" role="tab" aria-selected="${filter===key}" tabindex="${filter===key?0:-1}" data-reminder-filter="${key}" ${disabled}>${label} ${counts[key]}</button>`).join('')}</div>
    ${managing?`<div class="reminder-bulk"><label class="check"><input type="checkbox" data-reminder-select-all aria-label="全选当前列表" ${items.length&&selected.size===items.length?'checked':''} ${saving||!items.length?'disabled':''}><span>全选 · 已选 ${selected.size}</span></label><div class="row wrap">${filter!=='archived'?`<button type="button" class="button small" data-reminder-bulk="read" ${bulkDisabled}>标为已读</button>`:''}<button type="button" class="button small" data-reminder-bulk="unread" ${bulkDisabled}>${filter==='archived'?'恢复为未读':'标为未读'}</button>${filter!=='archived'?`<button type="button" class="button small" data-reminder-bulk="archived" ${bulkDisabled}>归档</button>`:''}</div></div>`:''}
    <div class="reminder-groups">${groups.map(([level,list])=>`<section class="reminder-group"><h3>${LEVEL_TEXT[level]} · ${list.length}</h3><div class="reminder-list">${list.map(itemMarkup).join('')}</div></section>`).join('')||`<div class="reminder-empty">${icon('check')}<p>${{unread:'暂无未读提醒',all:'暂无提醒',read:'暂无已读提醒',archived:'暂无已归档提醒'}[filter]}</p></div>`}</div>`;
  }
  function centerFocus() {
    const content=$('[data-reminder-content]'),focus=document.activeElement;
    const marker=content?.contains(focus)?[...focus.attributes].find(attr=>attr.name.startsWith('data-reminder-')):null;
    return marker?{content,name:marker.name,value:marker.value,rowId:focus.dataset.reminderId}:null;
  }
  function renderCenter(savedFocus=null) {
    const content=$('[data-reminder-content]');if(!content||!content.closest('dialog')?.open)return;
    const active=document.activeElement,canRestore=savedFocus?.content===content&&(active===document.body||active===content.closest('dialog')||content.contains(active));
    const marker=centerFocus()||(canRestore?savedFocus:null);
    const body=content.closest('.dialog-body'),scroll=body.scrollTop;content.innerHTML=centerMarkup();
    const selectAll=$('[data-reminder-select-all]');if(selectAll)selectAll.indeterminate=selected.size>0&&selected.size<visibleItems().length;
    if(marker&&!saving){const replacement=[...content.querySelectorAll(`[${marker.name}]`)].find(el=>el.getAttribute(marker.name)===marker.value&&(!marker.rowId||el.dataset.reminderId===marker.rowId));(replacement&&!replacement.disabled?replacement:content.querySelector('[data-reminder-filter][aria-selected="true"]'))?.focus({preventScroll:true});}
    body.scrollTop=scroll;
  }
  async function open() {
    const view=captureUiContext(state);await refresh();if(!view.sameDialog())return;
    filter='unread';managing=false;selected.clear();
    showDialog('提醒',`<div class="reminder-center"><div data-reminder-content>${centerMarkup()}</div><p class="small muted">已读和归档仅管理提醒，不会完成待办；期限或通知有新变化时会重新提醒。</p>${push?`<div data-push-settings>${push.markup()}</div><details class="details"><summary>页面内提醒</summary>${browserControl()}</details>`:browserControl()}</div>`);push?.refresh();
  }
  async function update(ids,status) {
    if(saving||!ids.length||owner!==state.session?.user.id)return false;
    const uid=owner,epoch=++generation,focus=centerFocus();saving=true;loading=null;renderCenter();
    try { for(let offset=0;offset<ids.length;offset+=1000){const result=await api('/reminders/state',{method:'POST',json:{ids:ids.slice(offset,offset+1000),state:status}});if(!current(uid,epoch))return false;publish(result);}selected.clear();return true; }
    catch(error){if(current(uid,epoch)){lastError=error.message;toast(error.message,true);}return false;}
    finally {if(current(uid,epoch)){saving=false;renderCenter(focus);}}
  }
  function summary(limit=4) {
    if(!data)return '';const seen=new Set(),unread=unreadItems();
    const items=unread.filter(item=>{if(item.level==='info'&&item.kind!=='arrangement')return false;const key=item.task_id||item.arrangement_id||item.kind;if(seen.has(key))return false;seen.add(key);return true;}).slice(0,limit);
    return `${items.length?`<div class="reminder-list compact">${items.map(item=>itemLink(item,true)).join('')}</div>`:'<p class="small muted">暂无紧急未读提醒</p>'}<button type="button" class="link-button small" data-action="reminders">${unread.length?`查看全部 ${unread.length} 条未读提醒`:'查看提醒'}</button>`;
  }
  document.addEventListener('change',async event=>{
    const input=event.target;
    if(input.matches('[data-reminder-select]')){if(input.checked)selected.add(input.dataset.reminderSelect);else selected.delete(input.dataset.reminderSelect);renderCenter();return;}
    if(input.matches('[data-reminder-select-all]')){selected=new Set(input.checked?visibleItems().map(item=>item.id):[]);renderCenter();return;}
    if(!input.matches('[data-reminder-browser]'))return;
    if(input.checked){const permission=Notification.permission==='granted'?'granted':await Notification.requestPermission();if(permission!=='granted'){input.checked=false;toast('浏览器没有允许通知，可在网站设置中开启。',true);return;}try{localStorage.setItem(ENABLED_KEY,'on');}catch{}}
    else{try{localStorage.setItem(ENABLED_KEY,'off');}catch{}}schedule();
  });
  document.addEventListener('click',async event=>{
    const control=event.target.closest('button,a');if(!control||control.disabled)return;
    if(control.matches('[data-reminder-filter]')){filter=control.dataset.reminderFilter;selected.clear();renderCenter();}
    else if(control.matches('[data-reminder-manage]')){managing=!managing;selected.clear();renderCenter();}
    else if(control.matches('[data-reminder-refresh]')){control.disabled=true;await refresh();}
    else if(control.matches('[data-reminder-all]'))await update(unreadItems().map(item=>item.id),'read');
    else if(control.matches('[data-reminder-command]'))await update([control.dataset.reminderId],control.dataset.reminderCommand);
    else if(control.matches('[data-reminder-bulk]'))await update([...selected],control.dataset.reminderBulk);
    else if(control.matches('[data-reminder-link]')&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){
      event.preventDefault();if(saving)return;const view=captureUiContext(state),href=control.getAttribute('href'),item=data?.items.find(item=>item.id===control.dataset.reminderLink);
      if(item&&!item.is_read&&!await update([item.id],'read'))return;if(!view.sameDialog())return;$('#dialog')?.close();location.hash=href;
    }
  });
  $('#dialog')?.addEventListener('dialog-back',()=>requestAnimationFrame(renderCenter));
  document.addEventListener('campus:push-state',schedule);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&owner)refresh();});
  return {start,stop,refresh,open,summary,latest:()=>data};
}
