$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot '.run\dev-processes.json'
if (Test-Path $pidFile) {
    $items = @((Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json))
    $items = @($items | ForEach-Object { if ($_ -is [System.Array]) { $_ } else { $_ } })
} else {
    $items = @()
    Write-Host 'No process record found; stopping container services.'
}
foreach ($item in $items) {
    if ($null -eq $item.pid) { continue }
    $processId = [int]$item.pid
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        & taskkill.exe /PID $processId /T /F | Out-Host
    }
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Push-Location (Join-Path $projectRoot 'backend')
try { docker compose -f docker-compose.worker.yml stop | Out-Host } finally { Pop-Location }
& (Join-Path $projectRoot 'scripts\stop-local-supabase.ps1')
Write-Host 'Project services stopped.'
