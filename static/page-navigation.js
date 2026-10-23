const names={dashboard:'工作台',settings:'个人与账号',memory:'我的记忆',notices:'通知资料',notice:'通知详情',new:'通知资料',sources:'通知来源',tasks:'待办',calendar:'日历',chat:'对话'};
const parents={memory:'#settings',notice:'#notices',new:'#notices'};
function parentOf(hash){
  const [page,id]=hash.replace(/^#/,'').split('/');
  if(page==='notice')return id?'#notices':null;
  if(['tasks','calendar','memory'].includes(page)&&id)return '#'+page;
  if(page==='chat'&&hash.split('/').length>2)return '#chat/'+id;
  return parents[page]||null;
}
const session=crypto.randomUUID(),entries=[];
let index=-1,lastHash='',owner=null,backButton=null;
const $=selector=>document.querySelector(selector);

export function syncPageNavigation(account){
  if(account!==owner){owner=account;entries.length=0;index=-1;lastHash='';}
  const hash=location.hash||'#dashboard',saved=history.state?.campusNavigation;
  if(hash!==lastHash){
    if(saved?.session===session&&saved.hash===hash&&entries[saved.index]===hash)index=saved.index;
    else{entries.splice(index+1);entries.push(hash);index=entries.length-1;history.replaceState({...history.state,campusNavigation:{session,index,hash}},'');}
    lastHash=hash;
  }
  const destination=parentOf(hash);
  let button=backButton;
  if(!button){button=backButton=document.createElement('button');button.type='button';button.className='icon-button workspace-back';button.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5 m5-5-5 5 5 5"/></svg>';button.addEventListener('click',()=>{
    const hash=parentOf(location.hash);if(!hash)return;
    if(index>0&&entries[index-1]===hash){history.back();return;}
    const oldURL=location.href;
    entries.splice(0,entries.length,hash);index=0;
    replacePageNavigation(hash);
    window.dispatchEvent(new HashChangeEvent('hashchange',{oldURL,newURL:location.href}));
  });}
  if(!button.isConnected)$('.topbar-left')?.append(button);
  button.hidden=!destination;
  const label='返回'+(names[(destination||'').slice(1).split('/')[0]]||'上一级');button.setAttribute('aria-label',label);button.title=label;
  positionPageNavigation();
}

export function positionPageNavigation(){
  const route=document.documentElement.dataset.route,button=backButton;if(!button)return;
  const host=route==='chat'?$('.chat-heading'):route==='calendar'?$('.calendar-navigation'):$('.topbar-left');
  if(host){const toggle=host.querySelector('.workspace-chrome-toggle');if(toggle){if(button.previousElementSibling!==toggle)toggle.after(button);}else if(host.firstElementChild!==button)host.prepend(button);}
}

// Creating or restoring a conversation replaces the current route. Preserve
// that history entry so Back returns to the page before the conversation.
export function replacePageNavigation(hash){
  if(index>=0)entries[index]=hash;
  history.replaceState({...history.state,campusNavigation:{session,index,hash}},'',hash);
  lastHash='';syncPageNavigation(owner);
}

export function installPageNavigation(){
  positionPageNavigation();
  new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n instanceof Element&&(n.matches('.chat-heading,.calendar-navigation')||n.querySelector('.chat-heading,.calendar-navigation')))))positionPageNavigation();}).observe(document.querySelector('#app'),{subtree:true,childList:true});
}
