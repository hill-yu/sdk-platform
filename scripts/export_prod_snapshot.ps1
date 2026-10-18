$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$PrivateRoot = Join-Path $RepoRoot ".local-run"
$RunDir = Join-Path $PrivateRoot ("prod-snapshot-20261018-" + (Get-Date -Format yyyyMMdd-HHmmssfff))
$isFake = $env:SNAPSHOT_EXPORT_FAKE_RUNNER -eq "1"
if ($isFake -and $env:SNAPSHOT_EXPORT_TEST_RUN_DIR) { $RunDir = $env:SNAPSHOT_EXPORT_TEST_RUN_DIR }
$UserProfile = [Environment]::GetFolderPath("UserProfile")
$SshKey = Join-Path $UserProfile ".ssh\id_ed25519_hill_yu"
$KnownHosts = Join-Path $UserProfile ".ssh\known_hosts"
$ProdTarget = "root@104.244.92.6"
$RemoteCommand = "cd /www/releases/sdk-platform/current/backend && /www/releases/sdk-platform/current/backend/venv/bin/python -"
$SnapshotStart = "2026-10-17T16:00:00Z"
$SnapshotEnd = "2026-10-18T14:58:52Z"
$BatchSize = 500; $MaxRows = 100000; $MaxBytes = 200MB
if ($isFake -and $env:SNAPSHOT_EXPORT_TEST_MAX_ROWS) { $MaxRows = [int]$env:SNAPSHOT_EXPORT_TEST_MAX_ROWS }
$script:TotalRows = 0; $script:TotalBytes = 0L; $script:Completed = $false
if (Test-Path -LiteralPath $RunDir) { throw "Refusing to reuse existing run directory" }
New-Item -ItemType Directory -Path $RunDir | Out-Null
if (-not (Test-Path -LiteralPath $SshKey)) { throw "Missing SSH key" }
if (-not (Test-Path -LiteralPath $KnownHosts)) { throw "Missing known_hosts" }
$sshArgs = @("-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","ConnectTimeout=5","-o","StrictHostKeyChecking=yes","-o","UserKnownHostsFile=$KnownHosts","-i",$SshKey,$ProdTarget)

$remotePython = @'
import asyncio, json, sys
from datetime import datetime, timezone
from urllib.parse import quote
import asyncpg

ENV_FILE = "/www/releases/sdk-platform/current/backend/.env"
START = "2026-10-17T16:00:00Z"
END = "2026-10-18T14:58:52Z"
BATCH = 500

def env_value(name):
    with open(ENV_FILE, encoding="utf-8") as stream:
        for line in stream:
            if line.startswith(name + "="):
                return line.rstrip("\n").split("=", 1)[1].strip().strip('"').strip("'")
    return ""

def db_url():
    raw = env_value("DATABASE_URL").replace("${DB_PASSWORD}", quote(env_value("DB_PASSWORD"), safe=""))
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)

def json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(type(value).__name__)

async def read_table(conn, table):
    rows = 0; last_id = 0; last_ts = datetime(1970, 1, 1, tzinfo=timezone.utc); minimum = None; maximum = None
    while True:
        if table == "events":
            sql = """SELECT id, server_ts, package_name, event_type, device_id, sdk_version, session_id, payload, client_ts
                     FROM sdk_events WHERE server_ts >= $1::timestamptz AND server_ts < $2::timestamptz
                       AND (id > $3 OR (id = $3 AND server_ts > $4::timestamptz))
                     ORDER BY id, server_ts LIMIT $5"""
        else:
            sql = """SELECT id, server_ts, package_name, device_id, device_model, os, app_version, sdk_version, duration_s
                     FROM sdk_usage_durations WHERE server_ts >= $1::timestamptz AND server_ts < $2::timestamptz
                       AND (server_ts > $4::timestamptz OR (server_ts = $4::timestamptz AND id > $3))
                     ORDER BY server_ts, id LIMIT $5"""
        async with conn.transaction():
            await conn.execute("SET TRANSACTION READ ONLY")
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            await conn.execute("SET LOCAL lock_timeout = '1s'")
            batch = await conn.fetch(sql, START, END, last_id, last_ts, BATCH)
        for record in batch:
            row = dict(record); current_ts = row["server_ts"]
            print(json.dumps({"kind": "row", "table": table, "row": row}, default=json_default, separators=(",", ":")), flush=True)
            last_id = int(row["id"]); last_ts = current_ts; minimum = current_ts if minimum is None or current_ts < minimum else minimum; maximum = current_ts if maximum is None or current_ts > maximum else maximum; rows += 1
        if len(batch) < BATCH:
            print(json.dumps({"kind": "table_complete", "table": table, "rows": rows, "min_ts": json_default(minimum) if minimum else None, "max_ts": json_default(maximum) if maximum else None}, separators=(",", ":")), flush=True)
            return
        await asyncio.sleep(0.25)

