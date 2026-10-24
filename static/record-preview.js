// Only application records are translated; uploaded source documents stay verbatim.
const recordKinds=new Set(['task','arrangement','profile','memory','execution']);
const labels={title:'事项',details:'说明',due_date:'正式期限',due_time:'截止时刻',deadline_text:'期限说明',start_date:'日期',end_date:'结束日期',start_time:'开始',end_time:'结束',location:'地点',submission:'提交至',materials:'材料',next_step:'下一步',content:'内容',notes:'备注',preferred_name:'称呼',school:'学校',college:'学院',major:'专业',level:'培养层次 / 职务',grade:'年级',semester:'学期',semester_start:'开学日期',campus_area:'校区',goals:'近期目标',interests:'关注方向',available_time:'可用时间',student_id:'学号',employee_id:'工号',phone:'联系电话',wechat:'微信',qq:'QQ',scope_name:'所属范围',topic:'专题'};
const enums={status:['状态',{pending:'待完成',done:'已完成',cancelled:'已取消',succeeded:'已完成',committed:'已保存',success:'已完成',failed:'未完成',undone:'已撤销'}],campus_role:['校园身份',{student:'学生',teacher:'教师',staff:'教职工',other:'其他'}],response_detail:['回答篇幅',{concise:'简洁',balanced:'适中',detailed:'详细'}],response_style:['回答风格',{warm:'温和自然',direct:'直接清楚',academic:'严谨规范'}]};
const stages={preparing:'准备中',submitted:'已提交',blocked:'卡住了',active:'进行中',waiting:'等待中',recorded:'已记录'};
const outcomes={accepted:'已受理',rejected:'未通过',supplement:'待补件',unknown:'尚无结果',pending:'等待结果',none:'尚无结果'};
const textValue=value=>Array.isArray(value)?value.filter(v=>typeof v==='string'||typeof v==='number').join('、'):['string','number'].includes(typeof value)?String(value):'';
export function recordPreviewKind(text,kind){
  if(recordKinds.has(kind))return kind;
  // Older saved application snapshots can be carried as conversation materials.
  // The application-specific marker is required so arbitrary JSON files remain intact.
  try{const value=JSON.parse(text);if(value?.values&&typeof value.values==='object'&&!Array.isArray(value.values)&&typeof value.record_type==='string'){
    if(value.record_type.startsWith('用户确认的待办记录'))return 'task';
    if(value.record_type==='用户安排，属于计划而非正式期限')return 'arrangement';
  }}catch{}
  return null;
}
export function readableSnapshot(text,kind,{multiline=false}={}){
  if(!recordPreviewKind(text,kind))return text;
  let record;try{record=JSON.parse(text);}catch{return /^\s*[\[{]/.test(text)||/"[a-z_]+"\s*:/.test(text)?'这段记录摘录不完整，请打开对应记录查看。':text;}
  if(!record||typeof record!=='object'||Array.isArray(record))return '这段记录摘录不完整，请打开对应记录查看。';
  const values=record.values||record.data||record.record?.data||record.record||record,parts=[];
  const append=(label,value)=>{const readable=textValue(value);if(readable)parts.push(`${label}：${readable}`);};
  for(const [key,label]of Object.entries(labels))append(label,values[key]??record[key]);
  for(const [key,[label,choices]]of Object.entries(enums)){const value=values[key]??record[key];if(value!=null&&value!=='')append(label,choices[value]||'待确认');}
  if(values.deadline_confirmed===false)parts.push('期限待核实');
  const scheduled=values.scheduled;
  if(scheduled&&typeof scheduled==='object'){
    append('活动开始',[scheduled.start_date,scheduled.start_time].filter(Boolean).join(' '));
    append('活动结束',[scheduled.end_date,scheduled.end_time].filter(Boolean).join(' '));
    append('活动地点',scheduled.location);if(scheduled.confirmed===false)parts.push('活动时间待核实');
  }
  const workflow=record.workflow?.data||record.workflow;
  if(workflow&&typeof workflow==='object'){
    append('办理进度',stages[workflow.stage]);append('办理结果',outcomes[workflow.outcome]);
    append('提交凭证',workflow.receipt);append('下一步',workflow.next_step);
    for(const step of workflow.milestones||[])if(step&&typeof step==='object')append(step.done?'已完成步骤':'待办步骤',step.title||step.label);
  }
  for(const key of ['execution_warning','pending_change_warning','completion_warning','workflow_authority'])append('核对提示',record[key]);
  return parts.join(multiline?'\n':' · ')||'这条记录没有可展示的摘要，请打开对应记录查看。';
}
