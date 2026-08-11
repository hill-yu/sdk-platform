import asyncio

from scripts.migrate_event_package_name import _columns, build_migration_statements


def test_old_event_schema_builds_lossless_package_name_migration():
    statements = build_migration_statements(
        event_columns={"app_id"},
        view_columns={"app_id"},
    )
    sql = "\n".join(statements)

    assert "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats" in statements[0]
    assert "RENAME COLUMN app_id TO package_name" in sql
    assert "ALTER COLUMN package_name TYPE VARCHAR(255)" in sql
    assert "DROP INDEX IF EXISTS idx_events_app" in sql
    assert "idx_events_package" in sql
    assert "package_name" in sql


def test_migrated_schema_requires_no_changes():
    assert build_migration_statements(
        event_columns={"package_name"},
        view_columns={"package_name"},
    ) == []


def test_migration_rebuilds_legacy_view_when_event_column_is_already_migrated():
    statements = build_migration_statements(
        event_columns={"package_name"},
        view_columns={"app_id"},
    )
    sql = "\n".join(statements)

    assert "RENAME COLUMN" not in sql
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats" in sql
    assert "package_name" in sql


def test_migration_rejects_ambiguous_event_columns():
    try:
        build_migration_statements(
            event_columns={"app_id", "package_name"},
            view_columns={"app_id"},
        )
    except RuntimeError as exc:
        assert "同时存在" in str(exc)
    else:
        raise AssertionError("expected ambiguous schema to be rejected")


def test_column_inspection_uses_postgres_catalog_for_materialized_views():
    class Result:
        def __iter__(self):
            return iter([("package_name",), ("event_type",)])

    class Connection:
        async def execute(self, statement, params):
            assert "pg_attribute" in str(statement)
            assert params == {"relation": "mv_daily_event_stats"}
            return Result()

    columns = asyncio.run(_columns(Connection(), "mv_daily_event_stats"))
    assert columns == {"package_name", "event_type"}
