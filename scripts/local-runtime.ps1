$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskManage = Join-Path $taskRoot 'manage.py'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Get-TaskConfiguration {
    $json = & $taskPython $taskManage runtime --local-env
    if ($LASTEXITCODE -ne 0) { throw 'Invalid .env configuration.' }
    return ($json | ConvertFrom-Json)
}

function Get-OwnedTaskProcess($configuration) {
    $runtimeFile = Join-Path $configuration.data_dir 'campus-runtime.json'
    if (-not (Test-Path -LiteralPath $runtimeFile)) { return $null }
    $runtime = Get-Content -LiteralPath $runtimeFile -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($runtime.root -ne $taskRoot) { throw 'Runtime belongs to another project directory.' }
    $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$runtime.pid)
    if (-not $process) { return $null }
    # Verify identity before stopping or reusing a PID, which Windows can recycle.
    if ($process.CommandLine -notlike ('*"' + $taskManage + '" serve*') -and
        $process.CommandLine -notlike ('*' + $taskManage + ' serve*')) {
        throw 'Runtime PID no longer identifies this application. No process was changed.'
    }
    return $process
}

function Stop-OwnedTask($configuration) {
    $process = Get-OwnedTaskProcess $configuration
    if ($process) {
        Stop-Process -Id $process.ProcessId -ErrorAction Stop
        Wait-Process -Id $process.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    $runtimeFile = Join-Path $configuration.data_dir 'campus-runtime.json'
    if (Test-Path -LiteralPath $runtimeFile) { Remove-Item -LiteralPath $runtimeFile }
}
