"""Migrate sdk_events.app_id to package_name without losing event data."""
from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


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


async def migrate(database_url: str, *, apply: bool) -> Sequence[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            event_columns = await _columns(connection, "sdk_events")
            view_columns = await _columns(connection, "mv_daily_event_stats")
            statements = build_migration_statements(event_columns, view_columns)
            if not apply:
                return statements

            before_count = (
                await connection.execute(text("SELECT COUNT(*) FROM sdk_events"))
            ).scalar_one()
            for statement in statements:
                await connection.execute(text(statement))

            after_columns = await _columns(connection, "sdk_events")
            after_view_columns = await _columns(connection, "mv_daily_event_stats")
            after_count = (
                await connection.execute(text("SELECT COUNT(*) FROM sdk_events"))
            ).scalar_one()
            missing_partition_columns = (
                await connection.execute(
                    text(
                        "SELECT child.relname FROM pg_inherits i "
                        "JOIN pg_class parent ON parent.oid=i.inhparent "
                        "JOIN pg_class child ON child.oid=i.inhrelid "
                        "WHERE parent.relname='sdk_events' AND NOT EXISTS ("
                        "SELECT 1 FROM pg_attribute a WHERE a.attrelid=child.oid "
                        "AND a.attname='package_name' AND NOT a.attisdropped)"
                    )
                )
            ).scalars().all()
            if before_count != after_count:
                raise RuntimeError(
                    f"迁移前后事件数不一致: {before_count} != {after_count}"
                )
            if "package_name" not in after_columns or "app_id" in after_columns:
                raise RuntimeError("sdk_events 列迁移验证失败")
            if "package_name" not in after_view_columns or "app_id" in after_view_columns:
                raise RuntimeError("物化视图迁移验证失败")
            if missing_partition_columns:
                raise RuntimeError(
                    "分区表缺少 package_name: " + ", ".join(missing_partition_columns)
                )
            return statements
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
    statements = asyncio.run(migrate(database_url, apply=args.apply))
    action = "迁移完成" if args.apply else "预检通过"
    print(f"{action}: statements={len(statements)}")
    for statement in statements:
        print(statement.splitlines()[0])


if __name__ == "__main__":
    main()
