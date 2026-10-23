import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {bindProfileForm,saveProfileForm,patchProfile,applyProfileForm} from './profile-editor.js';
import {taskIsPending} from './action-plans.js';
import {dayKey,addDays,weekStart,sundayStart,monthDays,shiftMonth,calendarEntries,layoutTimed,PERIOD_TIMES,periodPosition,minute,dayDistance} from './calendar-model.js';

const $=(s,root=document)=>root.querySelector(s);
const kinds={deadline:'通知期限',plan:'待办计划',course:'课程',activity:'校园活动',personal:'个人安排'};
const weekdays=['一','二','三','四','五','六','日'];
const pretty=day=>new Intl.DateTimeFormat('zh-CN',{timeZone:'UTC',month:'long',day:'numeric',weekday:'long'}).format(new Date(day+'T00:00:00Z'));
const tone=e=>e.kind==='course'?'tone-'+([...e.title].reduce((sum,ch)=>sum+ch.codePointAt(0),0)%4):'';
const monthLabel=day=>`${Number(day.slice(0,4))} 年 ${Number(day.slice(5,7))} 月`;

export function createCalendarUI({state,api,esc,icon,companion,showDialog,ask,toast,field,area,download,moveSelection,calendarHelp,editTask,taskRow,drafts}){
  let selected=dayKey(),view='month',owner=null,records=[],query='',showDone=false,visible=new Set(Object.keys(kinds)),entries=[],editRecord=null;
  const pendingCreates=new Set();
  let monthElement=null;
  const monthResize=new ResizeObserver(fitMonthEvents);
  let formRequest='',listPage=1,listDay=false,weekStartsOn=1,pickerMonth='',pickerMode='day';
  const startWeek=day=>(weekStartsOn===0?sundayStart:weekStart)(day);
  const gridDays=day=>Array.from({length:42},(_,i)=>addDays(startWeek(day.slice(0,7)+'-01'),i));
  const weekLabels=()=>weekStartsOn===0?['日','一','二','三','四','五','六']:weekdays;
  const phone=matchMedia('(max-width:600px)');
  const control=(label,action,attrs='',cls='')=>`<button type="button" class="button ${cls}" data-calendar-action="${action}" ${attrs}>${label}</button>`;
  const belongs=()=>(location.hash==='#calendar'||/^#calendar\/[A-Za-z0-9_-]+$/.test(location.hash))&&$('#calendar-body');
  const range=()=>view==='day'||(view==='list'&&listDay)?[selected,selected]:view==='week'?[startWeek(selected),addDays(startWeek(selected),6)]:[selected.slice(0,7)+'-01',addDays(shiftMonth(selected.slice(0,7)+'-01',1),-1)];
  function filter(list){return list.filter(e=>visible.has(e.kind)&&(!query||(e.title+' '+e.location+' '+e.notes).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));}
  const preferenceKey=()=>`luojia:calendar:${owner}`;
  function saveDisplay(){try{localStorage.setItem(preferenceKey(),JSON.stringify({view,visible:[...visible],showDone}));}catch{}}
  function reset(){
    owner=state.session.user.id;selected=dayKey();listDay=false;listPage=1;view=phone.matches?'list':'month';query='';showDone=false;visible=new Set(Object.keys(kinds));records=[];weekStartsOn=state.session.user.profile.week_starts_on??1;
    try{const saved=JSON.parse(localStorage.getItem(preferenceKey())||'null');if(saved){if(['day','week','month','list'].includes(saved.view))view=saved.view;if(Array.isArray(saved.visible))visible=new Set(saved.visible.filter(k=>k in kinds));showDone=saved.showDone===true;}}catch{}
  }
  async function render(renderId=state.renderId){
    if(owner!==state.session.user.id)reset();
    const items=await api('/arrangements');if(renderId!==state.renderId)return;records=items;
    $('#content').innerHTML=`<section class="calendar-workspace"><h1 class="sr-only">我的日历</h1><div class="calendar-layout"><aside class="calendar-sidebar"><div id="calendar-mini"></div><details class="calendar-filters" open><summary>显示内容</summary><div class="calendar-filter-fields">${Object.entries(kinds).map(([k,label])=>`<label class="check"><input type="checkbox" data-calendar-kind="${k}" checked><i class="calendar-dot ${k}" aria-hidden="true"></i>${label}</label>`).join('')}<label class="check calendar-done"><input type="checkbox" id="calendar-show-done">包含已完成待办</label><label class="calendar-search"><span class="sr-only">搜索日历安排</span>${icon('search')}<input type="search" id="calendar-query" placeholder="查找安排" value="${esc(query)}"></label><div class="calendar-filter-actions"><button type="button" class="link-button small" data-calendar-action="reset-filters" hidden>重置筛选</button><button type="button" class="link-button small" data-calendar-action="undated" id="calendar-undated" hidden></button></div></div></details><div class="calendar-side-note">${companion('planning','calendar-companion')}<p>把时间理顺，<br>也留一点空白。</p></div></aside><div class="calendar-main"><header class="calendar-toolbar"><div class="calendar-navigation">${control(icon('back'),'previous','aria-label="上一个日期范围"','icon-button')}${control(icon('arrow'),'next','aria-label="下一个日期范围"','icon-button')}<h2><button type="button" id="calendar-title" class="calendar-date-trigger" data-calendar-action="date-picker" aria-label="点选日期、周或月份"></button></h2>${control('今','today','aria-label="回到今天"','small calendar-today')}</div><div class="calendar-tools">${control(icon('settings'),'options','aria-label="显示与导出"','icon-button')}${control(icon('plus'),'new','aria-label="新建安排"','icon-button calendar-add')}</div><div class="tabs calendar-view-tabs" role="tablist" aria-label="日历视图">${[['day','日'],['week','周'],['month','月'],['list','列表']].map(([v,label])=>`<button type="button" role="tab" class="tab" data-calendar-view="${v}">${label}</button>`).join('')}</div></header><span id="calendar-count" class="sr-only" role="status"></span><div id="calendar-body" role="tabpanel" aria-label="日历安排"></div><section id="calendar-selection" class="calendar-selection"></section></div></div></section>`;
    for(const input of document.querySelectorAll('[data-calendar-kind]'))input.checked=visible.has(input.dataset.calendarKind);
    $('#calendar-show-done').checked=showDone;
    if(matchMedia('(max-width:1000px)').matches)$('.calendar-filters').open=false;
    refresh();
  }
  function refresh(){
    if(!belongs())return;
    saveDisplay();
    for(const input of document.querySelectorAll('#calendar-query,#calendar-option-query'))if(input.value!==query)input.value=query;
    monthResize.disconnect();monthElement=null;
    const positionKey=view+':'+selected,previousScroll=$('.time-calendar-scroll');
    const previousPosition=previousScroll?.dataset.positionKey===positionKey?{left:previousScroll.scrollLeft,top:previousScroll.scrollTop}:null;
    const [from,to]=range(),days=gridDays(selected),all=calendarEntries(records,state.tasks,days[0]<from?days[0]:from,days[41]>to?days[41]:to,{showDone});entries=filter(all);
    const term=state.session.user.profile,week=term.semester_start?Math.floor(dayDistance(weekStart(term.semester_start),weekStart(selected))/7)+1:0;
    $('#calendar-title').textContent=view==='day'||(view==='list'&&listDay)?pretty(selected):view==='week'?(phone.matches?(week>0&&week<=40?`${term.semester||'本学期'} 第 ${week} 周`:`${Number(from.slice(5,7))}月${Number(from.slice(8))}日 — ${from.slice(5,7)===to.slice(5,7)?'':Number(to.slice(5,7))+'月'}${Number(to.slice(8))}日`):`${pretty(from)} — ${to.slice(5).replace('-','月')}日`):monthLabel(selected);
    if(phone.matches&&view==='week'&&week>0&&week<=40)$('#calendar-title').innerHTML=`<span class="calendar-term">${esc(term.semester||'本学期')}</span><small class="calendar-term-week">第 ${week} 周</small>`;
    $('#calendar-title').setAttribute('aria-label',$('#calendar-title').textContent+'，点选日期、周或月份');

    document.querySelectorAll('[data-calendar-view]').forEach(b=>{const active=b.dataset.calendarView===view;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});moveSelection($('.calendar-view-tabs'));
    const count=entries.filter(e=>e.day>=from&&e.day<=to).length;$('#calendar-count').textContent=`北京时间 · ${count} 项${query?'匹配安排':'安排'}${visible.size===0?' · 还没选要显示的分类':''}`;
    const status=$('#calendar-option-status');
    if(status)status.textContent=`已应用 · 周${weekStartsOn===0?'日':'一'}开始 · ${visible.size} 类安排 · 当前范围 ${count} 项${showDone?' · 含已完成':''}`;
    const preview=$('#calendar-option-preview');
    if(preview){const items=entries.filter(e=>e.day>=from&&e.day<=to).slice(0,3);preview.innerHTML=items.length?items.map(e=>`<div><i class="calendar-dot ${e.kind}" aria-hidden="true"></i><span>${esc(e.title)}</span><small>${esc(e.day.slice(5))}</small></div>`).join(''):'<p>这样筛选下没有安排，换个分类、日期或关键词看看。</p>';}
    for(const reset of document.querySelectorAll('[data-calendar-action="reset-filters"]'))reset.hidden=visible.size===5&&!query&&!showDone;
    const undated=state.tasks.filter(t=>taskIsPending(t)&&t.data.scope==='personal'&&!t.data.due_date&&!t.data.planned_at);$('#calendar-undated').hidden=!undated.length;$('#calendar-undated').textContent=`${undated.length} 项待办还没定日期`;
    $('#calendar-mini').innerHTML=`<div class="mini-title"><strong>${monthLabel(selected)}</strong></div><div class="mini-week">${weekLabels().map(x=>`<span>${x}</span>`).join('')}</div><div class="mini-grid">${days.map(day=>`<button type="button" data-calendar-day="${day}" class="${dateClasses(day)}" aria-label="${pretty(day)}" ${day===selected?'aria-pressed="true"':'aria-pressed="false"'}>${Number(day.slice(-2))}</button>`).join('')}</div>`;
    $('#calendar-body').innerHTML=view==='month'?monthGrid(days):view==='list'?agenda(entries.filter(e=>e.day>=from&&e.day<=to)):timeGrid(view==='day'?[selected]:Array.from({length:7},(_,i)=>addDays(from,i)));
    $('#calendar-body').dataset.view=view;
    if(view==='month'){
      monthElement=$('.month-grid');
      monthElement.style.setProperty('--month-rows',String(monthElement.childElementCount/7));
      fitMonthEvents();monthResize.observe(monthElement);
    }
    // CSP disallows HTML style attributes. Apply bounded layout measurements via CSSOM.
    for(const node of document.querySelectorAll('#calendar-body [data-columns]'))node.style.setProperty('--day-count',String(Number(node.dataset.columns)));
    for(const node of document.querySelectorAll('#calendar-body [data-height]'))node.style.height=Number(node.dataset.height)+'px';
    for(const node of document.querySelectorAll('#calendar-body [data-top]'))node.style.top=Number(node.dataset.top)+'px';
    for(const node of document.querySelectorAll('#calendar-body [data-geometry]'))if(node.dataset.geometry){const [top,height,left,width]=node.dataset.geometry.split(',').map(Number);Object.assign(node.style,{top:top+'px',height:height+'px',left:`calc(${left}% + 3px)`,width:`calc(${width}% - 6px)`});}
    for(const node of document.querySelectorAll('#calendar-body [data-period-layout]')){const [top,height,left,width]=node.dataset.periodLayout.split(',').map(Number);Object.assign(node.style,{top:`calc(${top}% + 1px)`,height:`calc(${height}% - 2px)`,left:`calc(${left}% + 1px)`,width:`calc(${width}% - 2px)`});}
    for(const node of document.querySelectorAll('[data-hour-height]'))node.style.setProperty('--hour-height',node.dataset.hourHeight+'px');
    const scroll=$('.time-calendar-scroll');
    if(scroll){
      scroll.dataset.positionKey=positionKey;
      if(previousPosition){scroll.scrollLeft=previousPosition.left;scroll.scrollTop=previousPosition.top;}
      else{
        const focusDay=scroll.querySelector(`[data-calendar-day="${selected}"]`);
        if(focusDay&&scroll.scrollWidth>scroll.clientWidth)scroll.scrollLeft=focusDay.getBoundingClientRect().left-scroll.getBoundingClientRect().left-scroll.clientWidth/2+focusDay.clientWidth/2;
        const firstHour=Math.min(8,...entries.filter(e=>!e.allDay&&e.day>=from&&e.day<=to).map(e=>Math.floor(minute(e.start)/60)));
        scroll.scrollTop=firstHour*Number(scroll.querySelector('[data-hour-height]')?.dataset.hourHeight||0);
      }
    }
    $('#calendar-selection').hidden=view!=='month';
    if(view==='month'){
      const selectedEntries=entries.filter(e=>e.day===selected);
      $('#calendar-selection').innerHTML=`<div class="between"><h3>${pretty(selected)}<small> · ${selectedEntries.length} 项</small></h3>${control('查看这一天 '+icon('arrow'),'open-day','','small plain')}</div>${selectedEntries.length?selectedEntries.slice(0,5).map(e=>agendaRow(e,false)).join(''):`<div class="calendar-day-empty"><span>这一天还空着，留给自己也很好。</span>${control('安排一件事','new','','small plain')}</div>`}${selectedEntries.length>5?control(`还有 ${selectedEntries.length-5} 项，展开全部`,'open-day','','small plain'):''}`;
    }
  }
  function dateClasses(day){return [day.slice(0,7)!==selected.slice(0,7)?'outside':'',day===dayKey()?'today':'',day===selected?'selected':''].filter(Boolean).join(' ');}
  function fitMonthEvents(){
    if(!monthElement?.isConnected||!belongs()){monthResize.disconnect();monthElement=null;return;}
    // A month can have four, five or six rows. Reserve the remainder button
    // before showing previews, so resizing never hides an uncounted entry.
    const layouts=[...monthElement.querySelectorAll('.month-events')].filter(list=>Number(list.dataset.total)>0).map(list=>{
      const total=Number(list.dataset.total),buttons=[...list.querySelectorAll('.calendar-event')],more=list.querySelector('.calendar-more');
      const style=getComputedStyle(list),gap=parseFloat(style.rowGap)||0;
      const eventHeight=parseFloat(style.getPropertyValue('--month-event-height')),moreHeight=parseFloat(style.getPropertyValue('--month-more-height'));
      let shown=Math.min(total,buttons.length,Math.floor((list.clientHeight+gap)/(eventHeight+gap)));
      if(shown<total)shown=Math.min(shown,Math.max(0,Math.floor((list.clientHeight-moreHeight)/(eventHeight+gap))));
      return {list,total,buttons,more,shown,compact:list.clientWidth<64};
    });
    // Read all geometry first; keep sidebar dragging to one layout calculation.
    let focusTarget=null;
    for(const {list,total,buttons,more,shown,compact} of layouts){
      const active=document.activeElement;
      buttons.forEach((button,index)=>{button.hidden=index>=shown;});
      more.hidden=shown===total;
      more.textContent=compact?`+${total-shown} 项`:`还有 ${total-shown} 项`;
      more.setAttribute('aria-label',`${pretty(more.dataset.day)}，另有 ${total-shown} 项，查看当天全部 ${total} 项安排`);
      if(buttons.some(button=>button===active&&button.hidden)||(more===active&&more.hidden)){
        focusTarget=more.hidden?list.parentElement.querySelector('.month-date'):more;
      }
    }
    if(focusTarget)focusMonthControl(focusTarget);
  }
  function focusMonthControl(node){
    if(!node)return;
    node.focus({preventScroll:true});
    const body=$('#calendar-body'),bounds=body.getBoundingClientRect(),box=node.getBoundingClientRect();
    const top=bounds.top+($('.month-week')?.getBoundingClientRect().height||0)+4;
    if(box.bottom>bounds.bottom-4)body.scrollTop+=box.bottom-bounds.bottom+4;
    else if(box.top<top)body.scrollTop-=top-box.top;
  }
  function eventButton(e,extraClass='',style=''){
    const clock=e.allDay?'全天':(e.continuesBefore?'← ': '')+e.start+(e.continuesAfter?' →':'');
    return `<button type="button" class="calendar-event ${e.kind} ${tone(e)} ${e.done?'is-done':''} ${extraClass}" data-calendar-event="${esc(e.key)}" data-geometry="${style}" title="${esc(clock+' '+e.title+' · '+kinds[e.kind]+(e.location?' · '+e.location:''))}" aria-label="${esc(pretty(e.day)+' '+clock+' '+e.title+'，'+kinds[e.kind]+(e.verified===false?'，期限待核实':''))}"><span class="calendar-event-time">${esc(clock)}</span><strong>${esc(e.title)}</strong>${extraClass==='timed-event'&&e.location?`<small>${esc(e.location)}</small>`:''}${e.verified===false?'<span class="unverified-marker" aria-label="期限待核实">?</span>':''}</button>`;
  }
  function monthGrid(days){const last=addDays(shiftMonth(selected.slice(0,7)+'-01',1),-1);days=days.slice(0,Math.ceil((days.indexOf(last)+1)/7)*7);return `<div class="month-week">${weekLabels().map(x=>`<span>周${x}</span>`).join('')}</div><div class="month-grid" aria-label="月视图，日期可使用方向键切换">${days.map(day=>{
    const items=entries.filter(e=>e.day===day);return `<div class="month-cell ${dateClasses(day)}" data-calendar-cell="${day}"><button class="month-date" type="button" data-calendar-day="${day}" aria-label="${pretty(day)}，${items.length} 项安排" tabindex="${day===selected?0:-1}" ${day===dayKey()?'aria-current="date"':''}>${Number(day.slice(-2))}</button><div class="month-events" data-total="${items.length}">${items.slice(0,3).map(e=>eventButton(e)).join('')}<button type="button" class="calendar-more" data-calendar-action="open-day" data-day="${day}" hidden></button></div></div>`;
  }).join('')}</div>`;}
  function agendaRow(e,withDay=true){return `<button type="button" class="agenda-row ${e.done?'is-done':''}" data-calendar-event="${esc(e.key)}"><i class="calendar-dot ${e.kind}" aria-hidden="true"></i><span class="agenda-time">${withDay?'<span>'+esc(e.day.slice(5))+'</span>':''}${e.allDay?'全天':esc(e.start+(e.end?'–'+e.end:''))}</span><span class="agenda-title"><strong>${esc(e.title)}</strong><small>${esc(kinds[e.kind]+(e.location?' · '+e.location:'')+(e.verified===false?' · 期限待核实':''))}</small></span>${icon('arrow')}</button>`;}
  function agenda(list){
    const wholeMonth=listDay?control('查看整月','list-month','','small plain'):'';
    if(!list.length)return `<div class="calendar-empty"><h3>${query||visible.size<5?'没找到匹配的安排':listDay?'这天还空着':'这个月还没有安排'}</h3><div class="row wrap">${wholeMonth}${control('新建安排','new','','small')}</div></div>`;
    const pages=Math.max(1,Math.ceil(list.length/12));listPage=Math.min(Math.max(1,listPage),pages);
    return `<div class="calendar-agenda">${list.slice((listPage-1)*12,listPage*12).map(e=>agendaRow(e)).join('')}</div><div class="calendar-pagination">${control(icon('back'),'list-prev',listPage===1?'disabled':'','small')}<span>${listDay?'当日':'本月'} ${list.length} 项 · ${listPage} / ${pages}</span>${wholeMonth}${control(icon('arrow'),'list-next',listPage===pages?'disabled':'','small')}</div>`;
  }
  function options(){
    showDialog('显示与导出',`<div class="stack"><label class="field">每周从哪一天开始<select id="calendar-week-start" aria-label="每周开始日期"><option value="1" ${weekStartsOn===1?'selected':''}>周一</option><option value="0" ${weekStartsOn===0?'selected':''}>周日</option></select></label><fieldset class="calendar-option-group"><legend>显示哪些安排</legend>${Object.entries(kinds).map(([kind,label])=>`<label class="check"><input type="checkbox" data-calendar-kind="${kind}" ${visible.has(kind)?'checked':''}><i class="calendar-dot ${kind}"></i>${label}</label>`).join('')}<label class="check"><input type="checkbox" id="calendar-option-done" ${showDone?'checked':''}>包含已完成待办</label></fieldset><label class="field">查找安排<input id="calendar-option-query" type="search" value="${esc(query)}" placeholder="课程、地点或备注"></label><label class="field">跳转日期<input id="calendar-option-date" type="date" min="2000-01-01" max="2100-12-31" value="${selected}"></label><div class="row wrap">${control('重置筛选','reset-filters','','small plain')}${control('回到今天','today','','small')}${control('学期与周次','semester','','small')}${control('导出与提醒','exports','','small')}${control('还没定日期的待办','undated','','small')}</div><p class="small muted">日、周视图会显示完整的 24 小时。跨天的安排按天分段，箭头表示接着前一天，或延续到第二天。</p><div class="form-footer"><button type="button" class="button primary" data-action="close-dialog">完成</button></div></div>`);
    const stack=$('#calendar-week-start').closest('.stack');stack.classList.add('calendar-options');
    const feedback=document.createElement('section');feedback.className='calendar-option-preview';feedback.innerHTML='<p id="calendar-option-status" role="status"></p><div id="calendar-option-preview"></div>';stack.prepend(feedback);
    stack.querySelector('.form-footer button').textContent='查看日历';
    refresh();
  }
  function datePicker(){
    const days=gridDays(pickerMonth);showDialog('选择日期',`<div class="calendar-date-picker"><div class="search-mode-tabs" role="group" aria-label="跳转视图">${[['day','日'],['week','周'],['month','月']].map(([mode,label])=>`<button type="button" data-calendar-action="picker-mode" data-mode="${mode}" aria-pressed="${mode===pickerMode}">${label}</button>`).join('')}</div><div class="picker-navigation">${control(icon('back'),'picker-prev','aria-label="上个月"'+(pickerMonth==='2000-01-01'?' disabled':''),'icon-button')}<select id="picker-year" aria-label="年份">${Array.from({length:101},(_,i)=>`<option value="${2000+i}" ${Number(pickerMonth.slice(0,4))===2000+i?'selected':''}>${2000+i} 年</option>`).join('')}</select><select id="picker-month" aria-label="月份">${Array.from({length:12},(_,i)=>`<option value="${String(i+1).padStart(2,'0')}" ${Number(pickerMonth.slice(5,7))===i+1?'selected':''}>${i+1} 月</option>`).join('')}</select>${control(icon('arrow'),'picker-next','aria-label="下个月"'+(pickerMonth==='2100-12-01'?' disabled':''),'icon-button')}</div><div class="picker-days">${weekLabels().map(label=>`<span>周${label}</span>`).join('')}${days.map(day=>`<button type="button" class="${day===dayKey()?'today':''} ${day===selected?'selected':''} ${day.slice(0,7)!==pickerMonth.slice(0,7)?'outside':''} ${pickerMode==='week'&&startWeek(day)===startWeek(selected)?'week-selected':''}" data-calendar-action="picker-date" data-day="${day}" ${day<'2000-01-01'||day>'2100-12-31'?'disabled':''} ${day===dayKey()?'aria-current="date"':''} aria-pressed="${pickerMode==='week'?startWeek(day)===startWeek(selected):day===selected}" aria-label="${pretty(day)}${pickerMode==='week'?'所在周':''}">${Number(day.slice(-2))}</button>`).join('')}</div>${pickerMode==='month'?control('查看 '+monthLabel(pickerMonth),'picker-month','','primary'):''}</div>`);
  }
  function periodGrid(days){
    const dayEntries=entries.filter(e=>days.includes(e.day));
    const outside=dayEntries.filter(e=>e.allDay||minute(e.start)<480||minute(e.start)>=1320||(e.end&&minute(e.end)>1320));
    return `<div class="period-calendar ${days.length===1?'period-single':''}" data-columns="${days.length}"><div class="period-week-header"><span>${Number(selected.slice(5,7))}<small>月</small></span>${days.map(day=>`<button type="button" class="${dateClasses(day)}" data-calendar-day="${day}" aria-label="${pretty(day)}"><small>${weekdays[(new Date(day+'T00:00:00Z').getUTCDay()+6)%7]}</small><strong>${Number(day.slice(-2))}</strong></button>`).join('')}</div>${outside.length?control(`全天与其他时段 · ${outside.length} 项 ${icon('arrow')}`,'outside-times','','period-outside'):''}<div class="period-body"><div class="period-numbers">${PERIOD_TIMES.map((time,i)=>`<span><b>${i+1}</b><small>${time}</small></span>`).join('')}</div>${days.map(day=>`<div class="period-day">${layoutTimed(dayEntries.filter(e=>e.day===day&&!e.allDay&&minute(e.start)>=480&&minute(e.start)<1320)).filter((e,index,list)=>days.length===1||list.findIndex(x=>x.cluster===e.cluster)===index).map(e=>{
      const top=periodPosition(e.begin),bottom=periodPosition(e.finish);
      return `<button type="button" class="period-event ${e.kind} ${tone(e)} ${e.done?'is-done':''}" data-calendar-event="${esc(e.key)}" data-period-layout="${top/14*100},${(bottom-top)/14*100},${days.length===1?e.lane/e.lanes*100:0},${days.length===1?100/e.lanes:100}" aria-label="${esc(pretty(day)+' '+e.start+' '+e.title+'，'+kinds[e.kind])}">${e.kind!=='course'?`<small>${esc(e.kind==='deadline'?'截止':e.start)}</small>`:''}<strong>${esc(e.title)}</strong>${e.location&&bottom-top>1.9?`<span>${esc(e.location)}</span>`:''}${e.verified===false?'<small>待核实</small>':''}${days.length>1&&e.clusterSize>1?`<small class="period-conflict">另 ${e.clusterSize-1} 项</small>`:''}</button>${days.length>1&&e.clusterSize>1?`<button type="button" class="period-conflict-action" data-calendar-action="day-collisions" data-day="${day}" data-period-layout="${top/14*100},${(bottom-top)/14*100},0,100" aria-label="${pretty(day)}有 ${e.clusterSize} 项时间重叠的安排，展开查看"></button>`:''}`;
    }).join('')}</div>`).join('')}</div></div>`;
  }
  function timeGrid(days){
    const dayEntries=entries.filter(e=>days.includes(e.day));
    const timed=dayEntries.filter(e=>!e.allDay);
    const startHour=0,endHour=24,scale=phone.matches?36:44,height=24*scale;
    const allDay=dayEntries.filter(e=>e.allDay);
    return `${allDay.length?`<div class="calendar-allday-events" aria-label="全天安排">${allDay.map(e=>eventButton(e)).join('')}</div>`:''}${view==='week'?'<p class="calendar-scroll-hint">左右滑动查看整周，上下滑动查看时段</p>':''}<div class="time-calendar-scroll" tabindex="0" aria-label="${view==='week'?'周课表，可左右和上下滚动':'当日时间安排，可上下滚动'}"><div class="time-calendar ${view==='day'?'single-day':''}" data-columns="${days.length}"><div class="time-grid-header"><span>时间</span>${days.map(day=>`<button type="button" class="${dateClasses(day)}" data-calendar-day="${day}"><small>周${weekdays[(new Date(day+'T00:00:00Z').getUTCDay()+6)%7]}</small><strong>${Number(day.slice(-2))}</strong></button>`).join('')}</div><div class="time-grid-body" data-height="${height}" data-hour-height="${scale}"><div class="time-labels">${Array.from({length:endHour-startHour+1},(_,i)=>`<span data-top="${i*scale}">${String(startHour+i).padStart(2,'0')}:00</span>`).join('')}</div>${days.map(day=>`<div class="time-day" data-day="${day}" data-height="${height}">${layoutTimed(dayEntries.filter(e=>e.day===day)).map(e=>eventButton(e,'timed-event',`${(e.begin/60-startHour)*scale+1},${Math.min(height-(e.begin/60-startHour)*scale-1,Math.max(18,(e.finish-e.begin)/60*scale-2))},${e.lane/e.lanes*100},${100/e.lanes}`)).join('')}</div>`).join('')}</div></div></div>${dayEntries.length?'':`<div class="calendar-day-empty"><span>这段时间空着。</span>${control('新建安排','new','','small plain')}</div>`}`;
  }
  function detail(key){
    const event=entries.find(e=>e.key===key);if(!event)return;
    const record=event.source==='arrangement'?records.find(r=>r.id===event.id):state.tasks.find(t=>t.id===event.id),d=record.data;
    showDialog(event.title,`<div class="event-detail"><div class="calendar-detail-hero"><span class="event-category ${event.kind}"><i class="calendar-dot ${event.kind}"></i>${kinds[event.kind]}${event.done?' · 已完成':''}</span><div class="event-when">${event.allDay?'全天':esc(event.start+(event.end?' — '+event.end:''))}</div><span class="muted">${pretty(event.day)}</span></div><dl class="calendar-detail-meta">${event.location?'<dt>地点</dt><dd>'+esc(event.location)+'</dd>':''}${event.recurring?'<dt>重复</dt><dd>'+({weekly:'每周',biweekly:'每两周'}[d.repeat])+'，至 '+esc(d.repeat_until)+'</dd>':''}${event.notes?'<dt>备注</dt><dd class="preserve-lines">'+esc(event.notes)+'</dd>':''}</dl>${event.verified===false?'<p class="alert">这个期限还没确认，对照原通知看看吧。</p>':''}${event.source==='task'?`<div class="form-footer"><button type="button" class="button" data-calendar-action="source" data-id="${record.notice_id}">查看原通知</button>${control('查看与编辑待办','edit-task',`data-id="${record.id}"`,'primary')}</div>`:`<div class="form-footer">${control('删除'+(event.recurring?'整组安排':''),'delete',`data-id="${record.id}"`,'danger')}${control('编辑'+(event.recurring?'重复安排':''),'edit',`data-id="${record.id}"`,'primary')}</div>`}</div>`);
  }
  const emptyArrangement=()=>({title:'',category:'personal',start_date:selected,end_date:selected,start_time:'09:00',end_time:'10:00',repeat:'none',repeat_until:null,location:'',notes:''});
  async function creationStatus(requestId){
    try{return await api('/arrangements/requests/'+encodeURIComponent(requestId));}
    catch(error){
      // Static files can update before an older local process is restarted.
      // Only a confirmed pre-receipt server may use the original editable flow.
      if(error.status===404){
        const health=await api('/health'),version=/^(\d+)\.(\d+)\.(\d+)$/.exec(health.version||'');
        if(health.status==='ok'&&version&&Number(version[1])===1&&(Number(version[2])<14||(Number(version[2])===14&&Number(version[3])===0)))return {state:'legacy'};
      }
      throw error;
    }
  }
  function recoverySummary(data={}){
    return `<dl class="calendar-detail-meta"><dt>名称</dt><dd>${esc(data.title||'未命名安排')}</dd><dt>分类</dt><dd>${esc(kinds[data.category]||'个人安排')}</dd><dt>日期</dt><dd>${esc(data.start_date)}${data.end_date!==data.start_date?' 至 '+esc(data.end_date):''}</dd><dt>时间</dt><dd>${data.start_time?esc(data.start_time+' — '+data.end_time):'全天'}</dd>${data.repeat&&data.repeat!=='none'?'<dt>重复</dt><dd>'+esc((data.repeat==='weekly'?'每周':'每两周')+'，至 '+data.repeat_until)+'</dd>':''}${data.location?'<dt>地点</dt><dd>'+esc(data.location)+'</dd>':''}${data.notes?'<dt>备注</dt><dd class="preserve-lines">'+esc(data.notes)+'</dd>':''}</dl>`;
  }
  function recoverCreation(key,payload,receipt=null){
    const saved=receipt?.arrangement,deleted=receipt?.state==='deleted';
    showDialog(receipt?'看看上次有没有存上':'暂时查不到保存结果',`<section id="arrangement-recovery" class="stack"><p class="alert">${!receipt?'暂时连不上，查不到上次有没有存成功。草稿还在，网络好了再试一次。':deleted?'这份草稿的安排之前存过，后来被删掉了，不会自动重新建。':'这份草稿的安排已经存好了。可以看看现在的记录，或者另建一项新安排。'}</p>${saved?'<details class="recovery-record" open><summary>已经存好的安排</summary>'+recoverySummary(saved.data)+'</details>':''}<details class="recovery-record" ${!saved?'open':''}><summary>草稿里的内容</summary>${recoverySummary(payload.data)}</details><p class="small muted recovery-note">${receipt?'另建的话原来的安排不变；去看记录的话，草稿也会留着。':'查清楚之前，不会重复提交，也不会丢掉草稿。'}</p><div class="form-footer recovery-actions">${!receipt?'<button type="button" class="button primary" data-arrangement-recovery="retry">再查一次</button>':`${saved?'<button type="button" class="button primary" data-arrangement-recovery="view">查看已保存安排</button>':''}<button type="button" class="button" data-arrangement-recovery="copy">用这些内容另建</button><button type="button" class="button" data-arrangement-recovery="blank">清空草稿后新建</button>`}</div></section>`);
    const root=$('#arrangement-recovery'),context=captureUiContext(state,root);
    for(const button of root.querySelectorAll('[data-arrangement-recovery]'))button.addEventListener('click',async()=>{
      if(!context.sameDialog()||!context.sameRoute())return;
      const action=button.dataset.arrangementRecovery;
      if(action==='retry'){await editor();return;}
      if(action==='view'){
        selected=saved.data.start_date;view='day';query='';visible.add(saved.data.category);
        records=records.filter(r=>r.id!==saved.id);records.push(saved);refresh();detail(saved.id+':'+selected);return;
      }
      root.inert=true;button.classList.add('request-pending');button.setAttribute('aria-busy','true');
      try{
        drafts.activate(key);drafts.stage(key,{request_id:crypto.randomUUID(),data:action==='copy'?payload.data:emptyArrangement()});
        await drafts.flush(key);
        if(context.sameDialog()&&context.sameRoute())await editor();
      }catch(error){
        if(!context.sameDialog())return;
        let message=$('.form-error',root);if(!message){message=document.createElement('p');message.className='alert error form-error';message.setAttribute('role','alert');root.prepend(message);}message.textContent='新草稿还没暂存：'+error.message;
      }finally{root.inert=false;button.classList.remove('request-pending');button.removeAttribute('aria-busy');}
    });
  }
  async function editor(record=null){
    const renderId=state.renderId,uid=owner,request=++state.dialogRequest,key=record?'arrangement:'+record.id+':'+record.version:'arrangement-new';
    const cached=await drafts.load(key);if(renderId!==state.renderId||uid!==state.session?.user.id||request!==state.dialogRequest)return;let legacyStatus=false;
    if(!record&&!cached.retired&&cached.payload?.request_id&&!pendingCreates.has(cached.payload.request_id)){
      const payload=structuredClone(cached.payload);let receipt;
      try{receipt=await creationStatus(payload.request_id);}
      catch{if(renderId===state.renderId&&uid===state.session?.user.id&&request===state.dialogRequest)recoverCreation(key,payload);return;}
      if(renderId!==state.renderId||uid!==state.session?.user.id||request!==state.dialogRequest)return;
      legacyStatus=receipt.state==='legacy';
      if(!legacyStatus&&receipt.state!=='missing'){recoverCreation(key,payload,receipt);return;}
    }
    editRecord=record;const creatingAnother=!record&&pendingCreates.has(cached.payload?.request_id);const retired=cached.retired;drafts.activate(key);const restore=creatingAnother||retired?null:cached.payload?.data;
    const d=restore||record?.data||emptyArrangement();
    formRequest=(!creatingAnother&&!retired&&cached.payload?.request_id)||crypto.randomUUID();
    showDialog(record?'编辑安排':'新建安排',`<form id="arrangement-form" data-workspace-form="calendar" data-cache-key="${key}" data-request-id="${formRequest}" class="stack">${field('安排名称','title',d.title,'text','required maxlength="160" autofocus placeholder="例如：课程、办理材料、和朋友的约定"')}<div class="form-grid"><label class="field">分类<select name="category" aria-label="分类">${['course','activity','personal'].map(k=>`<option value="${k}" ${d.category===k?'selected':''}>${kinds[k]}</option>`).join('')}</select></label><label class="check calendar-all-day"><input type="checkbox" name="all_day" ${d.start_time?'':'checked'}>全天安排</label>${field('开始日期','start_date',d.start_date,'date','required min="2000-01-01" max="2100-12-31"')}${field('结束日期','end_date',d.end_date,'date','required min="2000-01-01" max="2100-12-31"')}<div data-schedule-time ${d.start_time?'':'hidden'}>${field('开始时间','start_time',d.start_time||'09:00','time','required')}</div><div data-schedule-time ${d.start_time?'':'hidden'}>${field('结束时间','end_time',d.end_time||'10:00','time','required')}</div></div><details class="schedule-options" ${d.location||d.notes||d.repeat!=='none'?'open':''}><summary>地点、重复和备注</summary><div class="stack">${field('地点（选填）','location',d.location,'text','maxlength="300" placeholder="校区、教学楼或办理地点"')}<div class="form-grid"><label class="field">重复<select name="repeat" aria-label="重复"><option value="none" ${d.repeat==='none'?'selected':''}>不重复</option><option value="weekly" ${d.repeat==='weekly'?'selected':''}>每周</option><option value="biweekly" ${d.repeat==='biweekly'?'selected':''}>每两周（隔周）</option></select></label><div id="repeat-until-field" ${d.repeat==='none'?'hidden':''}>${field('最后重复日期','repeat_until',d.repeat_until||'','date','min="2000-01-01" max="2100-12-31"')}</div></div>${area('备注（选填）','notes',d.notes,3,'maxlength="3000" placeholder="要带的材料、课程周次或留给自己的话"')}</div></details>${record&&d.repeat!=='none'?'<p class="small muted">保存后，整组重复安排会一起更新。</p>':''}<div class="form-footer"><span class="small muted spacer">北京时间<span class="autosave-status" role="status"></span></span><button type="submit" class="button primary">保存安排</button></div></form>`);
    if(legacyStatus){const note=document.createElement('p');note.className='alert';note.dataset.creationStatus='legacy';note.textContent='上次有没有存上，去日历里看一眼吧。已经有的话直接打开编辑，别重复新建。';$('#arrangement-form').prepend(note);}
    syncForm();
  }
  function readForm(form){const f=new FormData(form),all=f.get('all_day')==='on',repeat=f.get('repeat');return {title:f.get('title'),category:f.get('category'),start_date:f.get('start_date'),end_date:f.get('end_date'),start_time:all?null:f.get('start_time'),end_time:all?null:f.get('end_time'),repeat,repeat_until:repeat==='none'?null:f.get('repeat_until')||null,location:f.get('location'),notes:f.get('notes')};}
  function syncForm(){const form=$('#arrangement-form');if(!form)return;const all=form.elements.all_day.checked,repeat=form.elements.repeat.value;for(const wrap of form.querySelectorAll('[data-schedule-time]')){wrap.hidden=all;wrap.querySelector('input').disabled=all;}$('#repeat-until-field').hidden=repeat==='none';form.elements.repeat_until.required=repeat!=='none';if(repeat!=='none')$('.schedule-options').open=true;}
  function stash(){const f=$('#arrangement-form');if(f){const key=f.dataset.cacheKey;if(drafts.peek(key).retired)return;const snapshot={data:readForm(f),request_id:f.dataset.requestId};if(JSON.stringify(snapshot)!==JSON.stringify(drafts.peek(key).payload))drafts.stage(key,snapshot);}}
  document.addEventListener('input',e=>{if(e.target.id==='calendar-query'||e.target.id==='calendar-option-query'){query=e.target.value;listPage=1;refresh();}if(e.target.closest('#arrangement-form'))stash();});
  document.addEventListener('change',e=>{
    const el=e.target;if(el.id==='calendar-week-start'){
      const view=captureUiContext(state,el),base=structuredClone(state.session.user.profile),value=Number(el.value);el.disabled=true;
      patchProfile(api,base,{week_starts_on:value}).then(profile=>{if(!view.sameUser())return;state.session.user.profile.week_starts_on=profile.week_starts_on;weekStartsOn=profile.week_starts_on;refresh();toast('一周开始日期已保存');})
        .catch(error=>{if(!view.sameUser())return;if(error.detail?.profile)state.session.user.profile=error.detail.profile;weekStartsOn=state.session.user.profile.week_starts_on;el.value=weekStartsOn;refresh();toast(error.message,true);}).finally(()=>{el.disabled=false;});
    }
    if(el.id==='picker-year'||el.id==='picker-month'){pickerMonth=$('#picker-year').value+'-'+$('#picker-month').value+'-01';datePicker();$('#'+el.id)?.focus({preventScroll:true});}
    if(el.dataset.calendarKind){el.checked?visible.add(el.dataset.calendarKind):visible.delete(el.dataset.calendarKind);for(const input of document.querySelectorAll('[data-calendar-kind]'))input.checked=visible.has(input.dataset.calendarKind);refresh();}
    if(el.id==='calendar-show-done'||el.id==='calendar-option-done'){showDone=el.checked;for(const input of document.querySelectorAll('#calendar-show-done,#calendar-option-done'))input.checked=showDone;refresh();}
    if((el.id==='calendar-jump'||el.id==='calendar-option-date')&&el.value&&el.validity.valid){selected=el.value;view='day';listPage=1;refresh();}
    if(el.closest('#arrangement-form')){if(el.name==='start_date'&&el.value&&el.form.elements.end_date.value<el.value)el.form.elements.end_date.value=el.value;syncForm();stash();}
  });
  document.addEventListener('submit',async e=>{
    const form=e.target;if(form.id==='semester-form'){
      e.preventDefault();const view=captureUiContext(state,form),finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;
      const values=Object.fromEntries(new FormData(form));form.inert=true;
      try{const profile=await saveProfileForm(api,form,values);if(!view.sameUser())return;applyProfileForm(state,form,profile,values);if(view.sameDialog())$('#dialog').close();if(view.sameRoute())refresh();toast('学期与周次已保存');}
      catch(error){if(view.sameUser()&&!error.formHandled)toast(error.message,true);}finally{form.inert=false;finishFeedback();}return;
    }if(form.id!=='arrangement-form')return;e.preventDefault();const finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;stash();form.inert=true;const key=form.dataset.cacheKey;const submissionContext=captureUiContext(state,form),old=editRecord,uid=owner,request=form.dataset.requestId,submittedCache=drafts.checkpoint(key),submittedData=readForm(form);if(!old)pendingCreates.add(request);
    try{await drafts.flush(key);const saved=await api('/arrangements'+(old?'/'+old.id:''),{method:old?'PUT':'POST',json:old?{data:submittedData,version:old.version}:{data:submittedData,request_id:request}});if(uid!==state.session?.user.id)return;records=records.filter(r=>r.id!==saved.id);records.push(saved);let cacheWarning='';try{await drafts.retire(key,submittedCache);}catch{cacheWarning='；不过旧草稿没清理掉，可以检查一下暂存内容';}if(formRequest===request)formRequest='';if($('#arrangement-form')===form)$('#dialog').close();toast('安排存好了'+cacheWarning,!!cacheWarning,{duration:15000,action:{label:'撤销',run:async()=>{if(uid!==state.session?.user.id)throw Error('账号切换了，没法撤销原账号的安排。');const restored=await api('/arrangements/'+saved.id,{method:old?'PUT':'DELETE',json:old?{version:saved.version,data:old.data}:{version:saved.version}});if(uid!==state.session?.user.id)return;records=records.filter(r=>r.id!==saved.id);if(old)records.push(restored);if(submissionContext.sameRoute())refresh();}}});refresh();document.dispatchEvent(new CustomEvent('campus:milestone',{detail:'arrangement-saved'}));}
    catch(error){
      if(uid!==state.session?.user.id)return;
      if(!old&&submissionContext.sameDialog()&&submissionContext.sameRoute()){
        try{const receipt=await creationStatus(request);if(submissionContext.sameDialog()&&submissionContext.sameRoute()&&receipt.state!=='missing'&&receipt.state!=='legacy'){recoverCreation(key,{request_id:request,data:submittedData},receipt);return;}}catch{/* Keep the original error and the editable draft when status is unavailable. */}
      }
      let p=$('.form-error',form);if(!p){p=document.createElement('p');p.className='alert error form-error';p.setAttribute('role','alert');form.prepend(p);}p.textContent=error.message;p.scrollIntoView({block:'nearest'});
    }
    finally{pendingCreates.delete(request);form.inert=false;finishFeedback();}
  });
  document.addEventListener('click',async e=>{
    const tab=e.target.closest('[data-calendar-view]'),date=e.target.closest('[data-calendar-day]'),item=e.target.closest('[data-calendar-event]'),button=e.target.closest('[data-calendar-action]');
    if(tab){view=tab.dataset.calendarView;listDay=false;listPage=1;refresh();}
    const cell=e.target.closest('[data-calendar-cell]');if(cell&&!item&&!button){selected=cell.dataset.calendarCell;view='week';refresh();return;}
    if(date){selected=date.dataset.calendarDay;listPage=1;if(date.closest('#calendar-mini')){if(view==='list')listDay=true;else view='day';}else if(date.classList.contains('month-date'))view='week';const focusMonth=date.classList.contains('month-date');refresh();if(focusMonth)$(`.time-grid-header [data-calendar-day="${selected}"]`)?.focus({preventScroll:true});else document.querySelector(`.period-week-header [data-calendar-day="${selected}"],.time-grid-header [data-calendar-day="${selected}"],#calendar-mini [data-calendar-day="${selected}"]`)?.focus({preventScroll:true});}
    if(item)detail(item.dataset.calendarEvent);
    if(!button)return;const action=button.dataset.calendarAction,id=button.dataset.id;button.disabled=true;
    try{
      if(action==='list-prev'||action==='list-next'){listPage+=action==='list-prev'?-1:1;refresh();}
      else if(action==='list-month'){listDay=false;listPage=1;refresh();}
      else if(action==='reset-filters'){visible=new Set(Object.keys(kinds));showDone=false;query='';listPage=1;for(const el of document.querySelectorAll('[data-calendar-kind]'))el.checked=true;for(const el of document.querySelectorAll('#calendar-show-done,#calendar-option-done'))el.checked=false;refresh();}
      else if(action==='options-back'){options();}
      else if(action==='today'){selected=dayKey();refresh();if($('#calendar-option-date'))$('#calendar-option-date').value=selected;}
      else if(action==='previous'||action==='next'){const n=action==='next'?1:-1,candidate=view==='month'||(view==='list'&&!listDay)?shiftMonth(selected,n):addDays(selected,n*(view==='week'?7:1));if(candidate>='2000-01-01'&&candidate<='2100-12-31'){selected=candidate;listPage=1;refresh();}}
      else if(action==='open-day'){selected=button.dataset.day||selected;view='day';refresh();$('#calendar-title').scrollIntoView({block:'nearest'});}
      else if(action==='new')await editor();
      else if(action==='options')options();
      else if(action==='date-picker'){pickerMonth=selected.slice(0,7)+'-01';pickerMode=['day','week','month'].includes(view)?view:'day';datePicker();}
      else if(action==='picker-prev'||action==='picker-next'){const candidate=shiftMonth(pickerMonth,action==='picker-next'?1:-1);if(candidate>='2000-01-01'&&candidate<='2100-12-31'){pickerMonth=candidate;datePicker();document.querySelector('[data-calendar-action="'+action+'"]')?.focus({preventScroll:true});}}
      else if(action==='picker-mode'){pickerMode=button.dataset.mode;datePicker();document.querySelector('[data-calendar-action="picker-mode"][data-mode="'+pickerMode+'"]')?.focus({preventScroll:true});}
      else if(action==='picker-date'||action==='picker-month'){selected=action==='picker-month'?pickerMonth:button.dataset.day;view=pickerMode;listPage=1;$('#dialog').close();refresh();$('#calendar-title')?.focus({preventScroll:true});}
      else if(action==='semester'){const p=state.session.user.profile;showDialog('学期与周次',`<form id="semester-form" data-workspace-form="calendar" class="stack">${field('学期名称','semester',p.semester||'','text','maxlength="40" placeholder="例如：2026—2027 第一学期"')}${field('第一周内的任意一天','semester_start',p.semester_start||'','date','min="2000-01-01" max="2100-12-31"')}<p class="small muted">照着学校校历填就行。不填的话只显示日期；改周次不会挪动已保存的课程。</p><div class="form-footer"><button type="submit" class="button primary">保存</button></div></form>`);bindProfileForm($('#semester-form'),p);}
      else if(action==='day-collisions'){showDialog(pretty(button.dataset.day)+'的安排',entries.filter(e=>e.day===button.dataset.day).map(e=>agendaRow(e,false)).join(''));}
      else if(action==='outside-times'){const [from,to]=range();showDialog('全天与其他时段',entries.filter(e=>e.day>=from&&e.day<=to&&(e.allDay||minute(e.start)<480||minute(e.start)>=1320||(e.end&&minute(e.end)>1320))).map(e=>agendaRow(e)).join(''));}
      else if(action==='edit')await editor(records.find(r=>r.id===id));
      else if(action==='source'){$('#dialog').close();location.hash='notice/'+id;}
      else if(action==='edit-task'){await editTask(id);}
      else if(action==='delete'){const record=records.find(r=>r.id===id);if(!record)return;const repeated=record.data.repeat!=='none';if(await ask(repeated?'删除整组重复安排？':'删除这项安排？',`“${record.data.title}”${repeated?'的所有重复日期':'的记录'}会被删除。已经导进手机或其他日历的，记得在那边也删掉。`,'删除')){await api('/arrangements/'+id,{method:'DELETE',json:{version:record.version}});records=records.filter(r=>r.id!==id);toast('安排已删除');refresh();}}
      else if(action==='undated'){showDialog('还没定日期的待办',`<p class="small muted">正式期限还不明确时，可以先设一个自己的准备时间。</p>${state.tasks.filter(t=>taskIsPending(t)&&t.data.scope==='personal'&&!t.data.due_date&&!t.data.planned_at).map(taskRow).join('')}`);}
      else if(action==='exports'){showDialog('导出与提醒',`<div class="stack"><p>导出的日历文件要自己导入手机或电脑日历。导入后，看看时间、重复和提醒对不对。</p><div class="row wrap">${control('导出课程与个人安排','export-arrangements','','primary')}<button type="button" class="button" data-action="export-all">导出已确认的待办</button></div><p class="small muted">导出后如果改期或删除，记得在手机日历里同步改。网页没法在锁屏时提醒你，提醒要靠手机日历。</p>${calendarHelp()}</div>`);}
      else if(action==='export-arrangements'){if(!records.length){toast('还没有可导出的课程或个人安排');return;}const blob=await api('/arrangements/export',{method:'POST',json:{ids:records.map(r=>r.id),versions:Object.fromEntries(records.map(r=>[r.id,r.version]))},blob:true});download(blob,'我的校园安排.ics');toast('文件导出好了，记得导入手机日历并检查一下');}
    if(['semester','exports','undated'].includes(action)&&$('#dialog').open&&!$('#dialog [data-dialog-back]')){const back=document.createElement('button');back.type='button';back.className='button small plain dialog-context-back';back.dataset.calendarAction='options-back';back.innerHTML=icon('back')+' 返回日历设置';$('#dialog .dialog-body').prepend(back);}
    }catch(error){toast(error.message,true);}finally{button.disabled=false;if(document.activeElement===document.body&&button.isConnected&&!$('#dialog').open)button.focus({preventScroll:true});}
  });
  document.addEventListener('keydown',e=>{const cell=e.target.closest('.month-date');if(!cell)return;const n={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[e.key];if(n){e.preventDefault();selected=addDays(cell.dataset.calendarDay,n);refresh();focusMonthControl($(`.month-date[data-calendar-day="${selected}"]`));}});
  window.addEventListener('hashchange',()=>{stash();if(!belongs()){monthResize.disconnect();monthElement=null;}});
  phone.addEventListener('change',()=>{if(belongs())refresh();});
  function openRecord(id){
    const record=records.find(r=>r.id===id);if(!record)throw Error('这项日程已经删掉了，或者不在你的账号里。');
    selected=record.data.start_date;visible.add(record.data.category||'personal');query='';refresh();
    const event=entries.find(e=>e.id===id);
    if(event)detail(event.key);else editor(record);
  }
  return {render,refresh,persist:stash,openRecord};
}
