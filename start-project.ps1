[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$frontendDir = Join-Path $projectRoot 'frontend'
if (-not (Test-Path (Join-Path $frontendDir 'package.json'))) {
    throw 'Missing frontend\package.json.'
}
$viteExe = Join-Path $frontendDir 'node_modules\.bin\vite.cmd'
$runDir = Join-Path $projectRoot '.run'
$pidFile = Join-Path $runDir 'dev-processes.json'
$env:NO_PROXY = 'localhost,127.0.0.1'
$env:no_proxy = $env:NO_PROXY

function Test-Port([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Wait-Port([int]$Port, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

Write-Host '========================================' -ForegroundColor Cyan
Write-Host '       AI Study Workspace Launcher' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan

if (-not (Test-Path $pythonExe)) { throw 'Missing backend virtual environment: backend\.venv' }
if (-not (Test-Path $viteExe)) { throw 'Missing frontend dependencies. Run npm install in frontend first.' }

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$started = @()

docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not ready.' }

& (Join-Path $projectRoot 'scripts\start-local-supabase.ps1')
Push-Location (Join-Path $projectRoot 'backend')
try {
    docker compose -f docker-compose.worker.yml up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Redis and background workers failed to start.' }
} finally {
    Pop-Location
}

if (-not (Wait-Port 18000 60)) { throw 'Supabase gateway did not become ready on port 18000.' }
if (-not (Wait-Port 6379 30)) { throw 'Redis did not become ready on port 6379.' }

if (Test-Port 8000) {
    Write-Host '[Backend] Already running on port 8000.' -ForegroundColor Yellow
} else {
    $backendScript = Join-Path $projectRoot 'scripts\dev-backend.ps1'
    $process = Start-Process powershell.exe -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$backendScript`"" -PassThru
    $started += [pscustomobject]@{ name = 'backend'; pid = $process.Id }
    Write-Host '[Backend] Starting...' -ForegroundColor Green
}

if (Test-Port 5173) {
    Write-Host '[Frontend] Already running on port 5173.' -ForegroundColor Yellow
} else {
    $frontendScript = Join-Path $projectRoot 'scripts\dev-frontend.ps1'
    $process = Start-Process powershell.exe -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$frontendScript`"" -PassThru
    $started += [pscustomobject]@{ name = 'frontend'; pid = $process.Id }
    Write-Host '[Frontend] Starting...' -ForegroundColor Green
}

if ($started.Count -gt 0) {
    $started | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
}

$frontendReady = Wait-Port 5173
$backendReady = Wait-Port 8000
if ($frontendReady) {
    Write-Host '[Ready] Frontend: http://localhost:5173' -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process 'http://localhost:5173' }
} else {
    Write-Host '[Failed] Frontend did not start. Read the frontend terminal error.' -ForegroundColor Red
}
if ($backendReady) {
    Write-Host '[Ready] Backend: http://localhost:8000/docs' -ForegroundColor Green
} else {
    Write-Host '[Failed] Backend did not start. Read the backend terminal error.' -ForegroundColor Red
}
Write-Host '[Ready] Supabase: http://localhost:18000' -ForegroundColor Green
Write-Host '[Ready] Mailpit: http://localhost:8025' -ForegroundColor Green
Write-Host '[Ready] Redis: localhost:6379' -ForegroundColor Green

Write-Host ''
Write-Host 'Press Enter to close this launcher. Service terminals stay open.'
Read-Host | Out-Null
if (-not $frontendReady) { exit 1 }
