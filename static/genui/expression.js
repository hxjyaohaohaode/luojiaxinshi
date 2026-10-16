import {CATALOG} from './catalog.js';
import {pathParts,readPath,bytes} from './security.js';
import {DATA_FUNCTIONS,dataFunction} from './data-functions.js';
const cached=new Map();
const precedence={'||':1,'&&':2,'==':3,'!=':3,'===':3,'!==':3,'<':4,'<=':4,'>':4,'>=':4,'+':5,'-':5,'*':6,'/':6,'%':6};
export function parseExpression(source,limits=CATALOG.limits){
  if(typeof source!=='string'||source.length>limits.expressionChars)throw Error('expression_limit');
  const cacheKey=[source,limits.expressionSteps,limits.expressionDepth].join('|');
  if(cached.has(cacheKey))return cached.get(cacheKey);
  const tokens=[];let cursor=0;
  while(cursor<source.length){
    if(/\s/.test(source[cursor])){cursor++;continue;}
    const tail=source.slice(cursor),match=tail.match(/^(?:(\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|([A-Za-z_][A-Za-z0-9_.]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(===|!==|<=|>=|==|!=|&&|\|\||[+\-*/%<>()!?:,\[\]]))/);
    if(!match)throw Error('invalid_expression_token');
    const raw=match[0];cursor+=raw.length;
    if(match[1])tokens.push({kind:'literal',value:Number(raw)});
    else if(match[2]){pathParts(raw);tokens.push({kind:'name',value:raw});}
    else if(match[3]){let value;if(raw[0]==='"')value=JSON.parse(raw);else value=raw.slice(1,-1).replace(/\\([\\'nrt])/g,(_,c)=>({n:'\n',r:'\r',t:'\t'}[c]||c));tokens.push({kind:'literal',value});}
    else tokens.push({kind:raw,value:raw});
  }
  let index=0,steps=0;
  const take=kind=>{if(tokens[index]?.kind!==kind)throw Error('invalid_expression');return tokens[index++];};
  function parse(min=0,depth=0){
    if(depth>limits.expressionDepth||++steps>limits.expressionSteps)throw Error('expression_steps');
    let token=tokens[index++],left;if(!token)throw Error('invalid_expression');
    if(token.kind==='literal')left={kind:'literal',value:token.value};
    else if(token.kind==='name'){
      if(['true','false','null'].includes(token.value))left={kind:'literal',value:{true:true,false:false,null:null}[token.value]};
      else if(tokens[index]?.kind==='('){
        if(!CATALOG.functions.includes(token.value))throw Error('forbidden_function');index++;const args=[];
        if(tokens[index]?.kind!==')')do{args.push(parse(0,depth+1));if(tokens[index]?.kind!==',')break;index++;}while(true);
        take(')');left={kind:'call',name:token.value,args};
      }else left={kind:'path',path:token.value};
    }else if(token.kind==='['){const items=[];if(tokens[index]?.kind!==']')do{items.push(parse(0,depth+1));if(items.length>limits.dataItems)throw Error('expression_limit');if(tokens[index]?.kind!==',')break;index++;}while(true);take(']');left={kind:'array',items};}
    else if(['!','+','-'].includes(token.kind))left={kind:'unary',op:token.kind,arg:parse(7,depth+1)};
    else if(token.kind==='('){left=parse(0,depth+1);take(')');}
    else throw Error('invalid_expression');
    while(tokens[index]&&precedence[tokens[index].kind]>=min){const op=tokens[index++].kind;left={kind:'binary',op,left,right:parse(precedence[op]+1,depth+1)};}
    if(min===0&&tokens[index]?.kind==='?'){index++;const yes=parse(0,depth+1);take(':');left={kind:'ternary',test:left,yes,no:parse(0,depth+1)};}
    return left;
  }
  const ast=parse();if(index!==tokens.length)throw Error('invalid_expression');
  if(cached.size>=200)cached.delete(cached.keys().next().value);cached.set(cacheKey,ast);return ast;
}
const numeric=value=>{if(typeof value!=='number'||!Number.isFinite(value))throw Error('expected_number');return value;};
export function evaluateExpression(source,state,limits=CATALOG.limits){
  const ast=parseExpression(source,limits);let steps=0;
  function run(node,depth=0){
    if(++steps>limits.expressionSteps||depth>limits.expressionDepth)throw Error('expression_steps');
    let value;
    if(node.kind==='literal')value=node.value;
    else if(node.kind==='array')value=node.items.map(item=>run(item,depth+1));
    else if(node.kind==='path')value=readPath(state,node.path);
    else if(node.kind==='ternary')value=run(node.test,depth+1)?run(node.yes,depth+1):run(node.no,depth+1);
    else if(node.kind==='unary'){const a=run(node.arg,depth+1);value=node.op==='!'?!a:node.op==='-'?-numeric(a):numeric(a);}
    else if(node.kind==='binary'){
      const a=run(node.left,depth+1);if(node.op==='&&')return a?run(node.right,depth+1):a;if(node.op==='||')return a||run(node.right,depth+1);
      const b=run(node.right,depth+1);
      if(['==','==='].includes(node.op))value=a===b;else if(['!=','!=='].includes(node.op))value=a!==b;
      else if(node.op==='<')value=a<b;else if(node.op==='<=')value=a<=b;else if(node.op==='>')value=a>b;else if(node.op==='>=')value=a>=b;
      else if(node.op==='+'&&(typeof a==='string'||typeof b==='string'))value=String(a)+String(b);
      else{numeric(a);numeric(b);value=node.op==='+'?a+b:node.op==='-'?a-b:node.op==='*'?a*b:node.op==='/'?a/b:a%b;}
    }else if(node.kind==='call'){
      const args=node.args.map(a=>run(a,depth+1)),flat=args.length===1&&Array.isArray(args[0])?args[0]:args;
      if(Object.hasOwn(DATA_FUNCTIONS,node.name))return dataFunction(node.name,args,cost=>{steps+=cost;if(steps>limits.expressionSteps)throw Error('expression_steps');});
      const arity={round:[1,2],format:[1,2],floor:[1,1],ceil:[1,1],abs:[1,1],pow:[2,2],clamp:[3,3],min:[1,100],max:[1,100],sum:[1,100]}[node.name];
      if(args.length<arity[0]||args.length>arity[1])throw Error('invalid_arity');
      steps+=flat.length;if(steps>limits.expressionSteps)throw Error('expression_steps');
      if(['min','max','sum'].includes(node.name)){flat.forEach(numeric);value=node.name==='sum'?flat.reduce((a,b)=>a+b,0):node.name==='min'?Math.min(...flat):Math.max(...flat);}
      else{args.forEach(numeric);const [a,b=0,c]=args;
        if(node.name==='pow')value=Math.pow(a,b);else if(node.name==='clamp')value=Math.min(c,Math.max(b,a));
        else if(node.name==='round'){if(b<0||b>10||!Number.isInteger(b))throw Error('invalid_precision');value=Math.round(a*10**b)/10**b;}
        else if(node.name==='format'){if(b<0||b>10||!Number.isInteger(b))throw Error('invalid_precision');value=a.toLocaleString('zh-CN',{minimumFractionDigits:b,maximumFractionDigits:b});}
        else value=Math[node.name](a);
      }
    }else throw Error('invalid_expression');
    if(typeof value==='number'&&!Number.isFinite(value))throw Error('non_finite_result');
    if(typeof value==='string'&&bytes(value)>limits.stringBytes)throw Error('string_limit');return value;
  }
  return run(ast);
}
