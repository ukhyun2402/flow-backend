param([string]$JavaHome = $env:JAVA_HOME)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if (-not $JavaHome) { $JavaHome = Split-Path -Parent (Split-Path -Parent (Get-Command java).Source) }
$java = Join-Path $JavaHome 'bin/java.exe'
$maven = Join-Path $root '.tools/apache-maven-3.9.11/bin/mvn.cmd'
$repo = Join-Path $root '.tools/repository'
$env:JAVA_HOME = $JavaHome
$work = Join-Path $root ('.tools/smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$adminToken = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$runtimeToken = [guid]::NewGuid().ToString('N')
$env:FLOW_ADMIN_TOKEN = $adminToken
$env:FLOW_RUNTIME_TOKEN = $runtimeToken
$env:FLOW_DATA = Join-Path $work 'data'
$env:PORT = '18080'
$platform = $null
$runtime = $null
function Wait-Http([string]$url, [System.Diagnostics.Process]$process) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($process.HasExited) { throw "Server exited. Inspect logs in $work" }
        try { $null = Invoke-WebRequest -Uri $url -TimeoutSec 2 -SkipHttpErrorCheck; return } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "Server startup timed out: $url"
}
function Assert([bool]$value, [string]$message) { if (-not $value) { throw $message } }
try {
    $platform = Start-Process -FilePath $java -ArgumentList '-jar', 'target/flow-platform-0.1.0.jar' -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $work 'platform.log') -RedirectStandardError (Join-Path $work 'platform.err.log')
    Wait-Http 'http://127.0.0.1:18080/' $platform
    $headers = @{ Authorization = "Bearer $adminToken" }
    $flowText = Get-Content -LiteralPath (Join-Path $root 'examples/hello-flow.json') -Raw
    $flow = $flowText | ConvertFrom-Json
    $validation = Invoke-RestMethod 'http://127.0.0.1:18080/api/validate' -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($flowText))
    Assert $validation.valid 'Sample flow validation failed'
    $previewBody = @{ flow = $flow; input = @{ name = 'test' } } | ConvertTo-Json -Depth 80
    $preview = Invoke-RestMethod 'http://127.0.0.1:18080/api/preview' -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($previewBody))
    Assert ($preview.status -eq 200 -and $preview.trace.Count -eq 3) 'Preview failed'
    $zip = Join-Path $work 'generated.zip'
    Invoke-WebRequest 'http://127.0.0.1:18080/api/generate' -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($flowText)) -OutFile $zip
    $generated = Join-Path $work 'generated'
    Expand-Archive -LiteralPath $zip -DestinationPath $generated
    Assert (-not (Test-Path -LiteralPath (Join-Path $generated 'src/main/java/dev/flow/platform'))) 'Management source leaked into generated server'
    & $maven "-Dmaven.repo.local=$repo" -f (Join-Path $generated 'pom.xml') package -q
    if ($LASTEXITCODE -ne 0) { throw 'Generated project build failed' }
    $env:PORT = '18081'
    $runtime = Start-Process -FilePath $java -ArgumentList '-jar', 'target/flow-platform-0.1.0.jar' -WorkingDirectory $generated -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $work 'runtime.log') -RedirectStandardError (Join-Path $work 'runtime.err.log')
    Wait-Http 'http://127.0.0.1:18081/hello' $runtime
    $unauthorized = Invoke-WebRequest 'http://127.0.0.1:18081/hello' -Method Post -ContentType 'application/json' -Body '{"name":"test"}' -SkipHttpErrorCheck
    Assert ($unauthorized.StatusCode -eq 401) 'Generated API must require authentication'
    $response = Invoke-RestMethod 'http://127.0.0.1:18081/hello' -Method Post -Headers @{Authorization="Bearer $runtimeToken"} -ContentType 'application/json' -Body '{"name":"test"}'
    Assert ($response.message -eq $preview.body.message) 'Preview and generated runtime differ'
    $missing = Invoke-WebRequest 'http://127.0.0.1:18081/api/flows' -Headers $headers -SkipHttpErrorCheck
    Assert ($missing.StatusCode -eq 404) 'Management route exists in generated server'
    Write-Output 'PASS: authenticated platform preview -> ZIP export -> independent Maven build -> protected generated API; management routes absent.'
    Write-Output "Artifacts: $work"
} finally {
    if ($runtime -and -not $runtime.HasExited) { Stop-Process -Id $runtime.Id }
    if ($platform -and -not $platform.HasExited) { Stop-Process -Id $platform.Id }
    Remove-Item Env:FLOW_ADMIN_TOKEN, Env:FLOW_RUNTIME_TOKEN, Env:FLOW_DATA, Env:PORT -ErrorAction SilentlyContinue
}
