export class EndPullState{
  constructor(threshold=92){this.threshold=threshold;this.distance=0;}
  pull(distance){this.distance=Math.max(0,distance);return this.progress;}
  get progress(){return Math.min(1,this.distance/this.threshold);}
  get armed(){return this.distance>=this.threshold;}
  reset(){this.distance=0;}
}

// A second deliberate gesture at the end, never the momentum that got there.
// This only opens the existing new-chat flow; the previous draft stays saved.
export function createChatEndGesture({reader,onNew,enabled=()=>true,onError=()=>{}}){
  const area=reader.closest('.chat-reading-area')||reader.parentElement,controller=new AbortController(),signal=controller.signal;
  const pull=new EndPullState(),button=document.createElement('button');button.type='button';button.className='chat-end-gesture';button.hidden=true;
  button.innerHTML='<span class="chat-end-symbol" aria-hidden="true"><svg viewBox="0 0 36 36" fill="none" stroke="currentColor"><circle class="chat-end-track" cx="18" cy="18" r="16"/><circle class="chat-end-progress" cx="18" cy="18" r="16" pathLength="1"/><path d="M13 14H9v13h14v-4M14 22l1-5L25 7l4 4-10 10Z"/></svg></span><span class="chat-end-label"></span>';
  button.setAttribute('aria-label','新建对话');area.append(button);const label=button.querySelector('.chat-end-label');
  let release=0,confirmation=0,touch=null,wheelAt=0,wheelEligible=false,wheelDistance=0,opening=false,bottomSince=0,disposed=false,confirming=false;
  const bottom=()=>reader.scrollHeight-reader.scrollTop-reader.clientHeight<=3;
  const available=()=>!disposed&&reader.isConnected&&enabled()&&!document.hidden&&!document.querySelector('#dialog[open]')&&!document.body.classList.contains('materials-open')&&window.getSelection()?.type!=='Range';
  const excluded=target=>target.closest?.('button,a,input,textarea,select,summary,[contenteditable],pre,canvas,.gu-table-wrap,.gu-chart,.gu-plot,.openui-surface,.execution-trace');
  function paint(kind){button.hidden=pull.distance<4&&!confirming;area.classList.toggle('is-end-pull',!button.hidden);area.style.setProperty('--end-pull',Math.min(160,pull.distance*.9)+'px');button.style.setProperty('--end-progress',String(pull.progress));button.style.opacity=String(confirming?1:Math.min(1,pull.progress*1.4));button.dataset.armed=String(pull.armed);button.dataset.phase=confirming?'confirming':'pulling';button.setAttribute('aria-label',confirming?'取消新建对话':'新建对话');label.textContent=confirming?'即将新建 · 取消':pull.armed?(kind==='wheel'?'停止滚动后新建':'松手新建'):'新对话';}
  function reset(){clearTimeout(release);clearTimeout(confirmation);confirming=false;pull.reset();touch=null;wheelDistance=0;wheelEligible=false;paint();}
  async function open(){if(opening||!available())return reset();opening=true;button.disabled=true;try{await onNew();}catch(error){onError(error);}finally{opening=false;button.disabled=false;reset();}}
  function finish(){if(!pull.armed||!available()){reset();return;}confirming=true;touch=null;paint();confirmation=setTimeout(()=>{confirming=false;void open();},1200);}
  const noteBottom=()=>{if(bottom()){if(!bottomSince)bottomSince=performance.now();}else{bottomSince=0;if(pull.distance)reset();}};
  reader.addEventListener('scroll',noteBottom,{passive:true,signal});noteBottom();
  area.addEventListener('wheel',event=>{
    if(!available()||excluded(event.target)&&!button.contains(event.target)||event.ctrlKey||event.shiftKey||Math.abs(event.deltaX)>Math.abs(event.deltaY)){reset();return;}
    if(confirming){reset();wheelAt=performance.now();return;}
    const now=performance.now(),gap=now-wheelAt;
    if(event.deltaY<=0){reset();wheelAt=now;return;}
    if(!wheelEligible&&gap>=420){wheelDistance=0;wheelEligible=bottom()&&!!bottomSince&&now-bottomSince>=300;}
    if(wheelEligible&&gap>1600){wheelDistance=0;wheelEligible=bottom();}
    wheelAt=now;if(!wheelEligible||!bottom())return;
    event.preventDefault();const delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?reader.clientHeight:1);wheelDistance+=Math.min(72,Math.max(0,delta));pull.threshold=220;pull.pull(wheelDistance);paint('wheel');clearTimeout(release);release=setTimeout(pull.armed?finish:reset,pull.armed?500:1600);
  },{passive:false,signal});
  reader.addEventListener('touchstart',event=>{
    const cancelling=confirming;reset();if(cancelling||event.touches.length!==1||!available()||!bottom()||excluded(event.target))return;
    const point=event.touches[0];touch={x:point.clientX,y:point.clientY,id:point.identifier};pull.threshold=110;
  },{passive:false,signal});
  reader.addEventListener('touchmove',event=>{
    if(!touch)return;if(event.touches.length!==1||!available()){reset();return;}
    const point=event.touches[0],dy=touch.y-point.clientY,dx=point.clientX-touch.x;
    if(Math.abs(dx)>Math.abs(dy)+8){reset();return;}
    if(dy>3){event.preventDefault();event.stopPropagation();reader.scrollTop=reader.scrollHeight;pull.pull(dy);paint('touch');}else if(pull.distance){pull.pull(0);paint('touch');}
  },{passive:false,signal});
  reader.addEventListener('touchend',()=>{if(touch)finish();},{signal});reader.addEventListener('touchcancel',reset,{signal});
  button.addEventListener('click',()=>{if(confirming)reset();else{pull.pull(pull.threshold);finish();}},{signal});
  document.addEventListener('keydown',event=>{if(confirming||event.key==='Escape')reset();},{signal});
  document.addEventListener('pointerdown',event=>{if(!button.contains(event.target)&&(confirming||!reader.contains(event.target)))reset();},{passive:true,signal});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)reset();},{signal});
  const dispose=()=>{if(disposed)return;reset();disposed=true;controller.abort();button.remove();area.classList.remove('is-end-pull');area.style.removeProperty('--end-pull');};
  window.addEventListener('hashchange',dispose,{signal});
  return {dispose,reset};
}
