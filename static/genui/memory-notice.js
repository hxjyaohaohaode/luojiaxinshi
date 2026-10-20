// Only server receipts may announce memory changes, never model-authored prose.
export function memoryOperationSummary(operations=[]){
  const labels={accepted:'条记忆已保存',updated:'条记忆已更新',archived:'条记忆已停用',pending:'条记忆等你核对',rejected:'条记忆建议未保存',forgotten_blocked:'条已遗忘内容未重新保存'};
  const counts=new Map();
  for(const item of Array.isArray(operations)?operations:[]){
    if(!item||!Object.hasOwn(labels,item.status))continue;
    counts.set(item.status,(counts.get(item.status)||0)+1);
  }
  return [...counts].map(([status,count])=>`${count} ${labels[status]}`).join('；');
}
