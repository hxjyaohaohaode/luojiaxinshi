import {taskMatchesFilter} from './workflow.js';

export function taskLane(task) {
  if(task.status!=='pending'||task.action_excluded)return 'closed';
  return task.workflow?.data.board_lane || (taskMatchesFilter(task,'followup')?'followup':'action');
}

export function taskLanes(tasks) {
  const lanes = [
    {key: 'action', title: '接着推进', description: '准备、核对与本人办理', tasks: []},
    {key: 'followup', title: '留意反馈', description: '提交之后，继续跟进', tasks: []},
    {key: 'closed', title: '已收尾', description: '已完成、取消或不参加', tasks: []},
  ];
  for (const task of tasks) {
    lanes.find(lane=>lane.key===taskLane(task)).tasks.push(task);
  }
  for(const lane of lanes)lane.tasks.sort((a,b)=>(a.workflow?.data.board_order??Infinity)-(b.workflow?.data.board_order??Infinity));
  return lanes;
}

export function taskBoardMarkup(tasks, taskRow, icon) {
  const lanes = taskLanes(tasks);
  return `<p class="task-board-hint" id="task-board-help">靠上优先 · 按住卡片右上角移动</p><nav class="task-board-lanes" aria-label="看板进度">${lanes.map((lane,i)=>`<button type="button" data-board-jump="${lane.key}" aria-current="${i===0?'true':'false'}">${lane.title}<span>${lane.tasks.length}</span></button>`).join('')}</nav><div class="task-board-scroll"><div class="task-board" data-lanes="${lanes.length}">${lanes.map(lane => `<section class="task-board-column lane-${lane.key}" data-task-lane="${lane.key}" aria-label="${lane.title}">
    <header class="task-lane-heading"><span class="lane-dot" aria-hidden="true"></span><h2>${lane.title}</h2><span>${lane.tasks.length}</span></header>
    <div class="task-lane-items">${lane.tasks.map(task=>taskRow(task,true)).join('')}<div class="lane-empty" aria-label="${lane.title}暂无事项" ${lane.tasks.length?'hidden':''}>${icon(lane.key === 'closed' ? 'check' : 'tasks')}<span>${lane.key==='closed'?'拖到这里标记完成':'拖到这里'}</span></div></div>
  </section>`).join('')}</div></div>`;
}
