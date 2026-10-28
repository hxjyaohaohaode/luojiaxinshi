"""Opt-in real public-column intake through isolated application APIs; no AI."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.security import new_invite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-public-network', action='store_true', required=True)
    parser.add_argument('--preset', action='append', choices=['whu-sres-notices', 'whu-notices', 'whu-journal-affairs'])
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts' / 'public-sources-2026-10-29')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'live_model_calls': 0,
              'isolated_account': True, 'real_user_data_used': False, 'columns': [], 'failures': []}
    with tempfile.TemporaryDirectory(prefix='api-verification-', dir=out) as scratch:
        cfg = Settings(Path(scratch), ai_api_key='', ai_grounding=False,
                       notice_semantic_review=False, agent_enabled=False)
        app = create_app(cfg)
        # No lifespan: polling, automation, push and model workers never start.
        client = TestClient(app, base_url=cfg.origin)
        client.headers.update({'Origin': cfg.origin, 'X-Requested-With': 'campus-notice'})
        def request(method, path, **kwargs):
            response = client.request(method, '/api' + path, **kwargs)
            response.raise_for_status()
            return response.json()
        try:
            request('POST', '/auth/register', json={
                'invite': new_invite(app.state.db), 'username': 'school.source.verification',
                'password': 'Synthetic-Verification-Only-2026',
                'display_name': '公开官网接入验收', 'accepted_terms': True})
            client.headers['X-CSRF-Token'] = request('GET', '/session')['csrf']
            for preset_id in args.preset or ['whu-sres-notices', 'whu-notices']:
                print('Checking ' + preset_id, flush=True)
                saved = request('POST', '/source-presets/' + preset_id + '/subscribe', json={})
                sid = saved['source_id']
                again = request('POST', '/source-presets/' + preset_id + '/subscribe', json={})
                assert again['source_id'] == sid and not again['created']
                rounds, first_ids = [], set()
                for round_number in range(2):
                    synced = request('POST', '/source-catalog/' + sid + '/refresh')
                    rounds.append({k: synced[k] for k in ('state', 'received_count', 'updated_count', 'pending_count', 'error')})
                    with app.state.db.connect() as conn:
                        identities = {r[0] for r in conn.execute(
                            'SELECT DISTINCT notice_id FROM notice_ingest_receipts WHERE user_id=? AND external_key LIKE ?',
                            (request('GET', '/session')['user']['id'], 'website:' + sid + ':%'))}
                    if round_number == 0:
                        first_ids = identities
                    else:
                        assert first_ids.issubset(identities), 'Repeat refresh lost an existing notice'
                with app.state.db.connect() as conn:
                    entries = [dict(r) for r in conn.execute(
                        'SELECT url,title,published_at,error FROM source_subscription_items WHERE source_id=?', (sid,))]
                    rows = conn.execute('SELECT DISTINCT notice_id FROM notice_ingest_receipts WHERE external_key LIKE ?',
                                        ('website:' + sid + ':%',)).fetchall()
                notices = []
                for row in rows:
                    detail = request('GET', '/notices/' + row['notice_id'])
                    sources = detail['sources']
                    text = '\n'.join(s['text'] for source in sources for s in source['sections'])
                    assert text.strip(), 'Empty notice was saved'
                    assert detail['published_at'], 'Known publication date was lost'
                    notices.append({'id': detail['id'], 'title': detail['title'], 'url': detail['source_url'],
                                    'published_at': detail['published_at'], 'characters': len(text),
                                    'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                                    'sources': [{'kind': s['kind'], 'status': s['status'],
                                                 'origin': s.get('origin', {})} for s in sources]})
                assert notices, 'No real public notice was received'
                assert len({n['url'] for n in notices}) == len(notices), 'Duplicate source URL created multiple notices'
                report['columns'].append({'preset_id': preset_id, 'rounds': rounds, 'discovered_count': len(entries),
                                          'received_count': len(notices), 'entries': entries, 'notices': notices,
                                          'repeat_identity_preserved': True})
                print(preset_id + ': ' + str(len(notices)) + ' received / ' + str(len(entries)) + ' discovered', flush=True)
            assert request('GET', '/tasks') == []
            assert request('GET', '/notice-automation')['enabled'] is False
        except Exception as error:
            report['failures'].append(str(error))
        finally:
            client.close()
    report['result'] = ('failed' if report['failures'] else 'partial' if any(
        e['error'] for c in report['columns'] for e in c['entries']) else 'passed')
    (out / 'live-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('result', 'failures')}, ensure_ascii=False))
    return int(bool(report['failures']))


if __name__ == '__main__':
    raise SystemExit(main())
