"""Read-only personal inbox routing, derived from current facts and decisions."""
import json

from .notice_automation import profile_hash


def annotate(conn, uid, records):
    profile = profile_hash(conn.execute('SELECT profile FROM users WHERE id=?', (uid,)).fetchone()[0])
    notices = {r['id']: r for r in conn.execute('SELECT id,version,draft_version,status,draft FROM notices WHERE user_id=?', (uid,))}
    checks = {r['notice_id']: r for r in conn.execute('SELECT p.* FROM notice_profile_checks p JOIN notices n ON n.id=p.notice_id WHERE n.user_id=?', (uid,))}
    reviewed = {r[0] for r in conn.execute("SELECT DISTINCT t.notice_id FROM task_reviews r JOIN tasks t ON t.id=r.task_id WHERE t.user_id=? AND r.state='pending'", (uid,))}
    changes = {r[0] for r in conn.execute("SELECT DISTINCT notice_id FROM notice_changes WHERE user_id=? AND state='pending'", (uid,))}
    grouped = {}
    for row in conn.execute('SELECT t.notice_id,t.status,t.data,w.data AS workflow FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=?', (uid,)):
        data = json.loads(row['data']);workflow = json.loads(row['workflow'] or '{}')
        if data.get('scope') != 'personal' or row['status'] == 'cancelled' or workflow.get('participation') == 'declined':
            continue
        grouped.setdefault(row['notice_id'], []).append((row['status'], workflow))
    for record in records:
        nid=record['id'];notice=notices[nid];check=checks.get(nid)
        current = notice['status'] in {'draft','confirmed'} and notice['draft_version']==notice['version']
        profile_changed = bool(check and check['profile_hash']!=profile)
        record['needs_profile_review']=profile_changed
        # Never filter a new source version using an old model's applicability.
        if not current or profile_changed:record['applicability']=None
        tasks=grouped.get(nid,[]);active=[w for status,w in tasks if status=='pending']
        disposition=record.get('disposition','inbox')
        if disposition=='not_applicable':intent='irrelevant'
        elif disposition=='reference':intent='read'
        elif disposition=='closed':intent='closed'
        elif record.get('pending_intake_updates') or nid in reviewed or nid in changes or profile_changed:intent='verify'
        elif active:
            if any(w.get('execution_mode')=='decision' or w.get('action_kind')=='optional' and w.get('participation','undecided')=='undecided' for w in active):intent='decide'
            elif any(w.get('stage') not in {'submitted','waiting'} and w.get('execution_mode') not in {'reading','waiting'} for w in active):intent='act'
            elif any(w.get('stage') in {'submitted','waiting'} or w.get('execution_mode')=='waiting' for w in active):intent='followup'
            else:intent='read'
        elif tasks and all(status=='done' for status,_ in tasks):intent='closed'
        elif record.get('applicability')=='not_matching':intent='irrelevant'
        elif not current or record.get('applicability')!='matches_known':intent='verify'
        else:
            draft=json.loads(notice['draft'] or '{}')
            intent='act' if any(t.get('scope','personal')=='personal' for t in draft.get('tasks',[])) else 'read'
        record['intent']=intent
    return records
