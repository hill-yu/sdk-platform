"""Migrate sdk_events.app_id to package_name without losing event data."""
from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@dataclass(frozen=True)
class SchemaSnapshot:
    total_count: int
    non_null_package_count: int
    partition_counts: dict[str, int]
    partition_columns: dict[str, set[str]]
    event_columns: set[str]
    view_columns: set[str]


@dataclass(frozen=True)
class MigrationReport:
    statements: Sequence[str]
    before: SchemaSnapshot
    after: SchemaSnapshot | None = None


def build_migration_statements(
    event_columns: set[str], view_columns: set[str]
) -> list[str]:
    """Build an idempotent migration plan from the observed database schema."""
    has_app_id = "app_id" in event_columns
    has_package_name = "package_name" in event_columns
    if has_app_id and has_package_name:
        raise RuntimeError("sdk_events 同时存在 app_id 和 package_name，请先人工核对数据")
    if not has_app_id and not has_package_name:
        raise RuntimeError("sdk_events 缺少 app_id/package_name 列")

    view_is_current = "package_name" in view_columns and "app_id" not in view_columns
    if has_package_name and view_is_current:
        return []

    statements = ["DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats"]
    if has_app_id:
        statements.extend(
            [
                "ALTER TABLE sdk_events RENAME COLUMN app_id TO package_name",
                "ALTER TABLE sdk_events ALTER COLUMN package_name TYPE VARCHAR(255)",
            ]
        )
    statements.extend(
        [
            "DROP INDEX IF EXISTS idx_events_app",
            "CREATE INDEX IF NOT EXISTS idx_events_package ON sdk_events (package_name, server_ts DESC)",
            """CREATE MATERIALIZED VIEW mv_daily_event_stats AS
SELECT date_trunc('day', server_ts)::DATE AS stat_date,
       event_type,
       package_name,
       payload->>'page' AS page,
       payload->>'element' AS element,
       COUNT(*) AS event_count,
       COUNT(DISTINCT device_id) AS unique_devices
FROM sdk_events
GROUP BY 1, 2, 3, 4, 5""",
            """CREATE UNIQUE INDEX idx_mv_daily ON mv_daily_event_stats
(stat_date, event_type, package_name, page, element)""",
        ]
    )
    return statements


async def _columns(connection, relation: str) -> set[str]:
    rows = await connection.execute(
        text(
            "SELECT attribute.attname FROM pg_attribute attribute "
            "JOIN pg_class relation ON relation.oid=attribute.attrelid "
            "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "WHERE namespace.nspname=current_schema() AND relation.relname=:relation "
            "AND attribute.attnum > 0 AND NOT attribute.attisdropped"
        ),
        {"relation": relation},
    )
    return {str(row[0]) for row in rows}


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def read_snapshot(connection) -> SchemaSnapshot:
    event_columns = await _columns(connection, "sdk_events")
    if "app_id" in event_columns and "package_name" in event_columns:
        raise RuntimeError("sdk_events 同时存在 app_id 和 package_name")
    package_column = "package_name" if "package_name" in event_columns else "app_id"
    if package_column not in event_columns:
        raise RuntimeError("sdk_events 缺少包名列")

    total_count = int(
        (await connection.execute(text("SELECT COUNT(*) FROM sdk_events"))).scalar_one()
    )
    non_null_package_count = int(
        (
            await connection.execute(
                text(f"SELECT COUNT(*) FROM sdk_events WHERE {package_column} IS NOT NULL")
            )
        ).scalar_one()
    )
    partition_names = (
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
    partition_columns: dict[str, set[str]] = {}
    partition_counts: dict[str, int] = {}
    for raw_name in partition_names:
        name = str(raw_name)
        columns = await _columns(connection, name)
        partition_columns[name] = columns
        if package_column not in columns:
            raise RuntimeError(f"分区表 {name} 缺少 {package_column} 列")
        partition_counts[name] = int(
            (
                await connection.execute(
                    text(f"SELECT COUNT(*) FROM {_quoted_identifier(name)}")
                )
            ).scalar_one()
        )
    return SchemaSnapshot(
        total_count=total_count,
        non_null_package_count=non_null_package_count,
        partition_counts=partition_counts,
        partition_columns=partition_columns,
        event_columns=event_columns,
        view_columns=await _columns(connection, "mv_daily_event_stats"),
    )


def verify_lossless(before: SchemaSnapshot, after: SchemaSnapshot) -> None:
    if before.total_count != after.total_count:
        raise RuntimeError(
            f"迁移前后事件数不一致: {before.total_count} != {after.total_count}"
        )
    if before.non_null_package_count != after.non_null_package_count:
        raise RuntimeError("迁移前后非空包名数不一致")
    if before.partition_counts != after.partition_counts:
        raise RuntimeError("迁移前后分区行数不一致")
    if "package_name" not in after.event_columns or "app_id" in after.event_columns:
        raise RuntimeError("sdk_events 列迁移验证失败")
    if "package_name" not in after.view_columns or "app_id" in after.view_columns:
        raise RuntimeError("物化视图迁移验证失败")
    invalid_partitions = [
        name
        for name, columns in after.partition_columns.items()
        if "package_name" not in columns or "app_id" in columns
    ]
    if invalid_partitions:
        raise RuntimeError("分区表列迁移失败: " + ", ".join(invalid_partitions))


async def migrate(database_url: str, *, apply: bool) -> MigrationReport:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            before = await read_snapshot(connection)
            statements = build_migration_statements(before.event_columns, before.view_columns)
            if not apply:
                return MigrationReport(statements=statements, before=before)
            for statement in statements:
                await connection.execute(text(statement))
            after = await read_snapshot(connection)
            verify_lossless(before, after)
            return MigrationReport(statements=statements, before=before, after=after)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行迁移；默认仅预检")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("必须设置 DATABASE_URL")
    if args.apply and args.confirm != "MIGRATE_EVENT_PACKAGE_NAME":
        raise SystemExit(
            "正式迁移必须传入 --confirm MIGRATE_EVENT_PACKAGE_NAME"
        )
    report = asyncio.run(migrate(database_url, apply=args.apply))
    action = "迁移完成" if args.apply else "预检通过"
    print(
        f"{action}: statements={len(report.statements)}, events={report.before.total_count}, "
        f"non_null_package={report.before.non_null_package_count}, "
        f"partitions={len(report.before.partition_counts)}"
    )
    for name, count in report.before.partition_counts.items():
        print(f"partition={name}, rows={count}")
    for statement in report.statements:
        print(statement.splitlines()[0])


if __name__ == "__main__":
    main()
