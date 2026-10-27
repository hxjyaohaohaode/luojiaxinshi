// A successful command has temporary feedback; a toggle keeps its own state.
const active=new WeakMap();
export function clearActionFeedback(control){
  const entry=active.get(control);if(!entry)return;
  clearTimeout(entry.timer);active.delete(control);
  entry.indicator.remove();entry.original.replaceWith(...entry.original.childNodes);
  for(const name of ['aria-label','title'])if(control.getAttribute(name)===entry.label){
    if(entry.attributes[name]===null)control.removeAttribute(name);else control.setAttribute(name,entry.attributes[name]);
  }
  delete control.dataset.actionSuccess;
}
export function actionSucceeded(control,label='操作成功',duration=5000){
  if(!control?.isConnected)return;
  clearActionFeedback(control);
  const attributes=Object.fromEntries(['aria-label','title'].map(name=>[name,control.getAttribute(name)]));
  const original=document.createElement('span');original.className='action-feedback-original';
  original.append(...control.childNodes);
  const indicator=document.createElement('span');indicator.className='action-success-indicator';indicator.setAttribute('aria-hidden','true');
  indicator.innerHTML='<svg viewBox="0 0 28 28" fill="none" stroke="currentColor"><circle class="action-success-track" cx="14" cy="14" r="11"/><circle class="action-success-countdown" cx="14" cy="14" r="11" pathLength="1"/><path class="action-success-check" d="m9 14 3.3 3.3L19 10.5"/></svg>';
  indicator.style.setProperty('--feedback-duration',duration+'ms');control.append(original,indicator);
  control.dataset.actionSuccess='true';control.setAttribute('aria-label',label);control.title=label;
  const entry={original,indicator,label,attributes,timer:null};active.set(control,entry);
  entry.timer=setTimeout(()=>{if(active.get(control)===entry)clearActionFeedback(control);},duration);
}
