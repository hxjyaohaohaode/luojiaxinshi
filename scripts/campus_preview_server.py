"""Isolated, synthetic campus role demo for local browser verification only."""
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.account import record_consent
from app.config import Settings
from app.db import dumps, ident
from app.main import create_app
from app.models import Profile
from app.security import hash_password

PORT = int(os.environ.get('CAMPUS_PREVIEW_PORT', '8797'))
DATA = (ROOT / 'artifacts' / 'campus-permissions-2026-10-31' / 'preview-data').resolve()
assert DATA.is_relative_to((ROOT / 'artifacts').resolve()) and 1024 <= PORT <= 65535
# A different hostname keeps the synthetic login cookie separate from the real
# local application at 127.0.0.1:8765 (cookies do not isolate by port).
ORIGIN = 'http://localhost:' + str(PORT)
PASSWORD = 'Campus-Fixture-Only-2026!'
app = create_app(Settings(DATA, origin=ORIGIN, ai_api_key='', ai_grounding=False,
                          notice_semantic_review=False, agent_enabled=False))


def seed():
    with app.state.db.connect(write=True) as conn:
        for username, display, role in [
            ('fixture-site-admin', '测试系统管理员', 'admin'),
            ('fixture-college-admin', '测试学院管理员', 'user'),
            ('fixture-counselor', '测试辅导员', 'user'),
            ('fixture-student-one', '测试一班学生', 'user'),
            ('fixture-student-two', '测试二班学生', 'user'),
            ('fixture-student-three', '测试其他年级学生', 'user'),
        ]:
            row = conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            if not row:
                uid = ident()
                conn.execute('INSERT INTO users(id,username,password,display_name,role,profile,created_at) VALUES(?,?,?,?,?,?,?)',
                             (uid, username, hash_password(PASSWORD), display, role, dumps(Profile().model_dump()), int(time.time())))
                record_consent(conn, uid)


if __name__ == '__main__':
    import uvicorn
    seed()
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
