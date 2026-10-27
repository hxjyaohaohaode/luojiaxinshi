import {motionAllowed} from './experience-system.js';
import {actionSucceeded,clearActionFeedback} from './action-feedback.js';

// Interaction-only adaptations of the supplied AnimatedList, Stepper and Files.
// Existing styles and containers remain the source of all final dimensions.
const running=new Map(),easing='cubic-bezier(.22,.8,.24,1)';
function animate(node,frames,finish=()=>{},duration=180){
  const previous=running.get(node),entry={animation:null,finish:null};
  entry.finish=()=>{
    if(running.get(node)!==entry)return;
    running.delete(node);entry.animation?.cancel();finish();
  };
  running.set(node,entry);previous?.animation?.cancel();
  if(!node.isConnected||!motionAllowed()||!node.animate){entry.finish();return;}
  entry.animation=node.animate(frames,{duration,easing});
  entry.animation.finished.then(entry.finish,entry.finish);
}
export function finishReferenceMotion(){for(const entry of [...running.values()])entry.finish();}

// No stored pixel heights: after completion/interruption the original auto
// layout resumes. Repeated clicks replace the current transition immediately.
export function setDisclosureVisible(panel,open){
  const before=panel.hidden?0:panel.getBoundingClientRect().height;
  running.get(panel)?.animation?.cancel();
  panel.hidden=false;
  const after=panel.getBoundingClientRect().height;
  panel.inert=!open;
  animate(panel,[
    {height:before+'px',opacity:before?1:0,overflow:'clip'},
    {height:(open?after:0)+'px',opacity:open?1:0,overflow:'clip'},
  ],()=>{panel.hidden=!open;panel.inert=false;});
}

export function animateStepChange(form,panel,before,direction){
  const after=form.getBoundingClientRect().height;
  animate(form,[{height:before+'px',overflow:'clip'},{height:after+'px',overflow:'clip'}],()=>{},200);
  animate(panel,[{opacity:0,transform:`translateX(${direction*12}px)`},{opacity:1,transform:'translateX(0)'}],()=>{},200);
}

export function animateLocalPanel(panel,direction=0){
 if(!panel)return;
 animate(panel,[{opacity:.35,transform:`translate(${direction*6}px,${direction?0:4}px)`},{opacity:1,transform:'translate(0,0)'}],()=>{},160);
}

const markerNumbers=new WeakMap();
export function syncStepMarkers(stepper){
  for(const button of stepper?.querySelectorAll('[data-notice-stage]')||[]){
    const marker=button.querySelector('b');if(!marker)continue;
    if(!markerNumbers.has(marker))markerNumbers.set(marker,marker.textContent);
    const complete=button.classList.contains('is-complete');
    marker.innerHTML=complete?'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>':'';
    if(!complete)marker.textContent=markerNumbers.get(marker);
    marker.setAttribute('aria-hidden','true');
    if(complete)animate(marker.querySelector('path'),[{strokeDasharray:'24',strokeDashoffset:24},{strokeDasharray:'24',strokeDashoffset:0}],()=>{},180);
  }
}

export function listNavigationIndex(key,index,count){
  if(count<1)return -1;
  return key==='Home'?0:key==='End'?count-1:Math.max(0,Math.min(count-1,index+(key==='ArrowDown'?1:-1)));
}

const folderTargets=new WeakMap(),detailInert=new WeakMap();
export const detailsExpanded=folder=>folderTargets.get(folder)??folder.open;
export function setDetailsExpanded(folder,requested){
  if(!folder)return;
  const current=detailsExpanded(folder),open=requested??!current;if(current===open)return;
  const before=folder.getBoundingClientRect().height;
  folderTargets.set(folder,open);running.get(folder)?.animation?.cancel();
  folder.open=open;const after=folder.getBoundingClientRect().height;folder.open=true;
  const summary=folder.querySelector(':scope > summary'),body=[...folder.children].filter(node=>node!==summary);
  // Native summary derives expansion from details.open, including direct
  // updates during validation or search. Do not leave a stale ARIA override.
  summary?.removeAttribute('aria-expanded');
  if(!detailInert.has(folder))detailInert.set(folder,body.map(node=>[node,node.inert]));
  for(const [node,previous] of detailInert.get(folder))node.inert=!open||previous;
  animate(folder,[{height:before+'px',overflow:'clip'},{height:after+'px',overflow:'clip'}],()=>{
    folder.open=open;folderTargets.delete(folder);for(const [node,previous] of detailInert.get(folder)||[])node.inert=previous;detailInert.delete(folder);
  });
}

function keepVisible(root,item){
  const box=item.getBoundingClientRect(),viewport=root.getBoundingClientRect();
  if(box.top<viewport.top+8)root.scrollTop-=viewport.top+8-box.top;
  else if(box.bottom>viewport.bottom-8)root.scrollTop+=box.bottom-viewport.bottom+8;
}

