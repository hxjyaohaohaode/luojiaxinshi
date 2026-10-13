import {CATALOG} from './catalog.js';
export const FORBIDDEN=new Set(CATALOG.forbiddenKeys);
export const bytes=value=>new TextEncoder().encode(value).length;
export const safeKey=key=>typeof key==='string'&&/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(key)&&!FORBIDDEN.has(key);
export function pathParts(path){
  if(typeof path!=='string'||path.length>200)throw Error('invalid_path');
  const parts=path.split('.');
  if(parts.length>8||parts.some(p=>!/^([A-Za-z][\w-]{0,63}|\d{1,4})$/.test(p)||FORBIDDEN.has(p)))throw Error('invalid_path');
  return parts;
}
export function readPath(value,path){for(const key of pathParts(path)){if(value===null||typeof value!=='object'||!Object.hasOwn(value,key))throw Error('missing_reference');value=value[key];}return value;}
export function safeClone(value,limits=CATALOG.limits){
  let steps=0;
  function walk(item,depth){
    if(++steps>20000||depth>limits.depth)throw Error('value_too_deep');
    if(item===null||typeof item==='boolean')return item;
    if(typeof item==='number'){if(!Number.isFinite(item))throw Error('non_finite_number');return item;}
    if(typeof item==='string'){if(bytes(item)>limits.stringBytes)throw Error('string_limit');return item;}
    if(typeof item!=='object')throw Error('invalid_value');
    if(Array.isArray(item)){if(item.length>limits.dataItems)throw Error('array_limit');return item.map(v=>walk(v,depth+1));}
    if(![Object.prototype,null].includes(Object.getPrototypeOf(item)))throw Error('invalid_object');
    const output=Object.create(null);
    for(const key of Object.keys(item)){if(FORBIDDEN.has(key)||key.length>100)throw Error('forbidden_key');output[key]=walk(item[key],depth+1);}
    return output;
  }
  return walk(value,0);
}
export function matches(value,schema={},dynamic=true){
  if(dynamic&&value&&typeof value==='object'&&!Array.isArray(value)){
    const keys=Object.keys(value);
    if(keys.length===1&&['$bind','$expr','$ref'].includes(keys[0])){
      if(typeof value[keys[0]]!=='string')return false;
      try{if(keys[0]!=='$expr')pathParts(value[keys[0]]);else if(value.$expr.length>CATALOG.limits.expressionChars)return false;return true;}catch{return false;}
    }
  }
  if(schema.const!==undefined&&value!==schema.const)return false;
  const type=value===null?'null':Array.isArray(value)?'array':typeof value;
  const types=Array.isArray(schema.type)?schema.type:schema.type?[schema.type]:[];
  if(types.length&&!types.includes(type)&&!(types.includes('integer')&&typeof value==='number'&&Number.isInteger(value)))return false;
  if(schema.enum&&!schema.enum.includes(value))return false;
  if(typeof value==='string'&&schema.maxLength!==undefined&&value.length>schema.maxLength)return false;
  if(typeof value==='number'&&(!Number.isFinite(value)||(schema.minimum!==undefined&&value<schema.minimum)||(schema.maximum!==undefined&&value>schema.maximum)||(schema.exclusiveMinimum!==undefined&&value<=schema.exclusiveMinimum)))return false;
  if(Array.isArray(value)){if(schema.maxItems!==undefined&&value.length>schema.maxItems)return false;if(schema.items&&!value.every(v=>matches(v,schema.items,dynamic)))return false;}
  if(type==='object'){
    if(schema.required?.some(k=>!Object.hasOwn(value,k)))return false;
    if(schema.properties)for(const key of Object.keys(value)){if(!Object.hasOwn(schema.properties,key)){if(schema.additionalProperties===false)return false;}else if(!matches(value[key],schema.properties[key],dynamic))return false;}
  }
  return true;
}
export function safeUrl(value,{hosts=CATALOG.policy.urlHosts,origin=typeof location==='undefined'?'http://localhost':location.origin,mailto=false}={}){
  if(typeof value!=='string'||value.length>2000||/[\u0000-\u0020\u007f]/.test(value))return null;
  try{const url=new URL(value,origin);if(url.username||url.password)return null;if(mailto&&url.protocol==='mailto:')return url.href;if(!['https:','http:'].includes(url.protocol))return null;
    if(url.origin===origin)return url.href;
    if(hosts===null)return url.href;
    if(!hosts.some(host=>url.hostname===host||url.hostname.endsWith('.'+host)))return null;
    return url.href;
  }catch{return null;}
}
