// Pointer dragging and an equivalent button menu share the same versioned move.
export function boardMoveError(error,refreshed=false) {
  if(error.code==='board_unavailable'||error.status===404&&error.message==='Not Found')return '服务版本尚未同步，请重启预览后刷新。';
  if(error.status===0)return refreshed?'连接曾中断，已同步最新位置，请核对。':'连接中断，保存结果待确认；联网后刷新查看。';
  if(error.status===409)return refreshed?'事项已在别处更新，位置已同步，请重新拖动。':'事项已更新，暂未同步；刷新后再拖。';
  if(error.status===404)return '事项或落点已移除，刷新后重新选择。';
  const message=String(error.message||'');
  if(/依据|变更|复核/.test(message))return '办理要求有变化，先点“办理”核对后再拖。';
  if(/前置/.test(message))return '前置步骤还没完成，先处理前置后再试。';
  if(/清单.*步骤/.test(message))return '办理清单还有未完成项，先点“办理”核对。';
  if(/取消|不参加/.test(message))return '事项已取消或不参加，先在“办理”中恢复。';
  if(/条件|材料/.test(message))return '办理条件尚未满足，先点“办理”核对。';
  if(error.status>=500)return '服务暂未返回结果，请刷新核对后再试。';
  return message.length<=80&&message.includes('请')?message:'这次移动未保存，请刷新后重新拖动。';
}

