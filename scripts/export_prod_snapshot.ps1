$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$PrivateDir = Join-Path $RepoRoot ".local-run"
$UserProfile = [Environment]::GetFolderPath("UserProfile")
$SshKey = Join-Path $UserProfile ".ssh\id_ed25519_hill_yu"
$KnownHosts = Join-Path $UserProfile ".ssh\known_hosts"
$ProdTarget = "root@104.244.92.6"
$ProdEnvFile = "/www/releases/sdk-platform/current/backend/.env"
$SnapshotStart = "2026-10-17T16:00:00Z"
$SnapshotEnd = "2026-10-18T14:58:52Z"
$BatchSize = 500
$MaxRows = 100000
$MaxBytes = 200MB
$DelayMs = 250

if (-not (Test-Path -LiteralPath $PrivateDir)) { New-Item -ItemType Directory -Path $PrivateDir | Out-Null }
if (-not (Test-Path -LiteralPath $SshKey)) { throw "Missing SSH key" }
if (-not (Test-Path -LiteralPath $KnownHosts)) { throw "Missing known_hosts" }

$sshArgs = @(
  "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=5",
  "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=$KnownHosts",
  "-i", $SshKey, $ProdTarget
)

function Invoke-ProdBatch([string] $sql) {
  $sql64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sql))
  $remote = "envfile=$ProdEnvFile; dburl=`$(grep -m1 '^DATABASE_URL=' `"`$envfile`" | cut -d= -f2-); dbpass=`$(grep -m1 '^DB_PASSWORD=' `"`$envfile`" | cut -d= -f2-); dburl=`${dburl//\$\{DB_PASSWORD\}/`$dbpass}; dburl=`${dburl/postgresql+asyncpg/postgresql}; echo $sql64 | base64 -d | psql `"`$dburl`" -X -qAt -v ON_ERROR_STOP=1"
  $out = & ssh @sshArgs $remote
  if ($LASTEXITCODE -ne 0) { throw "Production batch failed; stopped without retry" }
  return @($out | Where-Object { $_ -match '^\s*\{' })
}

function Export-Table([string] $name, [string] $cursorShape, [string] $fileName) {
  $path = Join-Path $PrivateDir $fileName
  if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
  $header = "{`"table`":`"$name`",`"snapshot_start`":`"$SnapshotStart`",`"snapshot_end`":`"$SnapshotEnd`"}"
  [IO.File]::WriteAllText($path, $header + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
  $rows = 0
  $bytes = [IO.File]::Length($path)
  $lastId = 0L
  $lastTs = "1970-01-01T00:00:00Z"
  while ($true) {
    if ($rows -ge $MaxRows -or $bytes -ge $MaxBytes) { throw "$name export limit exceeded; incomplete" }
    $sql = if ($name -eq "events") {
      "BEGIN; SET TRANSACTION READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT json_build_object('id',id,'server_ts',server_ts,'package_name',package_name,'event_type',event_type,'device_id',device_id,'sdk_version',sdk_version,'session_id',session_id,'payload',payload,'client_ts',client_ts)::text FROM sdk_events WHERE server_ts >= '$SnapshotStart'::timestamptz AND server_ts < '$SnapshotEnd'::timestamptz AND (id > $lastId OR (id = $lastId AND server_ts > '$lastTs'::timestamptz)) ORDER BY id,server_ts LIMIT $BatchSize; ROLLBACK;"
    } else {
      "BEGIN; SET TRANSACTION READ ONLY; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='1s'; SELECT json_build_object('id',id,'server_ts',server_ts,'package_name',package_name,'device_id',device_id,'device_model',device_model,'os',os,'app_version',app_version,'sdk_version',sdk_version,'duration_s',duration_s)::text FROM sdk_usage_durations WHERE server_ts >= '$SnapshotStart'::timestamptz AND server_ts < '$SnapshotEnd'::timestamptz AND (server_ts > '$lastTs'::timestamptz OR (server_ts = '$lastTs'::timestamptz AND id > $lastId)) ORDER BY server_ts,id LIMIT $BatchSize; ROLLBACK;"
    }
    $batch = @(Invoke-ProdBatch $sql)
    foreach ($line in $batch) {
      [IO.File]::AppendAllText($path, $line.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
      $obj = $line | ConvertFrom-Json
      $lastId = [int64]$obj.id
      $lastTs = [string]$obj.server_ts
      $rows++
    }
    $bytes = [IO.File]::Length($path)
    if ($batch.Count -lt $BatchSize) { break }
    Start-Sleep -Milliseconds $DelayMs
  }
  Write-Output "$name rows=$rows bytes=$bytes file=$path"
}

Export-Table "events" "id,server_ts" "prod-events-20261018.jsonl"
Export-Table "usage" "server_ts,id" "prod-usage-20261018.jsonl"