async def main():
    conn = await asyncpg.connect(db_url(), timeout=5)
    try:
        await read_table(conn, "events"); await read_table(conn, "usage")
        print(json.dumps({"kind": "complete", "snapshot_start": START, "snapshot_end": END}, separators=(",", ":")), flush=True)
    finally:
        await conn.close()

try:
    asyncio.run(main())
except Exception:
    print(json.dumps({"kind": "error", "error": "remote snapshot export failed"}), flush=True)
    sys.exit(1)
'@

function Export-Stream {
  $paths = @{ events = Join-Path $RunDir "prod-events-20261018.jsonl"; usage = Join-Path $RunDir "prod-usage-20261018.jsonl" }
  foreach ($table in @("events", "usage")) {
    $header = "{`"table`":`"$table`",`"snapshot_start`":`"$SnapshotStart`",`"snapshot_end`":`"$SnapshotEnd`"}"
    [IO.File]::WriteAllText($paths[$table] + ".partial", $header + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
  }
  $tableRows = @{ events = 0; usage = 0 }; $tableMeta = @{}
  $remotePython | & ssh @sshArgs $RemoteCommand | ForEach-Object {
    $line = $_
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $message = $line | ConvertFrom-Json
    if ($message.kind -eq "row") {
      $table = [string]$message.table
      if (-not $paths.ContainsKey($table)) { throw "Unexpected table in remote stream" }
      if ($tableRows[$table] -ge $MaxRows) { throw "$table export limit exceeded; incomplete" }
      $encoded = $message.row | ConvertTo-Json -Compress -Depth 20
      [IO.File]::AppendAllText($paths[$table] + ".partial", $encoded + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
      $tableRows[$table]++; $script:TotalRows++; $script:TotalBytes += [Text.Encoding]::UTF8.GetByteCount($encoded) + 1
      if ($script:TotalBytes -gt $MaxBytes) { throw "snapshot file limit exceeded; incomplete" }
    } elseif ($message.kind -eq "table_complete") {
      if (-not $paths.ContainsKey([string]$message.table) -or [int]$message.rows -ne [int]$tableRows[[string]$message.table]) { throw "remote table completion count mismatch" }
      $tableMeta[[string]$message.table] = $message
    } elseif ($message.kind -eq "complete") {
      $script:Completed = $true
    } else { throw "unexpected remote stream message" }
  }
  $streamExitCode = if ($isFake -and $env:SNAPSHOT_EXPORT_FAKE_EXIT -eq "1") { 1 } elseif ($isFake) { 0 } else { $LASTEXITCODE }
  if ($streamExitCode -ne 0) { throw "Production stream failed; stopped without retry" }
  if (-not $script:Completed) { throw "Production stream ended without completion; partial files retained" }
  foreach ($table in @("events", "usage")) {
    if (-not $tableMeta.ContainsKey($table)) { throw "missing table completion; partial files retained" }
    Move-Item -LiteralPath ($paths[$table] + ".partial") -Destination $paths[$table]
  }
  $manifest = [pscustomobject]@{ complete=$true; snapshot_start=$SnapshotStart; snapshot_end=$SnapshotEnd; max_rows_per_table=$MaxRows; max_bytes_total=$MaxBytes; total_rows=$script:TotalRows; total_bytes=$script:TotalBytes; tables=@(
    [pscustomobject]@{ table="events"; file="prod-events-20261018.jsonl"; rows=$tableRows.events; bytes=(Get-Item -LiteralPath $paths.events).Length; sha256=(Get-FileHash -LiteralPath $paths.events -Algorithm SHA256).Hash; min_ts=$tableMeta.events.min_ts; max_ts=$tableMeta.events.max_ts },
    [pscustomobject]@{ table="usage"; file="prod-usage-20261018.jsonl"; rows=$tableRows.usage; bytes=(Get-Item -LiteralPath $paths.usage).Length; sha256=(Get-FileHash -LiteralPath $paths.usage -Algorithm SHA256).Hash; min_ts=$tableMeta.usage.min_ts; max_ts=$tableMeta.usage.max_ts }
  ) }
  $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $RunDir "manifest.json") -Encoding utf8
  Write-Output ([pscustomobject]@{ run_dir=$RunDir; total_rows=$script:TotalRows; total_bytes=$script:TotalBytes })
}
Export-Stream
