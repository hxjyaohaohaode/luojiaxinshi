// Only server receipts may announce memory changes, never model-authored prose.
export function memoryUseCount(message={}){
  const ids=new Set();
  const operations=message.grounding?.memory_operations,sources=message.evidence_sources;
  for(const operation of Array.isArray(operations)?operations:[])if(operation?.status==='used'&&operation.id)ids.add(String(operation.id).replace(/^(?:memo|memory)-/,''));
  const cited=new Set((Array.isArray(message.citations)?message.citations:[]).map(c=>c?.source_id).filter(Boolean));
  for(const source of Array.isArray(sources)?sources:[])if(source?.evidence_kind==='memory'&&cited.has(source.id))ids.add(String(source.memory_id||source.id).replace(/^(?:memo|memory)-/,''));
  return ids.size;
}
export function memoryOperationSummary(operations=[]){
  const labels={accepted:'条记忆已保存',updated:'条记忆已更新',archived:'条记忆已停用',pending:'条记忆等你核对',rejected:'条记忆建议未保存',forgotten_blocked:'条已遗忘内容未重新保存',session_saved:'条条件仅保留在本会话',checkpointed:'次工作记忆已更新',forgotten:'条记忆已遗忘',all_forgotten:'次记忆已全部清空',used:'条记忆被 Agent 报告采用'};
  const counts=new Map();
  for(const item of Array.isArray(operations)?operations:[]){
    if(!item||!Object.hasOwn(labels,item.status))continue;
    counts.set(item.status,(counts.get(item.status)||0)+1);
  }
  return [...counts].map(([status,count])=>`${count} ${labels[status]}`).join('；');
}
