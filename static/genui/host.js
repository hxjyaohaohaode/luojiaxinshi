import {calendarEntries,dayKey,addDays} from '../calendar-model.js';
import {el,button} from './dom.js';
const poses=new Set(['welcome','reading','planning','blossom','rest']);
export function hostRegistry({sources=[],arrangements=[],tasks=[],preview,openCalendar,openSources}){
  const hostViews={
    campus_schedule:()=>{
      const panel=el('section','gu-host-panel'),today=dayKey(),entries=calendarEntries(arrangements,tasks,today,addDays(today,6));panel.append(el('h4','','未来七天 · 工作台当前记录'));
      const list=el('ul','gu-host-list');for(const item of entries.slice(0,5)){const li=el('li');li.append(el('strong','',item.title),el('div','gu-muted',item.day+' · '+(item.start||'全天')+(item.location?' · '+item.location:'')));list.append(li);}
      if(!entries.length)panel.append(el('p','gu-muted','这七天还没有已保存的安排。'));else panel.append(list);panel.append(button(entries.length>5?'在日历查看全部 '+entries.length+' 项':'打开日历',openCalendar));return panel;
    },
    material_index:()=>{
      const panel=el('section','gu-host-panel');panel.append(el('h4','','本次材料'));const list=el('ul','gu-host-list');for(const source of sources){const li=el('li');li.append(button(source.name,()=>preview(source.id)),el('span','gu-muted',source.status==='failed'?'读取失败':'请对照原件核对'));list.append(li);}panel.append(sources.length?list:el('p','gu-muted','可以先从“添加材料”放入通知原文。'));return panel;
    },
    messenger:p=>{
      const panel=el('div','gu-messenger'),b=button('',null,'gu-messenger-button'),img=el('img'),words=el('span','',p.title||'先把眼前的一件事做好。');let taps=0,timer;
      img.src='/static/assets/luojia-messenger-'+(poses.has(p.pose)?p.pose:'reading')+'.png';img.alt='珞珈小信使';b.setAttribute('aria-label','和小信使打个招呼');b.append(img);b.addEventListener('click',()=>{taps++;clearTimeout(timer);if(taps===3){img.src='/static/assets/luojia-messenger-blossom.png';words.textContent='忙完这一件，也记得去珞珈山下走走。';taps=0;}timer=setTimeout(()=>{taps=0;},1000);});panel.append(b,words);return panel;
    }
  };
  return {hostViews,hostActions:{open_calendar:{run:openCalendar},open_sources:{run:openSources},review_material:{run:({source_id})=>{if(!sources.some(s=>s.id===source_id))throw Error('这份材料不在本次对话中。');preview(source_id);}}}};
}
