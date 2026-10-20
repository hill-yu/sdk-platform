from pathlib import Path
import os
import subprocess
import sys


def test_snapshot_start_script_starts_only_the_local_parse_worker_once():
    root = Path(__file__).parents[2]
    script = (root / "scripts" / "start_snapshot_local.ps1").read_text(encoding="utf-8")
    launcher = (root / "scripts" / "start_snapshot_parse_worker.py").read_text(encoding="utf-8")

    assert "sdk_prod_snapshot_20261018_001" in script
    assert "app.workers.log_parse_worker" in launcher
    assert "snapshot parse launcher refuses a non-snapshot DATABASE_URL" in launcher
    assert "start_snapshot_parse_worker.py" in script
    assert "snapshot-parse-worker.lock.json" in script
    assert "start_time_ticks" in script
    assert "Threading.Mutex" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "candidate.database -eq \"sdk_prod_snapshot_20261018_001\"" in script
    assert "candidate.launcher -eq $workerLauncher" in script
    assert "(-not $candidate.launcher)" in script
    assert "Unowned bare log_parse_worker detected" in script
    assert "-m\\s+app\\.workers\\.log_parse_worker" in script
    assert "log_export_worker" not in script
    assert "cos_worker" not in script.lower()


def test_snapshot_launcher_refuses_another_database():
    launcher = Path(__file__).parents[2] / "scripts" / "start_snapshot_parse_worker.py"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql+asyncpg://postgres@127.0.0.1:55432/another_database"
    result = subprocess.run([sys.executable, str(launcher)], env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "non-snapshot DATABASE_URL" in result.stderr or "non-snapshot DATABASE_URL" in result.stdout
