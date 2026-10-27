param(
    [string]$EnvFile = $env:SDK_ACCEPTANCE_ENV_FILE
)

$ErrorActionPreference = "Stop"
if (-not $EnvFile) { throw "Pass -EnvFile pointing to a private, untracked env file." }
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { throw "Acceptance env file was not found." }

$allowed = @{
    SDK_LOG_HISTORY_TEST_DATABASE_URL = $true
    SDK_CONFIG_PUBLISH_TEST_DATABASE_URL = $true
}
foreach ($line in Get-Content -LiteralPath $EnvFile) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith("#")) { continue }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2 -or -not $allowed.ContainsKey($parts[0].Trim())) { throw "Env file contains an unsupported entry." }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if ($name -eq "SDK_LOG_HISTORY_TEST_DATABASE_URL" -and $value -notmatch ":55432/sdk_log_history_test_[^/]+$") { throw "History URL must use port 55432 and sdk_log_history_test_* database." }
    if ($name -eq "SDK_CONFIG_PUBLISH_TEST_DATABASE_URL" -and $value -notmatch ":55432/sdk_config_publish_test_[^/]+$") { throw "Publish URL must use port 55432 and sdk_config_publish_test_* database." }
    Set-Item -Path ("Env:" + $name) -Value $value
}
if (-not $env:SDK_LOG_HISTORY_TEST_DATABASE_URL -or -not $env:SDK_CONFIG_PUBLISH_TEST_DATABASE_URL) { throw "Both dedicated database URLs are required." }

python -m pytest backend/tests/test_log_history_postgres_integration.py backend/tests/test_config_publish_postgres_integration.py -q -rs
