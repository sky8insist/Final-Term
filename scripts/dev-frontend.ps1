$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $projectRoot 'scripts\enable-utf8.ps1')
$frontendDir = Join-Path $projectRoot 'frontend'
if (-not (Test-Path (Join-Path $frontendDir 'package.json'))) {
    throw 'Missing frontend\package.json.'
}
Set-Location -LiteralPath $frontendDir
& npm.cmd run dev
