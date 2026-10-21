from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_parser_uses_env_file_and_rejects_dsn_option():
    from scripts.backfill_package_catalog import build_parser

    parser = build_parser()
    args = parser.parse_args(["--env-file", ".env.test", "--source", "log", "--apply"])
    assert args.env_file == Path(".env.test")
    assert args.source == "log"
    with pytest.raises(SystemExit):
        parser.parse_args(["--database-url", "postgresql://secret"])


def test_source_query_is_keyset_ordered_and_bounded():
    from scripts.backfill_package_catalog import build_source_query

    query = build_source_query("log", has_cursor=True)
    normalized = " ".join(query.split()).lower()
    assert "event_type = 'log'" in normalized
    assert "(server_ts, id) > (:cursor_server_ts, :cursor_id)" in normalized
    assert "order by server_ts, id" in normalized
    assert "limit :batch_size" in normalized


def test_database_url_resolves_password_placeholder_without_printing_it(monkeypatch):
    from scripts.backfill_package_catalog import resolve_database_url

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://sdk_admin:${DB_PASSWORD}@127.0.0.1/sdk_platform")
    monkeypatch.setenv("DB_PASSWORD", "p@ss word")
    assert resolve_database_url() == "postgresql+asyncpg://sdk_admin:p%40ss+word@127.0.0.1/sdk_platform"


def test_resume_cursor_advances_only_after_committed_batch():
    from scripts.backfill_package_catalog import advance_cursor

    assert advance_cursor(None, ("2026-10-21T00:00:00+00:00", 7), committed=True) == (
        "2026-10-21T00:00:00+00:00",
        7,
    )
    assert advance_cursor(("2026-10-21T00:00:00+00:00", 7), ("2026-10-21T00:01:00+00:00", 8), committed=False) == (
        "2026-10-21T00:00:00+00:00",
        7,
    )
