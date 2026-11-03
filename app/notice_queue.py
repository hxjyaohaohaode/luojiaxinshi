"""Read-only personal inbox routing, derived from current facts and decisions."""
import json

from .notice_automation import profile_hash
from .proactive_policy import assess,preferences
from .proactive_feedback import apply as apply_feedback
from .notice_lifecycle import RETIRED_STATES


def annotate(conn, uid, records):
    saved_profile=conn.execute('SELECT profile FROM users WHERE id=?', (uid,)).fetchone()[0]
    profile = profile_hash(saved_profile);pref=preferences(saved_profile)
    notices = {r['id']: r for r in conn.execute('SELECT id,title,published_at,version,draft_version,status,draft FROM notices WHERE user_id=?', (uid,))}
    checks = {r['notice_id']: r for r in conn.execute('SELECT p.* FROM notice_profile_checks p JOIN notices n ON n.id=p.notice_id WHERE n.user_id=?', (uid,))}
    feedbacks={r['notice_id']:dict(r) for r in conn.execute('SELECT f.* FROM notice_recommendation_feedback f JOIN notices n ON n.id=f.notice_id AND n.user_id=f.user_id WHERE f.user_id=?',(uid,))}
    automation={}
    for row in conn.execute('SELECT notice_id,state FROM notice_automation_jobs WHERE user_id=? ORDER BY created_at,rowid',(uid,)):
        automation[row['notice_id']]=row['state']
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
        record['automation_state']=automation.get(nid,'')
        decision=assess(dict(notice),current_draft=bool(current and check and check['notice_version']==notice['version'] and not profile_changed),pref=pref)
        record['assessment']=decision
        record['tracking']=decision['tracking']
        record['recommended']=decision['recommended']
        # Never filter a new source version using an old model's applicability.
        if not current or profile_changed:record['applicability']=None
        elif record.get('applicability')=='not_matching' and decision['relevance']!='not_matching':record['applicability']='needs_review'
        tasks=grouped.get(nid,[]);active=[w for status,w in tasks if status=='pending']
        disposition=record.get('disposition','inbox')
        if disposition=='not_applicable':intent='irrelevant'
        elif disposition=='reference':intent='read'
        elif disposition=='closed':intent='closed'
        elif not tasks and record['automation_state'] in {'queued','running'} and nid not in reviewed and nid not in changes:intent='tracking'
        elif not tasks and decision['tracking']['state'] in RETIRED_STATES:intent='closed'
        elif record.get('pending_intake_updates') or nid in reviewed or nid in changes or profile_changed:intent='verify'
        elif active:
            if any(w.get('execution_mode')=='decision' or w.get('action_kind')=='optional' and w.get('participation','undecided')=='undecided' for w in active):intent='decide'
            elif any(w.get('stage') not in {'submitted','waiting'} and w.get('execution_mode') not in {'reading','waiting'} for w in active):intent='act'
            elif any(w.get('stage') in {'submitted','waiting'} or w.get('execution_mode')=='waiting' for w in active):intent='followup'
            else:intent='read'
        elif tasks and all(status=='done' for status,_ in tasks):intent='closed'
        elif decision['tracking']['state'] in RETIRED_STATES:intent='closed'
        elif decision['relevance']=='not_matching':intent='irrelevant'
        elif record.get('applicability')=='not_matching':intent='verify'
        elif record['automation_state'] in {'queued','running'}:intent='tracking'
        elif current and decision['quality'] not in {'passed','unverified'}:intent='verify'
        elif not current or record.get('applicability')!='matches_known':intent='verify'
        else:
            draft=json.loads(notice['draft'] or '{}')
            intent='decide' if any(t.get('scope','personal')=='personal' for t in draft.get('tasks',[])) else 'read'
        record['intent']=intent
        if intent in {'closed','irrelevant'}:record['recommended']=False
        # Revisions to already chosen tasks need attention even if the old
        # opportunity elapsed or old applicability was negative.
        if tasks and disposition=='inbox' and intent in {'verify','act','decide','followup'}:record['recommended']=True
        feedback=feedbacks.get(nid,{'mode':'auto','version':0,'note':'','notice_version':None})
        record['feedback']=feedback
        if feedback['mode']!='auto':
            decision=apply_feedback(decision,feedback)
            record['assessment']=decision;record['recommended']=decision['recommended']
            if feedback['mode']=='include' and record['intent'] in {'closed','irrelevant'}:record['intent']='decide'
    return records
