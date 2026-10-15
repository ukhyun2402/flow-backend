$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$tools=Join-Path $root '.tools'
New-Item -ItemType Directory -Path $tools -Force | Out-Null
$url='https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.11/apache-maven-3.9.11-bin.zip'
$zip=Join-Path $tools 'maven.zip'
if(-not (Test-Path -LiteralPath (Join-Path $tools 'apache-maven-3.9.11/bin/mvn.cmd'))){
 Invoke-WebRequest -Uri $url -OutFile $zip
 $expected=(Invoke-RestMethod -Uri ($url+'.sha512')).Trim().Split(' ')[0]
 if((Get-FileHash -LiteralPath $zip -Algorithm SHA512).Hash.ToLowerInvariant() -ne $expected.ToLowerInvariant()){throw 'Maven SHA512 mismatch'}
 Expand-Archive -LiteralPath $zip -DestinationPath $tools -Force
}
Write-Host 'Maven ready: .tools/apache-maven-3.9.11/bin/mvn.cmd'
