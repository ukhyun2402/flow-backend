param([int]$Port=8080)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if(-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')){throw 'Run scripts/bootstrap.ps1 first.'}
if(-not (Test-Path -LiteralPath 'frontend/dist/index.html')){throw 'Build the UI first: npm.cmd --prefix frontend run build'}
$env:PORT=$Port
$env:FLOW_LOCAL_WORKSPACE='1'
Write-Host "Flow Studio: http://127.0.0.1:$Port"
Write-Host 'Local workspace opens automatically. No token input is needed.'
& .\.venv\Scripts\python.exe -m uvicorn flowstudio.app:app --host 127.0.0.1 --port $Port
