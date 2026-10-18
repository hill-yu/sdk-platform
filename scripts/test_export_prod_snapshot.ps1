$ErrorActionPreference = "Stop"
$env:SNAPSHOT_EXPORT_FAKE_RUNNER = "1"
$env:SNAPSHOT_EXPORT_TEST_MAX_ROWS = "100000"
$script:FakeMode = "complete"
$script:FakeCalls = 0

function ssh {
  begin { $script:FakeInput = [System.Text.StringBuilder]::new() }
  process { [void]$script:FakeInput.Append([string]$_) }
  end {
    $script:FakeCalls++
    $events = '{"kind":"row","table":"events","row":{"id":1,"server_ts":"2026-10-18T14:00:00Z","package_name":"test","event_type":"test","payload":{}}}', '{"kind":"table_complete","table":"events","rows":1,"min_ts":"2026-10-18T14:00:00Z","max_ts":"2026-10-18T14:00:00Z"}'
    $usage = '{"kind":"row","table":"usage","row":{"id":1,"server_ts":"2026-10-18T14:01:00Z","package_name":"test","device_id":"d","device_model":"m","os":"android","app_version":"1","sdk_version":"1","duration_s":1}}', '{"kind":"table_complete","table":"usage","rows":1,"min_ts":"2026-10-18T14:01:00Z","max_ts":"2026-10-18T14:01:00Z"}'
    if ($script:FakeMode -eq "断流") { $events[0]; return }
    if ($script:FakeMode -eq "超限") { $events[0]; $events[0]; return }
    $events; $usage; '{"kind":"complete","snapshot_start":"2026-10-17T16:00:00Z","snapshot_end":"2026-10-18T14:58:52Z"}'
  }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$before = @(Get-ChildItem -LiteralPath (Join-Path $root ".local-run") -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
. (Join-Path $PSScriptRoot "export_prod_snapshot.ps1") | Out-Null
if ($script:FakeCalls -ne 1) { throw "expected exactly one SSH invocation" }
$after = @(Get-ChildItem -LiteralPath (Join-Path $root ".local-run") -Directory | Where-Object { $before -notcontains $_.FullName })
if ($after.Count -ne 1 -or -not (Test-Path (Join-Path $after[0] "manifest.json"))) { throw "complete fake export did not create manifest" }
Remove-Item -LiteralPath $after[0] -Recurse -Force

$script:FakeMode = "断流"; $script:FakeCalls = 0
try { . (Join-Path $PSScriptRoot "export_prod_snapshot.ps1") | Out-Null; throw "断流 was not rejected" } catch { if ($_.Exception.Message -notmatch "without completion") { throw } }
$partial = Get-ChildItem -LiteralPath (Join-Path $root ".local-run") -Recurse -Filter "*.partial" | Select-Object -Last 1
if (-not $partial) { throw "断流 did not retain partial file" }
Remove-Item -LiteralPath $partial.Directory.FullName -Recurse -Force

$env:SNAPSHOT_EXPORT_TEST_MAX_ROWS = "1"; $script:FakeMode = "超限"; $script:FakeCalls = 0
try { . (Join-Path $PSScriptRoot "export_prod_snapshot.ps1") | Out-Null; throw "超限 was not rejected" } catch { if ($_.Exception.Message -notmatch "export limit exceeded") { throw } }
$partial = Get-ChildItem -LiteralPath (Join-Path $root ".local-run") -Recurse -Filter "*.partial" | Select-Object -Last 1
if (-not $partial) { throw "超限 did not retain partial file" }
Remove-Item -LiteralPath $partial.Directory.FullName -Recurse -Force
Write-Output "fake export runner: one SSH call, completion, pagination, over-limit and断流 checks passed"
