// Keep a real reading anchor through reflow and asynchronous renderer paints.
// Any deliberate reading gesture immediately takes control back.
const pending=new WeakMap();
const automatic=new WeakMap();
export const chatViewportHeld=reader=>!!reader&&pending.has(reader);
export function scrollChatToEnd(reader){if(!reader)return;pending.get(reader)?.stop();reader.scrollTop=reader.scrollHeight;automatic.set(reader,{top:reader.scrollTop,at:performance.now()});}
export function automaticChatScroll(reader){const mark=automatic.get(reader);return chatViewportHeld(reader)||!!mark&&performance.now()-mark.at<120&&Math.abs(reader.scrollTop-mark.top)<1;}
export function preserveChatViewport(reader,change,{anchor=null,pinBottom=true}={}){
 if(!reader){change();return;}
 const active=pending.get(reader);if(active){active.update(change);return;}
 const box=reader.getBoundingClientRect(),bottom=pinBottom&&!anchor&&reader.scrollHeight-reader.clientHeight-reader.scrollTop<28;
 const heading=reader.closest('.chat-main')?.querySelector('.chat-heading'),head=heading?.getBoundingClientRect(),style=heading&&getComputedStyle(heading);
 const readingTop=head&&['absolute','fixed'].includes(style.position)&&style.visibility!=='hidden'&&Number(style.opacity)>.5&&head.right>box.left&&head.left<box.right?Math.max(box.top,Math.min(box.bottom,head.bottom)):box.top;
 let saved=null;
 const identify=(node,top)=>{const article=node.closest?.('.message');return article?{turn:article.dataset.turnId||article.dataset.messageId,role:article.dataset.role||'assistant',part:node.closest('.message-footer')?'footer':'article',top}:null;};
 if(anchor)saved=identify(anchor,anchor.closest('.message-footer')?.getBoundingClientRect().top??anchor.closest('.message')?.getBoundingClientRect().top);
 if(!bottom&&!saved){
  const walker=document.createTreeWalker(reader,NodeFilter.SHOW_TEXT);let node;
  while((node=walker.nextNode())){
   if(!node.textContent.trim()||node.parentElement.closest('[hidden],[inert],.sr-only,button,script,style,.chat-time-separator'))continue;
   const range=document.createRange();range.selectNodeContents(node);
   const rects=[...range.getClientRects()],visible=rects.find(r=>r.top>=readingTop+2&&r.bottom<=box.bottom-2)||rects.find(r=>r.bottom>readingTop+8&&r.top<box.bottom-8);
   if(!visible)continue;
   let low=0,high=node.length-1;
   while(low<high){const mid=(low+high)>>1;range.setStart(node,mid);range.setEnd(node,mid+1);if(range.getBoundingClientRect().top<visible.top-1)low=mid+1;else high=mid;}
   range.setStart(node,low);range.setEnd(node,Math.min(node.length,low+1));const article=node.parentElement.closest('.message');saved={...identify(node.parentElement,article?.getBoundingClientRect().top),range,rangeTop:range.getBoundingClientRect().top};break;
  }
 }
 const previousOverflow=reader.style.overflowAnchor,previousBehavior=reader.style.scrollBehavior;reader.style.overflowAnchor='none';reader.style.scrollBehavior='auto';
 let observer,mutations,timer,frame,finished=false;
 const stop=()=>{if(finished)return;finished=true;observer?.disconnect();mutations?.disconnect();clearTimeout(timer);cancelAnimationFrame(frame);reader.style.overflowAnchor=previousOverflow;reader.style.scrollBehavior=previousBehavior;for(const name of ['wheel','touchstart','pointerdown','keydown'])reader.removeEventListener(name,stop);if(pending.get(reader)?.stop===stop)pending.delete(reader);};
 const target=()=>saved?.turn?[...reader.querySelectorAll('.message')].find(node=>(node.dataset.turnId||node.dataset.messageId)===saved.turn&&(node.dataset.role||'assistant')===saved.role):null;
 const restore=()=>{
  if(finished||!reader.isConnected)return;
  if(bottom)reader.scrollTop=reader.scrollHeight-reader.clientHeight;
  else if(saved?.range?.startContainer.isConnected)reader.scrollTop+=saved.range.getBoundingClientRect().top-saved.rangeTop;
  else{const article=target(),node=saved?.part==='footer'?article?.querySelector('.message-footer:not([hidden])')||article:article;if(node&&Number.isFinite(saved.top))reader.scrollTop+=node.getBoundingClientRect().top-saved.top;}
 };
 const watch=()=>{if(!observer)return;observer.disconnect();observer.observe(reader);const article=target();if(article)observer.observe(article);if(reader.lastElementChild&&reader.lastElementChild!==article)observer.observe(reader.lastElementChild);};
 const settle=()=>{clearTimeout(timer);timer=setTimeout(stop,650);};
 const update=mutation=>{try{mutation();restore();watch();cancelAnimationFrame(frame);frame=requestAnimationFrame(restore);settle();}catch(error){stop();throw error;}};
 pending.set(reader,{stop,update});
 for(const name of ['wheel','touchstart','pointerdown','keydown'])reader.addEventListener(name,stop,{passive:true});
 try{
  if(typeof ResizeObserver!=='undefined')observer=new ResizeObserver(()=>{if(!reader.isConnected){stop();return;}restore();settle();});
  mutations=new MutationObserver(()=>{watch();restore();settle();});mutations.observe(reader,{childList:true});
  update(change);
 }catch(error){stop();throw error;}
}
