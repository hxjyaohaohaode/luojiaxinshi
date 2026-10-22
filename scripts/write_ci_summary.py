"""Expose actual test counts in Actions, including missing or failed reports."""
import argparse
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent


def junit(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    return [len(cases), sum(c.find('failure') is not None for c in cases),
            sum(c.find('error') is not None for c in cases), sum(c.find('skipped') is not None for c in cases)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=['unit', 'browser', 'all'], default='all')
    kind = parser.parse_args().kind
    rows = []
    units = [('Python', 'artifacts/ci/python-tests.xml'), ('Node', 'artifacts/ci/node-tests.xml')]
    for label, path in units if kind in {'unit', 'all'} else []:
        try:
            values = junit(ROOT/path)
        except (OSError, ET.ParseError):
            values = ['report unavailable', '-', '-', '-']
        rows.append([label, *values])
    browsers = [('Browser stability', 'artifacts/frontend-v9-browser/report.json'),
                ('Browser regression', 'artifacts/frontend-v8-browser/report.json'),
                ('Reference interactions', 'artifacts/reference-interactions-browser/report.json'),
                ('Workspace interactions', 'artifacts/workspace-interactions-browser/report.json')]
    for label, path in browsers if kind in {'browser', 'all'} else []:
        try:
            data = json.loads((ROOT/path).read_text(encoding='utf-8'))
            rows.append([label, len(data['checks']), sum(not c['ok'] for c in data['checks']), len(data['errors']), 0])
        except (OSError, ValueError, KeyError, TypeError):
            rows.append([label, 'report unavailable', '-', '-', '-'])
    text = '## Verification results\n\nCommit: `'+os.getenv('GITHUB_SHA', 'local')+'`\n\n'
    text += '| Suite | Tests | Failures | Errors | Skipped |\n| --- | --- | --- | --- | --- |\n'
    text += '\n'.join('| '+' | '.join(map(str, row))+' |' for row in rows)
    text += '\n\nOnly synthetic data is used. Download the reports from this run\'s Artifacts section.\n'
    out = ROOT/'artifacts/ci/summary.md'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding='utf-8')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(text)
    print(text)


if __name__ == '__main__':
    main()
