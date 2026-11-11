"""Committed revisions for selective workspace refresh.

Triggers cover both HTTP writes and background workers. A rollback rolls back
its revision too, and reads never scan notice, task or audit history.
"""
import hashlib
import time

from fastapi import Depends, Request
from fastapi.responses import JSONResponse,Response

from .db import dumps


OWNED = {
    'users': ('account', 'id'),
    'verified_contacts': ('account', 'user_id'),
    'account_consents': ('account', 'user_id'),
    'genui_preferences': ('account', 'user_id'),
    'campus_members': ('account', 'user_id'),
    'campus_counselor_scopes': ('account', 'user_id'),
    'notices': ('notices', 'user_id'),
    'notice_ingest_receipts': ('notices', 'user_id'),
    'notice_recommendation_feedback': ('notices', 'user_id'),
    'notice_matters': ('notices', 'user_id'),
    'notice_relation_dismissals': ('notices','user_id'),
    'tasks': ('tasks', 'user_id'),
    'notice_changes': ('tasks', 'user_id'),
    'task_materials': ('tasks', 'user_id'),
    'task_submission_records': ('tasks', 'user_id'),
    'arrangements': ('calendar', 'user_id'),
    'reminder_states': ('reminders', 'user_id'),
    'source_subscriptions': ('sources', 'user_id'),
    'source_catalog': ('sources', 'user_id'),
    'publisher_subscriptions': ('sources','user_id'),
    'qq_group_subscriptions': ('sources','user_id'),
    'qq_group_intake_settings': ('sources','user_id'),
    'qq_group_deliveries': ('sources','user_id'),
    'notice_automation_settings': ('sources', 'user_id'),
    'notice_automation_jobs': ('sources', 'user_id'),
    'external_bindings': ('sources', 'user_id'),
    'push_devices': ('delivery', 'user_id'),
    'mail_preferences': ('delivery', 'user_id'),
    'mail_outbox': ('delivery','user_id'),
    'push_outbox': ('delivery','user_id'),
    'conversations': ('chat', 'user_id'),
    'personal_memories': ('memory', 'user_id'),
    'memory_projects': ('memory', 'user_id'),
    'memory_settings': ('memory', 'user_id'),
    'memory_lifecycle_settings': ('memory','user_id'),
    'memory_nodes': ('memory','user_id'),
    'memory_session_items': ('memory','user_id'),
}

# The parent is also versioned on deletion. A cascade whose parent has already
# disappeared need not publish a second signal.
RELATED = {
    'sources': ('notices', 'notices', 'notice_id'),
    'notice_ingest_updates': ('notices', 'notices', 'notice_id'),
    'notice_dispositions': ('notices', 'notices', 'notice_id'),
    'notice_matter_members': ('notices', 'notices', 'notice_id'),
    'notice_delivery_suppressions': ('notices','notices','notice_id'),
    'notice_profile_checks': ('notices', 'notices', 'notice_id'),
    'task_workflows': ('tasks', 'tasks', 'task_id'),
    'task_reviews': ('tasks', 'tasks', 'task_id'),
    'calendar_checks': ('tasks', 'tasks', 'task_id'),
    'conversation_sources': ('chat', 'conversations', 'conversation_id'),
    'conversation_messages': ('chat', 'conversations', 'conversation_id'),
}

MESSAGE_DOMAINS={'reply_selection':'parent_id','reply_reactions':'message_id','message_emojis':'message_id',
                 'genui_messages':'message_id'}


