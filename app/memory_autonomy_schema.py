"""Automatic selection preferences and single-flight, user-directed AI edits."""
TABLES={'memory_selection_modes','memory_assist_jobs','memory_resource_sources','memory_resource_versions','memory_message_selection'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS memory_selection_modes(
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 mode TEXT NOT NULL CHECK(mode IN ('auto','manual')));
INSERT OR IGNORE INTO memory_selection_modes SELECT conversation_id,'manual' FROM conversation_context;
CREATE TABLE IF NOT EXISTS memory_message_selection(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,mode TEXT NOT NULL);
INSERT OR IGNORE INTO memory_message_selection SELECT m.id,coalesce(s.mode,'manual') FROM conversation_messages m
 LEFT JOIN memory_selection_modes s ON s.conversation_id=m.conversation_id WHERE m.role='user';
CREATE TRIGGER IF NOT EXISTS memory_message_selection_insert AFTER INSERT ON conversation_messages WHEN NEW.role='user' BEGIN
 INSERT OR IGNORE INTO memory_message_selection VALUES(NEW.id,coalesce((SELECT mode FROM memory_selection_modes WHERE conversation_id=NEW.conversation_id),'auto'));
END;
CREATE TABLE IF NOT EXISTS memory_assist_jobs(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 memory_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,expected_version INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('running','done','failed','cancelled')),
 result_version INTEGER,error_code TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,finished_at INTEGER,
 UNIQUE(user_id,request_id));
CREATE INDEX IF NOT EXISTS memory_assist_owner ON memory_assist_jobs(user_id,created_at);
CREATE TABLE IF NOT EXISTS memory_resource_sources(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,fingerprint TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS memory_resource_locator ON memory_resource_sources(source_kind,source_id);
CREATE TABLE IF NOT EXISTS memory_resource_versions(
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(source_kind,source_id));
UPDATE meta SET value='5' WHERE key='memory_engine_schema_version';
"""

# Coalesce changes while retaining durable work across process restarts. Readers
# verify the fingerprint immediately, even before the worker gets to this job.
for table,kind,owner in (
    ('sources','resource_notice','SELECT user_id FROM notices WHERE id=NEW.notice_id'),
    ('conversation_sources','resource_material','SELECT user_id FROM conversations WHERE id=NEW.conversation_id'),
    ('memory_projects','resource_project','SELECT NEW.user_id'),
):
    queue=f"""INSERT INTO memory_resource_versions VALUES('{kind}',NEW.id,1)
      ON CONFLICT(source_kind,source_id) DO UPDATE SET version=version+1;
      INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
      VALUES('resource:{kind}:'||NEW.id,({owner}),'{kind}',NEW.id,unixepoch())
      ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL,created_at=excluded.created_at;"""
    for event in ('INSERT','UPDATE'):
        SCHEMA+=f'CREATE TRIGGER IF NOT EXISTS memory_resource_{table}_{event.lower()} AFTER {event} ON {table} BEGIN {queue} END;\n'
    SCHEMA+=f"""CREATE TRIGGER IF NOT EXISTS memory_resource_{table}_delete BEFORE DELETE ON {table} BEGIN
      DELETE FROM personal_memories WHERE id IN (SELECT memory_id FROM memory_resource_sources WHERE source_kind='{kind}' AND source_id=OLD.id);
      DELETE FROM memory_jobs WHERE source_kind='{kind}' AND source_id=OLD.id;
      DELETE FROM memory_resource_versions WHERE source_kind='{kind}' AND source_id=OLD.id;
    END;\n"""
    SCHEMA+=f"INSERT OR IGNORE INTO memory_resource_versions SELECT '{kind}',id,1 FROM {table};\n"

SCHEMA+="""
INSERT OR IGNORE INTO memory_resource_versions SELECT 'resource_task',id,
 CASE WHEN EXISTS(SELECT 1 FROM task_workflows w WHERE w.task_id=tasks.id) THEN 1 ELSE 0 END FROM tasks;
INSERT OR IGNORE INTO memory_resource_sources
 SELECT e.memory_id,'resource_task',e.source_id,'0' FROM memory_evidence e WHERE e.source_kind='task';
INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'workflow:'||t.id,t.user_id,'task',t.id,unixepoch() FROM tasks t JOIN task_workflows w ON w.task_id=t.id;
CREATE TRIGGER IF NOT EXISTS memory_task_resource_insert AFTER INSERT ON tasks BEGIN
 INSERT OR IGNORE INTO memory_resource_versions VALUES('resource_task',NEW.id,0);
END;
CREATE TRIGGER IF NOT EXISTS memory_task_resource_delete AFTER DELETE ON tasks BEGIN
 DELETE FROM memory_resource_versions WHERE source_kind='resource_task' AND source_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_resource_full_sections AFTER UPDATE OF full_sections ON material_library BEGIN
 UPDATE memory_resource_versions SET version=version+1 WHERE source_kind='resource_material' AND source_id=NEW.source_id;
 INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:resource_material:'||s.id,c.user_id,'resource_material',s.id,unixepoch()
 FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE s.id=NEW.source_id
 ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL,created_at=excluded.created_at;
END;
CREATE TRIGGER IF NOT EXISTS memory_resource_full_insert AFTER INSERT ON material_library BEGIN
 UPDATE memory_resource_versions SET version=version+1 WHERE source_kind='resource_material' AND source_id=NEW.source_id;
 INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:resource_material:'||s.id,c.user_id,'resource_material',s.id,unixepoch()
 FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE s.id=NEW.source_id
 ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL,created_at=excluded.created_at;
END;
CREATE TRIGGER IF NOT EXISTS memory_resource_full_delete AFTER DELETE ON material_library BEGIN
 UPDATE memory_resource_versions SET version=version+1 WHERE source_kind='resource_material' AND source_id=OLD.source_id;
 INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:resource_material:'||s.id,c.user_id,'resource_material',s.id,unixepoch()
 FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE s.id=OLD.source_id
 ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL,created_at=excluded.created_at;
END;
INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:resource_notice:'||s.id,n.user_id,'resource_notice',s.id,unixepoch() FROM sources s JOIN notices n ON n.id=s.notice_id;
INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:resource_material:'||s.id,c.user_id,'resource_material',s.id,unixepoch() FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id;
INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:resource_project:'||id,user_id,'resource_project',id,unixepoch() FROM memory_projects;
"""

for action in ('INSERT','UPDATE','DELETE'):
    record='OLD' if action=='DELETE' else 'NEW'
    SCHEMA+=f"""CREATE TRIGGER IF NOT EXISTS memory_workflow_resource_{action.lower()} AFTER {action} ON task_workflows BEGIN
      UPDATE memory_resource_versions SET version=version+1 WHERE source_kind='resource_task' AND source_id={record}.task_id;
      INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
      SELECT 'workflow:'||id,user_id,'task',id,unixepoch() FROM tasks WHERE id={record}.task_id
      ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL,created_at=excluded.created_at;
    END;\n"""
