import {markdown} from './dom.js';
import {motionAllowed} from '../experience-system.js';
import {protectOrphans} from './typography.js';

const runs=new WeakSet();
const segmenter=typeof Intl.Segmenter==='function'?new Intl.Segmenter('zh',{granularity:'grapheme'}):null;
export const graphemes=text=>segmenter?[...segmenter.segment(text)].map(part=>part.segment):Array.from(text);

// Reconcile the append-only prose tree. Unchanged paragraphs and text runs keep
// their identity; interactive controls are rebound from the current parser.
export class StreamMarkdownView{
  constructor(root,{view={},changed=()=>{}}={}){this.root=root;this.view=view;this.changed=changed;this.glyphs=new Set();this.cursor=0;this.timer=0;}
  render(text,{streaming=false}={}){
    if(this.text===text&&this.streaming===streaming)return;
    const previous=this.root.textContent.length,next=markdown(text,{enhance:!streaming,streaming,view:this.view,changed:this.changed});
    const append=this.text===undefined||String(text).startsWith(this.text);
    this.revealFrom=streaming&&append&&motionAllowed()?Math.max(previous,next.textContent.length-96):Infinity;
    // A preview correction is a replacement, not another arrival of old words.
    if(this.text===undefined)this.revealFrom=streaming&&motionAllowed()?Math.max(0,next.textContent.length-96):Infinity;
    this.cursor=0;this.sequence=0;
    if(streaming&&this.streaming!==false)this.patch(this.root,[next]);
    else{this.clear();this.root.replaceChildren(next);if(!streaming)protectOrphans(this.root);}
    this.text=String(text);this.streaming=streaming;
    clearTimeout(this.timer);if(this.glyphs.size)this.timer=setTimeout(()=>this.clear(),400);
  }
  textRun(old,text){
    const start=this.cursor;this.cursor+=text.length;
    let run=old;
    if(!run||!runs.has(run)){run=document.createElement('span');run.className='ink-run';runs.add(run);}
    const previous=run.textContent;
    if(previous===text)return run;
    const prefix=text.startsWith(previous)?previous.length:0;
    if(!prefix)run.replaceChildren();
    let offset=prefix,plain='';
    const flush=()=>{if(plain){run.append(document.createTextNode(plain));plain='';}};
    for(const glyph of graphemes(text.slice(prefix))){
      if(start+offset>=this.revealFrom&&glyph.trim()){
        if(this.glyphs.size>=128)this.settle(this.glyphs.values().next().value);
        flush();const span=document.createElement('span');span.className='ink-glyph';span.textContent=glyph;span.style.setProperty('--ink-delay',Math.min(this.sequence++*9,90)+'ms');this.glyphs.add(span);run.append(span);
        span.addEventListener('animationend',()=>this.settle(span),{once:true});
      }else plain+=glyph;
      offset+=glyph.length;
    }
    flush();return run;
  }
  patch(parent,fresh){
    let index=0;
    for(const next of fresh){
      const old=parent.childNodes[index];let node;
      if(next.nodeType===Node.TEXT_NODE)node=this.textRun(old,next.textContent);
      else if(next.nodeType!==Node.ELEMENT_NODE){node=next;}
      else if(next.matches('button,input,textarea,select,pre,svg,.gu-code')){
        this.cursor+=next.textContent.length;node=next;
      }else{
        node=old?.nodeType===Node.ELEMENT_NODE&&!runs.has(old)&&old.tagName===next.tagName?old:next.cloneNode(false);
        for(const attr of [...node.attributes])if(!next.hasAttribute(attr.name))node.removeAttribute(attr.name);
        for(const attr of next.attributes)if(node.getAttribute(attr.name)!==attr.value)node.setAttribute(attr.name,attr.value);
        this.patch(node,[...next.childNodes]);
      }
      if(old!==node){if(old)old.replaceWith(node);else parent.append(node);}
      index++;
    }
    while(parent.childNodes.length>index)parent.lastChild.remove();
  }
  settle(node){
    if(!this.glyphs.delete(node))return;
    const parent=node.parentElement;node.replaceWith(document.createTextNode(node.textContent));parent?.normalize();
  }
  clear(){clearTimeout(this.timer);for(const glyph of this.glyphs)this.settle(glyph);this.glyphs.clear();}
  dispose(){this.clear();}
}
