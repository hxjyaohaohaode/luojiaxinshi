$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:DATA_DIR = Join-Path (Get-Location) 'artifacts\browser-test-data'
$env:APP_ORIGIN = 'http://127.0.0.1:8766'
$env:APP_PORT = '8766'
$env:APP_HOST = '127.0.0.1'
$env:MIMO_API_KEY = ''
& '.\.venv\Scripts\python.exe' manage.py init
& '.\.venv\Scripts\python.exe' manage.py serve
