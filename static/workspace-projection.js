/** Complete owner-scoped lightweight collections. Paging belongs to list views;
 * the home summary and calendar must never use a first page as the whole account. */
export function createWorkspaceProjection({api,owner,context=()=>null}){
  let identity=null,request=0,cache={};
  function reset(){identity=owner();cache={};request++;}
  async function load(kinds=['notices','tasks'],{clockOnly=false}={}){
    if(identity!==owner())reset();
    const account=identity,view=context(),token=++request,selected=[...new Set(kinds)];
    if(!account||!selected.length)return null;
    if(selected.some(kind=>!['notices','tasks'].includes(kind)))throw Error('不支持的工作台数据类型');
    const current=()=>identity===account&&owner()===account&&context()===view&&request===token;
    const versions=selected.map(kind=>cache[kind]?.revision),base=versions[0];
    const canMerge=clockOnly&&base&&versions.every(revision=>revision===base);
    const params=new URLSearchParams({include:selected.join(',')});
    if(canMerge){params.set('clock_only','1');params.set('revision',base);}
    let result=await api('/workspace/projection?'+params);
    if(!current())return null;
    const invalidSparse=()=>selected.some(kind=>{
      if(!Array.isArray(result[kind])||!cache[kind])return true;
      const ids=new Set(cache[kind].items.map(item=>item.id));return result[kind].some(item=>!ids.has(item.id));
    });
    if(result.clock_only&&(!canMerge||result.revision!==base||invalidSparse())){
      // A server restart or changed entity set requires a complete lightweight
      // snapshot. Sparse fields are never mistaken for complete task data.
      result=await api('/workspace/projection?'+new URLSearchParams({include:selected.join(',')}));
      if(!current())return null;
      if(result.clock_only)throw Error('工作台数据范围已变化，请重新读取。');
    }
    const complete={...result};
    for(const kind of selected){
      if(!Array.isArray(result[kind]))throw Error('工作台数据暂未完整返回，请重试。');
      const patches=new Map(result[kind].map(item=>[item.id,item]));
      const items=result.clock_only?cache[kind].items.map(item=>patches.has(item.id)?{...item,...patches.get(item.id)}:item):result[kind];
      complete[kind]=items;cache[kind]={revision:result.revision,items};
    }
    return complete;
  }
  return {load,clear:reset};
}
