import {motionAssets} from './motion-assets.js';

const storageKey='campus.motion.enabled',hintKey='campus.hints.dismissed';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let sequence=0,enabled=true,installed=false,activeRouteFeedback=null;
let dismissed=new Set();
try{enabled=localStorage.getItem(storageKey)!=='false';}catch{/* Preferences are optional. */}
try{dismissed=new Set(JSON.parse(localStorage.getItem(hintKey)||'[]'));}catch{/* Preferences are optional. */}

// Prefix EVERY SVG ID and fragment reference, including repeated copies of a pose.
export function namespaceSvg(svg,prefix){
  const ids=[...svg.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  let result=svg;
  for(const id of ids){
    result=result.replaceAll('id="'+id+'"','id="'+prefix+'-'+id+'"')
      .replaceAll('url(#'+id+')','url(#'+prefix+'-'+id+')')
      .replaceAll('href="#'+id+'"','href="#'+prefix+'-'+id+'"');
  }
  return result;
}

export function brandMotion(name='radar',className='',{once=false,priority=1}={}){
  const asset=motionAssets[name];if(!asset)throw new Error('Unknown brand motion: '+name);
  const svg=namespaceSvg(asset.svg,'luojia-motion-'+(++sequence));
  return `<span class="brand-motion motion-${asset.family} motion-${name} ${esc(className)}" data-brand-motion="${name}" data-motion-priority="${Number(priority)||1}" aria-hidden="true">${svg}</span>`;
}

export function loadingState(title='正在打开你的空间',text='资料加载完成后会自动显示。',name='cascade'){
  return `<div class="state-loading" role="status">${brandMotion(name,'state-motion',{priority:3})}<div><strong>${esc(title)}</strong><p>${esc(text)}</p></div></div>`;
}

export function contextHint(key,title,text,action=''){
  if(dismissed.has(key))return '';
  return `<aside class="context-hint" data-context-hint="${esc(key)}"><span class="hint-mark" aria-hidden="true">✦</span><div><strong>${esc(title)}</strong><p>${esc(text)}</p>${action}</div><button type="button" class="icon-button hint-dismiss" data-dismiss-hint="${esc(key)}" aria-label="收起${esc(title)}提示">×</button></aside>`;
}

export function motionSetting(){
  return `<label class="check"><input type="checkbox" id="interface-motion-enabled" ${enabled?'checked':''}><span>播放插画与等待动效</span></label><p class="small muted">跟随设备的“减少动态效果”设置。关闭后保留必要的操作反馈；离开屏幕或切到后台时自动暂停。</p><button type="button" class="button small plain" data-restore-hints>重新显示已收起的小提示</button>`;
}

export function motionToggle(){
  return '';
}

// A real pending route gets feedback after 280 ms; fast routes add no visual flash.
export function beginRouteFeedback(content,title='正在打开你的空间'){
  activeRouteFeedback?.();
  let host,slowTimer;
  const timer=setTimeout(()=>{
    if(!content.isConnected)return;
    host=document.createElement('div');host.className='route-feedback';
    host.innerHTML=loadingState(title,'正在读取已保存的内容。')+'<div class="route-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>';content.before(host);
    slowTimer=setTimeout(()=>{
      if(!host?.isConnected)return;
      host.querySelector('p').textContent='连接有些慢。已保存的资料仍在，可以稍候或重新加载。';
      host.insertAdjacentHTML('beforeend','<button type="button" class="button small" data-action="refresh">重新加载</button>');
    },12000);
  },280);
  const finish=()=>{clearTimeout(timer);clearTimeout(slowTimer);host?.remove();if(activeRouteFeedback===finish)activeRouteFeedback=null;};
  activeRouteFeedback=finish;return finish;
}

export function initializeMotion(){
  if(installed)return;installed=true;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),visible=new Set(),observed=new Set();
  function synchronize(){
    document.documentElement.dataset.uiMotion=enabled?'on':'off';
    const running=enabled&&!reduced.matches;
    document.querySelectorAll('[data-motion-toggle]').forEach(button=>{
      button.setAttribute('aria-pressed',String(!running));
      button.setAttribute('aria-label',reduced.matches?'系统已减少动效':running?'暂停界面动效':'开启界面动效');
      button.title=reduced.matches?'跟随系统的减少动效设置':running?'暂停界面动效':'开启界面动效';
      button.disabled=reduced.matches;
    });
    document.querySelectorAll('#interface-motion-enabled').forEach(input=>input.checked=enabled);
    choose();
  }
  function choose(){
    for(const node of observed)if(!node.isConnected){observer.unobserve(node);observed.delete(node);visible.delete(node);}
    const foreground=document.querySelector('dialog[open]')||(document.body.classList.contains('materials-open')?document.querySelector('#chat-materials'):null);
    for(const node of observed)node.classList.toggle('motion-paused',document.hidden||!visible.has(node)||!!(foreground&&!foreground.contains(node)));
  }
  const observer=new IntersectionObserver(entries=>{for(const entry of entries)entry.isIntersecting?visible.add(entry.target):visible.delete(entry.target);choose();},{threshold:.2});
  function watch(root){
    if(!(root instanceof Element))return;
    const nodes=[...(root.matches('[data-brand-motion]')?[root]:[]),...root.querySelectorAll('[data-brand-motion]')];
    for(const node of nodes)if(!observed.has(node)){observed.add(node);node.classList.add('motion-paused');observer.observe(node);}
    if(root.matches('[data-motion-toggle]')||root.querySelector('[data-motion-toggle]'))synchronize();
  }
  const mutations=new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)watch(node);choose();});
  mutations.observe(document.body,{childList:true,subtree:true});watch(document.body);synchronize();
  const foregroundChanges=new MutationObserver(choose);
  foregroundChanges.observe(document.body,{attributes:true,attributeFilter:['class']});
  const dialog=document.querySelector('#dialog');if(dialog)foregroundChanges.observe(dialog,{attributes:true,attributeFilter:['open']});
  document.addEventListener('visibilitychange',choose);reduced.addEventListener('change',synchronize);
  window.addEventListener('storage',event=>{
    if(event.key===storageKey||event.key===null){enabled=event.key===null?true:event.newValue!=='false';synchronize();}
    if(event.key===hintKey){try{dismissed=new Set(JSON.parse(event.newValue||'[]'));}catch{return;}document.querySelectorAll('[data-context-hint]').forEach(hint=>{if(dismissed.has(hint.dataset.contextHint))hint.remove();});}
  });
  document.addEventListener('change',event=>{if(event.target.id==='interface-motion-enabled')setEnabled(event.target.checked);});
  function setEnabled(value){enabled=value;try{localStorage.setItem(storageKey,String(enabled));}catch{}synchronize();}
  document.addEventListener('click',event=>{
    if(event.target.closest('[data-motion-toggle]'))setEnabled(!enabled);
    const dismiss=event.target.closest('[data-dismiss-hint]');
    if(dismiss){dismissed.add(dismiss.dataset.dismissHint);try{localStorage.setItem(hintKey,JSON.stringify([...dismissed]));}catch{}const hint=dismiss.closest('[data-context-hint]'),next=hint?.nextElementSibling?.querySelector('input,button,a')||document.querySelector('#content');hint?.remove();next?.focus({preventScroll:true});}
    if(event.target.closest('[data-restore-hints]')){dismissed.clear();try{localStorage.removeItem(hintKey);}catch{}event.target.closest('button').textContent='小提示已恢复，下次打开相关页面时显示';}
  });
}
