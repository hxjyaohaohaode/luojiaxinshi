// Preserve a text anchor through the whole resize, including an existing CSS
// transition. Any deliberate reading gesture immediately takes control back.
const pending=new WeakMap();
export function preserveChatViewport(reader,change){
 if(!reader){change();return;}
 const active=pending.get(reader);if(active){active.update(change);return;}
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
 let observer,timer,frame,finished=false;
 const stop=()=>{if(finished)return;finished=true;observer?.disconnect();clearTimeout(timer);cancelAnimationFrame(frame);for(const name of ['wheel','touchstart','pointerdown','keydown'])reader.removeEventListener(name,stop);if(pending.get(reader)?.stop===stop)pending.delete(reader);};
 const restore=()=>{
  if(!reader.isConnected)return;
  if(bottom)reader.scrollTop=reader.scrollHeight-reader.clientHeight;
  else if(saved?.range.startContainer.isConnected){const top=saved.range.getBoundingClientRect().top;reader.scrollTop+=top-saved.top;}
 };
 const update=mutation=>{try{mutation();restore();cancelAnimationFrame(frame);frame=requestAnimationFrame(restore);clearTimeout(timer);timer=setTimeout(stop,500);}catch(error){stop();throw error;}};
 pending.set(reader,{stop,update});
 for(const name of ['wheel','touchstart','pointerdown','keydown'])reader.addEventListener(name,stop,{passive:true});
 try{
  update(change);
  if(typeof ResizeObserver!=='undefined'){
   observer=new ResizeObserver(()=>{if(finished)return;if(!reader.isConnected){stop();return;}restore();clearTimeout(timer);timer=setTimeout(stop,100);});observer.observe(reader);
  }
 }catch(error){stop();throw error;}
}
