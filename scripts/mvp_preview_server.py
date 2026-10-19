"""Local-only synthetic acceptance environment. Real data/ is never read."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import TaskData

PORT=int(os.getenv('MVP_PORT','8780'))
assert 1024<=PORT<=65535
ORIGIN = f'http://127.0.0.1:{PORT}'
DATA = Path(os.getenv('MVP_DATA_DIR',str(ROOT / 'artifacts/mvp-acceptance/data'))).resolve()
assert DATA.is_relative_to((ROOT/'artifacts').resolve()), 'Synthetic fixture data must stay in artifacts/'
app = create_app(Settings(DATA, origin=ORIGIN, ai_api_key='', ai_grounding=False))
USERNAME = 'workflow.demo'
PASSWORD = 'Mvp-Verification-Only-2026'


def seed():
    with app.state.db.connect(write=True) as conn:
        if conn.execute('SELECT 1 FROM users WHERE username=?', (USERNAME,)).fetchone():
            # A fresh verification run resets throttling only in this isolated fixture DB.
            conn.execute('DELETE FROM limits')
            return
    c = TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Requested-With': 'campus-notice'})
    r = c.post('/api/auth/register', json={'username': USERNAME, 'password': PASSWORD,
                'display_name': '虚构验收同学', 'accepted_terms': True})
    assert r.status_code == 200, r.text
    c.headers['X-CSRF-Token'] = c.get('/api/session').json()['csrf']
    c.put('/api/profile', json={'college': '资源与环境科学学院（虚构验收）', 'level': '本科', 'grade': '2025级', 'semester': '2026—2027学年第一学期'})
    now = datetime.now(timezone(timedelta(hours=8)))
    day = (now + timedelta(days=3)).date().isoformat()
    for i, title in enumerate(['虚构验收｜秋季学生实践项目申请', '虚构验收｜课程材料报送与签字确认', '虚构验收｜校园活动报名通知']):
        body = f'{title}。\n适用对象：本科生，自行核对专业与年级条件。\n本人于{day} 17:00前提交申请表和个人说明；学院审核时间另行通知。\n材料提交至学院办公室。'
        r = c.post('/api/notices', data={'title': title, 'body': body, 'source_label': '虚构学院办公室 · 工程测试', 'materials_complete': 'true'})
        assert r.status_code == 200, r.text
        n = r.json()
        if i == 2:
            continue
        n = c.post(f"/api/notices/{n['id']}/manual", json={'version': n['version']}).json()
        titles = ['准备申请材料', '核对资格并签字', '提交申请，跟进受理结果'] if i == 0 else ['补交课程实践材料与经本人签字确认的活动记录（虚构长标题验收）']
        tasks = [TaskData(title=t, due_date=day, due_time='17:00', deadline_text=day+' 17:00前', deadline_confirmed=True,
                          materials=['申请表', '个人说明'], submission='学院办公室（虚构）', notes='工程验收记录，不代表真实校园安排').model_dump() for t in titles]
        r = c.post(f"/api/notices/{n['id']}/confirm", json={'version': n['version'], 'reviewed': True, 'tasks': tasks})
        assert r.status_code == 200, r.text
        ids = r.json()['task_ids']
        if i == 0:
            for j, tid in enumerate(ids):
                t = c.get(f'/api/tasks/{tid}/workflow').json()['task']
                d = {**t['workflow']['data'], 'next_step': '核对材料并完成本人提交', 'action_kind': 'optional', 'participation': 'joined'}
                if j == 2:
                    d.update(stage='blocked', outcome='签字环节尚未完成', dependencies=[ids[1]], followup_at=(now-timedelta(hours=1)).isoformat())
                c.put(f'/api/tasks/{tid}/workflow', json={'version': 0, 'task_version': 1, 'data': d})
            c.post(f"/api/notices/{n['id']}/changes", json={'notice_version': n['version'], 'kind': 'unverified',
                   'text': '虚构测试：群内有人转述提交日期可能调整，尚未找到正式通知。', 'source_label': '虚构群内转述', 'targets': []})


if __name__ == '__main__':
    import uvicorn
    seed()
    print('Synthetic acceptance environment; no model credentials; loopback only.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
