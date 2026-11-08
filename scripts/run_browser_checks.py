"""Run browser suites against synthetic, loopback-only application data."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.run_openui_browser_checks import ensure_fixture_port_free
OUT = ROOT / 'artifacts' / 'ci-browser'
SUITES = [('verify_frontend_stability.mjs', 'frontend-v9-browser'),
          ('verify_frontend_review.mjs', 'frontend-v8-browser'),
          ('verify_reference_interactions.mjs', 'reference-interactions-browser'),
          ('verify_workspace_interactions.mjs', 'workspace-interactions-browser'),
          ('verify_visual_review.mjs', 'visual-review-browser'),
          ('verify_notice_flow.mjs', 'notice-flow-browser'),
          ('verify_task_board.mjs', 'task-board-browser'),
          ('verify_natural_intake.mjs', 'natural-intake-browser'),
          ('verify_task_materials.mjs', 'task-materials-browser'),
          ('verify_source_inbox.mjs', 'source-inbox-browser'),
          ('verify_push_browser.mjs', 'push-browser'),
          ('verify_notice_matters.mjs', 'notice-matters-browser'),
          ('verify_source_presets_ui.mjs', 'source-presets-browser'),
          ('verify_pilot_workspace.mjs', 'pilot-workspace-browser')]


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
    ensure_fixture_port_free(8786)
    OUT.mkdir(parents=True, exist_ok=True)
    fixture_data = tempfile.TemporaryDirectory(prefix='fixture-', dir=OUT)
    data = Path(fixture_data.name).resolve()
    if not data.is_relative_to((ROOT / 'artifacts').resolve()):
        raise SystemExit('Synthetic data must stay under artifacts/.')
    env = dict(os.environ, CAMPUS_AUTO_LOAD_ENV='0', MVP_PORT='8786', MVP_DATA_DIR=str(data), INTAKE_TEST_ORIGIN='http://127.0.0.1:8786', PYTHONUNBUFFERED='1')
    env['PILOT_BROWSER_FIXTURE']='1' if not selected or 'verify_pilot_workspace.mjs' in selected else '0'
    for key in ('MIMO_API_KEY','AI_API_KEY','OPENAI_API_KEY','ALIYUN_ACCESS_KEY_ID','ALIYUN_ACCESS_KEY_SECRET','SMTP_AUTHORIZATION_CODE','SMTP_PASSWORD'):
        env.pop(key, None)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with (OUT / 'fixture.log').open('w', encoding='utf-8') as log:
        fixture = subprocess.Popen([sys.executable, 'scripts/push_preview_server.py'],
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
            results = []
            for script, folder in SUITES:
                if selected and script not in selected:
                    continue
                reset_fixture_limits(data)
                (ROOT/'artifacts'/folder/'report.json').unlink(missing_ok=True)
                print('Running '+script, flush=True)
                with (OUT / (script+'.log')).open('w', encoding='utf-8') as output:
                    try:
                        code = subprocess.run(['node', 'scripts/'+script], cwd=ROOT, env=env,
                                              stdout=output, stderr=subprocess.STDOUT, timeout=360).returncode
                    except subprocess.TimeoutExpired:
                        output.write('\nBrowser suite exceeded the 360-second deadline.\n')
                        code = 124
                failed |= code != 0
                results.append({'script': script, 'returncode': code})
                (OUT/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                print(script+': '+('passed' if code == 0 else 'FAILED'), flush=True)
                if code:
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