def bump_sql(subject, domain):
    return f"""INSERT INTO workspace_revisions(subject,domain,revision)
        SELECT subject,'{domain}',1 FROM ({subject}) WHERE subject IS NOT NULL
        ON CONFLICT(subject,domain) DO UPDATE SET revision=revision+1;"""


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS workspace_revisions(
        subject TEXT NOT NULL, domain TEXT NOT NULL, revision INTEGER NOT NULL,
        PRIMARY KEY(subject,domain)) WITHOUT ROWID""")
    statements = []
    for table in sorted(OWNED.keys() | RELATED.keys() | MESSAGE_DOMAINS.keys() |
                        {'campus_publications','campus_audit','campus_deliveries','collaboration_cases','collaboration_files'}):
        for action, ref in (('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')):
            # A deleted account's children cascade before its cleanup trigger.
            if table == 'users' and action == 'DELETE':
                continue
            body = []
            if table in OWNED:
                domain, column = OWNED[table]
                body.append(bump_sql(f"SELECT 'user:'||{ref}.{column} AS subject", domain))
            if table in RELATED:
                domain, parent, fk = RELATED[table]
                body.append(bump_sql(f"SELECT 'user:'||user_id AS subject FROM {parent} WHERE id={ref}.{fk}", domain))
            if table in MESSAGE_DOMAINS:
                column=MESSAGE_DOMAINS[table]
                body.append(bump_sql(f"""SELECT 'user:'||c.user_id AS subject FROM conversation_messages m
                    JOIN conversations c ON c.id=m.conversation_id WHERE m.id={ref}.{column}""",'chat'))
            if table == 'collaboration_cases':
                for column in ('sender_id','recipient_id'):
                    body.append(bump_sql(f"SELECT 'user:'||{ref}.{column} AS subject", 'collaboration'))
            if table == 'collaboration_files':
                for column in ('sender_id','recipient_id'):
                    body.append(bump_sql(f"SELECT 'user:'||{column} AS subject FROM collaboration_cases WHERE id={ref}.case_id", 'collaboration'))
            if table in {'campus_members','campus_counselor_scopes'}:
                body.append(bump_sql(f"""SELECT 'user:'||sender_id AS subject FROM collaboration_cases WHERE recipient_id={ref}.user_id
                    UNION SELECT 'user:'||recipient_id FROM collaboration_cases WHERE sender_id={ref}.user_id""", 'collaboration'))
            if table in {'campus_members', 'campus_publications', 'campus_audit'}:
                body.append(bump_sql(f"SELECT 'college:'||{ref}.college_id AS subject", 'campus'))
                if action == 'UPDATE':
                    body.append(bump_sql(f"SELECT 'college:'||OLD.college_id AS subject WHERE OLD.college_id<>NEW.college_id", 'campus'))
                body.append(bump_sql("SELECT 'system' AS subject", 'campus'))
            if table=='campus_deliveries':
                body.append(bump_sql(f"""SELECT 'college:'||college_id AS subject FROM campus_publications
                    WHERE id={ref}.publication_id""",'campus'))
            when=action
            if action=='UPDATE' and table=='genui_messages':
                when='UPDATE OF snapshot_version'
            elif action=='UPDATE' and table in {'mail_outbox','push_outbox'}:
                when='UPDATE OF state'
            statements.append(f"CREATE TRIGGER IF NOT EXISTS workspace_rev_{table}_{action.lower()} "
                              f"AFTER {when} ON {table} BEGIN {''.join(body)} END;")
    statements.append("""CREATE TRIGGER IF NOT EXISTS workspace_rev_users_cleanup AFTER DELETE ON users
        BEGIN DELETE FROM workspace_revisions WHERE subject='user:'||OLD.id; END;""")
    conn.executescript('BEGIN IMMEDIATE;' + '\n'.join(statements) + 'COMMIT;')


def revisions(conn, current, now):
    uid = current['id']
    domains = {r['domain']: r['revision'] for r in conn.execute(
        'SELECT domain,revision FROM workspace_revisions WHERE subject=?', ('user:'+uid,))}
    if current['role'] == 'admin':
        scope = 'system'
    else:
        member = conn.execute("""SELECT college_id FROM campus_members
            WHERE user_id=? AND role IN ('college_admin','counselor')""", (uid,)).fetchone()
        scope = 'college:' + member['college_id'] if member else None
    if scope:
        row = conn.execute("SELECT revision FROM workspace_revisions WHERE subject=? AND domain='campus'", (scope,)).fetchone()
        # The scope is part of the value, even when two colleges have the same revision.
        domains['campus'] = scope + ':' + str(row[0] if row else 0)
    domains['clock'] = now // 60
    return domains


def snapshot(conn,current):
    domains = revisions(conn,current,int(time.time()))
    revision = hashlib.sha256(dumps([current['id'], domains]).encode()).hexdigest()
    return {'revision':revision,'domains':domains}


def projection(conn,request,current,name,keys,read):
    conn.execute('BEGIN')
    values=revisions(conn,current,int(time.time()))
    identity=[name,current['id'],[values.get(key,0) for key in keys]]
    tag='"'+hashlib.sha256(dumps(identity).encode()).hexdigest()+'"'
    headers={'ETag':tag}
    if request.headers.get('if-none-match')==tag:
        return Response(status_code=304,headers=headers)
    return JSONResponse(read(),headers=headers)


def install(app, db, user):
    @app.get('/api/proactive/revision')
    def revision(request:Request,current=Depends(user)):
        with db.connect() as conn:
            conn.execute('BEGIN')
            value = snapshot(conn,current)
        result = {'revision':value['revision'], 'poll_after_seconds':15, 'temporal_precision_seconds':60}
        if request.headers.get('x-workspace-revision') == '1':
            result.update(domains=value['domains'],poll_after_seconds=3)
        return result
