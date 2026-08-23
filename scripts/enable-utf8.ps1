# Keep project logs and Chinese text consistent on Windows PowerShell 5 and 7.
$projectUtf8Encoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $projectUtf8Encoding
[Console]::OutputEncoding = $projectUtf8Encoding
$OutputEncoding = $projectUtf8Encoding
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$PSDefaultParameterValues['Get-Content:Encoding'] = 'UTF8'
