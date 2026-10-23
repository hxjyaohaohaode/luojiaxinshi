// Workspace chrome responds to intentional reading, never to streamed auto-scroll.
import {preserveChatViewport} from './chat-viewport.js';
const $=selector=>document.querySelector(selector);
const mobile=()=>matchMedia('(max-width:850px)').matches;
let installed=false,drag=null,idleTimer,lastGesture=-Infinity;
const positions=new WeakMap();
const storage={get(key,fallback){try{return localStorage.getItem(key)??fallback;}catch{return fallback;}},set(key,value){try{localStorage.setItem(key,String(value));}catch{}}};
function widthLimit(){return Math.max(180,Math.min(460,innerWidth*.48));}
function setWidth(value,save=false){const width=Math.round(Math.max(180,Math.min(widthLimit(),Number(value)||234)));$('.shell')?.style.setProperty('--sidebar-width',width+'px');const grip=$('.sidebar-resize');if(grip){grip.setAttribute('aria-valuenow',String(width));grip.setAttribute('aria-valuemax',String(Math.floor(widthLimit())));}window.dispatchEvent(new Event('campus:layout'));if(save)storage.set('campus.sidebar.width',width);}
export function revealChrome(){clearTimeout(idleTimer);document.documentElement.classList.remove('reading-content');}
export function syncChrome(page){document.documentElement.dataset.route=page;revealChrome();const shell=$('.shell');if(!shell)return;shell.classList.toggle('sidebar-collapsed',storage.get('campus.sidebar.collapsed','false')==='true');const toggle=$('.workspace-chrome-toggle'),host=['chat','calendar'].includes(page)?$('.workspace'):$('.topbar-left');if(toggle&&host&&toggle.parentElement!==host)host.prepend(toggle);setWidth(storage.get('campus.sidebar.width',234));updateToggle();}
function updateToggle(){const shell=$('.shell'),collapsed=shell?.classList.contains('sidebar-collapsed');document.querySelectorAll('[data-shell-toggle]').forEach(b=>{b.setAttribute('aria-label',mobile()?'打开导航菜单':collapsed?'展开侧栏':'收起侧栏');b.setAttribute('aria-expanded',String(mobile()?!!shell?.classList.contains('menu-open'):!collapsed));});}
export function installChrome({setMenu}){
 if(installed)return;installed=true;
 function toggle(opener=null){if(mobile()){setMenu(true,true,opener);return;}const shell=$('.shell');if(!shell)return;preserveChatViewport($('#chat-thread'),()=>shell.classList.toggle('sidebar-collapsed'));storage.set('campus.sidebar.collapsed',shell.classList.contains('sidebar-collapsed'));updateToggle();}
 document.addEventListener('click',e=>{const opener=e.target.closest('[data-shell-toggle]');if(opener)toggle(opener);});
 document.addEventListener('pointerdown',e=>{const grip=e.target.closest('.sidebar-resize');if(!grip||mobile()||e.button!==0)return;e.preventDefault();drag={grip,start:e.clientX,width:$('.sidebar').getBoundingClientRect().width};grip.setPointerCapture(e.pointerId);document.documentElement.classList.add('resizing-sidebar');});
 document.addEventListener('pointermove',e=>{if(drag)preserveChatViewport($('#chat-thread'),()=>setWidth(drag.width+e.clientX-drag.start));});
 function endDrag(){if(!drag)return;setWidth($('.sidebar').getBoundingClientRect().width,true);drag=null;document.documentElement.classList.remove('resizing-sidebar');}
 document.addEventListener('pointerup',endDrag);document.addEventListener('pointercancel',endDrag);
 document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='\\'){e.preventDefault();toggle();}if(e.target.matches('.sidebar-resize')&&['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const width=$('.sidebar').getBoundingClientRect().width;preserveChatViewport($('#chat-thread'),()=>setWidth(e.key==='Home'?180:e.key==='End'?widthLimit():width+(e.key==='ArrowRight'?16:-16),true));}if(!e.defaultPrevented&&['ArrowDown','ArrowUp','PageDown','PageUp',' '].includes(e.key)&&!e.target.closest('input,textarea,select,[contenteditable]'))lastGesture=performance.now();});
 let touch=null;
 const ignore=e=>!$('.shell')||e.target.closest?.('dialog,input,textarea,select,.sidebar,.chat-turn-rail,.chat-materials')||$('.shell.menu-open');
 function reading(delta){if(Math.abs(delta)<12)return;lastGesture=performance.now();if(delta<0||document.activeElement?.closest('input,textarea,select'))revealChrome();else document.documentElement.classList.add('reading-content');clearTimeout(idleTimer);idleTimer=setTimeout(revealChrome,1800);}
 document.addEventListener('wheel',e=>{if(!ignore(e)&&Math.abs(e.deltaY)>Math.abs(e.deltaX))reading(e.deltaY);},{passive:true});
 document.addEventListener('touchstart',e=>{touch=!ignore(e)&&e.touches.length===1?{x:e.touches[0].clientX,y:e.touches[0].clientY}:null;},{passive:true});
 document.addEventListener('touchmove',e=>{if(!touch||ignore(e)||e.touches.length!==1)return;const point=e.touches[0],dx=touch.x-point.clientX,dy=touch.y-point.clientY;if(Math.abs(dy)>Math.abs(dx)&&Math.abs(dy)>16){reading(dy);touch={x:point.clientX,y:point.clientY};}},{passive:true});
 document.addEventListener('touchend',()=>touch=null,{passive:true});
 window.addEventListener('campus:menu',()=>{revealChrome();updateToggle();});
 document.addEventListener('scroll',e=>{
   const target=e.target===document?document.scrollingElement:e.target;if(!(target instanceof Element)||target.closest('dialog,.sidebar')||!$('.shell'))return;
   const top=target.scrollTop,previous=positions.get(target)??top;positions.set(target,top);
   if(performance.now()-lastGesture>850||Math.abs(top-previous)<3)return;
   if(top<8||top<previous||document.activeElement?.closest('input,textarea,select'))revealChrome();
   else document.documentElement.classList.add('reading-content');
   clearTimeout(idleTimer);idleTimer=setTimeout(revealChrome,1800);
 },{passive:true,capture:true});
 document.addEventListener('focusin',e=>{if(e.target.closest('.topbar,.chat-heading,.calendar-toolbar,.mobile-bottom-nav,input,textarea,select'))revealChrome();});
 document.addEventListener('pointermove',e=>{if(e.clientY<20)revealChrome();},{passive:true});
 function viewport(){const v=window.visualViewport;document.documentElement.style.setProperty('--visual-height',(v?.height||innerHeight)+'px');document.documentElement.classList.toggle('keyboard-open',!!v&&innerHeight-v.height>140&&!!document.activeElement?.closest('input,textarea'));}
 window.visualViewport?.addEventListener('resize',viewport);window.addEventListener('resize',()=>{setWidth(storage.get('campus.sidebar.width',234));updateToggle();viewport();});viewport();
}
