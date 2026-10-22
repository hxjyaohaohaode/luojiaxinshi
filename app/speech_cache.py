"""Private, bounded speech reuse. Source deletion removes its derived audio."""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import Future

TTL = 7 * 86400
OWNER_BYTES = 64 * 1024 * 1024
TOTAL_BYTES = 256 * 1024 * 1024


class SpeechCache:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.pending = {}
        with db.connect() as conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS speech_audio_cache(
              cache_key TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              message_id TEXT REFERENCES conversation_messages(id) ON DELETE CASCADE,
              created_at INTEGER NOT NULL, accessed_at INTEGER NOT NULL, audio BLOB NOT NULL);
              CREATE INDEX IF NOT EXISTS speech_audio_cache_owner ON speech_audio_cache(user_id,accessed_at);
            ''')
            conn.execute('DELETE FROM speech_audio_cache WHERE created_at<?', (int(time.time())-TTL,))

    def get_or_create(self, uid, message_id, settings, payload, generate):
        # Credential rotation, provider, voice, instructions and exact text all invalidate reuse.
        key = hashlib.sha256(json.dumps([uid, message_id, settings.ai_base_url,
                settings.ai_api_key, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        now = int(time.time())
        with self.lock:
            try:
                with self.db.connect() as conn:
                    row = conn.execute('SELECT audio FROM speech_audio_cache WHERE cache_key=? AND user_id=? AND created_at>=?',
                                       (key, uid, now-TTL)).fetchone()
                    if row:
                        conn.execute('UPDATE speech_audio_cache SET accessed_at=? WHERE cache_key=?', (now, key))
                        return bytes(row['audio']), True
            except sqlite3.Error:
                logging.getLogger(__name__).warning('Speech cache read unavailable; continuing without reuse')
            future = self.pending.get(key)
            leader = future is None
            if leader:
                future = Future()
                self.pending[key] = future
        if not leader:
            return future.result(), True
        try:
            audio = generate()
            with self.lock:
                try:
                    self._store(uid, message_id, key, now, audio)
                except sqlite3.Error:
                    # A cache failure must not discard already generated, billable audio.
                    logging.getLogger(__name__).warning('Speech cache write unavailable; returning generated audio')
                future.set_result(audio)
            return audio, False
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def _store(self, uid, message_id, key, now, audio):
        with self.db.connect() as conn:
            # A request can outlive deletion. Never resurrect an orphaned response.
            present = conn.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone()
            if present and message_id:
                present = conn.execute('''SELECT 1 FROM conversation_messages m JOIN conversations c
                  ON c.id=m.conversation_id WHERE m.id=? AND c.user_id=? AND m.status='complete' AND m.role='assistant' ''',
                                       (message_id, uid)).fetchone()
            if present and len(audio) <= OWNER_BYTES:
                conn.execute('DELETE FROM speech_audio_cache WHERE created_at<?', (now-TTL,))
                conn.execute('INSERT OR REPLACE INTO speech_audio_cache VALUES(?,?,?,?,?,?)',
                             (key, uid, message_id, now, now, audio))
                self._trim(conn, 'WHERE user_id=?', (uid,), OWNER_BYTES)
                self._trim(conn, '', (), TOTAL_BYTES)
    @staticmethod
    def _trim(conn, where, params, budget):
        total = conn.execute('SELECT COALESCE(SUM(length(audio)),0) FROM speech_audio_cache '+where, params).fetchone()[0]
        if total <= budget:
            return
        for row in conn.execute('SELECT cache_key,length(audio) AS bytes FROM speech_audio_cache '+where+' ORDER BY accessed_at,created_at', params).fetchall():
            conn.execute('DELETE FROM speech_audio_cache WHERE cache_key=?', (row['cache_key'],))
            total -= row['bytes']
            if total <= budget:
                break
