// A completed request may update its owner's data; it may only change the
// visible page or dialog if that is still the view which started the request.
export function captureUiContext(state,element=null){
  const owner=state.session?.user?.id,route=state.renderId,hash=location.hash;
  const dialogVersion=state.dialogRequest,dialog=element?.closest('dialog')||document.querySelector('dialog[open]');
  const sameUser=()=>state.session?.user?.id===owner;
  const sameRoute=()=>sameUser()&&state.renderId===route&&location.hash===hash;
  const sameDialog=()=>sameRoute()&&state.dialogRequest===dialogVersion&&
    (!element||element.isConnected)&&(!dialog||dialog.open);
  return {sameUser,sameRoute,sameDialog};
}

const pending=new WeakMap();
export function beginFormFeedback(form,label='正在保存…'){
  if(pending.has(form))return null;
  const buttons=[...form.querySelectorAll('[type=submit]')];
  const previous=buttons.map(button=>({button,disabled:button.disabled,busy:button.getAttribute('aria-busy')}));
  const previousBusy=form.getAttribute('aria-busy');
  const status=document.createElement('p');
  status.className='form-request-status sr-only';status.setAttribute('role','status');status.textContent=label;
  // A sibling remains available to assistive technology while the form is inert.
  form.before(status);form.setAttribute('aria-busy','true');
  for(const {button} of previous){button.disabled=true;button.setAttribute('aria-busy','true');button.classList.add('request-pending');}
  const slow=setTimeout(()=>{if(form.isConnected){status.classList.remove('sr-only');status.textContent=label+'连接较慢，请稍候；无需重复点击。';}},8000);
  const finish=()=>{
    if(pending.get(form)!==finish)return;
    pending.delete(form);clearTimeout(slow);status.remove();
    if(previousBusy===null)form.removeAttribute('aria-busy');else form.setAttribute('aria-busy',previousBusy);
    for(const {button,disabled,busy} of previous){button.disabled=disabled;button.classList.remove('request-pending');if(busy===null)button.removeAttribute('aria-busy');else button.setAttribute('aria-busy',busy);}
  };
  pending.set(form,finish);return finish;
}
