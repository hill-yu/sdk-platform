from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_parse_worker_unit_matches_deployment_contract() -> None:
    unit = (ROOT / "deploy/systemd/sdk-log-parse-worker.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/www/wwwroot/sdk-api/backend" in unit
    assert "EnvironmentFile=/www/wwwroot/sdk-api/backend/.env" in unit
    assert "ExecStart=/www/wwwroot/sdk-api/backend/venv/bin/python -m app.workers.log_parse_worker" in unit
    assert "Restart=always" in unit
    assert "CPUQuota=300%" in unit
    assert "MemoryMax=1536M" in unit
    assert "Nice=5" in unit


def test_env_example_contains_worker_controls_without_real_credentials() -> None:
    env = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
    for key in ("LOG_PARSE_BATCH_SIZE", "LOG_PARSE_CONCURRENCY", "LOG_PARSE_MAX_DAYS", "LOG_PARSE_LEASE_SECONDS"):
        assert f"{key}=" in env
    assert "your_password_here" in env
    assert "your_admin_token_here" in env
    assert "sk-" not in env


def test_benchmark_creates_and_polls_a_real_parse_job() -> None:
    source = (ROOT / "scripts/benchmark_log_parse.py").read_text(encoding="utf-8")
    assert "create_parse_job(" in source
    assert "run_worker_once(" in source
    assert "get_parse_job(" in source
    assert "TERMINAL_STATES" in source
    assert "--events" in source
    assert "--max-seconds" in source
    assert "passed" in source
    assert "delete(SdkEvent)" in source
    assert "H1|" in source
    assert "pa=" in source
    assert "select(func.count()).select_from(H1Declaration)" in source
    assert "select(func.count()).select_from(LogClickAttempt)" in source
    assert "job_id=job_id" in source


def test_benchmark_fixture_has_real_h1_pa_mix_and_explicit_fallback_counts() -> None:
    spec = spec_from_file_location("benchmark_log_parse", ROOT / "scripts/benchmark_log_parse.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    events = module.make_events(
        "__sdk_parse_benchmark__test",
        21,
        datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    extras = [event["payload"]["extra"] for event in events]
    h1_extras = [extra for extra in extras if "H1|" in extra]
    assert len(h1_extras) == 19
    assert all(extra.count("H1|") == 2 and "|pa=" in extra for extra in h1_extras)
    assert module.expected_counts(21) == (38, 95, 2)


def test_benchmark_help_is_runnable() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/benchmark_log_parse.py"), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--events" in result.stdout
