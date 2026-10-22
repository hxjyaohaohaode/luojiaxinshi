// Keep the visible text at the same reading position while a side panel reflows it.
export function preserveChatViewport(reader,change){
 if(!reader){change();return;}
 const box=reader.getBoundingClientRect(),bottom=reader.scrollHeight-reader.clientHeight-reader.scrollTop<28;
 let saved=null;
 if(!bottom){
  const walker=document.createTreeWalker(reader,NodeFilter.SHOW_TEXT);let node;
  while((node=walker.nextNode())){
   if(!node.textContent.trim()||node.parentElement.closest('[hidden],button,script,style'))continue;
   const range=document.createRange();range.selectNodeContents(node);
   const visible=[...range.getClientRects()].find(r=>r.bottom>box.top+8&&r.top<box.bottom-8);
   if(!visible)continue;
   let low=0,high=node.length-1;
   while(low<high){const mid=(low+high)>>1;range.setStart(node,mid);range.setEnd(node,mid+1);if(range.getBoundingClientRect().top<visible.top-1)low=mid+1;else high=mid;}
   range.setStart(node,low);range.setEnd(node,Math.min(node.length,low+1));saved={range,top:range.getBoundingClientRect().top};break;
  }
 }
 const restore=()=>{
  if(!reader.isConnected)return;
  if(bottom)reader.scrollTop=reader.scrollHeight-reader.clientHeight;
  else if(saved?.range.startContainer.isConnected){const top=saved.range.getBoundingClientRect().top;reader.scrollTop+=top-saved.top;}
 };
 change();restore();requestAnimationFrame(restore);
}
