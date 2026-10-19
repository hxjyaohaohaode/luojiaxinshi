// Calendar calculations use civil days and UTC arithmetic; never the device timezone.
export const dayKey=(value=new Date())=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
export const addDays=(day,n)=>new Date(Date.parse(day+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
export const dayDistance=(a,b)=>Math.round((Date.parse(b+'T00:00:00Z')-Date.parse(a+'T00:00:00Z'))/86400000);
export const weekStart=day=>addDays(day,-((new Date(day+'T00:00:00Z').getUTCDay()+6)%7));
export const sundayStart=day=>addDays(day,-new Date(day+'T00:00:00Z').getUTCDay());
export const monthDays=day=>Array.from({length:42},(_,i)=>addDays(weekStart(day.slice(0,7)+'-01'),i));
export function shiftMonth(day,n){const d=new Date(day+'T00:00:00Z'),wanted=d.getUTCDate();d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+n);const next=new Date(d);next.setUTCMonth(next.getUTCMonth()+1);next.setUTCDate(0);d.setUTCDate(Math.min(wanted,next.getUTCDate()));return d.toISOString().slice(0,10);}
export const minute=time=>time?Number(time.slice(0,2))*60+Number(time.slice(3,5)):0;
// Visual period starts transcribed from the user-supplied timetable screenshot.
// This scale never changes the stored start/end time of an arrangement.
export const PERIOD_TIMES=['08:00','08:50','09:50','10:40','11:30','14:05','14:55','15:45','16:40','17:30','18:30','19:20','20:10','21:00'];
export function periodPosition(value){const limits=[...PERIOD_TIMES.map(minute),22*60];if(value<=limits[0])return 0;if(value>=limits.at(-1))return 14;for(let i=0;i<14;i++)if(value<limits[i+1])return i+(value-limits[i])/(limits[i+1]-limits[i]);return 14;}
const localTime=value=>new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));

export function calendarEntries(arrangements,tasks,from,to,{showDone=false}={}){
  const entries=[];
  for(const record of arrangements){
    const d=record.data,interval=d.repeat==='biweekly'?14:d.repeat==='weekly'?7:0;
    const first=interval?Math.max(0,Math.ceil((dayDistance(d.start_date,from)-dayDistance(d.start_date,d.end_date))/interval)):0;
    const last=interval?(to<d.repeat_until?to:d.repeat_until):d.start_date;
    let start=addDays(d.start_date,first*interval);
    for(let safety=0;safety<54&&start<=last;safety++){
      const end=interval?addDays(start,dayDistance(d.start_date,d.end_date)):d.end_date;
      for(let day=start;day<=end;day=addDays(day,1))if(day>=from&&day<=to&&!(day===end&&day!==start&&d.end_time==='00:00')){
        entries.push({key:record.id+':'+day,id:record.id,source:'arrangement',kind:d.category,title:d.title,location:d.location,notes:d.notes,day,start:day===start?d.start_time:'00:00',end:day===end?d.end_time:'24:00',allDay:!d.start_time,continuesBefore:day>start,continuesAfter:day<end,recurring:!!interval,version:record.version});
      }
      if(!interval)break;
      start=addDays(start,interval);
    }
  }
  for(const task of tasks){
    if(task.status==='cancelled'||(task.action_excluded&&task.status==='pending')||(!showDone&&task.status==='done')||task.data.scope!=='personal')continue;
    const d=task.data,base={id:task.id,source:'task',title:d.title,location:d.location,notes:d.details,done:task.status==='done',version:task.version};
    if(d.due_date&&d.due_date>=from&&d.due_date<=to)entries.push({...base,key:task.id+':due',kind:'deadline',day:d.due_date,start:d.due_time,end:null,allDay:!d.due_time,verified:d.deadline_confirmed});
    if(d.planned_at){const day=dayKey(d.planned_at),start=localTime(d.planned_at);if(day>=from&&day<=to)entries.push({...base,key:task.id+':plan',kind:'plan',day,start,end:null,allDay:false,verified:true});}
  }
  return entries.sort((a,b)=>a.day.localeCompare(b.day)||Number(b.allDay)-Number(a.allDay)||(a.start||'').localeCompare(b.start||'')||a.title.localeCompare(b.title));
}

// Overlapping events receive distinct columns; interval boundaries that touch do not overlap.
export function layoutTimed(entries){
  const sorted=entries.filter(e=>!e.allDay).map(e=>({...e,begin:minute(e.start),finish:Math.min(1440,Math.max(minute(e.start)+20,e.end?minute(e.end):minute(e.start)+30))})).sort((a,b)=>a.begin-b.begin||a.finish-b.finish);
  let group=[],groupEnd=-1;
  const result=[];
  function flush(){const ends=[],cluster=result.length;for(const event of group){let lane=ends.findIndex(end=>end<=event.begin);if(lane<0)lane=ends.length;ends[lane]=event.finish;event.lane=lane;}for(const event of group)result.push({...event,lanes:ends.length,cluster,clusterSize:group.length});group=[];}
  for(const event of sorted){if(group.length&&event.begin>=groupEnd){flush();groupEnd=-1;}group.push(event);groupEnd=Math.max(groupEnd,event.finish);}flush();return result;
}
