$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$services = Join-Path $env:RUNNER_TEMP 'historykg-services'
$logs = Join-Path $env:GITHUB_WORKSPACE '.local/windows-validation'
New-Item -ItemType Directory -Force $services, $logs | Out-Null

$pgZip = Join-Path $services 'postgresql-16.4.zip'
$neoZip = Join-Path $services 'neo4j-5.26.0.zip'
Invoke-WebRequest 'https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip' -OutFile $pgZip
Invoke-WebRequest 'https://dist.neo4j.org/neo4j-community-5.26.0-windows.zip' -OutFile $neoZip
Get-FileHash $pgZip, $neoZip -Algorithm SHA256 | Format-Table | Out-File (Join-Path $logs 'download-hashes.txt') -Encoding utf8
Expand-Archive $pgZip -DestinationPath $services
Expand-Archive $neoZip -DestinationPath $services

$pgBin = Join-Path $services 'pgsql/bin'
$pgData = Join-Path $services 'pgdata'
& "$pgBin/initdb.exe" -D $pgData -U collector -A trust --encoding=UTF8 --locale=C
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL initdb failed' }
& "$pgBin/pg_ctl.exe" -D $pgData -l (Join-Path $logs 'postgres.log') -o '-h 127.0.0.1 -p 16432' -w start
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL start failed' }
foreach ($database in @('collector_test', 'historykg_windows')) {
    & "$pgBin/createdb.exe" -h 127.0.0.1 -p 16432 -U collector $database
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL createdb failed: $database" }
}
& "$pgBin/psql.exe" -h 127.0.0.1 -p 16432 -U collector -d collector_test -c 'select version(); create extension if not exists pg_trgm;'
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL version/extension check failed' }

$neoHome = Join-Path $services 'neo4j-community-5.26.0'
@'
server.default_listen_address=127.0.0.1
server.bolt.listen_address=:17687
server.http.listen_address=:17474
dbms.security.auth_enabled=false
server.memory.heap.initial_size=256m
server.memory.heap.max_size=512m
server.memory.pagecache.size=128m
'@ | Add-Content (Join-Path $neoHome 'conf/neo4j.conf') -Encoding utf8
$env:NEO4J_HOME = $neoHome
$arguments = '/d /c ""' + (Join-Path $neoHome 'bin/neo4j.bat') + '" console"'
$process = Start-Process -FilePath $env:ComSpec -ArgumentList $arguments -WorkingDirectory $neoHome `
    -RedirectStandardOutput (Join-Path $logs 'neo4j.stdout.log') `
    -RedirectStandardError (Join-Path $logs 'neo4j.stderr.log') -PassThru
$healthy = $false
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $response = Invoke-WebRequest 'http://127.0.0.1:17474' -UseBasicParsing
        if ($response.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 2 }
    if ($process.HasExited) { break }
}
if (-not $healthy) {
    Get-Content (Join-Path $logs 'neo4j.stderr.log') -Tail 80
    throw 'Neo4j did not become healthy'
}
& python -c "from neo4j import GraphDatabase; d=GraphDatabase.driver('bolt://127.0.0.1:17687', auth=None); d.verify_connectivity(); d.close()"
if ($LASTEXITCODE -ne 0) { throw 'Neo4j Bolt connectivity failed' }
Write-Output 'Native Windows PostgreSQL 16.4 and Neo4j 5.26.0 are healthy.'
