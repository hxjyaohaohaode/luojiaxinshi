"""One synthetic text notice against the configured MiMo service; no user data."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ai import AIError, generate
from app.config import Settings
from app.documents import text_source

settings = replace(Settings.from_env(), ai_timeout=90)
folder = ROOT / 'artifacts/mvp-acceptance'
folder.mkdir(parents=True, exist_ok=True)
text = '''虚构工程验收通知，非真实校园安排。
资源与环境科学学院2025级本科生可自愿报名实践项目。
本人须于2030年10月20日17:00前将申请表和个人说明提交至学院办公室。
学院于2030年10月24日审核，学院审核不是学生提交截止时间。
联系电话：未公布。'''
source = text_source(text)
record = {'source_label': '虚构学院办公室', 'published_at': '2030-10-10T09:00:00+08:00', 'materials_complete': True}
report = {'sample': 'synthetic text only', 'model': settings.ai_model, 'configured': bool(settings.ai_api_key)}
started = time.monotonic()
try:
    draft, usage = generate(settings, record, [source], {'college': '资源与环境科学学院', 'grade': '2025级', 'level': '本科'})
    report.update(status='passed', usage=usage, draft=draft)
    personal = [t for t in draft['tasks'] if t['scope'] == 'personal']
    checks = {'personal_action_exists': bool(personal), 'no_institution_date_as_personal_deadline': all(t['due_date'] != '2030-10-24' for t in personal),
              'no_automatic_confirmation': all(not t['deadline_confirmed'] for t in draft['tasks']),
              'expected_submission_deadline': any(t['due_date'] == '2030-10-20' and t['due_time'] == '17:00' for t in personal)}
    report['checks'] = checks
    if not all(checks.values()): report['status'] = 'semantic_check_failed'
except AIError as exc:
    report.update(status='failed', error=str(exc))
report['elapsed_seconds'] = round(time.monotonic()-started, 2)
(folder/'live-model.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'draft'}, ensure_ascii=False))
sys.exit(0 if report['status'] == 'passed' else 1)
