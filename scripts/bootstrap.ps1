param([string]$Python='python',[switch]$SkipDrawio)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if(-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')){
 & $Python -m venv .venv
 if($LASTEXITCODE -ne 0){throw 'Python 3.12+ is required. Use -Python with its executable path.'}
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
if($LASTEXITCODE -ne 0){throw 'Runtime dependency installation failed.'}
& .\.venv\Scripts\python.exe -m pip install -e '.[test]'
if($LASTEXITCODE -ne 0){throw 'Project installation failed.'}
if(-not $SkipDrawio){& .\.venv\Scripts\python.exe scripts/install_drawio.py;if($LASTEXITCODE -ne 0){throw 'draw.io installation failed.'}}
npm.cmd --prefix frontend ci
if($LASTEXITCODE -ne 0){throw 'Frontend installation failed.'}
npm.cmd --prefix frontend run build
if($LASTEXITCODE -ne 0){throw 'Frontend build failed.'}
Write-Host 'Ready: scripts/run.ps1'
