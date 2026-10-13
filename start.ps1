param([string]$PythonPath = '', [switch]$NoBrowser, [switch]$Restart)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\local-runtime.ps1')
if (-not (Test-Path -LiteralPath $taskPython)) {
    if (-not $PythonPath) {
        $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundledPython) { $PythonPath = $bundledPython } else { $PythonPath = 'python' }
    }
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12+ with venv, or specify -PythonPath.' }
}
& $taskPython (Join-Path $taskRoot 'scripts\check_dependencies.py')
if ($LASTEXITCODE -ne 0) {
    & $taskPython -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and retry.' }
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$configuration = Get-TaskConfiguration
$expectedVersion = (& $taskPython -c "from app.version import VERSION; print(VERSION)").Trim()
if ($configuration.production) { throw 'Use OPERATIONS.md for production HTTPS deployment.' }
if ($Restart) { Stop-OwnedTask $configuration }
$existing = Get-OwnedTaskProcess $configuration
if (-not $existing) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $configuration.port -ErrorAction SilentlyContinue
    if ($listener) { throw ('Port ' + $configuration.port + ' is occupied. Change APP_PORT and APP_ORIGIN together.') }
    & $taskPython $taskManage init
    if ($LASTEXITCODE -ne 0) { throw 'Initialization failed.' }
    $logDirectory = Join-Path $configuration.data_dir 'logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    foreach ($filename in @('server.log','server-error.log')) {
        $logFile = Join-Path $logDirectory $filename
        if ((Test-Path -LiteralPath $logFile) -and (Get-Item -LiteralPath $logFile).Length -gt 2MB) {
            Copy-Item -LiteralPath $logFile -Destination ($logFile + '.previous') -Force
        }
    }
    Start-Process -FilePath $taskPython -ArgumentList @(('"' + $taskManage + '"'),'serve') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'server.log') -RedirectStandardError (Join-Path $logDirectory 'server-error.log') | Out-Null
}
$ready = $false
for ($attempt=0; $attempt -lt 40; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri ($configuration.origin + '/api/health') -TimeoutSec 2
        if ($health.status -eq 'ok' -and $health.version -eq $expectedVersion) { $ready=$true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) { throw ('Startup did not become healthy. Read ' + $configuration.data_dir + '\logs\server-error.log') }
$openUrl = $configuration.origin
$setupFile = Join-Path $configuration.data_dir 'admin-setup.url.txt'
if (Test-Path -LiteralPath $setupFile) { $openUrl=(Get-Content -LiteralPath $setupFile -Encoding UTF8 -Raw).Trim() }
Write-Host ('Campus Notice is ready: ' + $configuration.origin)
Write-Host 'The service runs in the background. Use stop.ps1 to stop, or start.ps1 -Restart after changing .env.'
if (-not $NoBrowser) { Start-Process $openUrl }
