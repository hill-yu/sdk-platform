"""Add decoded log analysis persistence tables and Beijing-time summary views."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REQUIRED_TABLES = (
    "sdk_log_decodes",
    "sdk_package_profiles",
    "sdk_admin_preferences",
    "sdk_log_reparse_jobs",
)


@dataclass(frozen=True)
class SchemaSnapshot:
    total_count: int
    non_null_extra_count: int
    partition_counts: dict[str, int]
    existing_tables: set[str]
    view_summaries: dict[str, str]


@dataclass(frozen=True)
class MigrationReport:
    statements: Sequence[str]
    before: SchemaSnapshot
    after: SchemaSnapshot | None = None


def _summary(definition: str | None) -> str:
    normalized = definition or ""
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    timezone_marker = "|tz:Asia/Shanghai" if "Asia/Shanghai" in normalized else "|tz:unknown"
    return f"sha256:{digest[:16]}{timezone_marker}"


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


DAILY_VIEW_SQL = """CREATE MATERIALIZED VIEW mv_daily_event_stats AS
SELECT
    (server_ts AT TIME ZONE 'Asia/Shanghai')::date AS stat_date,
    event_type,
    package_name,
    payload->>'page' AS page,
    payload->>'element' AS element,
    COUNT(*) AS event_count,
    COUNT(DISTINCT device_id) AS unique_devices
FROM sdk_events
GROUP BY 1, 2, 3, 4, 5"""

HOURLY_VIEW_SQL = """CREATE MATERIALIZED VIEW mv_hourly_trend AS
SELECT
    date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai') AS hour,
    event_type,
    COUNT(*) AS event_count,
    COUNT(DISTINCT device_id) AS unique_devices
FROM sdk_events
GROUP BY 1, 2"""

EXPECTED_VIEW_SUMMARIES = {
    "mv_daily_event_stats": _summary(DAILY_VIEW_SQL),
    "mv_hourly_trend": _summary(HOURLY_VIEW_SQL),
}

CREATE_TABLE_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS sdk_log_decodes (
    event_id         BIGINT       NOT NULL,
    event_server_ts  TIMESTAMPTZ  NOT NULL,
    record_index      INTEGER      NOT NULL,
    package_name     VARCHAR(255) NOT NULL,
    decoder_name     VARCHAR(64)  NOT NULL,
    decoder_version  VARCHAR(32)  NOT NULL,
    trace_id         VARCHAR(128),
    decoded_payload  JSONB        NOT NULL,
    decode_status    VARCHAR(20)  NOT NULL DEFAULT 'pending',
    error_summary    TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_sdk_log_decodes PRIMARY KEY (event_id, event_server_ts, record_index),
    CONSTRAINT chk_log_decodes_status CHECK (decode_status IN ('pending', 'success', 'failed'))
)""",
    "CREATE INDEX IF NOT EXISTS idx_log_decodes_package_ts ON sdk_log_decodes (package_name, event_server_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_log_decodes_trace_id ON sdk_log_decodes (trace_id)",
    """CREATE TABLE IF NOT EXISTS sdk_package_profiles (
    package_name      VARCHAR(255) PRIMARY KEY,
    display_name      VARCHAR(255),
    owner             VARCHAR(128),
    profile           JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)""",
    "CREATE INDEX IF NOT EXISTS idx_package_profiles_updated ON sdk_package_profiles (updated_at DESC)",
    """CREATE TABLE IF NOT EXISTS sdk_admin_preferences (
    preference_key    VARCHAR(128) PRIMARY KEY,
    preference_value  JSONB        NOT NULL,
    description       TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)""",
    "CREATE INDEX IF NOT EXISTS idx_admin_preferences_updated ON sdk_admin_preferences (updated_at DESC)",
    """CREATE TABLE IF NOT EXISTS sdk_log_reparse_jobs (
    id                BIGSERIAL PRIMARY KEY,
    package_name      VARCHAR(255),
    range_start       TIMESTAMPTZ  NOT NULL,
    range_end         TIMESTAMPTZ  NOT NULL,
    cursor_event_id   BIGINT,
    cursor_server_ts  TIMESTAMPTZ,
    processed_count   BIGINT       NOT NULL DEFAULT 0,
    decoded_count     BIGINT       NOT NULL DEFAULT 0,
    failed_count      BIGINT       NOT NULL DEFAULT 0,
    status            VARCHAR(20)  NOT NULL DEFAULT 'pending',
    error_summary     TEXT,
    created_by        VARCHAR(64),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_log_reparse_jobs_status CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))
)""",
    "CREATE INDEX IF NOT EXISTS idx_log_reparse_jobs_status ON sdk_log_reparse_jobs (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_log_reparse_jobs_range ON sdk_log_reparse_jobs (range_start, range_end)",
]


