[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$supabaseDir = Join-Path $projectRoot 'supabase-project'

Push-Location $supabaseDir
try {
    docker compose stop
    if ($LASTEXITCODE -ne 0) { throw 'Supabase failed to stop cleanly' }
    Write-Host 'Supabase containers stopped; local data was preserved.' -ForegroundColor Green
} finally {
    Pop-Location
}
