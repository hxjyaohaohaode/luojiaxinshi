$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\local-runtime.ps1')
if (-not (Test-Path -LiteralPath $taskPython)) { Write-Host 'Application is not installed.'; exit 0 }
$configuration = Get-TaskConfiguration
Stop-OwnedTask $configuration
Write-Host 'Campus Notice is stopped. Saved data is retained.'
