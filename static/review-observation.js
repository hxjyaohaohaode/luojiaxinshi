// Per-opening, scalar-only observation. It is not evidence of pure correction time.
const IDLE_MS=60000,MAX_MS=28800000;

export class ReviewClock{
  constructor(now=0){this.last=now;this.until=now+IDLE_MS;this.visible=true;this.editing=false;this.active=0;this.edited=0;}
  advance(now){
    now=Math.max(this.last,now);
    const delta=this.visible?Math.max(0,Math.min(now,this.until)-this.last):0;
    const accepted=Math.min(delta,MAX_MS-this.active);
    this.active+=accepted;if(this.editing)this.edited+=accepted;
    this.last=now;
  }
  activity(now){this.advance(now);this.until=this.last+IDLE_MS;}
  visibility(now,value){this.advance(now);if(value&&!this.visible)this.until=this.last+IDLE_MS;this.visible=value;}
  focus(now,value){this.advance(now);this.editing=value;}
  snapshot(now){this.advance(now);return {method:'visible_idle_60s_v1',active_ms:Math.floor(this.active),editing_ms:Math.floor(this.edited)};}
}

function duration(ms){if(ms>=MAX_MS)return '8 小时（记录上限）';const seconds=Math.floor(ms/1000);return seconds<60?seconds+' 秒':Math.floor(seconds/60)+' 分 '+seconds%60+' 秒';}
export function observationPanel(){
  return '<details class="review-observation"><summary>核对用时（本次页面）<span data-review-time>0 秒</span></summary><p class="small muted" data-review-editing>编辑区活跃 0 秒</p><p class="small muted">浏览器估算，切出页面或连续 60 秒无操作后暂停；提交等待不计入。关闭、刷新或重新打开分别计时。编辑区时间含停留阅读，完整办理用时还需计入材料准备、模型等待和日历操作。</p></details>';
}
export function observationReceipt(value,imported=false){
  if(!value)return '';
  return `<details class="review-observation"><summary>${imported?'原页面历史用时':'本次页面核对用时'} · ${duration(value.active_ms)}</summary><p class="small">页面活跃 ${duration(value.active_ms)}，其中编辑区活跃 ${duration(value.editing_ms)}。</p><p class="small muted">浏览器估算，仅含这次打开的时段；切出页面、连续 60 秒无操作后的时间和提交等待未计入。编辑区时间包含阅读，不能作为纯纠错时间或完整办理时间。</p></details>`;
}

export function createReviewObserver(){
  let current=null,timer=null;
  const now=()=>performance.now();
  const editable=target=>!!target?.matches?.('textarea,input:not([type=hidden]):not([type=submit]):not([name=reviewed]),select');
  function update(){
    if(!current)return;
    if(!current.form.isConnected){leave();return;}
    const visible=!current.paused&&document.visibilityState==='visible'&&document.hasFocus();
    current.clock.visibility(now(),visible);
    current.clock.focus(now(),editable(document.activeElement)&&current.form.contains(document.activeElement));
    const value=current.clock.snapshot(now());
    const label=current.form.querySelector('[data-review-time]');if(label)label.textContent=duration(value.active_ms);
    const editing=current.form.querySelector('[data-review-editing]');if(editing)editing.textContent='编辑区活跃 '+duration(value.editing_ms);
  }
  function leave(){if(current)current.clock.visibility(now(),false);current=null;clearInterval(timer);timer=null;}
  function activity(event){
    if(!current||current.paused||!current.form.isConnected||!document.hasFocus()||document.visibilityState!=='visible')return;
    if(!event.target?.closest?.('#content'))return;
    update();current.clock.activity(now());
  }
  for(const name of ['pointerdown','keydown','input','scroll'])document.addEventListener(name,activity,{capture:true,passive:true});
  for(const name of ['focusin','focusout'])document.addEventListener(name,update,true);
  document.addEventListener('visibilitychange',update);
  window.addEventListener('blur',()=>{if(current)current.clock.visibility(now(),false);});
  window.addEventListener('focus',update);
  window.addEventListener('pagehide',leave);
  return {
    bind(form,key){
      if(!form){leave();return;}
      if(!current||current.key!==key){leave();current={key,form,clock:new ReviewClock(now()),paused:false};timer=setInterval(update,1000);}
      else current.form=form;
      update();
    },
    leave,
    capture(form){
      if(!current||current.form!==form)return null;
      update();current.paused=true;current.clock.visibility(now(),false);
      return current.clock.snapshot(now());
    },
    resume(form){if(current?.form===form&&form.isConnected){current.paused=false;update();}},
  };
}
