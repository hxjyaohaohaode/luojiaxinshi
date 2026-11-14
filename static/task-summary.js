import {currentHandlingStep} from './handling-route.js';

export function taskRowSummary(task) {
  const data = task.data, workflow = task.workflow?.data || {}, next = currentHandlingStep(task);
  const labels = {changes: '变更待核对', prerequisites: '前提待核对', blocked: '办理受阻', followup: '待跟进', materials: workflow.stage === 'supplement' ? '待补件' : '准备材料', start: '待办理'};
  const state = task.status === 'done' ? '已完成个人办理' : task.status === 'cancelled' ? '已取消' : task.action_excluded ? '已选择不参加' :
    next.kind === 'choice' ? '待决定是否参加' : next.kind === 'receipt' ? ({submitted: '已提交，待反馈', accepted: '已记录受理', rejected: '已记录未通过', waiting: '等待结果'}[workflow.stage] || '待反馈') : labels[next.kind] || '待办理';
  let time = '时间尚未明确', unverified = false;
  if (next.kind === 'followup' && workflow.followup_at) {
    time = '跟进 ' + new Date(workflow.followup_at).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false});
  } else if (data.due_date) {
    unverified = !data.deadline_confirmed;
    time = '截止 ' + data.due_date + (data.due_time ? ' ' + data.due_time : '') + (unverified ? '（待核实）' : task.overdue ? ' · 期限已过' : '');
  } else if (data.scheduled) {
    const slot = data.scheduled; unverified = !slot.confirmed;
    time = (slot.kind === 'window' ? '办理时段 ' : '活动 ') + slot.start_date + (slot.start_time ? ' ' + slot.start_time : '') + (unverified ? '（待核实）' : '');
  } else if (data.planned_at) time = '个人计划 ' + new Date(data.planned_at).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false});
  const warnings = [
    task.pending_changes?.length ? `${task.pending_changes.length} 条通知变动待核对` : '',
    task.change_review?.state === 'pending' ? '当前要求受变更影响，需本人核对' : '',
    task.workflow?.blocked ? '前置步骤尚未完成' : '',
    ...(task.execution_issues || []).map(issue => issue.label),
    task.needs_calendar_sync ? '已导出的手机日历需手动同步' : task.calendar_check_required ? '尚未确认手机日历导入' : '',
    unverified ? '原文时间仍需核实，不能当作已确认期限' : '',
  ].filter(Boolean);
  return {state, time, next: next.kind === 'closed' ? '查看办理记录' : next.label, warnings: [...new Set(warnings)], unverified,
    opensHandling: task.status === 'pending' && workflow.execution_mode === 'submission' && ['preparing', 'supplement', 'blocked'].includes(workflow.stage)};
}
