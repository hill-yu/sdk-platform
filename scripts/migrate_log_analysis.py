"""Add decoded log analysis persistence tables and Beijing-time summary views."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REQUIRED_TABLES = (
    "sdk_log_decodes",
    "sdk_package_profiles",
    "sdk_admin_preferences",
    "sdk_log_reparse_jobs",
)

REQUIRED_INDEXES = frozenset(
    {
        "idx_log_decodes_package_ts",
        "idx_log_decodes_status_ts",
        "idx_log_decodes_decoder_status",
        "idx_log_decodes_event_ts",
        "idx_package_profiles_updated",
        "idx_admin_preferences_updated",
        "idx_log_reparse_jobs_status",
        "idx_log_reparse_jobs_range",
    }
)
REPARSE_STATUS_VALUES = frozenset({"pending", "running", "success", "failed", "cancelled"})


@dataclass(frozen=True)
class SchemaSnapshot:
    total_count: int
    non_null_extra_count: int
    partition_counts: dict[str, int]
    existing_tables: set[str]
    existing_indexes: set[str]
    view_summaries: dict[str, str]
    existing_columns: dict[str, set[str]] = field(default_factory=dict)
    constraint_definitions: dict[str, str] = field(default_factory=dict)
    view_column_types: dict[str, str] = field(default_factory=dict)


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


def _strip_redundant_parentheses(expression: str) -> str:
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        quote = False
        closes_at = None
        index = 0
        while index < len(expression):
            character = expression[index]
            if character == "'":
                if quote and index + 1 < len(expression) and expression[index + 1] == "'":
                    index += 2
                    continue
                quote = not quote
            elif not quote:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at = index
                        break
            index += 1
        if closes_at != len(expression) - 1:
            break
        expression = expression[1:-1].strip()
    return expression


def _is_target_reparse_status_constraint(definition: str) -> bool:
    """Return whether a constraint is the positive target status CHECK."""
    normalized = " ".join(definition.strip().split())
    check_match = re.fullmatch(r"CHECK\s*(.*)", normalized, flags=re.IGNORECASE)
    if check_match is None:
        return False

    expression = _strip_redundant_parentheses(check_match.group(1))
    in_match = re.fullmatch(
        r"status\s+IN\s*\((.*)\)", expression, flags=re.IGNORECASE
    )
    any_match = re.fullmatch(
        r"\(?status\)?\s*(?:::\s*[A-Za-z_]\w*(?:\[\])?)*\s*=\s*ANY\s*\((.*)\)",
        expression,
        flags=re.IGNORECASE,
    )
    value_expression = (
        in_match.group(1) if in_match is not None else any_match.group(1) if any_match else None
    )
    if value_expression is None:
        return False
    return set(re.findall(r"'([^']+)'", value_expression)) == REPARSE_STATUS_VALUES


def _has_exact_reparse_status_constraint(definition: str) -> bool:
    """Backward-compatible alias for the shared strict constraint check."""
    return _is_target_reparse_status_constraint(definition)


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
    date_trunc('hour', server_ts, 'Asia/Shanghai') AS hour,
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
    record_index     INTEGER      NOT NULL,
    package_name     VARCHAR(255) NOT NULL,
    device_id        VARCHAR(64),
    status           VARCHAR(32)  NOT NULL DEFAULT 'pending',
    decoder_version  VARCHAR(32)  NOT NULL,
    decoded_timestamp TIMESTAMPTZ,
    url              TEXT,
    config_id        INTEGER,
    "window" VARCHAR(32),
    expected_click_count INTEGER,
    actual_click_count INTEGER,
    ad_click_count   INTEGER,
    interstitial_presentation_count INTEGER,
    interstitial_click_count INTEGER,
    interstitial_close_count INTEGER,
    duration_ms      BIGINT,
    final_reason     VARCHAR(128),
    is_success       BOOLEAN,
    decoded_payload  JSONB,
    parse_error      VARCHAR(512),
    parsed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_sdk_log_decodes PRIMARY KEY (event_id, event_server_ts, record_index),
    CONSTRAINT chk_log_decodes_status CHECK (status IN ('pending', 'success', 'unsupported', 'failed'))
)""",
    """CREATE TABLE IF NOT EXISTS sdk_package_profiles (
    package_name      VARCHAR(255) PRIMARY KEY,
    alias             VARCHAR(255),
    company           VARCHAR(255),
    account           VARCHAR(255),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)""",
    """CREATE TABLE IF NOT EXISTS sdk_admin_preferences (
    preference_key    VARCHAR(128) PRIMARY KEY,
    value             JSONB        NOT NULL,
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)""",
    """CREATE TABLE IF NOT EXISTS sdk_log_reparse_jobs (
    id                BIGSERIAL PRIMARY KEY,
    package_name      VARCHAR(255),
    range_start       TIMESTAMPTZ  NOT NULL,
    range_end         TIMESTAMPTZ  NOT NULL,
    snapshot_end      TIMESTAMPTZ  NOT NULL,
    status_filter     VARCHAR(32),
    decoder_version_before VARCHAR(32),
    lease_owner       VARCHAR(64),
    lease_expires_at  TIMESTAMPTZ,
    cursor_event_id   BIGINT,
    cursor_server_ts  TIMESTAMPTZ,
    processed_count   BIGINT       NOT NULL DEFAULT 0,
    decoded_count     BIGINT       NOT NULL DEFAULT 0,
    failed_count      BIGINT       NOT NULL DEFAULT 0,
    total_count       BIGINT       NOT NULL DEFAULT 0,
    h1_count          BIGINT       NOT NULL DEFAULT 0,
    failed_h1_count   BIGINT       NOT NULL DEFAULT 0,
    no_h1_count       BIGINT       NOT NULL DEFAULT 0,
    batch_size        INTEGER      NOT NULL DEFAULT 200,
    concurrency       INTEGER      NOT NULL DEFAULT 3,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    status            VARCHAR(20)  NOT NULL DEFAULT 'pending',
    error_summary     TEXT,
    created_by        VARCHAR(64),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_log_reparse_jobs_status CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))
)""",
]

