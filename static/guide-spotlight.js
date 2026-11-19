// The ring and its shadow never receive pointer events. The highlighted element
// keeps its own link, focus, input and submit behaviour.
export function createGuideSpotlight(onAction){
  const layer=document.createElement('div');
  layer.className='guide-layer';
  layer.dataset.onboardingGuide='';
  layer.setAttribute('popover','manual');
  layer.innerHTML='<div class="guide-ring" aria-hidden="true"></div><aside class="guide-tip" aria-labelledby="guide-title"><div class="guide-tip-heading"><span class="guide-counter"></span><button type="button" class="guide-skip" data-guide-action="skip">跳过指引</button></div><div aria-live="polite" aria-atomic="true"><h2 id="guide-title"></h2><p id="guide-description"></p></div><button type="button" class="guide-tip-action" hidden></button></aside>';
  const tip=layer.querySelector('.guide-tip'),ring=layer.querySelector('.guide-ring');
  const counter=tip.querySelector('.guide-counter'),title=tip.querySelector('h2'),description=tip.querySelector('p'),action=tip.querySelector('.guide-tip-action');
  const skip=tip.querySelector('.guide-skip');
  let anchor=null,frame=0;
  const observer=typeof ResizeObserver==='function'?new ResizeObserver(schedule):null;
  const clamp=(value,min,max)=>Math.max(min,Math.min(value,max));
  function position(){
    if(!anchor?.isConnected||!layer.isConnected)return;
    const rect=anchor.getBoundingClientRect(),view=window.visualViewport;
    const left=view?.offsetLeft||0,top=view?.offsetTop||0,right=left+(view?.width||innerWidth),bottom=top+(view?.height||innerHeight);
    const r={left:Math.max(left,rect.left),top:Math.max(top,rect.top),right:Math.min(right,rect.right),bottom:Math.min(bottom,rect.bottom)};
    // Controls in the school picker scroll inside its dialog body.
    const scroller=anchor.closest('.dialog-body');
    if(scroller){const clip=scroller.getBoundingClientRect();r.top=Math.max(r.top,clip.top);r.bottom=Math.min(r.bottom,clip.bottom);}
    const visible=r.bottom>r.top&&r.right>r.left;
    ring.hidden=!visible;
    if(visible)Object.assign(ring.style,{left:r.left-3+'px',top:r.top-3+'px',width:r.right-r.left+6+'px',height:r.bottom-r.top+6+'px'});
    tip.style.maxHeight=Math.max(64,bottom-top-16)+'px';
    tip.classList.toggle('guide-tip-short',tip.offsetHeight>=bottom-top-17&&tip.scrollHeight>tip.clientHeight+1);
    const w=tip.offsetWidth,h=tip.offsetHeight,gap=16,margin=8;
    const cx=clamp((r.left+r.right)/2,left,right),cy=clamp((r.top+r.bottom)/2,top,bottom);
    const rooms={below:bottom-r.bottom-gap-margin,above:r.top-top-gap-margin,right:right-r.right-gap-margin,left:r.left-left-gap-margin};
    const side=['below','above','right','left'].find(s=>rooms[s]>=(s==='below'||s==='above'?h:w))||(rooms.below>=rooms.above?'below':'above');
    let x=cx-w/2,y=side==='below'?r.bottom+gap:r.top-gap-h;
    if(side==='right'||side==='left'){x=side==='right'?r.right+gap:r.left-gap-w;y=cy-h/2;}
    x=clamp(x,left+margin,right-w-margin);y=clamp(y,top+margin,bottom-h-margin);
    Object.assign(tip.style,{left:x+'px',top:y+'px'});
    const vertical=side==='above'||side==='below';
    tip.dataset.side=side;
    tip.style.setProperty('--guide-arrow',clamp(vertical?cx-x:cy-y,18,(vertical?w:h)-18)+'px');
  }
  function schedule(){
    if(!frame)frame=requestAnimationFrame(()=>{frame=0;position();});
  }
  function detach(){
    if(!anchor)return;
    const ids=(anchor.getAttribute('aria-describedby')||'').split(/\s+/).filter(s=>s&&s!=='guide-description');
    if(ids.length)anchor.setAttribute('aria-describedby',ids.join(' '));else anchor.removeAttribute('aria-describedby');
    anchor.removeAttribute('data-guide-current');observer?.unobserve(anchor);anchor=null;
  }
  function show(target,step){
    const host=target.closest('dialog[open]')||document.body;
    if(layer.parentElement!==host){
      layer.remove();host.append(layer);
      if(typeof layer.showPopover==='function')layer.showPopover();
    }
    const moved=target!==anchor;
    if(moved){
      detach();anchor=target;observer?.observe(target);observer?.observe(tip);
      const ids=target.getAttribute('aria-describedby');
      target.setAttribute('aria-describedby',(ids?ids+' ':'')+'guide-description');
      target.dataset.guideCurrent='';
      target.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
      if(!target.matches('input,textarea')||matchMedia('(pointer:fine)').matches)target.focus({preventScroll:true});
    }
    if(counter.textContent!==step.count)counter.textContent=step.count;
    if(title.textContent!==step.title)title.textContent=step.title;
    if(description.textContent!==step.text)description.textContent=step.text;
    const skipLabel=step.complete?'结束指引':'跳过指引';
    if(skip.textContent!==skipLabel)skip.textContent=skipLabel;
    skip.hidden=step.action==='finish';
    action.hidden=!step.action;
    if(step.action){
      if(action.textContent!==step.label)action.textContent=step.label;
      action.dataset.guideAction=step.action;action.disabled=!!step.disabled;
    }
    position();schedule();
  }
  function hide(){
    detach();layer.remove();
  }
  function destroy(){
    hide();observer?.disconnect();cancelAnimationFrame(frame);
    document.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule);
    window.visualViewport?.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('scroll',schedule);
  }
  layer.addEventListener('click',event=>{
    const button=event.target.closest('[data-guide-action]');
    if(button){event.preventDefault();event.stopPropagation();onAction(button.dataset.guideAction);}
  });
  document.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);
  window.visualViewport?.addEventListener('resize',schedule);window.visualViewport?.addEventListener('scroll',schedule);
  return {show,hide,destroy,get target(){return anchor;}};
}
