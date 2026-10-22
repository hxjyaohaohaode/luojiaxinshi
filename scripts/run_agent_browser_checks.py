"""Run the embedded Agent browser checks with an owned, offline fixture."""
import json
from contextlib import closing
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'artifacts' / 'ci-agent-browser'
SUITES = [
    ('agent-browser.mjs', 'artifacts/agent-chat-browser/results.json'),
    ('agent-adaptive-browser.mjs', 'artifacts/agent-adaptive-browser/results.json'),
    ('agent-fusion-browser.mjs', 'artifacts/reference-fusion/browser/results.json'),
    ('agent-quality-browser.mjs', 'artifacts/agent-quality-browser/performance.json'),
    ('composer-browser.mjs', 'artifacts/composer-browser/results.json'),
]


def main():
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 8793))
        except OSError:
            raise SystemExit('Port 8793 is occupied; no existing process was reused or stopped.') from None
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable,'tests/media_fixtures.py'],cwd=ROOT,check=True)
    env = dict(os.environ, PYTHONUNBUFFERED='1', AGENT_LIVE_UI='0')
    for key in ('MIMO_API_KEY', 'AI_API_KEY', 'OPENAI_API_KEY', 'AGENT_BROWSER_OUTPUT', 'AGENT_UI_REPLAY_DIR'):
        env.pop(key, None)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with tempfile.TemporaryDirectory(prefix='fixture-', dir=OUT) as data:
        env['AGENT_PREVIEW_DATA_DIR'] = str(Path(data).resolve())
        with (OUT / 'fixture.log').open('w', encoding='utf-8') as log:
            fixture = subprocess.Popen([sys.executable, 'scripts/agent_preview_server.py'], cwd=ROOT,
                env=env, stdout=log, stderr=subprocess.STDOUT, **flags)
            try:
                deadline = time.monotonic() + 45
                while True:
                    if fixture.poll() is not None:
                        raise RuntimeError('Offline Agent fixture exited before becoming ready.')
                    try:
                        with urlopen('http://127.0.0.1:8793/api/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Offline Agent fixture startup exceeded 45 seconds.')
                    time.sleep(.15)
                results = []
                for script, report in SUITES:
                    (ROOT / report).unlink(missing_ok=True)
                    print('Running ' + script, flush=True)
                    with (OUT / (script + '.log')).open('w', encoding='utf-8') as output:
                        try:
                            result = subprocess.run(['node', 'tests/' + script], cwd=ROOT, env=env,
                                stdout=output, stderr=subprocess.STDOUT, timeout=180)
                            code = result.returncode
                        except subprocess.TimeoutExpired:
                            code = 124
                    results.append({'suite': script, 'returncode': code})
                    print(script + ': ' + ('passed' if code == 0 else 'FAILED'), flush=True)
                    if code:
                        # Preserve the synthetic runtime failure before the
                        # fixture's temporary database is removed.
                        with closing(sqlite3.connect(Path(data) / 'campus.sqlite3')) as conn:
                            conn.row_factory = sqlite3.Row
                            failed = []
                            for row in conn.execute("SELECT * FROM agent_turns WHERE status='failed' ORDER BY created_at DESC LIMIT 3"):
                                turn = dict(row)
                                turn['messages'] = [json.loads(r[0]) for r in conn.execute('SELECT body FROM agent_messages WHERE turn_id=? ORDER BY seq',(turn['id'],))]
                                failed.append(turn)
                            (OUT / (script + '.failures.json')).write_text(json.dumps(failed,ensure_ascii=False,indent=2),encoding='utf-8')
                        details = (OUT / (script + '.log')).read_text(encoding='utf-8', errors='replace')
                        print('\n'.join(details.splitlines()[-35:])[-6000:], flush=True)
                (OUT / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                return int(any(result['returncode'] for result in results))
            finally:
                if fixture.poll() is None:
                    if os.name == 'nt':
                        # Windows venv Python can start a child interpreter.
                        # Terminate only this owned process tree, never by port.
                        subprocess.run(['taskkill', '/PID', str(fixture.pid), '/T', '/F'],
                            capture_output=True, timeout=10, **flags)
                    else:
                        fixture.terminate()
                    try:
                        fixture.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        fixture.kill()
                        fixture.wait(timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
