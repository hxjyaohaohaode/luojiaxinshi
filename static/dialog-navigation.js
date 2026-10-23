// Keep the actual parent nodes, including listeners, drafts and scroll position.
// Returning never replays a request or submits a form.
export function createDialogNavigation({dialog,state,persist}){
  let stack=[],lastTrigger=null;
  const owner=()=>state.session?.user?.id;
  // Feature handlers can disable their trigger before opening a child dialog,
  // which removes browser focus. Capture it before those handlers run.
  dialog.addEventListener('click',event=>{lastTrigger=event.target.closest('button,a,input,select,summary');},true);
  function remember(title){
    if(!dialog.open){stack=[];return;}
    if(dialog.querySelector('#dialog-title')?.textContent===title)return;
    stack.push({nodes:[...dialog.childNodes],focus:dialog.contains(lastTrigger)?lastTrigger:document.activeElement,scroll:dialog.querySelector('.dialog-body')?.scrollTop||0,owner:owner(),hash:location.hash,editTask:state.editTask,sourceAction:state.sourceAction});
  }
  function back(){
    const previous=stack.pop();
    if(!previous||previous.owner!==owner()||previous.hash!==location.hash){stack=[];return false;}
    persist();state.dialogRequest=(state.dialogRequest||0)+1;
    dialog.dispatchEvent(new Event('dialog-back'));
    dialog.replaceChildren(...previous.nodes);state.editTask=previous.editTask;state.sourceAction=previous.sourceAction;
    const body=dialog.querySelector('.dialog-body');if(body)body.scrollTop=previous.scroll;
    (previous.focus?.isConnected&&!previous.focus.disabled?previous.focus:dialog.querySelector('#dialog-title'))?.focus({preventScroll:true});
    return true;
  }
  function cancel(){if(!back())dialog.close();}
  dialog.addEventListener('click',event=>{
    if(event.target.closest('[data-dialog-back],[data-dialog-cancel]')){event.preventDefault();cancel();}
  });
  dialog.addEventListener('cancel',event=>{if(stack.length){event.preventDefault();cancel();}});
  dialog.addEventListener('close',()=>{if(!dialog.open)stack=[];});
  window.addEventListener('hashchange',()=>{stack=[];});
  return {remember,back,hasParent:()=>stack.length>0};
}

// Restore only unsaved form values. Files and credentials are not retained in
// edit history, and no request is issued by undo/redo.
export function installFormHistory(root){
  const histories=new WeakMap();
  const fields=form=>[...form.querySelectorAll('input,textarea,select')].filter(el=>!['hidden','file','password','submit','button'].includes(el.type)&&!el.readOnly);
  const capture=form=>fields(form).map(el=>({el,value:el.value,checked:el.checked,selected:el.multiple?[...el.options].map(o=>o.selected):null}));
  const equal=(a,b)=>a.length===b.length&&a.every((v,i)=>v.el===b[i].el&&v.value===b[i].value&&v.checked===b[i].checked&&String(v.selected)===String(b[i].selected));
  function controls(form){
    if(histories.has(form)||!form.querySelector('[type="submit"]'))return;
    const footer=form.querySelector('.form-footer')||form.appendChild(Object.assign(document.createElement('div'),{className:'form-footer'}));
    const actions=document.createElement('div');actions.className='form-edit-actions';
    actions.innerHTML='<button type="button" class="button plain small" data-form-undo disabled>撤销编辑</button><button type="button" class="button plain small" data-form-redo disabled>重做</button>';
    footer.prepend(actions);
    if(form.closest('dialog')&&!footer.querySelector('[data-dialog-cancel],[data-action="close-dialog"]')){
      const cancel=document.createElement('button');cancel.type='button';cancel.className='button';cancel.dataset.dialogCancel='';cancel.textContent='取消';footer.insertBefore(cancel,actions.nextSibling);
    }
    const h={past:[capture(form)],future:[],field:null,restoring:false};histories.set(form,h);
    if(!fields(form).length)actions.hidden=true;
    const update=()=>{actions.querySelector('[data-form-undo]').disabled=h.past.length<2;actions.querySelector('[data-form-redo]').disabled=!h.future.length;};
    form.addEventListener('focusin',()=>{if(h.past.length===1&&!h.future.length)h.past[0]=capture(form);});
    function record(event){
      if(h.restoring||!fields(form).includes(event.target))return;
      const next=capture(form);if(equal(h.past.at(-1),next))return;
      if(event.type==='input'&&h.field===event.target&&h.past.length>1)h.past[h.past.length-1]=next;
      else h.past.push(next);
      if(h.past.length>40)h.past.shift();h.future=[];h.field=event.type==='input'?event.target:null;update();
    }
    form.addEventListener('input',record);form.addEventListener('change',record);form.addEventListener('focusout',()=>{h.field=null;});
    actions.addEventListener('click',event=>{
      const undo=event.target.closest('[data-form-undo]'),redo=event.target.closest('[data-form-redo]');if(!undo&&!redo)return;
      if(form.inert||form.getAttribute('aria-busy')==='true')return;
      if(undo&&h.past.length>1)h.future.push(h.past.pop());else if(redo&&h.future.length)h.past.push(h.future.pop());else return;
      h.restoring=true;
      try{
        const changed=[];
        for(const value of h.past.at(-1)){
          if(!value.el.isConnected)continue;
          const el=value.el;if(el.value!==value.value||el.checked!==value.checked||(value.selected&&[...el.options].some((o,i)=>o.selected!==value.selected[i])))changed.push(el);
          el.value=value.value;if('checked' in el)el.checked=value.checked;if(value.selected)[...el.options].forEach((o,i)=>o.selected=!!value.selected[i]);
        }
        // Linked fields and draft listeners must see the complete restored form.
        for(const el of changed){el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
      }
      finally{h.restoring=false;h.field=null;update();}
    });
  }
  const eligible=form=>form.closest('dialog')||['profile-form','preferences-form','memory-inline-editor'].includes(form.id);
  function watch(node){if(!(node instanceof Element))return;const form=node.closest('form');if(form&&eligible(form))controls(form);for(const child of node.querySelectorAll('form'))if(eligible(child))controls(child);}
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)watch(node);}).observe(root,{childList:true,subtree:true});watch(root);
}
