[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$supabaseDir = Join-Path $projectRoot 'supabase-project'

if (-not (Test-Path -LiteralPath (Join-Path $supabaseDir 'docker-compose.yml'))) {
    throw 'Missing supabase-project\docker-compose.yml'
}

Push-Location $supabaseDir
try {
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Supabase failed to start' }
    Write-Host 'Supabase is ready at http://localhost:18000' -ForegroundColor Green
} finally {
    Pop-Location
}
