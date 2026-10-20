from pathlib import Path


def test_snapshot_start_script_starts_only_the_local_parse_worker_once():
    script = (Path(__file__).parents[2] / "scripts" / "start_snapshot_local.ps1").read_text(encoding="utf-8")

    assert "sdk_prod_snapshot_20261018_001" in script
    assert "app.workers.log_parse_worker" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "log_export_worker" not in script
    assert "cos_worker" not in script.lower()
