// Branching is a local reading state until the user submits new content.
export function branchPreview(conversation,messageId,owner){
  const index=conversation.messages.findIndex(m=>m.id===messageId);
  if(index<0||conversation.messages[index].role!=='assistant'||conversation.messages[index].status!=='complete'||conversation.processing)throw Error('请先选择一条完整回复，再从这里继续。');
  const preview=structuredClone(conversation);
  preview.messages=preview.messages.slice(0,index+1);preview.title=preview.title.slice(0,90)+' · 分支';preview.processing=false;
  return {owner,originId:conversation.id,messageId,version:conversation.version,requestId:crypto.randomUUID(),preview};
}
