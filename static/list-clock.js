const dynamic = {tasks:['overdue','due_soon','followup_due','handling_state'],notices:['intent','recommended','assessment','tracking','publication_context']};
const plain = value => value && typeof value === 'object' && !Array.isArray(value);
function merge(original, patch, key='') {
  if (key === 'summary' && patch === '' && typeof original === 'string') return original;
  if (Array.isArray(patch)) return patch.map(item => {
    const previous = plain(item) && Array.isArray(original) ? original.find(value =>
      plain(value) && (item.index != null ? value.index === item.index : item.id != null && value.id === item.id)) : null;
    return previous ? merge(previous,item) : structuredClone(item);
  });
  if (!plain(patch)) return patch;
  const result = {...(plain(original)?original:{})};
  for (const [field,value] of Object.entries(patch)) result[field] = merge(result[field],value,field);
  if (patch.detail_truncated && typeof original?.detail === 'string' && original.detail.startsWith(patch.detail) && original.kind === patch.kind) {
    result.detail = original.detail; delete result.detail_truncated;
  }
  return result;
}
export function mergeListClock(kind, item, light) {
  if (!light) return item;
  const next = {...item};
  for (const field of dynamic[kind]) if (field in light) next[field] = merge(item[field],light[field],field);
  return next;
}
export function sameListDisplay(a,b) {
  // Evaluation timestamps describe the computation, not a changed list label.
  const metadata = key => ['evaluated_at','detail_truncated'].includes(key);
  return JSON.stringify(a,(key,value)=>metadata(key)?undefined:value) === JSON.stringify(b,(key,value)=>metadata(key)?undefined:value);
}
export function clockSensitiveList(kind, filters) {
  return kind === 'tasks' ? ['soon','followup'].includes(filters.status) :
    !['','all'].includes(filters.intent||'') || ['priority','deadline'].includes(filters.sort);
}
export function invalidateChangedLists(domains, collections) {
  // These stable domains are shared by the authenticated list cursor contract.
  // A route that does not need a projection must still invalidate its cached
  // collections before the sync controller consumes the committed revision.
  if (domains && !['notices','tasks','account'].some(key => domains.has(key))) return false;
  for (const collection of collections) collection.invalidate();
  return true;
}
export function createListClock(kind) {
  let lastKey='', lastSignature='';
  return {async refresh(collection, projection, {owner,canApply=()=>true,reload}={}) {
    const value=collection.snapshot();if (!value.loaded || value.loading || !canApply() || !Array.isArray(projection?.[kind])) return null;
    const key=JSON.stringify([owner,value.filters]),rows=projection[kind],byId=new Map(rows.map(item=>[item.id,item]));
    const signature=clockSensitiveList(kind,value.filters)?JSON.stringify([projection.revision,rows.map(item=>kind==='tasks'?
      [item.id,!!item.overdue,!!item.due_soon,!!item.followup_due]:
      [item.id,item.intent,item.recommended,item.assessment?.priority,item.assessment?.urgency])]):'';
    // A new/deleted record can be outside the visible range. Comparing only
    // loaded IDs cannot detect it, so use the projection's cache-bound revision.
    const changedStable=value.projection_stale===true || projection.baseline_known!==true || projection.stable_changed===true || value.items.some(item=>{
      const next=byId.get(item.id);return !next || next.version!==item.version ||
        kind==='tasks'&&next.workflow?.version!==item.workflow?.version ||
        ['status','updated_at','disposition'].some(field=>field in next&&next[field]!==item[field]);
    });
    let result;
    if (changedStable || signature && (lastKey!==key || lastSignature!==signature)) {
      result=await reload({preserveRange:true,canApply,equal:sameListDisplay});
    } else result=collection.patch(item=>mergeListClock(kind,item,byId.get(item.id)),{canApply,equal:sameListDisplay});
    if(result&&canApply()){lastKey=key;lastSignature=signature;}
    return result;
  }};
}
