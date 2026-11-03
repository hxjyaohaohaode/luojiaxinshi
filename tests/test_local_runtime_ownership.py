"""Exercise Windows PID reuse without stopping any process."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows process ownership guard')
def test_stale_pid_can_start_but_never_authorizes_stop_or_another_workspace(tmp_path):
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:pytest.skip('PowerShell is unavailable')
    root = Path(__file__).resolve().parent.parent
    runtime = tmp_path/'campus-runtime.json'
    runtime.write_text(json.dumps({'root':str(root),'pid':os.getpid()}),encoding='utf-8')
    environment = {**os.environ,'RUNTIME_TEST_DATA':str(tmp_path),
                   'RUNTIME_TEST_HELPER':str(root/'scripts/local-runtime.ps1')}
    script = r'''
. $env:RUNTIME_TEST_HELPER
$configuration = [pscustomobject]@{data_dir=$env:RUNTIME_TEST_DATA}
if ($null -ne (Get-OwnedTaskProcess $configuration -AllowStalePid)) {
    throw 'A foreign PID must not be reused as an application process'
}
$stopDenied = $false
try { Get-OwnedTaskProcess $configuration | Out-Null } catch { $stopDenied = $true }
if (-not $stopDenied) { throw 'The strict stop guard must remain active' }
$runtimeFile = Join-Path $env:RUNTIME_TEST_DATA 'campus-runtime.json'
$record = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
$record.root = Join-Path $env:RUNTIME_TEST_DATA 'another-workspace'
$record | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding UTF8
$workspaceDenied = $false
try { Get-OwnedTaskProcess $configuration -AllowStalePid | Out-Null } catch { $workspaceDenied = $true }
if (-not $workspaceDenied) { throw 'Startup must reject another workspace metadata' }
@{strict_stop=$stopDenied;foreign_workspace=$workspaceDenied;fixture_exists=(Test-Path -LiteralPath $runtimeFile)} | ConvertTo-Json -Compress
'''
    result = subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',script],
                            env=environment,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'strict_stop':True,'foreign_workspace':True,'fixture_exists':True}
