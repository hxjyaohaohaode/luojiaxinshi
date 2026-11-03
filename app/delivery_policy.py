"""Keep the initial website snapshot readable without announcing it as new."""
TABLES={'source_baseline_runs','source_baseline_items','notice_delivery_suppressions'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS source_baseline_runs(
 source_id TEXT PRIMARY KEY REFERENCES source_subscriptions(source_id) ON DELETE CASCADE,
 completed_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_baseline_items(
 source_id TEXT NOT NULL REFERENCES source_subscriptions(source_id) ON DELETE CASCADE,
 url TEXT NOT NULL,PRIMARY KEY(source_id,url));
CREATE TABLE IF NOT EXISTS notice_delivery_suppressions(
 notice_id TEXT PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,reason TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES('delivery_policy_schema_version','1');
"""
def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='delivery_policy_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):raise ValueError('通知初始快照数据缺失或版本不兼容')
    conn.executescript(SCHEMA)
