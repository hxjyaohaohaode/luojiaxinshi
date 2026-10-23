const bases=new WeakMap();

export function bindProfileForm(form,profile){bases.set(form,structuredClone(profile));}

export function profileUndoValues(form,values){
  const base=bases.get(form);if(!base)throw Error('资料表单已失效。');
  return Object.fromEntries(Object.entries(values).filter(([key,value])=>(typeof value==='string'?value.trim():value)!==base[key]).map(([key])=>[key,base[key]]));
}

export function applyProfileForm(state,form,profile,values){
  const base=bases.get(form),current=state.session.user.profile;
  // A late response must not roll back another field already saved in this tab.
  for(const [key,input] of Object.entries(values)){
    const value=typeof input==='string'?input.trim():input;
    if(value!==base[key])current[key]=profile[key];
  }
}

export async function patchProfile(api,base,values){
  const changes={},expected={};
  for(const [key,input] of Object.entries(values)){
    const value=typeof input==='string'?input.trim():input;
    if(value!==base[key]){changes[key]=value;expected[key]=base[key];}
  }
  return (await api('/profile',{method:'PATCH',json:{changes,expected}})).profile;
}

export async function saveProfileForm(api,form,values){
  const base=bases.get(form);
  if(!base)throw new Error('资料表单已失效，请重新打开后保存。');
  form.querySelector('.profile-conflict')?.remove();
  try{return await patchProfile(api,base,values);}
  catch(error){
    if(error.detail?.code==='profile_conflict'&&form.isConnected){
      const latest=error.detail.profile;
      const panel=document.createElement('div');panel.className='alert profile-conflict';panel.setAttribute('role','alert');
      const intro=document.createElement('p');intro.textContent='这些资料已在另一处修改。本次填写仍在，请先核对下面的最新值。';panel.append(intro);
      const list=document.createElement('ul');
      for(const key of error.detail.fields){
        const input=form.elements.namedItem(key),label=input?.labels?.[0];
        const name=label?[...label.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join(''):key;
        const item=document.createElement('li');item.textContent=(name||key)+'：'+(latest[key]||'（空）');list.append(item);
      }
      panel.append(list);
      const reconcile=document.createElement('button');reconcile.type='button';reconcile.className='button small';reconcile.textContent='已核对，继续编辑';
      reconcile.addEventListener('click',()=>{
        // Refresh fields the user did not edit, then require another explicit
        // save. Further concurrent changes are still checked by the server.
        for(const key of Object.keys(values)){
          const input=form.elements.namedItem(key);
          if(input&&input.value.trim()===String(base[key]))input.value=latest[key];
        }
        bases.set(form,structuredClone(latest));panel.remove();form.querySelector('.form-error')?.remove();
        form.elements.namedItem(error.detail.fields[0])?.focus();
      });
      panel.append(reconcile);form.prepend(panel);panel.scrollIntoView({block:'nearest'});error.formHandled=true;
    }
    throw error;
  }
}
