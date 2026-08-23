$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $projectRoot 'scripts\enable-utf8.ps1')
$backendDir = Join-Path $projectRoot 'backend'
$pythonExe = Join-Path $backendDir '.venv\Scripts\python.exe'
$env:NO_PROXY = 'localhost,127.0.0.1'
$env:no_proxy = $env:NO_PROXY
Set-Location -LiteralPath $backendDir
& $pythonExe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
