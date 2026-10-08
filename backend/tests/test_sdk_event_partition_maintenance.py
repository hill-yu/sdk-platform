from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from scripts.ensure_sdk_event_partitions import (
    PartitionSafetyError,
    build_plan,
    build_create_partition_sql,
    normalize_catalog_text,
    parse_partition_bound,
    target_months,
)


def test_target_months_cross_year_boundary() -> None:
    assert target_months(date(2026, 12, 15)) == [
        date(2026, 12, 1),
        date(2027, 1, 1),
        date(2027, 2, 1),
    ]


def test_catalog_parser_normalizes_real_postgres_bytes_and_for_values_text() -> None:
    raw = b"FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00')"

    assert normalize_catalog_text(raw) == raw.decode("utf-8")
    assert parse_partition_bound(raw) == (date(2026, 9, 1), date(2026, 10, 1))


def test_missing_partition_plan_contains_only_missing_exact_months() -> None:
    existing = {
        "sdk_events_202610": (date(2026, 10, 1), date(2026, 11, 1)),
    }

    assert build_plan(date(2026, 10, 8), existing) == [
        ("sdk_events_202611", date(2026, 11, 1), date(2026, 12, 1)),
        ("sdk_events_202612", date(2026, 12, 1), date(2027, 1, 1)),
    ]


def test_same_name_with_wrong_bounds_fails_closed() -> None:
    with pytest.raises(PartitionSafetyError):
        build_plan(
            date(2026, 10, 8),
            {"sdk_events_202610": (date(2026, 10, 2), date(2026, 11, 2))},
        )


def test_partition_bound_rejects_non_utc_month_boundary() -> None:
    with pytest.raises(PartitionSafetyError):
        parse_partition_bound(
            "FOR VALUES FROM ('2026-10-01 00:00:00+08') "
            "TO ('2026-11-01 00:00:00+08')"
        )


def test_create_sql_has_explicit_utc_bounds_and_no_drop_operation() -> None:
    sql = build_create_partition_sql(
        "sdk_events_202610", date(2026, 10, 1), date(2026, 11, 1)
    )

    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "PARTITION OF public.\"sdk_events\"" in sql
    assert "2026-10-01 00:00:00+00" in sql
    assert "2026-11-01 00:00:00+00" in sql
    assert "DROP" not in sql


def test_alias_partition_overlapping_target_fails_closed() -> None:
    with pytest.raises(PartitionSafetyError):
        build_plan(
            date(2026, 10, 8),
            {"sdk_events_legacy_oct": (date(2026, 10, 1), date(2026, 11, 1))},
        )


def test_idempotent_plan_is_empty_when_all_three_exact_bounds_exist() -> None:
    existing = {
        "sdk_events_202610": (date(2026, 10, 1), date(2026, 11, 1)),
        "sdk_events_202611": (date(2026, 11, 1), date(2026, 12, 1)),
        "sdk_events_202612": (date(2026, 12, 1), date(2027, 1, 1)),
    }

    assert build_plan(date(2026, 10, 8), existing) == []


def test_maintenance_units_use_current_release_without_credentials() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/ensure_sdk_event_partitions.py").read_text(encoding="utf-8")
    service = (root / "deploy/systemd/sdk-event-partition-maintenance.service").read_text(
        encoding="utf-8"
    )
    timer = (root / "deploy/systemd/sdk-event-partition-maintenance.timer").read_text(
        encoding="utf-8"
    )

    assert "User=www-data" in service
    assert "EnvironmentFile=/www/releases/sdk-platform/current/backend/.env" in service
    assert "/www/releases/sdk-platform/current/backend/venv/bin/python" in service
    assert "/opt/sdk-platform-maintenance/current/scripts/ensure_sdk_event_partitions.py" in service
    assert "SET LOCAL TIME ZONE 'UTC'" in script
    assert "partstrat" in script
    assert "partattrs" in script
    assert "server_ts" in script
    assert "indisvalid" in script
    assert "pg_inherits" in script
    assert "relacl" in script
    assert "parent_oid" in script
    assert "if args.apply and args.as_of" in script
    assert "TimeoutStartSec=30s" in service
    assert "--apply --confirm ENSURE_SDK_EVENT_PARTITIONS" in service
    assert "Persistent=true" in timer
    assert "Unit=sdk-event-partition-maintenance.service" in timer
    for forbidden in ("password", "TOKEN=", "postgresql://", "/www/wwwroot"):
        assert forbidden not in service
        assert forbidden not in timer


