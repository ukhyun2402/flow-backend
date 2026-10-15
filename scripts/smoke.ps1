$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& .\.venv\Scripts\python.exe scripts/smoke.py
if($LASTEXITCODE -ne 0){throw 'Python smoke verification failed.'}
