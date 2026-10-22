"""Version six: durable hierarchy and complete, versioned source passages."""
TABLES = {'memory_nodes', 'memory_node_items', 'memory_tree_dirty', 'memory_source_units', 'memory_source_fts','memory_auto_state'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_nodes(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 parent_id TEXT REFERENCES memory_nodes(id) ON DELETE CASCADE,title TEXT NOT NULL,
 node_key TEXT NOT NULL,system INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(user_id,node_key));
CREATE INDEX IF NOT EXISTS memory_nodes_parent ON memory_nodes(user_id,parent_id,title,id);
CREATE TABLE IF NOT EXISTS memory_node_items(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 node_id TEXT NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
 custom INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS memory_node_members ON memory_node_items(node_id,memory_id);
CREATE TABLE IF NOT EXISTS memory_tree_dirty(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS memory_auto_state(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 reason TEXT NOT NULL,checked_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memory_source_units(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 node_id TEXT NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,fingerprint INTEGER NOT NULL,
 locator TEXT NOT NULL,ordinal INTEGER NOT NULL,start_offset INTEGER NOT NULL,
 title TEXT NOT NULL,content TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS memory_units_source ON memory_source_units(user_id,source_kind,source_id,fingerprint);
CREATE INDEX IF NOT EXISTS memory_units_node ON memory_source_units(node_id,ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_source_fts USING fts5(
 unit_id UNINDEXED,user_id UNINDEXED,words,tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS memory_units_insert AFTER INSERT ON memory_source_units BEGIN
 INSERT INTO memory_source_fts VALUES(NEW.id,NEW.user_id,memory_tokens(NEW.title||' '||NEW.content));
END;
CREATE TRIGGER IF NOT EXISTS memory_units_delete AFTER DELETE ON memory_source_units BEGIN
 DELETE FROM memory_source_fts WHERE unit_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_units_update AFTER UPDATE OF content,title ON memory_source_units BEGIN
 DELETE FROM memory_source_fts WHERE unit_id=OLD.id;
 INSERT INTO memory_source_fts VALUES(NEW.id,NEW.user_id,memory_tokens(NEW.title||' '||NEW.content));
END;
CREATE TRIGGER IF NOT EXISTS memory_tree_insert AFTER INSERT ON personal_memories BEGIN
 INSERT OR IGNORE INTO memory_tree_dirty VALUES(NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS memory_tree_update AFTER UPDATE OF scope,project_id,topic,kind ON personal_memories BEGIN
 INSERT OR IGNORE INTO memory_tree_dirty VALUES(NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS memory_tree_semantics AFTER UPDATE OF tier ON memory_semantics BEGIN
 INSERT OR IGNORE INTO memory_tree_dirty VALUES(NEW.memory_id);
END;
INSERT OR IGNORE INTO memory_tree_dirty SELECT id FROM personal_memories
 WHERE id NOT IN (SELECT memory_id FROM memory_node_items);
-- Requeue sources exactly once, so an upgrade indexes the complete parsed body.
INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:'||v.source_kind||':'||v.source_id,m.user_id,v.source_kind,v.source_id,unixepoch()
 FROM memory_resource_versions v JOIN memory_resource_sources b USING(source_kind,source_id)
 JOIN personal_memories m ON m.id=b.memory_id
 WHERE v.source_kind<>'resource_task'
 AND coalesce((SELECT value FROM meta WHERE key='memory_tree_source_seed'),'0')<>'1'
 ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL;
INSERT OR IGNORE INTO meta VALUES('memory_tree_source_seed','1');
-- Once on v7: rebuild old cached slices using whole-section credential spans.
UPDATE memory_source_units SET fingerprint=-1
 WHERE coalesce((SELECT value FROM meta WHERE key='memory_source_privacy_seed_v7'),'0')<>'1';
INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'resource:'||x.source_kind||':'||x.source_id,x.user_id,x.source_kind,x.source_id,unixepoch()
 FROM (SELECT user_id,source_kind,source_id FROM memory_source_units
       UNION SELECT m.user_id,b.source_kind,b.source_id FROM memory_resource_sources b
       JOIN personal_memories m ON m.id=b.memory_id) x
 WHERE x.source_kind IN ('resource_notice','resource_material','resource_project')
 AND coalesce((SELECT value FROM meta WHERE key='memory_source_privacy_seed_v7'),'0')<>'1'
 ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL;
INSERT OR IGNORE INTO meta VALUES('memory_source_privacy_seed_v7','1');
INSERT INTO memory_maintenance(user_id,dirty,updated_at)
 SELECT DISTINCT m.user_id,1,unixepoch() FROM personal_memories m JOIN memory_details d ON d.memory_id=m.id
 WHERE d.review_status='pending' AND coalesce((SELECT value FROM meta WHERE key='memory_auto_triage_seed'),'0')<>'1'
 ON CONFLICT(user_id) DO UPDATE SET dirty=1;
INSERT OR IGNORE INTO meta VALUES('memory_auto_triage_seed','1');
UPDATE memory_settings SET mode='auto',version=version+1 WHERE mode='review';
UPDATE meta SET value='6' WHERE key='memory_engine_schema_version';
"""
for kind,table in (('resource_notice','sources'),('resource_material','conversation_sources'),('resource_project','memory_projects')):
    SCHEMA += f"""CREATE TRIGGER IF NOT EXISTS memory_units_{table}_delete BEFORE DELETE ON {table} BEGIN
      DELETE FROM memory_source_units WHERE source_kind='{kind}' AND source_id=OLD.id;
    END;
    """
