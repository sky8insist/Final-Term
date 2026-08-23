[CmdletBinding()]
param(
    [string]$EnvPath = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env'),
    [string]$TemplatePath = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env.example')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'enable-utf8.ps1')

$envFile = (Resolve-Path -LiteralPath $EnvPath).Path
$templateFile = (Resolve-Path -LiteralPath $TemplatePath).Path
$projectRoot = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $projectRoot '.run\env-encoding-backups'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupPath = Join-Path $backupDir ('.env.' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bak')
Copy-Item -LiteralPath $envFile -Destination $backupPath

$assignmentPattern = '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*='
$currentAssignments = [ordered]@{}
foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
    if ($line -match $assignmentPattern -and -not $line.TrimStart().StartsWith('#')) {
        $currentAssignments[$Matches[1]] = $line
    }
}

# These entries were embedded in corrupted comment lines in the affected file.
# Keep the current real-provider behavior instead of copying the demo-mode value.
$safeRecoveredDefaults = @{
    MOCK_EXTERNAL_APIS = 'MOCK_EXTERNAL_APIS=false'
}

$templateKeys = [System.Collections.Generic.HashSet[string]]::new()
$repairedLines = [System.Collections.Generic.List[string]]::new()
foreach ($line in Get-Content -LiteralPath $templateFile -Encoding UTF8) {
    if ($line -match $assignmentPattern -and -not $line.TrimStart().StartsWith('#')) {
        $key = $Matches[1]
        $null = $templateKeys.Add($key)
        if ($currentAssignments.Contains($key)) {
            $repairedLines.Add([string]$currentAssignments[$key])
        } elseif ($safeRecoveredDefaults.ContainsKey($key)) {
            $repairedLines.Add([string]$safeRecoveredDefaults[$key])
        } else {
            $repairedLines.Add($line)
        }
    } else {
        $repairedLines.Add($line)
    }
}

$localOnlyKeys = @($currentAssignments.Keys | Where-Object { -not $templateKeys.Contains($_) })
if ($localOnlyKeys.Count -gt 0) {
    $repairedLines.Add('')
    $repairedLines.Add('# Local-only settings preserved from the previous .env')
    foreach ($key in $localOnlyKeys) {
        $repairedLines.Add([string]$currentAssignments[$key])
    }
}

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$content = ($repairedLines -join "`n").TrimEnd() + "`n"
[System.IO.File]::WriteAllText($envFile, $content, $utf8NoBom)

Write-Host "Repaired .env comments and UTF-8 formatting."
Write-Host "Backup: $backupPath"
Write-Host "Preserved configured values: $($currentAssignments.Count)"