REQUIRED_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_log_decodes_package_ts ON sdk_log_decodes (package_name, event_server_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_log_decodes_status_ts ON sdk_log_decodes (status, event_server_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_log_decodes_decoder_status ON sdk_log_decodes (decoder_version, status)",
    "CREATE INDEX IF NOT EXISTS idx_log_decodes_event_ts ON sdk_log_decodes (event_id, event_server_ts)",
    "CREATE INDEX IF NOT EXISTS idx_package_profiles_updated ON sdk_package_profiles (updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_admin_preferences_updated ON sdk_admin_preferences (updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_log_reparse_jobs_status ON sdk_log_reparse_jobs (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_log_reparse_jobs_range ON sdk_log_reparse_jobs (range_start, range_end)",
)


def _index_name(statement: str) -> str:
    return statement.split(" IF NOT EXISTS ", 1)[1].split(" ", 1)[0]


def build_migration_statements(
    *,
    existing_tables: set[str],
    view_summaries: dict[str, str],
    existing_indexes: set[str] | None = None,
    existing_columns: dict[str, set[str]] | None = None,
    constraint_definitions: dict[str, str] | None = None,
    view_column_types: dict[str, str] | None = None,
) -> list[str]:
    statements: list[str] = []
    missing_tables = not set(REQUIRED_TABLES).issubset(existing_tables)
    reparse_table_exists = "sdk_log_reparse_jobs" in existing_tables
    daily_view_stale = not view_summaries.get("mv_daily_event_stats", "").endswith("|tz:Asia/Shanghai")
    if view_column_types is None:
        hourly_view_stale = not view_summaries.get("mv_hourly_trend", "").endswith("|tz:Asia/Shanghai")
    else:
        hourly_view_stale = view_column_types.get("mv_hourly_trend.hour") != "timestamp with time zone"
    if missing_tables:
        statements.extend(CREATE_TABLE_STATEMENTS)
        statements.extend(REQUIRED_INDEX_STATEMENTS)
    elif existing_indexes is not None:
        statements.extend(
            statement
            for statement in REQUIRED_INDEX_STATEMENTS
            if _index_name(statement) not in existing_indexes
        )
    if reparse_table_exists and existing_columns is not None:
        job_columns = existing_columns.get("sdk_log_reparse_jobs", set())
        if "status_filter" not in job_columns:
            statements.append(
                "ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS status_filter VARCHAR(32)"
            )
        if "decoder_version_before" not in job_columns:
            statements.append(
                "ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS decoder_version_before VARCHAR(32)"
            )
        if "lease_owner" not in job_columns:
            statements.append(
                "ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(64)"
            )
        if "lease_expires_at" not in job_columns:
            statements.append(
                "ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ"
            )
        if "snapshot_end" not in job_columns:
            statements.extend(
                [
                    "ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS snapshot_end TIMESTAMPTZ",
                    "UPDATE sdk_log_reparse_jobs SET snapshot_end = range_end WHERE snapshot_end IS NULL",
                    "ALTER TABLE sdk_log_reparse_jobs ALTER COLUMN snapshot_end SET NOT NULL",
                ]
            )
        for column, sql_type, default in (
            ("total_count", "BIGINT", "0"),
            ("h1_count", "BIGINT", "0"),
            ("failed_h1_count", "BIGINT", "0"),
            ("no_h1_count", "BIGINT", "0"),
            ("batch_size", "INTEGER", "200"),
            ("concurrency", "INTEGER", "3"),
        ):
            if column not in job_columns:
                statements.append(
                    f"ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS {column} {sql_type} NOT NULL DEFAULT {default}"
                )
        for column in ("started_at", "finished_at", "last_heartbeat_at", "cancel_requested_at"):
            if column not in job_columns:
                statements.append(
                    f"ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS {column} TIMESTAMPTZ"
                )
    if reparse_table_exists and constraint_definitions is not None:
        definition = constraint_definitions.get("chk_log_reparse_jobs_status", "")
        if not _is_target_reparse_status_constraint(definition):
            statements.extend(
                [
                    "ALTER TABLE sdk_log_reparse_jobs DROP CONSTRAINT IF EXISTS chk_log_reparse_jobs_status",
                    "UPDATE sdk_log_reparse_jobs SET status = 'success' WHERE status = 'succeeded'",
                    "ALTER TABLE sdk_log_reparse_jobs ADD CONSTRAINT chk_log_reparse_jobs_status CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))",
                ]
            )
    if missing_tables or daily_view_stale:
        statements.extend(
            [
                "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats",
                DAILY_VIEW_SQL,
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily ON mv_daily_event_stats (stat_date, event_type, package_name, page, element)",
            ]
        )
    if missing_tables or hourly_view_stale:
        statements.extend(
            [
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
                text(
                    "SELECT COUNT(*) FROM sdk_events "
                    "WHERE payload->>'extra' IS NOT NULL "
                    "AND BTRIM(payload->>'extra') <> ''"
                )
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
    index_rows = (
        await connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname=current_schema() "
                "AND tablename IN ("
                + ", ".join(f"'{table_name}'" for table_name in REQUIRED_TABLES)
                + ")"
            )
        )
    ).scalars().all()
    view_column_rows = (
        await connection.execute(
            text(
                "SELECT c.relname || '.' || attribute.attname AS column_key, "
                "format_type(attribute.atttypid, attribute.atttypmod) AS column_type "
                "FROM pg_class c "
                "JOIN pg_namespace namespace ON namespace.oid = c.relnamespace "
                "JOIN pg_attribute attribute ON attribute.attrelid = c.oid "
                "WHERE namespace.nspname = current_schema() "
                "AND c.relname = 'mv_hourly_trend' "
                "AND attribute.attname = 'hour' "
                "AND attribute.attnum > 0 AND NOT attribute.attisdropped"
            )
        )
    ).all()
    column_rows = (
        await connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name IN ("
                + ", ".join(f"'{table_name}'" for table_name in REQUIRED_TABLES)
                + ")"
            )
        )
    ).all()
    existing_columns: dict[str, set[str]] = {}
    for table_name, column_name in column_rows:
        existing_columns.setdefault(str(table_name), set()).add(str(column_name))
    constraint_rows = (
        await connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = to_regclass('public.sdk_log_reparse_jobs')"
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
        existing_indexes={str(name) for name in index_rows},
        view_summaries={str(name): _summary(str(definition)) for name, definition in view_rows},
        view_column_types={str(key): str(column_type) for key, column_type in view_column_rows},
        existing_columns=existing_columns,
        constraint_definitions={str(name): str(definition) for name, definition in constraint_rows},
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
    missing_indexes = REQUIRED_INDEXES - after.existing_indexes
    if missing_indexes:
        raise RuntimeError("迁移后缺少索引: " + ", ".join(sorted(missing_indexes)))
    required_reparse_columns = {
        "status_filter",
        "decoder_version_before",
        "lease_owner",
        "lease_expires_at",
    }
    missing_reparse_columns = required_reparse_columns - after.existing_columns.get(
        "sdk_log_reparse_jobs", set()
    )
    if missing_reparse_columns:
        raise RuntimeError(
            "迁移后重解析表缺少列: " + ", ".join(sorted(missing_reparse_columns))
        )
    constraint = after.constraint_definitions.get("chk_log_reparse_jobs_status", "")
    if not _is_target_reparse_status_constraint(constraint):
        raise RuntimeError("迁移后重解析状态约束不是目标集合")
    if after.view_column_types.get("mv_hourly_trend.hour") != "timestamp with time zone":
        raise RuntimeError("迁移后小时列不是 timestamp with time zone")


async def migrate(database_url: str, *, apply: bool) -> MigrationReport:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            before = await read_snapshot(connection)
            statements = build_migration_statements(
                existing_tables=before.existing_tables,
                view_summaries=before.view_summaries,
                existing_indexes=before.existing_indexes,
                existing_columns=before.existing_columns,
                constraint_definitions=before.constraint_definitions,
                view_column_types=before.view_column_types,
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