export function createTaskBoardDrag({onMove,blocked=()=>false}) {
  const root=()=>document.querySelector('#task-results');
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.dataset.uiMotion==='off';
  const cards=()=>[...(root()?.querySelectorAll('.task-row[data-task-id]')||[])];
  let candidate=null,drag=null,busy=false,frame=0,suppressUntil=0,menu=null,selectedLane='action';
  function selectLane(lane,scroll=true,smooth=false){
    selectedLane=lane;
    for(const button of root()?.querySelectorAll('[data-board-jump]')||[])button.setAttribute('aria-current',String(button.dataset.boardJump===lane));
    const scroller=root()?.querySelector('.task-board-scroll'),column=root()?.querySelector(`[data-task-lane="${lane}"]`);
    if(scroll&&scroller&&column&&scroller.scrollWidth>scroller.clientWidth+1)scroller.scrollTo({left:scroller.scrollLeft+column.getBoundingClientRect().left-scroller.getBoundingClientRect().left,behavior:smooth&&!reduced()?'smooth':'instant'});
  }
  const rects=()=>new Map(cards().filter(el=>!el.hidden).map(el=>[el.dataset.taskId,el.getBoundingClientRect()]));
  function flip(previous){
    if(reduced())return;
    for(const el of cards()){
      const from=previous.get(el.dataset.taskId);if(!from||el.hidden)continue;
      const to=el.getBoundingClientRect(),x=from.x-to.x,y=from.y-to.y;
      if(Math.abs(x)+Math.abs(y)>1)el.animate([{transform:`translate(${x}px,${y}px)`},{transform:'none'}],{duration:190,easing:'cubic-bezier(.2,.8,.2,1)'});
    }
  }
  function emptyStates(){
    for(const list of root()?.querySelectorAll('.task-lane-items')||[]){
      const empty=list.querySelector('.lane-empty');
      if(empty)empty.hidden=!!list.querySelector('.task-row:not([hidden]),.task-drop-placeholder');
    }
  }
  function closeMenu(){if(menu){menu.remove();menu=null;}}
  function resetCandidate(){if(candidate)clearTimeout(candidate.timer);candidate=null;}
  function cleanup(active){
    cancelAnimationFrame(frame);frame=0;
    active.portal.remove();active.dock?.remove();active.placeholder.remove();active.row.hidden=false;
    active.row.classList.remove('is-moving');
    if(root()?.hasPointerCapture(active.pointerId))root().releasePointerCapture(active.pointerId);
    document.documentElement.classList.remove('task-dragging');
    for(const lane of root()?.querySelectorAll('.is-drop-target')||[])lane.classList.remove('is-drop-target');
    emptyStates();
  }
  function cancel(){
    resetCandidate();if(!drag)return;
    const active=drag;drag=null;cleanup(active);suppressUntil=performance.now()+300;
  }
  function start(){
    if(!candidate||busy||blocked()||!candidate.row.isConnected)return;
    const c=candidate;resetCandidate();closeMenu();
    if(window.getSelection()?.type==='Range')window.getSelection().removeAllRanges();
    const box=c.row.getBoundingClientRect(),placeholder=document.createElement('div');
    placeholder.className='task-drop-placeholder';placeholder.style.height=box.height+'px';placeholder.setAttribute('aria-hidden','true');
    c.row.before(placeholder);c.row.hidden=true;c.row.classList.add('is-moving');
    const portal=document.createElement('div');portal.className='task-board task-drag-portal';portal.setAttribute('aria-hidden','true');portal.inert=true;
    const ghost=c.row.cloneNode(true);ghost.hidden=false;ghost.classList.add('task-drag-ghost');ghost.style.width=box.width+'px';ghost.removeAttribute('data-task-id');
    ghost.querySelectorAll('[id]').forEach(el=>el.removeAttribute('id'));portal.append(ghost);document.body.append(portal);
    const scroll=c.row.closest('#content')||document.scrollingElement;
    let dock=null;
    if(c.pointerType==='touch'){
      dock=document.createElement('div');dock.className='task-drag-dock';dock.setAttribute('aria-label','移到');
      dock.innerHTML=[['action','接着推进'],['followup','留意反馈'],['closed','标记完成']].map(([lane,label])=>`<div data-task-drop-lane="${lane}">${label}</div>`).join('');document.body.append(dock);
    }
    drag={...c,placeholder,portal,ghost,scroll,dock,x:c.lastX,y:c.lastY,offsetX:c.startX-box.x,offsetY:c.startY-box.y,
      visualX:box.x,visualY:box.y,velocityX:0,velocityY:0,last:performance.now(),valid:true,lane:c.row.closest('[data-task-lane]')};
    root()?.setPointerCapture(c.pointerId);
    document.documentElement.classList.add('task-dragging');emptyStates();frame=requestAnimationFrame(tick);
  }
  function target(){
    const d=drag;if(!d)return;
    const board=root()?.querySelector('.task-board');if(!board){cancel();return;}
    const bounds=(board.closest('.task-board-scroll')||board).getBoundingClientRect();
    const pointed=document.elementFromPoint(d.x,d.y),dockTarget=pointed?.closest('[data-task-drop-lane]');
    const hit=dockTarget?board.querySelector(`[data-task-lane="${dockTarget.dataset.taskDropLane}"]`):pointed?.closest('[data-task-lane]');
    const nearby=d.x>=bounds.left-18&&d.x<=bounds.right+18&&d.y>=bounds.top-12&&d.y<=bounds.bottom+28;
    const lanes=[...board.querySelectorAll('[data-task-lane]')];
    const distance=el=>{const r=el.getBoundingClientRect();return Math.hypot(Math.max(r.left-d.x,0,d.x-r.right),Math.max(r.top-d.y,0,d.y-r.bottom));};
    const lane=hit&&board.contains(hit)?hit:nearby?lanes.sort((a,b)=>distance(a)-distance(b))[0]:null;
    d.valid=!!lane&&(nearby||!!dockTarget);
    for(const el of d.dock?.children||[])el.classList.toggle('is-target',el===dockTarget);
    d.ghost.classList.toggle('drop-outside',!d.valid);
    for(const el of board.querySelectorAll('.is-drop-target'))if(el!==lane)el.classList.remove('is-drop-target');
    if(!d.valid)return;
    lane.classList.add('is-drop-target');d.lane=lane;
    const list=lane.querySelector('.task-lane-items');
    const items=[...list.querySelectorAll('.task-row:not([hidden])')];
    const listTop=list.getBoundingClientRect().top;
    const before=(!dockTarget&&items.find(el=>d.y<listTop+el.offsetTop+el.offsetHeight/2))||list.querySelector('.lane-empty');
    if(d.placeholder.parentElement!==list||d.placeholder.nextElementSibling!==before){
      const previous=rects();list.insertBefore(d.placeholder,before);emptyStates();flip(previous);
    }
  }
  function tick(now){
    const d=drag;if(!d)return;
    const dt=Math.min((now-d.last)/1000,.032);d.last=now;
    if(reduced()){d.visualX=d.x-d.offsetX;d.visualY=d.y-d.offsetY;}
    else{
      // Slightly underdamped: a short, soft return, without delaying the drop target.
      d.velocityX+=((d.x-d.offsetX-d.visualX)*420-d.velocityX*30)*dt;
      d.velocityY+=((d.y-d.offsetY-d.visualY)*420-d.velocityY*30)*dt;
      d.visualX+=d.velocityX*dt;d.visualY+=d.velocityY*dt;
    }
    d.ghost.style.transform=`translate3d(${d.visualX}px,${d.visualY}px,0) scale(${reduced()?1:1.015})`;
    const r=d.scroll.getBoundingClientRect(),top=Math.max(r.top,0),bottom=Math.min(r.bottom,innerHeight);
    const dockHover=document.elementFromPoint(d.x,d.y)?.closest('[data-task-drop-lane]');
    if(!dockHover&&d.x>=r.left&&d.x<=r.right){
      const speed=d.y<top+56?-Math.min(14,(top+56-d.y)/4):d.y>bottom-56?Math.min(14,(d.y-bottom+56)/4):0;
      if(speed)d.scroll.scrollTop+=speed;
    }
    const scroller=d.row.closest('.task-board-scroll');
    if(scroller&&!dockHover&&scroller.scrollWidth>scroller.clientWidth+1){
      const b=scroller.getBoundingClientRect();
      if(d.y>=b.top&&d.y<=b.bottom){const speed=d.x<b.left+38?-Math.min(10,(b.left+38-d.x)/4):d.x>b.right-38?Math.min(10,(d.x-b.right+38)/4):0;if(speed)scroller.scrollLeft+=speed;}
    }
    target();if(drag)frame=requestAnimationFrame(tick);
  }
  function placement(list,node,lane){
    const next=[];for(let el=node.nextElementSibling;el;el=el.nextElementSibling)if(el.matches('.task-row:not([hidden])'))next.push(el);
    const previous=[];for(let el=node.previousElementSibling;el;el=el.previousElementSibling)if(el.matches('.task-row:not([hidden])'))previous.push(el);
    return {lane,before_id:next[0]?.dataset.taskId||null,after_id:next.length?null:previous[0]?.dataset.taskId||null};
  }
  async function commit(id,value,row,restoreFocus=false){
    if(busy)return;busy=true;selectedLane=value.lane;if(row?.isConnected){row.inert=true;row.setAttribute('aria-busy','true');}
    try{await onMove(id,value);}catch{/* The application refreshes and explains recoverable failures. */}
    finally{busy=false;if(row?.isConnected){row.inert=false;row.removeAttribute('aria-busy');}
      if(restoreFocus&&document.activeElement===document.body)root()?.querySelector(`[data-task-id="${CSS.escape(id)}"] [data-task-drag-handle]`)?.focus({preventScroll:true});}
  }
  function finish(event){
    if(candidate&&event.pointerId===candidate.pointerId){resetCandidate();return;}
    const d=drag;if(!d||event.pointerId!==d.pointerId)return;
    d.x=event.clientX;d.y=event.clientY;target();
    if(!drag||!d.valid){cancel();return;}
    drag=null;cancelAnimationFrame(frame);suppressUntil=performance.now()+400;
    if(root()?.hasPointerCapture(d.pointerId))root().releasePointerCapture(d.pointerId);
    const value=placement(d.placeholder.parentElement,d.placeholder,d.lane.dataset.taskLane);
    const oldList=d.row.parentElement,oldNext=[...oldList.children].slice([...oldList.children].indexOf(d.row)+1).find(el=>el.matches('.task-row:not([hidden])'));
    const unchanged=oldList===d.placeholder.parentElement&&(oldNext?.dataset.taskId||null)===value.before_id;
    selectLane(value.lane);d.dock?.remove();
    const landing=d.placeholder.getBoundingClientRect();
    d.placeholder.replaceWith(d.row);d.row.hidden=false;d.row.classList.remove('is-moving');
    document.documentElement.classList.remove('task-dragging');d.lane.classList.remove('is-drop-target');emptyStates();
    if(!reduced()){
      d.row.classList.add('task-drop-settling');
      const animation=d.ghost.animate([{transform:d.ghost.style.transform,opacity:1},{transform:`translate3d(${landing.x}px,${landing.y+2}px,0) scale(.995)`,opacity:.45,offset:.72},{transform:`translate3d(${landing.x}px,${landing.y}px,0) scale(1)`,opacity:0}],{duration:240,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
      animation.finished.catch(()=>{}).finally(()=>{d.portal.remove();d.row.classList.remove('task-drop-settling');});
    }else d.portal.remove();
    if(!unchanged)void commit(d.row.dataset.taskId,value,d.row);
  }
  function openMenu(handle){
    closeMenu();if(busy||blocked())return;
    const row=handle.closest('[data-task-id]'),lane=row.closest('[data-task-lane]').dataset.taskLane;
    const items=[...row.parentElement.querySelectorAll('.task-row')],index=items.indexOf(row);
    const choices=[
      {text:'上移一位',disabled:index===0,value:{lane,before_id:items[index-1]?.dataset.taskId}},
      {text:'下移一位',disabled:index===items.length-1,value:{lane,after_id:items[index+1]?.dataset.taskId}},
      ...[['action','移到接着推进'],['followup','移到留意反馈'],['closed','标记完成']].filter(([key])=>key!==lane).map(([key,text])=>({text,value:{lane:key}}))];
    menu=document.createElement('div');menu.className='task-move-menu';menu.setAttribute('popover','auto');menu.setAttribute('role','group');menu.setAttribute('aria-label','移动卡片');
    for(const choice of choices){
      const button=document.createElement('button');button.type='button';button.className='task-move-option';button.textContent=choice.text;button.disabled=!!choice.disabled;
      button.addEventListener('click',()=>{closeMenu();void commit(row.dataset.taskId,choice.value,row,true);});menu.append(button);
    }
    document.body.append(menu);menu.showPopover();
    const b=handle.getBoundingClientRect(),m=menu.getBoundingClientRect();
    menu.style.left=Math.max(8,Math.min(b.right-m.width,innerWidth-m.width-8))+'px';
    menu.style.top=Math.max(8,Math.min(b.bottom+6,innerHeight-m.height-8))+'px';
    menu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
    menu.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();closeMenu();handle.focus({preventScroll:true});}
      if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
      event.preventDefault();const buttons=[...menu.querySelectorAll('button:not(:disabled)')],i=buttons.indexOf(document.activeElement);
      buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(i+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();
    });
  }
  document.addEventListener('pointerdown',event=>{
    // Only swallow the click synthesized by the completed drag. A new press
    // (especially on Undo) is a deliberate action and must work immediately.
    suppressUntil=0;
    if(busy||blocked()||drag||event.button!==0||event.isPrimary===false||event.ctrlKey||event.metaKey||event.altKey)return;
    const row=event.target.closest?.('#task-results .task-board .task-row');if(!row)return;
    const handle=event.target.closest('[data-task-drag-handle]');
    if(event.target.closest('a,input,textarea,select,summary,[contenteditable],.task-check,.task-actions,.task-attachments'))return;
    if(event.pointerType==='touch'&&!handle)return;
    candidate={row,pointerId:event.pointerId,pointerType:event.pointerType,startX:event.clientX,startY:event.clientY,lastX:event.clientX,lastY:event.clientY};
    if(event.pointerType==='touch')candidate.timer=setTimeout(start,180);
  });
  document.addEventListener('pointermove',event=>{
    if(candidate&&candidate.pointerId===event.pointerId){
      candidate.lastX=event.clientX;candidate.lastY=event.clientY;
      if(Math.hypot(event.clientX-candidate.startX,event.clientY-candidate.startY)>=7)start();
    }
    if(drag&&drag.pointerId===event.pointerId){event.preventDefault();drag.x=event.clientX;drag.y=event.clientY;}
  },{passive:false});
  document.addEventListener('pointerup',finish);
  document.addEventListener('pointercancel',cancel);
  document.addEventListener('lostpointercapture',event=>{if(drag?.pointerId===event.pointerId)cancel();});
  document.addEventListener('click',event=>{
    if(event.detail!==0&&performance.now()<suppressUntil){suppressUntil=0;event.preventDefault();event.stopImmediatePropagation();return;}
    const handle=event.target.closest?.('#task-results [data-task-drag-handle]');
    if(handle){event.preventDefault();event.stopImmediatePropagation();openMenu(handle);}
    const jump=event.target.closest?.('#task-results [data-board-jump]');
    if(jump){event.preventDefault();selectLane(jump.dataset.boardJump,true,true);}
  },true);
  document.addEventListener('scroll',event=>{
    if(drag||!event.target.matches?.('#task-results .task-board-scroll'))return;
    const left=event.target.getBoundingClientRect().left,columns=[...event.target.querySelectorAll('[data-task-lane]')];
    const closest=columns.sort((a,b)=>Math.abs(a.getBoundingClientRect().left-left)-Math.abs(b.getBoundingClientRect().left-left))[0];
    if(closest)selectLane(closest.dataset.taskLane,false);
  },true);
  document.addEventListener('dragstart',event=>{if(candidate||drag)event.preventDefault();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&(drag||candidate)){event.preventDefault();event.stopImmediatePropagation();cancel();}},true);
  window.addEventListener('blur',cancel);
  window.addEventListener('hashchange',()=>{cancel();closeMenu();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel();});
  return {beforeRender(){cancel();closeMenu();},afterRender(lane=selectedLane){selectLane(lane);}};
}
