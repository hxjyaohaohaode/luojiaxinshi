"""Run every retained async-save and draft-recovery suite on owned synthetic data."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.run_openui_browser_checks import ensure_fixture_port_free

OUT = ROOT / 'artifacts' / 'ci-continuity-browser'
SUITES = [('verify_arrangement_recovery.mjs', 'arrangement-recovery-report.json', 'arrangement-recovery'),
          ('verify_ui_continuity.mjs', 'ui-continuity-report.json', 'ui-continuity'),
          ('verify_draft_continuity.mjs', 'draft-continuity-report.json', 'draft-continuity')]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CAMPUS_AUTO_LOAD_ENV='0', MVP_LIVE_MODEL='0', PYTHONUNBUFFERED='1')
    for key in ('MIMO_API_KEY', 'AI_API_KEY', 'OPENAI_API_KEY', 'ALIYUN_ACCESS_KEY_ID',
                'ALIYUN_ACCESS_KEY_SECRET', 'SMTP_AUTHORIZATION_CODE', 'SMTP_PASSWORD',
                'APP_ENV', 'DATA_DIR', 'APP_ORIGIN', 'APP_HOST', 'APP_PORT',
                'MVP_BROWSERS', 'MVP_VIEWPORTS', 'MVP_SCENARIO', 'MVP_BASELINE'):
        env.pop(key, None)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    results = []
    for script, raw_name, name in SUITES:
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        ensure_fixture_port_free(port)
        origin = 'http://127.0.0.1:' + str(port)
        report_dir = ROOT / 'artifacts' / 'continuity-browser' / name
        report_dir.mkdir(parents=True, exist_ok=True)
        raw_path, normalized = report_dir / raw_name, report_dir / 'report.json'
        raw_path.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix='fixture-', dir=OUT) as directory:
            data = Path(directory).resolve()
            assert data.parent == OUT.resolve() and data.name.startswith('fixture-')
            current_env = dict(env, MVP_PORT=str(port), MVP_ORIGIN=origin,
                               MVP_DATA_DIR=str(data), MVP_ARTIFACT_DIR=str(report_dir))
            with (report_dir / 'fixture.log').open('w', encoding='utf8') as fixture_log:
                fixture = subprocess.Popen([sys.executable, 'scripts/mvp_preview_server.py'],
                                           cwd=ROOT, env=current_env, stdout=fixture_log,
                                           stderr=subprocess.STDOUT, **flags)
                code, error = 1, ''
                try:
                    deadline = time.monotonic() + 45
                    while True:
                        if fixture.poll() is not None:
                            raise RuntimeError('Owned continuity fixture exited before readiness')
                        try:
                            with urlopen(origin + '/api/health', timeout=1) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            pass
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Owned continuity fixture did not become ready')
                        time.sleep(.15)
                    print('Running ' + script, flush=True)
                    with (report_dir / 'browser.log').open('w', encoding='utf8') as browser_log:
                        process_options = flags if os.name == 'nt' else {'start_new_session': True}
                        process = subprocess.Popen(['node', 'scripts/' + script], cwd=ROOT,
                                                   env=current_env, stdout=browser_log,
                                                   stderr=subprocess.STDOUT, **process_options)
                        try:
                            code = process.wait(timeout=600)
                        except subprocess.TimeoutExpired:
                            code = 124
                            error = 'Owned continuity browser exceeded its 600-second deadline'
                            if os.name == 'nt':
                                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                               capture_output=True, timeout=15, **flags)
                            else:
                                os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=15)
                    raw = json.loads(raw_path.read_text(encoding='utf8'))
                    scenarios = raw.get('scenarios', [])
                    checks = [{**check, 'engine': scenario.get('engine'),
                               'width': scenario.get('width'), 'scenario': scenario.get('label')}
                              for scenario in scenarios for check in scenario.get('checks', [])]
                    errors = list(raw.get('errors', []))
                    widths = [320, 390, 768, 844, 1440, 1920] if name == 'arrangement-recovery' else [390, 1440]
                    expected = {(engine, width) for engine in ('chromium', 'firefox', 'webkit') for width in widths}
                    if {(scenario.get('engine'), scenario.get('width')) for scenario in scenarios} != expected:
                        errors.append({'error': 'The complete declared browser and viewport inventory was not exercised'})
                    for scenario in scenarios:
                        if not scenario.get('passed') or not scenario.get('checks'):
                            errors.append({'scenario': scenario.get('label'),
                                           'error': scenario.get('error', 'Failed or empty scenario')})
                    if not scenarios or not checks or raw.get('passed') is not True:
                        errors.append({'error': 'Missing or incomplete continuity result'})
                    report = {'synthetic': True, 'live_model_calls': 0, 'external_messages': 0,
                              'fixture_origin': origin, 'checks': checks, 'errors': errors, 'raw_report': raw_name}
                    normalized.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                    if errors or any(not c.get('passed') for c in checks):
                        code = code or 1
                except Exception as exc:
                    code, error = 1, str(exc)
                finally:
                    if fixture.poll() is None:
                        if os.name == 'nt':
                            subprocess.run(['taskkill', '/PID', str(fixture.pid), '/T', '/F'],
                                           capture_output=True, timeout=15, **flags)
                        else:
                            fixture.terminate()
                        try:
                            fixture.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            fixture.kill()
                            fixture.wait(timeout=5)
        results.append({'script': script, 'returncode': code, 'error': error, 'fixture_port': port})
        (OUT / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf8')
        print(script + ': ' + ('passed' if code == 0 else 'FAILED') + (' ' + error if error else ''), flush=True)
        if code and (report_dir / 'browser.log').exists():
            print((report_dir / 'browser.log').read_text(encoding='utf8', errors='replace')[-6000:], flush=True)
    return int(any(result['returncode'] for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
