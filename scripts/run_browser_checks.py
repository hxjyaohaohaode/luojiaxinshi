"""Run browser suites against synthetic, loopback-only application data."""
import argparse
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
OUT = ROOT / 'artifacts' / 'ci-browser'
SUITES = [('verify_frontend_stability.mjs', 'frontend-v9-browser'),
          ('verify_frontend_review.mjs', 'frontend-v8-browser'),
          ('verify_reference_interactions.mjs', 'reference-interactions-browser'),
          ('verify_workspace_interactions.mjs', 'workspace-interactions-browser'),
          ('verify_visual_review.mjs', 'visual-review-browser'),
          ('verify_notice_flow.mjs', 'notice-flow-browser'),
          ('verify_task_board.mjs', 'task-board-browser')]


def reset_fixture_limits(data):
    # Suites have independent login attempts. This is the owned synthetic DB,
    # never the normal data/ directory or an arbitrary caller-supplied database.
    data = Path(data).resolve()
    if data.parent != OUT.resolve() or not data.name.startswith('fixture-'):
        raise ValueError('Only the owned synthetic fixture database may be reset.')
    database=data/'campus.sqlite3'
    if not database.is_file() or database.resolve().parent != data:
        raise ValueError('The owned synthetic database is missing or outside its data folder.')
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('DELETE FROM limits')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=[name for name, _ in SUITES], action='append',
                        help='Run only these suites; the default runs all suites.')
    selected = parser.parse_args().suite
    # Never reuse or terminate another service. In particular, leave 8765 alone.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 8786))
        except OSError:
            raise SystemExit('Port 8786 is occupied; the browser checks were not started.') from None
    OUT.mkdir(parents=True, exist_ok=True)
    fixture_data = tempfile.TemporaryDirectory(prefix='fixture-', dir=OUT)
    data = Path(fixture_data.name).resolve()
    if not data.is_relative_to((ROOT / 'artifacts').resolve()):
        raise SystemExit('Synthetic data must stay under artifacts/.')
    env = dict(os.environ, MVP_PORT='8786', MVP_DATA_DIR=str(data), PYTHONUNBUFFERED='1')
    for key in ('MIMO_API_KEY', 'AI_API_KEY', 'OPENAI_API_KEY'):
        env.pop(key, None)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with (OUT / 'fixture.log').open('w', encoding='utf-8') as log:
        fixture = subprocess.Popen([sys.executable, 'scripts/memory_engine_preview_server.py'],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, **flags)
        try:
            deadline = time.monotonic() + 45
            while True:
                if fixture.poll() is not None:
                    raise RuntimeError('Synthetic fixture exited before becoming ready.')
                try:
                    with urlopen('http://127.0.0.1:8786/api/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Synthetic fixture did not become ready within 45 seconds.')
                time.sleep(.15)
            failed = False
            for script, folder in SUITES:
                if selected and script not in selected:
                    continue
                reset_fixture_limits(data)
                (ROOT/'artifacts'/folder/'report.json').unlink(missing_ok=True)
                print('Running '+script, flush=True)
                with (OUT / (script+'.log')).open('w', encoding='utf-8') as output:
                    result = subprocess.run(['node', 'scripts/'+script], cwd=ROOT, env=env,
                                            stdout=output, stderr=subprocess.STDOUT)
                failed |= result.returncode != 0
                print(script+': '+('passed' if result.returncode == 0 else 'FAILED'), flush=True)
                if result.returncode:
                    # These are owned synthetic fixture logs. Surface diagnostics
                    # in the job itself so a failed run does not require downloading
                    # every screenshot before its cause can be investigated.
                    details = (OUT / (script+'.log')).read_text(encoding='utf-8', errors='replace')
                    print('\n'.join(details.splitlines()[-40:])[-8000:], flush=True)
            return int(failed)
        finally:
            if fixture.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(fixture.pid), '/T', '/F'], capture_output=True, timeout=10, **flags)
                else:
                    fixture.terminate()
                try:
                    fixture.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    fixture.kill()
                    fixture.wait(timeout=5)
            fixture_data.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
