// A small presentation grammar. It creates MathML nodes; it never evaluates text.
const symbols={alpha:'α',beta:'β',gamma:'γ',delta:'δ',theta:'θ',lambda:'λ',mu:'μ',pi:'π',sigma:'σ',sum:'∑',times:'×',cdot:'·',le:'≤',ge:'≥',neq:'≠',infty:'∞'};
export function mathTree(text){
  if(typeof text!=='string'||text.length>2000)throw Error('formula_limit');
  const tokens=text.match(/\\[a-z]+|\d+(?:\.\d+)?|[A-Za-z]+|[^\s]/g)||[];let at=0,steps=0;
  const node=(tag,...children)=>({tag,children});
  function atom(depth){
    if(++steps>600||depth>8)throw Error('formula_limit');
    const token=tokens[at++];if(token===undefined)throw Error('incomplete_formula');
    if(token==='{'){const group=groupAt(depth+1,true);return group;}
    if(token==='\\frac')return node('mfrac',atom(depth+1),atom(depth+1));
    if(token==='\\sqrt')return node('msqrt',atom(depth+1));
    if(token.startsWith('\\'))return node('mi',symbols[token.slice(1)]||token);
    if(['}','^','_'].includes(token))throw Error('invalid_formula');
    return node(/^\d/.test(token)?'mn':/^[A-Za-z]+$/.test(token)?'mi':'mo',token);
  }
  function groupAt(depth,nested=false){
    const children=[];
    while(at<tokens.length&&tokens[at]!=='}'){
      let base=atom(depth),sub,sup;
      while(['^','_'].includes(tokens[at])){const op=tokens[at++];if(op==='^'){if(sup)throw Error('duplicate_script');sup=atom(depth+1);}else{if(sub)throw Error('duplicate_script');sub=atom(depth+1);}}
      if(sub&&sup)base=node('msubsup',base,sub,sup);else if(sub)base=node('msub',base,sub);else if(sup)base=node('msup',base,sup);
      children.push(base);
    }
    if(nested&&tokens[at++]!=='}')throw Error('incomplete_formula');
    return node('mrow',...children);
  }
  const tree=groupAt(0);if(at!==tokens.length)throw Error('invalid_formula');return tree;
}
export function formula(text){
  const ns='http://www.w3.org/1998/Math/MathML',math=document.createElementNS(ns,'math');math.setAttribute('display','block');math.setAttribute('aria-label',text);
  function build(tree){const n=document.createElementNS(ns,tree.tag);for(const child of tree.children)n.append(typeof child==='string'?document.createTextNode(child):build(child));return n;}
  try{math.append(build(mathTree(text)));}catch{const fallback=document.createElementNS(ns,'mtext');fallback.textContent=text;math.append(fallback);}
  return math;
}
