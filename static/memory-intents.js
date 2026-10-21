// Hashes and random intent IDs stay in this page's memory; no remembered text
// is persisted in a retry cache or shared between accounts.
function canonical(value){
  if(Array.isArray(value))return value.map(canonical);
  if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
  return value;
}
export function createMemoryIntents(){
  let owner=null,generation=0;const entries=new Map();
  return {async headers(user,operation,payload){
    if(user!==owner){owner=user;generation++;entries.clear();}
    const ticket=generation;
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(canonical(payload))));
    const signature=operation+':'+Array.from(new Uint8Array(bytes),value=>value.toString(16).padStart(2,'0')).join('');
    if(ticket!==generation)return {'Idempotency-Key':crypto.randomUUID()};
    if(!entries.has(signature))entries.set(signature,crypto.randomUUID());
    const key=entries.get(signature);
    if(entries.size>250)entries.delete(entries.keys().next().value);
    return {'Idempotency-Key':key};
  }};
}
