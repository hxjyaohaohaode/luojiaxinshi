"""Opt-in, two-turn real-provider check with only synthetic records.

Runs the existing chat, grounding, Harness, UI parser and receipt protocol.
No production database, contact, mail or SMS is used; no model is mocked.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.config import Settings
from app.db import ident
from app.main import create_app
from app.security import hash_password
from scripts.verify_agent_adaptive_live import StreamTimeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid-synthetic-test', action='store_true')
    parser.add_argument('--preview-result', type=Path, help='Serve a retained synthetic result without a model or delivery credential')
    args = parser.parse_args()
    if args.preview_result:
        folder = (ROOT / args.preview_result).resolve()
        if not folder.is_relative_to(ROOT / 'artifacts') or not folder.name.startswith('deep-live-'):
            parser.error('Only a retained synthetic result under artifacts/deep-live-* may be previewed')
        manifest = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
        if manifest.get('synthetic_only') is not True or not (folder / 'data' / 'campus.sqlite3').is_file():
            parser.error('The result is not a retained synthetic database')
        import uvicorn
        preview_settings = Settings(data_dir=folder / 'data', origin='http://localhost:8794', registration_mode='invite')
        uvicorn.run(create_app(preview_settings), host='127.0.0.1', port=8794, access_log=False)
        return
    if not args.allow_paid_synthetic_test:
        parser.error('Real provider use requires --allow-paid-synthetic-test')
    output = ROOT / 'artifacts' / ('deep-live-' + time.strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    settings = replace(Settings.from_env(), data_dir=output / 'data',
                       origin='http://127.0.0.1:8794', production=False,
                       agent_enabled=True, ai_grounding=True, ai_daily_limit=6,
                       agent_mcp_servers={}, agent_sandbox_image='')
    if not settings.ai_api_key:
        raise SystemExit('No configured provider; no request sent')
    app = create_app(settings)
    timeline = {}
    app.add_middleware(StreamTimeline, timeline=timeline)
    with app.state.db.connect(write=True) as conn:
        conn.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',
                     (ident(), 'synthetic-deep', hash_password('SyntheticOnly2026!'),
                      '深度交互合成验收', 'user', '{}', int(time.time())))
    report = {'synthetic_only': True, 'provider_mocked': False, 'turns': [],
              'production_database_read': False, 'external_notifications_sent': False}

    def save():
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    with TestClient(app, base_url=settings.origin) as client:
        client.headers.update({'Origin': settings.origin, 'X-Requested-With': 'campus-notice'})
        client.post('/api/auth/login', json={'username': 'synthetic-deep', 'password': 'SyntheticOnly2026!'}).raise_for_status()
        client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf']
        chat = client.post('/api/conversations', json={'title': '联调测试 · 连续消息与真实 GenUI'}).json()

        def send(content, **extra):
            nonlocal chat
            timeline.clear()
            started = time.monotonic()
            body = {'version': chat['version'], 'request_id': uuid.uuid4().hex,
                    'content': content, 'allow_external_processing': True, **extra}
            response = client.post('/api/conversations/' + chat['id'] + '/messages/stream', json=body)
            response.raise_for_status()
            chat = client.get('/api/conversations/' + chat['id']).json()
            (output / ('conversation-turn-' + str(len(report['turns']) + 1) + '.json')).write_text(
                json.dumps(chat, ensure_ascii=False, indent=2), encoding='utf-8')
            final = next(m for m in reversed(chat['messages']) if m['role'] == 'assistant')
            grounding = final.get('grounding', {})
            turn = {'elapsed_seconds': round(time.monotonic() - started, 2), 'timeline': dict(timeline),
                    'status': final['status'], 'error': final.get('error'),
                    'answer': final.get('genui', {}).get('raw', final['content']),
                    'validated': final.get('genui', {}).get('validated'),
                    'planning_mode': grounding.get('planning_mode'), 'review_status': grounding.get('status'),
                    'harness': grounding.get('harness'), 'usage': grounding.get('usage'),
                    'review_issues': grounding.get('review_issues'),
                    'interactive_blocks': sum(p['kind'] == 'ui' for p in final.get('parts', [])),
                    'ui_preview': 'event: ui_preview\n' in response.text,
                    'user_message_count': sum(m['role'] == 'user' for m in chat['messages'])}
            report['turns'].append(turn)
            save()
            print(json.dumps({'turn': len(report['turns']), **{k: turn[k] for k in
                  ('elapsed_seconds', 'status', 'review_status', 'interactive_blocks', 'timeline')}}, ensure_ascii=False), flush=True)
            return final

        first = send('这是隔离工程验收，所有日期和事项都是合成数据，不是真实学校通知。仅用当前三条用户输入，纯文字简短给出最后有效的截止时间和材料要求。初始条件：演示事项2026年11月6日18:00截止，需要报名表和课程截图。不联网，不操作待办/日历/资料库，不保存记忆，不宣称校方受理。',
                     additional_messages=[
                         {'request_id': uuid.uuid4().hex, 'content': '补充一：截止时间改为2026年11月7日16:00，旧时间作废。'},
                         {'request_id': uuid.uuid4().hex, 'content': '补充二：取消课程截图要求，只保留报名表；明确这是合成工程验收，不是学校正式规则。'}])
        report['batch_receipts_complete'] = sum(m.get('client_request_id') is not None for m in chat['messages'] if m['role'] == 'user') == 3
        report['latest_conditions_retained'] = '11月7日' in first['content'] and '16:00' in first['content'] and '报名表' in first['content']
        if first['status'] != 'complete':
            report['stopped_reason'] = 'first turn incomplete; no automatic paid retry'
            save()
            raise SystemExit(1)
        second = send('请引用上条答复继续，但不要把助手旧答复当作官方证据。这仍是合成工程验收。用自由生成HTML/CSS/JS做一个简洁中文准备时间试算工具：hours为数字输入，初始2，min=0.5，max=8，step=0.5；days为数字输入，初始7，min=1，max=30，step=1；total输出总小时数。首屏先展示总小时数，再展示输入；空值、超范围、小数天数必须显示错误并清除旧结果。用CampusUI.form绑定输入与输出，提供原生重置按钮和明确的“分析当前选择”按钮（CampusUI.form的prompt或CampusUI.sendPrompt），使用共享设计系统。不要联网、不写文件、不保存记忆、不创建待办或日历。',
                      reply_to={'message_id': first['id']})
        report['quote_persisted'] = any(m.get('reply_to', {}).get('message_id') == first['id'] for m in chat['messages'] if m['role'] == 'user')
        report['passed'] = (report['batch_receipts_complete'] and report['latest_conditions_retained']
                            and report['quote_persisted'] and second['status'] == 'complete'
                            and second.get('genui', {}).get('validated')
                            and report['turns'][-1]['interactive_blocks'] > 0)
        with app.state.db.connect() as conn:
            report['database_integrity'] = conn.execute('PRAGMA quick_check').fetchone()[0]
        save()
        print(json.dumps({'report': str(output / 'results.json'), 'passed': report['passed']}, ensure_ascii=False), flush=True)
        if not report['passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
