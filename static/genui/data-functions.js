// Bounded, deterministic data operations. No callbacks, scripts, network or mutation.
import {readPath} from './security.js';
export const DATA_FUNCTIONS={count:[1,1],contains:[2,2],where:[3,3],search:[2,2],orderBy:[2,3],take:[2,2],pluck:[2,2],sumBy:[2,2],meanBy:[2,2],series:[3,3]};
export function dataFunction(name,args,charge){
  const [input,key,value]=args,arity=DATA_FUNCTIONS[name];
  if(args.length<arity[0]||args.length>arity[1])throw Error('invalid_arity');
  if(name==='contains'){if(!Array.isArray(input)&&typeof input!=='string')throw Error('expected_collection');charge(input.length);return input.includes(key);}
  if(!Array.isArray(input)||input.length>1000)throw Error('expected_bounded_array');
  charge(input.length+1);
  if(name==='count')return input.length;
  if(name==='take'){if(!Number.isInteger(key)||key<0||key>1000)throw Error('invalid_count');return input.slice(0,key);}
  if(name==='search'){
    if(typeof key!=='string'||key.length>500)throw Error('invalid_search');const q=key.trim().toLocaleLowerCase();
    return q?input.filter(row=>Object.values(row&&typeof row==='object'?row:{value:row}).some(v=>['string','number','boolean'].includes(typeof v)&&String(v).toLocaleLowerCase().includes(q))):input;
  }
  if(typeof key!=='string')throw Error('invalid_field');
  const get=row=>readPath(row,key);
  if(name==='where')return input.filter(row=>get(row)===value);
  if(name==='pluck')return input.map(get);
  if(name==='orderBy'){
    if(value!==undefined&&typeof value!=='boolean')throw Error('invalid_order');charge(Math.ceil(input.length*Math.log2(input.length+1)));
    return [...input].sort((a,b)=>{const x=get(a),y=get(b);if(!['string','number','boolean'].includes(typeof x)||typeof x!==typeof y)throw Error('invalid_sort_value');return (typeof x==='number'?x-y:String(x).localeCompare(String(y),'zh-CN',{numeric:true}))*(value?-1:1);});
  }
  const number=v=>{if(typeof v!=='number'||!Number.isFinite(v))throw Error('expected_number');return v;};
  if(name==='series'){
    if(typeof value!=='string')throw Error('invalid_field');return input.map(row=>({x:get(row),y:number(readPath(row,value))}));
  }
  const total=input.reduce((sum,row)=>sum+number(get(row)),0);
  if(!Number.isFinite(total))throw Error('non_finite_result');
  return name==='meanBy'?(input.length?total/input.length:0):total;
}
