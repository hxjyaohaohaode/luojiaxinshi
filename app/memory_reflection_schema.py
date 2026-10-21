"""Dependency-free schema shared by the store and reflection worker."""
TABLES={'memory_reflection_jobs'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS memory_reflection_jobs(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',snapshot TEXT NOT NULL,
 created_at INTEGER NOT NULL,started_at INTEGER,finished_at INTEGER,error_code TEXT NOT NULL DEFAULT '',
 proposal_count INTEGER NOT NULL DEFAULT 0,usage TEXT NOT NULL DEFAULT '{}',
 UNIQUE(user_id,conversation_id,fingerprint));
CREATE INDEX IF NOT EXISTS memory_reflection_queue ON memory_reflection_jobs(state,created_at);
CREATE TRIGGER IF NOT EXISTS memory_reflection_forget BEFORE DELETE ON personal_memories BEGIN
 DELETE FROM memory_reflection_jobs WHERE user_id=OLD.user_id AND EXISTS
 (SELECT 1 FROM json_each(memory_reflection_jobs.snapshot,'$.memories') m WHERE json_extract(m.value,'$.id')=OLD.id);
END;
"""
