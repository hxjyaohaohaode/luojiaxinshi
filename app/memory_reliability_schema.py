"""Dependency-free v4 migration for reversible edits and versioned evidence."""
TABLES={'memory_mutation_receipts','memory_withdrawn_answers','memory_feedback_versions','memory_session_usage','memory_reflection_attempts',
        'memory_reflection_leases','memory_session_edits'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS memory_mutation_receipts(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,request_id TEXT NOT NULL,
 operation TEXT NOT NULL,payload_hash TEXT NOT NULL,result TEXT NOT NULL,
 created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,PRIMARY KEY(user_id,request_id));
CREATE TABLE IF NOT EXISTS memory_withdrawn_answers(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 created_at INTEGER NOT NULL,PRIMARY KEY(user_id,message_id));
CREATE TABLE IF NOT EXISTS memory_feedback_versions(
 message_id TEXT NOT NULL,memory_id TEXT NOT NULL,memory_version INTEGER NOT NULL,
 PRIMARY KEY(message_id,memory_id),FOREIGN KEY(message_id,memory_id)
 REFERENCES memory_feedback(message_id,memory_id) ON DELETE CASCADE);
INSERT OR IGNORE INTO memory_feedback_versions
 SELECT f.message_id,f.memory_id,u.memory_version FROM memory_feedback f
 JOIN memory_usage u ON u.message_id=f.message_id AND u.memory_id=f.memory_id;
CREATE TABLE IF NOT EXISTS memory_reflection_leases(
 job_id TEXT PRIMARY KEY REFERENCES memory_reflection_jobs(id) ON DELETE CASCADE,
 token TEXT NOT NULL DEFAULT '',not_before INTEGER NOT NULL DEFAULT 0,
 external_started_at INTEGER,attempts INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO memory_reflection_leases(job_id,external_started_at,attempts)
 SELECT id,started_at,CASE WHEN started_at IS NULL THEN 0 ELSE 1 END FROM memory_reflection_jobs;
CREATE TABLE IF NOT EXISTS memory_reflection_attempts(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,attempt_id TEXT PRIMARY KEY,
 started_at INTEGER NOT NULL,outcome TEXT NOT NULL);
INSERT OR IGNORE INTO memory_reflection_attempts SELECT j.user_id,j.id,j.started_at,j.state
 FROM memory_reflection_jobs j LEFT JOIN memory_reflection_leases l ON l.job_id=j.id
 WHERE j.started_at IS NOT NULL AND j.state<>'queued' AND coalesce(l.token,'')='';
CREATE INDEX IF NOT EXISTS memory_reflection_budget ON memory_reflection_attempts(user_id,started_at);
CREATE TABLE IF NOT EXISTS memory_session_edits(
 session_id TEXT PRIMARY KEY REFERENCES memory_session_items(id) ON DELETE CASCADE,
 content TEXT NOT NULL,version INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memory_session_usage(
 session_id TEXT NOT NULL REFERENCES memory_session_items(id) ON DELETE CASCADE,
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 PRIMARY KEY(session_id,message_id));
CREATE TRIGGER IF NOT EXISTS memory_withdraw_session_answer BEFORE DELETE ON memory_session_items BEGIN
 INSERT OR IGNORE INTO memory_withdrawn_answers SELECT OLD.user_id,message_id,unixepoch()
 FROM memory_session_usage WHERE session_id=OLD.id;
END;
CREATE INDEX IF NOT EXISTS memory_semantic_keys ON memory_policies(semantic_key,memory_id);
CREATE INDEX IF NOT EXISTS memory_usage_memory ON memory_usage(memory_id,message_id);
CREATE INDEX IF NOT EXISTS memory_evidence_source ON memory_evidence(source_kind,source_id,memory_id);
CREATE INDEX IF NOT EXISTS memory_links_parent ON memory_links(parent_id,relation,child_id);
UPDATE memory_semantics SET (facet,canonical_value)=(SELECT memory_facet(m.content,coalesce(p.semantic_key,'')),
 memory_value(m.content,coalesce(p.semantic_key,'')) FROM personal_memories m LEFT JOIN memory_policies p ON p.memory_id=m.id WHERE m.id=memory_semantics.memory_id);
CREATE TRIGGER IF NOT EXISTS memory_withdraw_answer BEFORE DELETE ON personal_memories BEGIN
 INSERT OR IGNORE INTO memory_withdrawn_answers SELECT OLD.user_id,message_id,unixepoch()
 FROM memory_usage WHERE memory_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_feedback_new_version AFTER UPDATE OF version ON personal_memories
 WHEN NEW.version<>OLD.version BEGIN
 UPDATE memory_semantics SET positive=0,negative=0 WHERE memory_id=NEW.id;
END;
UPDATE memory_semantics SET
 positive=(SELECT count(*) FROM memory_feedback f JOIN memory_feedback_versions v
 ON v.message_id=f.message_id AND v.memory_id=f.memory_id JOIN personal_memories m ON m.id=f.memory_id
 WHERE f.memory_id=memory_semantics.memory_id AND v.memory_version=m.version AND f.outcome='helpful'),
 negative=(SELECT count(*) FROM memory_feedback f JOIN memory_feedback_versions v
 ON v.message_id=f.message_id AND v.memory_id=f.memory_id JOIN personal_memories m ON m.id=f.memory_id
 WHERE f.memory_id=memory_semantics.memory_id AND v.memory_version=m.version AND f.outcome IN ('irrelevant','outdated'));
UPDATE meta SET value='4' WHERE key='memory_engine_schema_version';
"""
