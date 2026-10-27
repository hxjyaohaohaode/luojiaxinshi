// Presentation only: keep the last two Han characters with closing punctuation.
// No inserted spaces/joiners: copied text, search and source quotes stay exact.
export function protectOrphans(root,selector='p,li,h2,h3,h4,.gu-heading,.chat-operation strong'){
  for(const block of root.querySelectorAll(selector)){
    if(block.closest('pre,code,svg,button,[contenteditable]')||block.querySelector('p,ul,ol,.prose-tail'))continue;
    const walker=document.createTreeWalker(block,NodeFilter.SHOW_TEXT);let last=null,node;
    while((node=walker.nextNode()))if(node.textContent.trim())last=node;
    if(!last||last.parentElement.closest('a,button,code,svg,.prose-tail,.ink-glyph'))continue;
    const match=last.textContent.match(/\p{Script=Han}{2}[，。！？；：、…）】》”’」』]*\s*$/u);if(!match)continue;
    const tail=document.createElement('span');tail.className='prose-tail';tail.textContent=match[0];
    last.replaceWith(document.createTextNode(last.textContent.slice(0,match.index)),tail);
  }
}
