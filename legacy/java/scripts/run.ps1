param([int]$Port=8080)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if(-not $env:JAVA_HOME){$env:JAVA_HOME=Split-Path -Parent (Split-Path -Parent (Get-Command java).Source)}
if(-not (Test-Path -LiteralPath 'target/flow-platform-0.1.0.jar')){throw 'Build first: npm --prefix frontend ci; npm --prefix frontend run build; Maven package (see README.md)'}
if(-not $env:FLOW_ADMIN_TOKEN){$env:FLOW_ADMIN_TOKEN=[guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N')}
$env:PORT=$Port
Write-Host "Flow Studio: http://127.0.0.1:$Port"
Write-Host 'Paste this local development token into the API token field:'
Write-Host $env:FLOW_ADMIN_TOKEN
& (Join-Path $env:JAVA_HOME 'bin/java.exe') -jar target/flow-platform-0.1.0.jar
