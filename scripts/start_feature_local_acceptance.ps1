$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$UserProfile = [Environment]::GetFolderPath("UserProfile")
$SecretFile = Join-Path $UserProfile ".codex\local-admin-login-20261017.txt"
$PgData = Join-Path $UserProfile ".codex\local-pg-admin-login-20261017-pgdata"
$PgCtl = "C:\pgsql\bin\pg_ctl.exe"
$DatabaseUrl = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_local_acceptance_20261018"

if (-not (Test-Path -LiteralPath $SecretFile)) { throw "Missing private credential file: $SecretFile" }
$secret = @{}
Get-Content -LiteralPath $SecretFile | ForEach-Object {
  if ($_ -match '^([^=]+)=(.*)$') { $secret[$Matches[1]] = $Matches[2] }
}
if (-not $secret["ADMIN_PASSWORD_HASH"]) { throw "ADMIN_PASSWORD_HASH is missing from the private credential file" }

if (Test-Path -LiteralPath $PgCtl) {
  if (-not (Test-NetConnection 127.0.0.1 -Port 55432 -InformationLevel Quiet)) {
    & $PgCtl -D $PgData -w start -o "-p 55432" | Out-Null
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

$backend = Start-Process -WindowStyle Hidden -FilePath (Get-Command python).Source -WorkingDirectory (Join-Path $RepoRoot "backend") -ArgumentList @("-m", "uvicorn", "app.admin_main:app", "--host", "127.0.0.1", "--port", "8101") -RedirectStandardOutput (Join-Path $RepoRoot ".local-run\admin-backend.out.log") -RedirectStandardError (Join-Path $RepoRoot ".local-run\admin-backend.err.log") -PassThru
$frontend = Start-Process -WindowStyle Hidden -FilePath (Get-Command npm).Source -WorkingDirectory (Join-Path $RepoRoot "frontend") -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") -RedirectStandardOutput (Join-Path $RepoRoot ".local-run\frontend.out.log") -RedirectStandardError (Join-Path $RepoRoot ".local-run\frontend.err.log") -PassThru

Write-Output (ConvertTo-Json @{ repo = $RepoRoot; database = "sdk_local_acceptance_20261018"; backend_pid = $backend.Id; frontend_pid = $frontend.Id })
