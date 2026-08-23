[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$supabaseEnvPath = Join-Path $projectRoot 'supabase-project\.env'
$appEnvPath = Join-Path $projectRoot '.env'
$workerEnvPath = Join-Path $projectRoot 'backend\.env.worker'

if (-not (Test-Path -LiteralPath $supabaseEnvPath)) {
    throw 'Missing supabase-project\.env'
}
if (-not (Test-Path -LiteralPath $appEnvPath)) {
    throw 'Missing project .env'
}

function Read-Env([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $parts = $line -split '=', 2
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Set-EnvValue([System.Collections.Generic.List[string]]$Lines, [string]$Name, [string]$Value) {
    $prefix = "$Name="
    for ($index = 0; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index].StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            $Lines[$index] = "$prefix$Value"
            return
        }
    }
    $Lines.Add("$prefix$Value")
}

$supabase = Read-Env $supabaseEnvPath
$required = @('POSTGRES_PASSWORD', 'JWT_SECRET', 'ANON_KEY', 'SERVICE_ROLE_KEY', 'POOLER_TENANT_ID')
foreach ($name in $required) {
    if (-not $supabase[$name] -or $supabase[$name] -match '^(your-|this_password)') {
        throw "Supabase value $name has not been generated"
    }
}

$password = [Uri]::EscapeDataString($supabase['POSTGRES_PASSWORD'])
$tenant = $supabase['POOLER_TENANT_ID']
$updates = [ordered]@{
    'SUPABASE_URL' = 'http://localhost:18000'
    # Docker containers must reach services through the host gateway; inside a
    # container, localhost points back to that container rather than Windows.
    'CONTAINER_SUPABASE_URL' = 'http://host.docker.internal:18000'
    'SUPABASE_ANON_KEY' = $supabase['ANON_KEY']
    'SUPABASE_SERVICE_ROLE_KEY' = $supabase['SERVICE_ROLE_KEY']
    'SUPABASE_JWT_SECRET' = $supabase['JWT_SECRET']
    'DATABASE_URL' = "postgresql://postgres.$tenant`:$password@localhost:5432/postgres"
    'CONTAINER_DATABASE_URL' = "postgresql://postgres.$tenant`:$password@host.docker.internal:5432/postgres"
    'VITE_SUPABASE_URL' = 'http://localhost:18000'
    'VITE_SUPABASE_ANON_KEY' = $supabase['ANON_KEY']
}

$lines = [System.Collections.Generic.List[string]]::new()
$lines.AddRange([string[]](Get-Content -LiteralPath $appEnvPath))
foreach ($entry in $updates.GetEnumerator()) {
    Set-EnvValue $lines $entry.Key $entry.Value
}
[System.IO.File]::WriteAllLines($appEnvPath, $lines, [System.Text.UTF8Encoding]::new($false))

# Compose env_file values are injected directly into the container. Keeping
# this generated file separate lets host processes use localhost while Docker
# processes use the Windows host gateway, without committing database secrets.
$workerLines = @(
    "SUPABASE_URL=http://host.docker.internal:18000"
    "DATABASE_URL=postgresql://postgres.$tenant`:$password@host.docker.internal:5432/postgres"
)
[System.IO.File]::WriteAllLines($workerEnvPath, $workerLines, [System.Text.UTF8Encoding]::new($false))

Write-Output 'Application and worker Supabase settings synchronized (secret values hidden).'
