$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$UserProfile = [Environment]::GetFolderPath("UserProfile")
$SecretFile = Join-Path $UserProfile ".codex\local-admin-login-20261017.txt"
$PgData = Join-Path $UserProfile ".codex\local-pg-admin-login-20261017-pgdata"
$PgCtl = "C:\pgsql\bin\pg_ctl.exe"
$DatabaseUrl = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_prod_snapshot_20261018_001"
if (-not (Test-Path -LiteralPath $SecretFile)) { throw "Missing private credential file" }
$secret = @{}
Get-Content -LiteralPath $SecretFile | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $secret[$Matches[1]] = $Matches[2] } }
if (-not $secret["ADMIN_PASSWORD_HASH"]) { throw "ADMIN_PASSWORD_HASH is missing" }
if (Test-Path -LiteralPath $PgCtl) {
  if (-not (Test-NetConnection 127.0.0.1 -Port 55432 -InformationLevel Quiet)) {
    $nativePreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    & $PgCtl -D $PgData -w start -o "-p 55432" | Out-Null
    $PSNativeCommandUseErrorActionPreference = $nativePreference
    Start-Sleep -Seconds 2
    if (-not (Test-NetConnection 127.0.0.1 -Port 55432 -InformationLevel Quiet)) { throw "Local PostgreSQL did not become ready" }
  }
}
$env:DATABASE_URL = $DatabaseUrl
$env:DEBUG = "true"
$env:ADMIN_TOKEN = (& python -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD_LOGIN_ENABLED = "true"
$env:ADMIN_PASSWORD_HASH = $secret["ADMIN_PASSWORD_HASH"]
$env:ADMIN_SESSION_COOKIE_SECURE = "false"
$env:ADMIN_AUTH_ALLOWED_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
$env:CORS_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
$env:CDN_BASE_URL = "https://local.invalid"
$env:COS_BUCKET = "local-bucket"
$env:CONFIG_META_LOCAL_BASE_URL = "http://127.0.0.1:8100"
$runRoot = Join-Path $RepoRoot ".local-run"
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$backend = Start-Process -WindowStyle Hidden -FilePath (Get-Command python).Source -WorkingDirectory (Join-Path $RepoRoot "backend") -ArgumentList @("-m", "uvicorn", "app.admin_main:app", "--host", "127.0.0.1", "--port", "8101") -RedirectStandardOutput (Join-Path $runRoot "snapshot-admin-backend.out.log") -RedirectStandardError (Join-Path $runRoot "snapshot-admin-backend.err.log") -PassThru
$frontend = Start-Process -WindowStyle Hidden -FilePath (Get-Command npm).Source -WorkingDirectory (Join-Path $RepoRoot "frontend") -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") -RedirectStandardOutput (Join-Path $runRoot "snapshot-frontend.out.log") -RedirectStandardError (Join-Path $runRoot "snapshot-frontend.err.log") -PassThru
$repoPattern = [regex]::Escape($RepoRoot)
$worker = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and $_.CommandLine -match "app\.workers\.log_parse_worker" -and $_.CommandLine -match $repoPattern
} | Select-Object -First 1
if ($worker) {
  $workerPid = $worker.ProcessId
} else {
  $workerProcess = Start-Process -WindowStyle Hidden -FilePath (Get-Command python).Source -WorkingDirectory (Join-Path $RepoRoot "backend") -ArgumentList @("-m", "app.workers.log_parse_worker") -RedirectStandardOutput (Join-Path $runRoot "snapshot-parse-worker.out.log") -RedirectStandardError (Join-Path $runRoot "snapshot-parse-worker.err.log") -PassThru
  $workerPid = $workerProcess.Id
}
Write-Output (ConvertTo-Json @{ database = "sdk_prod_snapshot_20261018_001"; backend_pid = $backend.Id; frontend_pid = $frontend.Id; parse_worker_pid = $workerPid })
