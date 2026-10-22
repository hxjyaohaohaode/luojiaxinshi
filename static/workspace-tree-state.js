// Search may reveal matching descendants; leaving search restores the user's
// own folder choices, scroll position and focus for this conversation only.
import {detailsExpanded} from './reference-interactions.js';
export class MaterialTreeState{
 constructor(){this.scope=null;this.folders=new Map();this.filtered=false;this.scroll=0;}
 update(container,{scope,filtered},render){
  const fresh=this.scope!==scope;
  if(fresh){this.scope=scope;this.folders.clear();this.filtered=false;this.scroll=0;}
  if(!fresh&&!this.filtered){
   for(const folder of container.querySelectorAll('[data-folder-path]'))this.folders.set(folder.dataset.folderPath,detailsExpanded(folder));
   this.scroll=container.scrollTop;
  }
  const top=container.scrollTop,restoring=this.filtered&&!filtered,active=document.activeElement;
  const focus=container.contains(active)?active.matches('summary')?{folder:active.closest('[data-folder-path]')?.dataset.folderPath}:{id:active.dataset.id,action:active.dataset.chatAction}:null;
  this.filtered=filtered;render();
  if(!filtered)for(const folder of container.querySelectorAll('[data-folder-path]'))if(this.folders.has(folder.dataset.folderPath))folder.open=this.folders.get(folder.dataset.folderPath);
  if(focus){
   const next=focus.folder!==undefined?[...container.querySelectorAll('[data-folder-path]')].find(node=>node.dataset.folderPath===focus.folder)?.querySelector(':scope > summary'):[...container.querySelectorAll('[data-chat-action][data-id]')].find(node=>node.dataset.id===focus.id&&node.dataset.chatAction===focus.action);
   if(next?.getClientRects().length)next.focus({preventScroll:true});
   else container.closest('.chat-materials')?.querySelector('input[type=search]')?.focus({preventScroll:true});
  }
  container.scrollTop=fresh?0:restoring?this.scroll:top;
 }
}