def build_migration_statements(
    *, existing_tables: set[str], view_summaries: dict[str, str]
) -> list[str]:
    statements: list[str] = []
    missing_tables = not set(REQUIRED_TABLES).issubset(existing_tables)
    stale_views = any(
        not view_summaries.get(name, "").endswith("|tz:Asia/Shanghai")
        for name in EXPECTED_VIEW_SUMMARIES
    )
    if missing_tables:
        statements.extend(CREATE_TABLE_STATEMENTS)
    if missing_tables or stale_views:
        statements.extend(
            [
                "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats",
                DAILY_VIEW_SQL,
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily ON mv_daily_event_stats (stat_date, event_type, package_name, page, element)",
                "DROP MATERIALIZED VIEW IF EXISTS mv_hourly_trend",
                HOURLY_VIEW_SQL,
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly ON mv_hourly_trend (hour, event_type)",
            ]
        )
    return statements


async def _table_exists(connection, table_name: str) -> bool:
    result = await connection.execute(
        text("SELECT to_regclass(:relation)"),
        {"relation": f"public.{table_name}"},
    )
    return result.scalar_one() is not None


async def read_snapshot(connection) -> SchemaSnapshot:
    total_count = int(
        (await connection.execute(text("SELECT COUNT(*) FROM sdk_events"))).scalar_one()
    )
    non_null_extra_count = int(
        (
            await connection.execute(
                text("SELECT COUNT(*) FROM sdk_events WHERE payload ? 'extra'")
            )
        ).scalar_one()
    )
    partitions = (
        await connection.execute(
            text(
                "SELECT child.relname FROM pg_inherits i "
                "JOIN pg_class parent ON parent.oid=i.inhparent "
                "JOIN pg_class child ON child.oid=i.inhrelid "
                "JOIN pg_namespace namespace ON namespace.oid=child.relnamespace "
                "WHERE parent.relname='sdk_events' AND namespace.nspname=current_schema() "
                "ORDER BY child.relname"
            )
        )
    ).scalars().all()
    partition_counts = {}
    for raw_name in partitions:
        name = str(raw_name)
        partition_counts[name] = int(
            (
                await connection.execute(
                    text(f"SELECT COUNT(*) FROM {_quoted_identifier(name)}")
                )
            ).scalar_one()
        )
    view_rows = (
        await connection.execute(
            text(
                "SELECT matviewname, definition FROM pg_matviews "
                "WHERE schemaname=current_schema() "
                "AND matviewname IN ('mv_daily_event_stats', 'mv_hourly_trend')"
            )
        )
    ).all()
    return SchemaSnapshot(
        total_count=total_count,
        non_null_extra_count=non_null_extra_count,
        partition_counts=partition_counts,
        existing_tables={
            table_name
            for table_name in REQUIRED_TABLES
            if await _table_exists(connection, table_name)
        },
        view_summaries={str(name): _summary(str(definition)) for name, definition in view_rows},
    )


def verify_lossless(before: SchemaSnapshot, after: SchemaSnapshot) -> None:
    if before.total_count != after.total_count:
        raise RuntimeError("迁移前后事件总数不一致")
    if before.non_null_extra_count != after.non_null_extra_count:
        raise RuntimeError("迁移前后非空extra数不一致")
    if before.partition_counts != after.partition_counts:
        raise RuntimeError("迁移前后分区行数不一致")
    missing = set(REQUIRED_TABLES) - after.existing_tables
    if missing:
        raise RuntimeError("迁移后缺少表: " + ", ".join(sorted(missing)))


async def migrate(database_url: str, *, apply: bool) -> MigrationReport:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            before = await read_snapshot(connection)
            statements = build_migration_statements(
                existing_tables=before.existing_tables,
                view_summaries=before.view_summaries,
            )
            if not apply:
                return MigrationReport(statements=statements, before=before)
            for statement in statements:
                await connection.execute(text(statement))
            after = await read_snapshot(connection)
            verify_lossless(before, after)
            return MigrationReport(statements=statements, before=before, after=after)
    finally:
        await engine.dispose()


def _statement_type(statement: str) -> str:
    first = statement.strip().split(maxsplit=1)[0].upper()
    if first == "CREATE" and "INDEX" in statement[:80].upper():
        return "CREATE INDEX"
    if first == "CREATE" and "TABLE" in statement[:80].upper():
        return "CREATE TABLE"
    if first == "DROP":
        return "DROP MATERIALIZED VIEW"
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行迁移；默认仅只读预检")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("必须设置 DATABASE_URL")
    if args.apply and args.confirm != "MIGRATE_LOG_ANALYSIS":
        raise SystemExit("正式迁移必须传入 --confirm MIGRATE_LOG_ANALYSIS")

    report = asyncio.run(migrate(database_url, apply=args.apply))
    action = "迁移完成" if args.apply else "只读预检通过"
    print(
        f"{action}: statements={len(report.statements)}, events={report.before.total_count}, "
        f"non_null_extra={report.before.non_null_extra_count}, "
        f"partitions={len(report.before.partition_counts)}"
    )
    for name, count in report.before.partition_counts.items():
        print(f"partition={name}, rows={count}")
    for name, summary in report.before.view_summaries.items():
        print(f"view={name}, definition={summary}")
    for statement in report.statements:
        print(f"plan={_statement_type(statement)}")


if __name__ == "__main__":
    main()
