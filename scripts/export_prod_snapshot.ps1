$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$PrivateRoot = Join-Path $RepoRoot ".local-run"
$RunDir = Join-Path $PrivateRoot ("prod-snapshot-20261018-" + (Get-Date -Format yyyyMMdd-HHmmssfff))
$UserProfile = [Environment]::GetFolderPath("UserProfile")
$SshKey = Join-Path $UserProfile ".ssh\id_ed25519_hill_yu"
$KnownHosts = Join-Path $UserProfile ".ssh\known_hosts"
$ProdTarget = "root@104.244.92.6"
$ProdEnvFile = "/www/releases/sdk-platform/current/backend/.env"
$SnapshotStart = "2026-10-17T16:00:00Z"
$SnapshotEnd = "2026-10-18T14:58:52Z"
$BatchSize = 500; $MaxRows = 100000; $MaxBytes = 200MB; $DelayMs = 250
$script:TotalRows = 0; $script:TotalBytes = 0L
if (Test-Path -LiteralPath $RunDir) { throw "Refusing to reuse existing run directory" }
New-Item -ItemType Directory -Path $RunDir | Out-Null
if (-not (Test-Path -LiteralPath $SshKey)) { throw "Missing SSH key" }
if (-not (Test-Path -LiteralPath $KnownHosts)) { throw "Missing known_hosts" }
$sshArgs = @("-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","ConnectTimeout=5","-o","StrictHostKeyChecking=yes","-o","UserKnownHostsFile=$KnownHosts","-i",$SshKey,$ProdTarget)

function Invoke-ProdBatch([string] $sql) {
  $sql64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sql))
  $remote = 'envfile=/www/releases/sdk-platform/current/backend/.env; raw=$(grep -m1 "^DATABASE_URL=" "$envfile" | cut -d= -f2-); dbpass=$(grep -m1 "^DB_PASSWORD=" "$envfile" | cut -d= -f2-); raw=${raw#*://}; authority=${raw%%/*}; dbname=${raw#*/}; hostport=${authority##*@}; dbuser=${authority%%:*}; host=${hostport%%:*}; port=${hostport##*:}; echo ' + $sql64 + ' | base64 -d | PGPASSWORD="$dbpass" psql -h "$host" -p "$port" -U "$dbuser" -d "$dbname" -X -qAt -v ON_ERROR_STOP=1'
  $out = & ssh @sshArgs $remote
  if ($LASTEXITCODE -ne 0) { throw "Production batch failed; stopped without retry" }
  return @($out | Where-Object { $_ -match '^\s*\{' })
}

function Export-Table([string] $name, [string] $fileName) {
  $partial = Join-Path $RunDir ($fileName + ".partial"); $final = Join-Path $RunDir $fileName
  $header = "{`"table`":`"$name`",`"snapshot_start`":`"$SnapshotStart`",`"snapshot_end`":`"$SnapshotEnd`"}"
  [IO.File]::WriteAllText($partial, $header + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
  $rows = 0; $lastId = 0L; $lastTs = "1970-01-01T00:00:00Z"; $minTs = $null; $maxTs = $null
  while ($true) {
    if ($rows -ge $MaxRows -or $script:TotalBytes -ge $MaxBytes) { throw "$name export limit exceeded; incomplete" }
    if ($name -eq "events") {
      $sql = "BEGIN; SET TRANSACTION READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT json_build_object('id',id,'server_ts',server_ts,'package_name',package_name,'event_type',event_type,'device_id',device_id,'sdk_version',sdk_version,'session_id',session_id,'payload',payload,'client_ts',client_ts)::text FROM sdk_events WHERE server_ts >= '$SnapshotStart'::timestamptz AND server_ts < '$SnapshotEnd'::timestamptz AND (id > $lastId OR (id = $lastId AND server_ts > '$lastTs'::timestamptz)) ORDER BY id,server_ts LIMIT $BatchSize; ROLLBACK;"
    } else {
      $sql = "BEGIN; SET TRANSACTION READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT json_build_object('id',id,'server_ts',server_ts,'package_name',package_name,'device_id',device_id,'device_model',device_model,'os',os,'app_version',app_version,'sdk_version',sdk_version,'duration_s',duration_s)::text FROM sdk_usage_durations WHERE server_ts >= '$SnapshotStart'::timestamptz AND server_ts < '$SnapshotEnd'::timestamptz AND (server_ts > '$lastTs'::timestamptz OR (server_ts = '$lastTs'::timestamptz AND id > $lastId)) ORDER BY server_ts,id LIMIT $BatchSize; ROLLBACK;"
    }
    $batch = @(Invoke-ProdBatch $sql)
    foreach ($line in $batch) { [IO.File]::AppendAllText($partial, $line.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false)); $obj = $line | ConvertFrom-Json; $lastId = [int64]$obj.id; $lastTs = [string]$obj.server_ts; $ts = [datetimeoffset]::Parse($lastTs); if ($null -eq $minTs -or $ts -lt $minTs) { $minTs = $ts }; if ($null -eq $maxTs -or $ts -gt $maxTs) { $maxTs = $ts }; $rows++; $script:TotalRows++; $script:TotalBytes += [Text.Encoding]::UTF8.GetByteCount($line) + 1 }
    if ((Get-Item -LiteralPath $partial).Length -gt $MaxBytes) { throw "$name file limit exceeded; incomplete" }
    if ($batch.Count -lt $BatchSize) { break }; Start-Sleep -Milliseconds $DelayMs
  }
  Move-Item -LiteralPath $partial -Destination $final
  $minOut = if ($minTs) { $minTs.ToUniversalTime().ToString("o") } else { $null }; $maxOut = if ($maxTs) { $maxTs.ToUniversalTime().ToString("o") } else { $null }
  [pscustomobject]@{ table=$name; file=$fileName; rows=$rows; bytes=(Get-Item -LiteralPath $final).Length; sha256=(Get-FileHash -LiteralPath $final -Algorithm SHA256).Hash; min_ts=$minOut; max_ts=$maxOut }
}
$metadata = @((Export-Table "events" "prod-events-20261018.jsonl"),(Export-Table "usage" "prod-usage-20261018.jsonl"))
$manifest = [pscustomobject]@{ complete=$true; snapshot_start=$SnapshotStart; snapshot_end=$SnapshotEnd; max_rows_per_table=$MaxRows; max_bytes_total=$MaxBytes; total_rows=$script:TotalRows; total_bytes=$script:TotalBytes; tables=$metadata }
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $RunDir "manifest.json") -Encoding utf8
Write-Output (ConvertTo-Json $manifest -Depth 5 -Compress)
