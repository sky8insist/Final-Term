$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $projectRoot 'scripts\enable-utf8.ps1')
$backendDir = Join-Path $projectRoot 'backend'
$pythonExe = Join-Path $backendDir '.venv\Scripts\python.exe'
$env:NO_PROXY = 'localhost,127.0.0.1,mineru.net,.aliyuncs.com'
$env:no_proxy = $env:NO_PROXY
Set-Location -LiteralPath $backendDir
& $pythonExe -m app.worker.recover
if ($LASTEXITCODE -ne 0) { throw 'Unable to recover unfinished material tasks.' }
& $pythonExe -m celery -A app.worker.celery_app:celery_app worker --loglevel=info --pool=solo --concurrency=1