@pytest.mark.integration
def test_real_postgres_dry_run_apply_idempotence_and_rollback(monkeypatch) -> None:
    database_url = os.environ.get("SDK_PARTITION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("SDK_PARTITION_TEST_DATABASE_URL is not set")
    parsed_url = make_url(database_url)
    if parsed_url.host not in {"127.0.0.1", "::1", "localhost"}:
        pytest.skip("integration database must be loopback")
    if not re.fullmatch(r"sdk_partition_test_[0-9a-f]{4,32}", parsed_url.database or ""):
        pytest.skip("integration database must use the dedicated sdk_partition_test_<suffix> name")

    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import scripts.ensure_sdk_event_partitions as maintenance

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DROP TABLE IF EXISTS sdk_events CASCADE"))
                await connection.execute(
                    text(
                        "CREATE TABLE sdk_events ("
                        "id BIGINT NOT NULL, event_type VARCHAR(50) NOT NULL, "
                        "package_name VARCHAR(255) NOT NULL, device_id VARCHAR(64), "
                        "sdk_version VARCHAR(20), payload JSONB NOT NULL, "
                        "server_ts TIMESTAMPTZ NOT NULL, "
                        "PRIMARY KEY (id, server_ts)) PARTITION BY RANGE (server_ts)"
                    )
                )
                await connection.execute(
                    text(
                        "CREATE TABLE sdk_events_202609 PARTITION OF sdk_events "
                        "FOR VALUES FROM ('2026-09-01 00:00:00+00') "
                        "TO ('2026-10-01 00:00:00+00')"
                    )
                )
                for statement in (
                    "CREATE INDEX idx_events_type_ts ON sdk_events (event_type, server_ts DESC)",
                    "CREATE INDEX idx_events_device ON sdk_events (device_id, server_ts DESC)",
                    "CREATE INDEX idx_events_package ON sdk_events (package_name, server_ts DESC)",
                    "CREATE INDEX idx_events_payload ON sdk_events USING GIN (payload)",
                    "CREATE INDEX idx_events_session ON sdk_events (package_name)",
                    "CREATE INDEX idx_events_client_ts ON sdk_events (server_ts DESC)",
                    "CREATE INDEX idx_events_sdk_version ON sdk_events (sdk_version)",
                ):
                    await connection.execute(text(statement))
                await connection.execute(
                    text(
                        "INSERT INTO sdk_events "
                        "(id,event_type,package_name,payload,server_ts) VALUES "
                        "(1,'log','fixture','{}','2026-09-30 12:00:00+00')"
                    )
                )

            dry = await maintenance.ensure_partitions(
                database_url, apply=False, current_day=date(2026, 10, 8)
            )
            assert dry.missing == (
                "sdk_events_202610",
                "sdk_events_202611",
                "sdk_events_202612",
            )
            assert dry.created == ()
            assert dry.verified is False

            async with engine.connect() as connection:
                assert (
                    await connection.execute(
                        text("SELECT to_regclass('public.sdk_events_202610')")
                    )
                ).scalar_one() is None
                assert (
                    await connection.execute(
                        text("SELECT count(*) FROM public.sdk_events_202609")
                    )
                ).scalar_one() == 1

            applied = await maintenance.ensure_partitions(
                database_url, apply=True, current_day=date(2026, 10, 8)
            )
            assert applied.missing == dry.missing
            assert applied.created == applied.missing
            assert applied.verified is True
            assert applied.committed is True

            repeated = await maintenance.ensure_partitions(
                database_url, apply=True, current_day=date(2026, 10, 8)
            )
            assert repeated.missing == ()
            assert repeated.created == ()
            assert repeated.verified is True

            blocker = await engine.connect()
            blocker_transaction = await blocker.begin()
            await blocker.execute(
                text(
                    "SELECT pg_advisory_xact_lock(" \
                    "hashtextextended('sdk_events_partition_maintenance', 0))"
                )
            )
            with pytest.raises(maintenance.PartitionSafetyError, match="advisory lock"):
                await maintenance.ensure_partitions(
                    database_url, apply=True, current_day=date(2026, 10, 8)
                )
            await blocker_transaction.rollback()
            await blocker.close()

            async def fail_index_verification(*_args, **_kwargs):
                raise maintenance.PartitionSafetyError("fixture rollback")

            monkeypatch.setattr(maintenance, "_verify_indexes", fail_index_verification)
            await connectionless_apply_expect_failure(database_url, maintenance)

            async with engine.connect() as connection:
                names = (
                    await connection.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i "
                            "JOIN pg_class p ON p.oid=i.inhparent "
                            "JOIN pg_class c ON c.oid=i.inhrelid "
                            "WHERE p.relname='sdk_events' ORDER BY c.relname"
                        )
                    )
                ).scalars().all()
                assert names == [
                    "sdk_events_202609",
                    "sdk_events_202610",
                    "sdk_events_202611",
                    "sdk_events_202612",
                ]
        finally:
            await engine.dispose()

    async def connectionless_apply_expect_failure(database_url, maintenance_module) -> None:
        with pytest.raises(maintenance_module.PartitionSafetyError, match="fixture rollback"):
            await maintenance_module.ensure_partitions(
                database_url, apply=True, current_day=date(2026, 11, 8)
            )

    asyncio.run(scenario())