const copyResets=new WeakMap();
export async function copyCode(button,text,announce=()=>{}){
  if(!button||button.disabled)return;
  clearTimeout(copyResets.get(button));clearActionFeedback(button);button.disabled=true;button.setAttribute('aria-busy','true');
  try{
    await navigator.clipboard.writeText(text);
    if(button.isConnected){actionSucceeded(button,'代码已复制');announce('代码已复制');}
  }catch{
    if(button.isConnected){button.textContent='复制失败';button.setAttribute('aria-label','复制失败，请选择代码后复制');button.title='请选择代码后复制';announce('复制失败，请选择代码后复制');}
  }finally{
    if(button.isConnected){button.disabled=false;button.removeAttribute('aria-busy');if(!button.dataset.actionSuccess)copyResets.set(button,setTimeout(()=>{if(button.isConnected){button.textContent='复制代码';button.setAttribute('aria-label','复制代码');button.title='复制代码';}},1800));}
  }
}

export function installReferenceInteractions(){
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
    const item=event.target.closest('[data-tree-record],.history-chat');if(!item)return;
    const root=item.closest('#memory-items,#chat-history-results');if(!root)return;
    const items=[...root.querySelectorAll(item.matches('[data-tree-record]')?'[data-tree-record]':'.history-chat')].filter(node=>node.getClientRects().length&&!node.disabled);
    const next=listNavigationIndex(event.key,items.indexOf(item),items.length);if(next<0)return;
    event.preventDefault();items[next].focus({preventScroll:true});keepVisible(root,items[next]);
  });
  document.addEventListener('click',event=>{
    const summary=event.target.closest('details.material-folder > summary,details.workflow-section > summary,details.catalog-card > summary');
    if(summary&&!event.target.closest('button,a,input,select,textarea')){event.preventDefault();setDetailsExpanded(summary.parentElement);}
    const record=event.target.closest('[data-tree-record]');
    if(record){const id=record.dataset.treeRecord,route=location.hash;requestAnimationFrame(()=>{
      if(location.hash===route&&document.activeElement===document.body&&!document.body.classList.contains('memory-detail-open'))document.querySelector(`[data-tree-record="${CSS.escape(id)}"]`)?.focus({preventScroll:true});
    });}
  });
  // Existing notice and composer menus retain their markup and positions.
  const menuItems=menu=>[...menu.querySelectorAll('button:not(:disabled),a[href]')].filter(item=>item.getClientRects().length&&!item.closest('[inert]'));
  document.addEventListener('toggle',event=>{
    const disclosure=event.target;if(!disclosure.matches?.('details.notice-actions')||!disclosure.open)return;
    for(const other of document.querySelectorAll('details.notice-actions[open]'))if(other!==disclosure)other.open=false;
    animateLocalPanel(disclosure.querySelector('.notice-actions-menu'));
  },true);
  document.addEventListener('pointerdown',event=>{for(const menu of document.querySelectorAll('details.notice-actions[open]'))if(!menu.contains(event.target))menu.open=false;});
  document.addEventListener('focusin',event=>{for(const menu of document.querySelectorAll('details.notice-actions[open]'))if(!menu.contains(event.target))menu.open=false;});
  document.addEventListener('click',event=>{if(event.target.closest('.composer-plus'))queueMicrotask(()=>{const menu=document.querySelector('#composer-menu');if(menu&&!menu.hidden)animateLocalPanel(menu);});});
  document.addEventListener('keydown',event=>{
    if(event.isComposing||event.altKey||event.ctrlKey||event.metaKey)return;
    const trigger=event.target.closest('details.notice-actions > summary,.composer-plus');
    let menu=event.target.closest('.notice-actions-menu,#composer-menu');
    if(trigger&&['ArrowDown','ArrowUp'].includes(event.key)){
      event.preventDefault();
      if(trigger.matches('summary')){trigger.parentElement.open=true;menu=trigger.parentElement.querySelector('.notice-actions-menu');}
      else{menu=document.querySelector('#composer-menu');if(menu?.hidden)trigger.click();}
      const items=menu?menuItems(menu):[];(event.key==='ArrowUp'?items.at(-1):items[0])?.focus({preventScroll:true});return;
    }
    if(!menu||menu.hidden)return;
    if(event.key==='Escape'){
      event.preventDefault();event.stopImmediatePropagation();
      const details=menu.closest('details');if(details){details.open=false;details.querySelector('summary').focus({preventScroll:true});}
      else{document.querySelector('.composer-plus')?.click();document.querySelector('.composer-plus')?.focus({preventScroll:true});}
      return;
    }
    if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
    const items=menuItems(menu),index=items.indexOf(event.target.closest('button,a'));if(index<0||!items.length)return;
    event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:items.length-1))%items.length;
    items[next].focus({preventScroll:true});
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)finishReferenceMotion();});
  window.addEventListener('resize',finishReferenceMotion);
  window.addEventListener('hashchange',finishReferenceMotion);
  matchMedia('(prefers-reduced-motion:reduce)').addEventListener('change',finishReferenceMotion);
  new MutationObserver(()=>{if(!motionAllowed())finishReferenceMotion();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-ui-motion']});
}
if(typeof document!=='undefined'&&document.getElementById?.('app'))installReferenceInteractions();
