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
$SnapshotStart = "2026-10-17T16:00:00Z"; $SnapshotEnd = "2026-10-18T14:58:52Z"
$MaxRows = 100000; $MaxBytes = 200MB
if ($isFake -and $env:SNAPSHOT_EXPORT_TEST_MAX_ROWS) { $MaxRows = [int]$env:SNAPSHOT_EXPORT_TEST_MAX_ROWS }
$script:TotalRows = 0; $script:TotalBytes = 0L; $script:Completed = $false
if (Test-Path -LiteralPath $RunDir) { throw "Refusing to reuse existing run directory" }
New-Item -ItemType Directory -Path $RunDir | Out-Null
if (-not (Test-Path -LiteralPath $SshKey)) { throw "Missing SSH key" }
if (-not (Test-Path -LiteralPath $KnownHosts)) { throw "Missing known_hosts" }
$sshArgs = @("-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","ConnectTimeout=5","-o","StrictHostKeyChecking=yes","-o","UserKnownHostsFile=$KnownHosts","-i",$SshKey,$ProdTarget)
$remotePython = Get-Content -LiteralPath (Join-Path $PSScriptRoot "remote_snapshot_reader.py") -Raw

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
      $table = [string]$message.table
      if (-not $paths.ContainsKey($table) -or [int]$message.rows -ne [int]$tableRows[$table]) { throw "remote table completion count mismatch" }
      $tableMeta[$table] = $message
    } elseif ($message.kind -eq "complete") {
      $script:Completed = $true
    } elseif ($message.kind -eq "error") {
      throw "remote snapshot reader failed during $($message.phase): $($message.error)"
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
