"""Publish only passing synthetic case results and explicitly selected fixture images."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = Path('docs/verification/frontend-v9-evidence')


def browser_cases(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if 'synthetic' not in data.get('fixture', '').lower():
        raise ValueError('Only explicitly synthetic browser evidence may be published.')
    if not data.get('checks') or data.get('errors') or any(c.get('ok') is not True for c in data['checks']):
        raise ValueError('A passing snapshot requires complete, passing browser results.')
    cases = [{'engine': c['engine'], 'name': c['name'], 'passed': True} for c in data['checks']]
    return {'origin': 'local synthetic fixture', 'tests': len(cases), 'failures': 0, 'page_errors': 0, 'cases': cases}


def junit_cases(path):
    cases = []
    for case in ET.parse(path).getroot().iter('testcase'):
        if any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')):
            raise ValueError('A passing snapshot cannot omit failed, errored or skipped test cases.')
        # No hostnames, paths, properties, captured output or environment fields.
        cases.append({'suite': case.get('classname', ''), 'name': case.get('name', ''),
                      'passed': True, 'seconds': float(case.get('time', '0'))})
    if not cases:
        raise ValueError('An empty report is not passing evidence.')
    return {'origin': 'local test process', 'tests': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0, 'cases': cases}


def export(root=ROOT):
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'app', 'static'], cwd=root).returncode:
        raise ValueError('Commit application changes before publishing a source-identified snapshot.')
    reports = {
        'browser-stability.json': browser_cases(root/'artifacts/frontend-v9-browser/report.json'),
        'browser-regression.json': browser_cases(root/'artifacts/frontend-v8-browser/report.json'),
        'python-related.json': junit_cases(root/'artifacts/frontend-v9-python.xml'),
        'node-unit.json': junit_cases(root/'artifacts/verification-node-junit.xml'),
        'verification-tools.json': junit_cases(root/'artifacts/verification-tooling.xml'),
    }
    target = root/OUTPUT
    target.mkdir(parents=True, exist_ok=True)
    for name, report in reports.items():
        (target/name).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    images = []
    for name in ('chromium-memory.png', 'chromium-chat.png'):
        source = root/'artifacts/frontend-v9-browser'/name
        if source.is_file():
            if not source.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Invalid synthetic screenshot: '+name)
            destination = target/'screenshots'/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            images.append(destination.relative_to(target).as_posix())
    files = [*reports, *images]
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    manifest = {'application_version': '1.19.0', 'application_source_commit': source_commit,
                'provenance': 'Local runs. Application code is unchanged from the stated commit; verification tooling is published with this snapshot.',
                'scope': {name: {key: value for key, value in report.items() if key != 'cases'} for name, report in reports.items()},
                'not_cloud_ci': True, 'contains_real_user_data': False,
                'files': {name: {'sha256': hashlib.sha256((target/name).read_bytes()).hexdigest(),
                                 'bytes': (target/name).stat().st_size} for name in files}}
    sources = ['.github/workflows/checks.yml', 'package.json', 'package-lock.json',
               'scripts/run_browser_checks.py', 'scripts/write_ci_summary.py',
               'scripts/export_verification_evidence.py', 'scripts/verify_frontend_stability.mjs',
               'scripts/verify_frontend_review.mjs', 'tests/test_verification_evidence.py']
    manifest['verification_source_sha256_lf'] = {
        name: hashlib.sha256((root/name).read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest()
        for name in sources}
    (target/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'published': str(OUTPUT), 'cases': {name: report['tests'] for name, report in reports.items()},
                      'synthetic_screenshots': len(images)}, ensure_ascii=False))
    return manifest


if __name__ == '__main__':
    export()
