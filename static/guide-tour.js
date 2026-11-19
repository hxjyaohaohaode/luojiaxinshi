import {createGuideSpotlight} from './guide-spotlight.js';

const receive='.home-heading a[href="#new"]',sources='.home-heading a[href="#sources"]';
const body='#notice-form textarea[name="body"]',save='#notice-form button[name="intent"][value="save"]';
const picker='.source-page-heading [data-source-action="school-presets"]',search='#source-presets #source-preset-search';
const result='#source-preset-list :is([data-source-action="preset-subscribe"],[data-source-action="preset-view"]):enabled';
const agenda='.home-agenda .home-section-heading a[href="#calendar"]',today='.calendar-toolbar [data-calendar-action="today"]';
const steps={
  receive:{page:'dashboard',target:receive,count:'新手指引 · 1 / 3',title:'点「收通知」',text:'群里收到通知时，从这个按钮开始。现在点一下，去看看正文贴在哪里。',action:'sources',label:'我想订阅武大官网'},
  sources:{page:'dashboard',target:sources,count:'官网订阅 · 1 / 4',title:'点「订阅与来源」',text:'从这里挑选想关注的武大官网栏目。',action:'receive',label:'我想试试收通知'},
  body:{page:'new',target:body,count:'收通知 · 2 / 3',title:'点「通知正文」输入框',text:'把收到的通知粘贴在这里。手头没有通知，也可以点一下空白处试试。'},
  editing:{page:'new',target:body,count:'收通知 · 2 / 3',title:'在这里粘贴原文',text:'填好后可以找保存按钮。只想熟悉页面，也可以留空继续。',action:'save',label:'看保存按钮'},
  save:{page:'new',target:save,count:'收通知 · 3 / 3',title:'用「仅保存原件」收下通知',text:'填好原文并确认有权保存后，点这里留存原件。想知道截止日期在哪里看，可以接着找日程。',complete:true,action:'agenda',label:'再看日程入口'},
  agenda:{page:'dashboard',target:agenda,count:'查看日程 · 1 / 2',title:'点「全部日程」',text:'首页这里通往你的个人日历。点亮框进去看看。'},
  today:{page:'calendar',target:today,count:'查看日程 · 2 / 2',title:'点「今」回到今天',text:'你确认要办、并且有明确日期的事项会出现在这里。点「今」回到今天，也就走完了指引。',action:'finish',label:'结束指引'},
  picker:{page:'sources',target:picker,count:'官网订阅 · 2 / 4',title:'点「选择武汉大学来源」',text:'这里列出了已接入的校级部门和学院，可以按栏目订阅。'},
  search:{page:'sources',target:search,count:'官网订阅 · 3 / 4',title:'搜索想关注的栏目',text:'在框里输入学院或部门，例如“图书馆”。',action:'result',label:'看栏目按钮'},
  result:{page:'sources',target:result,count:'官网订阅 · 4 / 4',action:'finish',label:'结束指引'}
};

export function startGuideTour({sameUser,onShown,onEnd}){
  let current='receive',frame=0,shown=false,enteredPicker=false;
  const spot=createGuideSpotlight(action=>{
    if(action==='finish'||action==='skip')stop(true);
    else if(action==='agenda'){change('agenda');location.hash='#dashboard';}
    else if(action==='result'&&!document.querySelector(result))change('search');
    else if(Object.hasOwn(steps,action))change(action);
  });
  const listeners=new AbortController();
  function change(next){
    if(steps[current].page!==steps[next].page)spot.hide();
    current=next;schedule();
  }
  function schedule(){
    if(!frame)frame=requestAnimationFrame(()=>{frame=0;sync();});
  }
  function sync(routeReady=false){
    if(!sameUser()){stop();return;}
    const step=steps[current],root=document.querySelector('#content');
    if(!root||root.inert)return;
    const actual=location.hash.slice(1)||'dashboard';
    if(step.page!==actual||root.dataset.page!==step.page){
      if(routeReady&&root.dataset.page===actual)stop();
      return;
    }
    const dialog=document.querySelector('dialog[open]');
    if(current==='search'||current==='result'){
      if(!dialog){if(enteredPicker)stop();return;}
      if(!dialog.querySelector('#source-presets')||dialog.querySelector('#source-presets .alert.error')){stop();return;}
      enteredPicker=true;
    }else if(dialog){stop();return;}
    const target=(dialog||root).querySelector(step.target);
    if(!target){
      if(current==='result')change('search');
      else if(routeReady&&current!=='search')stop();
      return;
    }
    let details=step;
    if(current==='search'){
      const term=target.value.trim(),found=!!dialog.querySelector(result);
      details={...step,disabled:!term||!found};
      if(term)details.text=found?'下方显示了匹配的栏目。点「看栏目按钮」，找到其中一个。':'当前结果里没有可选的栏目，换个学院或部门名称试试。';
    }else if(current==='result'){
      const name=target.closest('article')?.querySelector('h3')?.textContent||'这个栏目';
      const subscribed=target.dataset.sourceAction==='preset-view';
      details={...step,title:subscribed?'这个栏目已经订阅':'点「订阅此栏目」即可接收',text:subscribed?'「'+name+'」已在你的来源里。点亮框可以查看它。':'亮框对应「'+name+'」。想接收这个栏目的通知再点订阅，只练习可以直接结束。'};
    }
    spot.show(target,details);
    if(!shown){shown=true;onShown();}
  }
  function click(event){
    if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    const el=event.target;
    if(el.closest('[data-onboarding-guide]'))return;
    if(current==='receive'||current==='sources'){
      if(el.closest('a[href="#new"]'))change('body');
      else if(el.closest('a[href="#sources"]'))change('picker');
    }else if(current==='body'&&el.closest(body))change('editing');
    else if(current==='picker'&&el.closest(picker))change('search');
    else if(current==='agenda'&&el.closest('a[href="#calendar"]'))change('today');
    else if(el.closest(save)||el.closest(result)||current==='today'&&el.closest(today))stop();
  }
  function input(event){
    if(current==='body'&&event.target.matches(body))change('editing');
    else if((current==='result'||current==='search')&&event.target.closest('#source-presets'))change('search');
  }
  function stop(restore=false){
    const active=spot.target;
    const focusGuide=document.activeElement?.closest('[data-onboarding-guide]');
    listeners.abort();observer.disconnect();cancelAnimationFrame(frame);spot.destroy();onEnd();
    if(restore&&focusGuide&&active?.isConnected)active.focus({preventScroll:true});
  }
  function keydown(event){
    if(event.key==='Escape'){
      event.preventDefault();event.stopImmediatePropagation();stop(true);
    }
  }
  const observer=new MutationObserver(records=>{
    // The picker renders its list asynchronously; the personal home can also refresh in place.
    if(records.some(r=>!r.target.closest?.('[data-onboarding-guide]')))schedule();
  });
  observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});
  const capture={capture:true,signal:listeners.signal};
  document.addEventListener('click',click,capture);
  document.addEventListener('input',input,capture);document.addEventListener('change',input,capture);
  document.addEventListener('keydown',keydown,capture);
  document.addEventListener('close',schedule,capture);
  window.addEventListener('hashchange',()=>{
    if((location.hash.slice(1)||'dashboard')!==steps[current].page)stop();
  },{signal:listeners.signal});
  schedule();
  return {sync,stop};
}
