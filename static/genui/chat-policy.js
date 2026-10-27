// One policy for rendering controls and checking clicks after asynchronous updates.
export function replyPolicy(messages,message,{busy=false,readOnly=false,speech=true}={}){
  const complete=message?.role==='assistant'&&message.status==='complete';
  const content=!!(message?.content?.trim()||message?.genui?.raw?.trim());
  const idle=!busy&&!messages.some(item=>item.status==='processing');
  const lastUser=messages.findLast(item=>item.role==='user');
  const lastAssistant=messages.findLast(item=>item.role==='assistant');
  const lastTurn=!!lastUser&&message?.parent_id===lastUser.id;
  const writable=idle&&!readOnly;
  return {
    copy:complete&&content,
    speak:complete&&content&&speech,
    like:complete&&!readOnly,dislike:complete&&!readOnly,
    share:complete&&content&&!readOnly,
    branch:complete&&writable,
    regenerate:complete&&lastTurn&&writable,
    retry:['failed','cancelled'].includes(message?.status)&&lastTurn&&message?.id===lastAssistant?.id&&message?.id===(message?.versions?.at(-1)?.id||lastAssistant?.id)&&writable,
    version:!!message?.versions?.length&&writable,
    save:complete&&!!message?.genui?.validated&&writable,
  };
}

export const TIME_GROUP_SECONDS=5*60;
const dayKey=date=>[date.getFullYear(),date.getMonth(),date.getDate()].join('-');
export function timeGroups(messages,now=new Date()){
  const groups=new Map();let previous=null;
  for(const message of messages){
    // Model latency and selecting a revision do not create a new sent turn.
    if(message.role!=='user'&&previous!==null)continue;
    const at=Number(message.created_at);if(!Number.isFinite(at)||at<=0)continue;
    const date=new Date(at*1000);if(!Number.isFinite(date.getTime()))continue;
    if(previous===null||dayKey(date)!==dayKey(previous)||at-previous.getTime()/1000>=TIME_GROUP_SECONDS){
      const yesterday=new Date(now);yesterday.setDate(now.getDate()-1);
      const prefix=dayKey(date)===dayKey(now)?'':dayKey(date)===dayKey(yesterday)?'昨天 ':date.getFullYear()===now.getFullYear()?`${date.getMonth()+1}月${date.getDate()}日 `:`${date.getFullYear()}年${date.getMonth()+1}月${date.getDate()}日 `;
      groups.set(message.id,{at,label:prefix+date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})});
    }
    previous=date;
  }
  return groups;
}
