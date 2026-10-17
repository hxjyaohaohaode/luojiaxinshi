"""Operator tools must not fail after successful work on English Windows."""
import json
import os
import subprocess
import sys

import pytest

from app.config import ROOT


@pytest.mark.parametrize('encoding', ['ascii', 'cp1252'])
def test_offline_evaluation_prints_readable_utf8_through_restricted_pipes(encoding):
    result = subprocess.run([sys.executable, 'scripts/evaluate_genui.py'], cwd=ROOT,
                            env={**os.environ, 'PYTHONUTF8':'0', 'PYTHONIOENCODING':encoding},
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.decode('utf-8'))
    assert '离线合成' in report['source']
    assert report['passed'] == report['total'] == 40 and report['failed'] == 0
