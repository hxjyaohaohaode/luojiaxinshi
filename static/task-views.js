import {taskMatchesFilter} from './workflow.js';

// Group only the currently filtered records. No action is completed by moving a card.
export function taskLanes(tasks) {
  const lanes = [
    {key: 'action', title: '接着推进', description: '准备、核对与本人办理', tasks: []},
    {key: 'followup', title: '留意反馈', description: '提交之后，继续跟进', tasks: []},
    {key: 'closed', title: '已收尾', description: '已完成、取消或不参加', tasks: []},
  ];
  for (const task of tasks) {
    const lane = task.status !== 'pending' || task.action_excluded ? 2 : taskMatchesFilter(task, 'followup') ? 1 : 0;
    lanes[lane].tasks.push(task);
  }
  return lanes;
}

export function taskBoardMarkup(tasks, taskRow, icon) {
  const lanes = taskLanes(tasks).filter(lane => lane.tasks.length);
  return `<div class="task-board" data-lanes="${lanes.length}">${lanes.map(lane => `<section class="task-board-column lane-${lane.key}" aria-label="${lane.title}">
    <header class="task-lane-heading"><span class="lane-dot" aria-hidden="true"></span><h2>${lane.title}</h2><span>${lane.tasks.length}</span></header>
    <div class="task-lane-items">${lane.tasks.length ? lane.tasks.map(taskRow).join('') : `<div class="lane-empty" aria-label="${lane.title}暂无事项">${icon(lane.key === 'closed' ? 'check' : 'tasks')}<span>暂时没有这类事项</span></div>`}</div>
  </section>`).join('')}</div>`;
}
