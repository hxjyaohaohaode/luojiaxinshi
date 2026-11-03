"""One current handling interpretation for the page, Agent and verifier.

    This projection describes saved facts only. It grants no write permission and
    makes no claim that a school portal accepted a submission.
"""


def current_step(task):
    progress = (task.get('workflow') or {}).get('data') or {}
    data = task.get('data') or {}
    def step(kind, label, detail):
        return {'kind': kind, 'label': label, 'detail': detail}
    if task.get('status') == 'cancelled':
        return step('closed', '已取消', '保留此前的材料和办理记录。')
    if task.get('status') == 'done':
        return step('closed', '已完成个人办理', '可继续查看提交记录和实际反馈。')
    if task.get('pending_changes') or (task.get('change_review') or {}).get('state') == 'pending':
        return step('changes', '核对变动影响', '已有准备和记录保留，先查看哪些要求发生变化。')
    if progress.get('action_kind') == 'optional' and progress.get('participation') != 'joined':
        if progress.get('participation') == 'declined':
            return step('choice', '已选择不参加', '保留原通知，可按实际情况重新选择是否参加。')
        return step('choice', '先决定是否参加', '选择后再推进报名或提交，准备资料可以先做。')
    issues = task.get('execution_issues') or []
    if (task.get('workflow') or {}).get('blocked') or issues:
        return step('prerequisites', '处理这一步的前提',
                    '；'.join(item['label'] for item in issues) or '查看未完成的前置步骤；可先准备不依赖它们的材料。')
    stage = progress.get('stage')
    if stage == 'blocked':
        return step('blocked', '核对阻碍是否已经解除', progress.get('outcome') or '查看实际原因，按当前情况更新办理进度。')
    if task.get('followup_due') and progress.get('next_step'):
        return step('followup', '到时间跟进了', progress['next_step'])
    if stage in {'submitted', 'accepted', 'waiting'}:
        return step('receipt', '跟进实际反馈', progress.get('next_step') or '保留提交凭证，等待或查询受理结果。')
    if stage == 'rejected':
        return step('receipt', '先核对未通过的反馈', progress.get('outcome') or '查看实际原因，再决定是否补充、重新办理或结束个人事项。')
    if stage == 'supplement':
        return step('materials', '按反馈补充材料', progress.get('outcome') or '补充实际要求的文件，再记录这次提交。')
    missing = [item for item in data.get('materials', []) if item not in progress.get('prepared_materials', [])]
    if missing:
        return step('materials', '先准备材料', '、'.join(missing))
    return step('start', '进入原渠道办理' if progress.get('execution_mode') == 'submission' else '开始这一步',
                data.get('submission') or data.get('details') or data.get('title') or '')
