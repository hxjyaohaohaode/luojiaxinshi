"""Opt-in, bounded public-site integration check with an isolated local account."""
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
    parser.add_argument('--url', required=True)
    parser.add_argument('--article-path-prefix', required=True)
    parser.add_argument('--allow-public-network', action='store_true', required=True)
    args = parser.parse_args()
    out = ROOT/'artifacts'/'public-source-verification'
    out.mkdir(parents=True, exist_ok=True)
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'url': args.url,
              'article_path_prefix': args.article_path_prefix, 'public_network': True,
              'isolated_account': True, 'real_user_data_used': False, 'live_model_calls': 0,
              'checks': [], 'errors': []}
    with tempfile.TemporaryDirectory(prefix='isolated-', dir=out) as scratch:
        data = Path(scratch).resolve()
        assert data.parent == out.resolve()
        cfg = Settings(data, ai_api_key='', ai_grounding=False,
                       notice_semantic_review=False, agent_enabled=False)
        app = create_app(cfg)
        # No lifespan means no pollers, model consumers or push workers are started.
        client = TestClient(app, base_url=cfg.origin)
        client.headers.update({'Origin': cfg.origin, 'X-Requested-With': 'campus-notice'})

        def request(method, path, **kwargs):
            response = client.request(method, '/api'+path, **kwargs)
            response.raise_for_status()
            return response.json()

        try:
            request('POST', '/auth/register', json={
                'invite': new_invite(app.state.db), 'username': 'public.source.verification',
                'password': 'Synthetic-Verification-Only-2026',
                'display_name': '公开来源隔离验收', 'accepted_terms': True})
            client.headers['X-CSRF-Token'] = request('GET', '/session')['csrf']
            source = request('POST', '/source-catalog', json={
                'name': '公开官网隔离验收', 'platform': 'website', 'url': args.url})
            sid = source['id']
            request('PUT', f'/source-catalog/{sid}/subscription', json={
                'url': args.url, 'article_path_prefix': args.article_path_prefix,
                'mode': 'html', 'enabled': True, 'interval_minutes': 1440})
            first = request('POST', f'/source-catalog/{sid}/refresh')
            assert not first['error'], first['error']
            assert first['received_count'] > 0
            original = request('GET', '/notices')
            report['checks'].append('Real public list and article responses persist through the application API')
            second = request('POST', f'/source-catalog/{sid}/refresh')
            assert not second['error'], second['error']
            fresh = request('GET', '/notices')
            original_ids = {n['id'] for n in original}
            assert original_ids.issubset({n['id'] for n in fresh})
            if not first['pending_count']:
                assert len(fresh) == len(original)
            assert request('GET', '/tasks') == []
            assert all(n['status'] == 'received' and n['intent'] == 'verify' for n in fresh)
            report['checks'].append('Repeat refresh keeps existing identities and creates no tasks or confirmed applicability')
            report['first_sync'] = {k: first[k] for k in ['state', 'received_count', 'updated_count', 'pending_count']}
            report['second_sync'] = {k: second[k] for k in ['state', 'received_count', 'updated_count', 'pending_count']}
            report['notices'] = []
            for notice in fresh:
                detail = request('GET', '/notices/'+notice['id'])
                text = '\n'.join(section['text'] for source in detail['sources'] for section in source['sections'])
                assert text.strip()
                report['notices'].append({'title': notice['title'], 'source_url': detail['source_url'],
                                          'characters': len(text), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                                          'materials_complete': bool(detail['materials_complete'])})
            report['result'] = 'passed'
        except Exception as error:
            report['result'] = 'failed'
            report['errors'].append(str(error))
        finally:
            client.close()
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
