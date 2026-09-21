import asyncio

import pytest
from sqlalchemy import inspect

REQUIRED_LOG_ANALYSIS_INDEXES = {
    "idx_log_decodes_package_ts",
    "idx_log_decodes_status_ts",
    "idx_log_decodes_decoder_status",
    "idx_log_decodes_event_ts",
    "idx_package_profiles_updated",
    "idx_admin_preferences_updated",
    "idx_log_reparse_jobs_status",
    "idx_log_reparse_jobs_range",
}


def test_log_analysis_models_define_required_keys_and_no_raw_extra_storage():
    from app.models.log_analysis import (
        AdminPreference,
        LogDecode,
        LogReparseJob,
        PackageProfile,
    )

    decode_pk = [column.name for column in inspect(LogDecode).primary_key]
    assert decode_pk == ["event_id", "event_server_ts", "record_index"]
    assert LogDecode.__table__.c.record_index.nullable is False
    assert set(inspect(LogDecode).columns.keys()) == {
        "event_id",
        "event_server_ts",
        "record_index",
        "package_name",
        "device_id",
        "status",
        "decoder_version",
        "decoded_timestamp",
        "url",
        "config_id",
        "window",
        "expected_click_count",
        "actual_click_count",
        "ad_click_count",
        "interstitial_presentation_count",
        "interstitial_click_count",
        "interstitial_close_count",
        "duration_ms",
        "final_reason",
        "is_success",
        "decoded_payload",
        "parse_error",
        "parsed_at",
    }
    assert not {
        "decoder_name",
        "trace_id",
        "decode_status",
        "error_summary",
        "created_at",
        "updated_at",
    } & set(inspect(LogDecode).columns.keys())
    assert LogDecode.status.default.arg == "pending"
    constraints = " ".join(
        str(constraint.sqltext)
        for constraint in LogDecode.__table__.constraints
        if hasattr(constraint, "sqltext")
    )
    assert "pending" in constraints
    assert "success" in constraints
    assert "unsupported" in constraints
    assert "failed" in constraints

    assert [column.name for column in inspect(PackageProfile).primary_key] == ["package_name"]
    assert set(inspect(PackageProfile).columns.keys()) == {
        "package_name",
        "alias",
        "company",
        "account",
        "created_at",
        "updated_at",
    }
    assert [column.name for column in inspect(AdminPreference).primary_key] == ["preference_key"]
    assert set(inspect(AdminPreference).columns.keys()) == {
        "preference_key",
        "value",
        "updated_at",
    }

    reparse_columns = set(LogReparseJob.__table__.c.keys())
    assert {"range_start", "range_end", "cursor_event_id", "cursor_server_ts", "processed_count", "failed_count", "status", "error_summary"} <= reparse_columns
    assert "extra" not in reparse_columns
    assert "raw_extra" not in reparse_columns


def test_log_decode_pending_contract_uses_status_and_composite_key():
    from app.models.log_analysis import LogDecode

    assert [column.name for column in LogDecode.__table__.primary_key.columns] == [
        "event_id",
        "event_server_ts",
        "record_index",
    ]
    assert LogDecode.__table__.c.record_index.nullable is False
    assert LogDecode.__table__.c.status.type.length == 32
    assert LogDecode.__table__.c.parsed_at.nullable is False

    from sqlalchemy.dialects.postgresql import insert

    statement = insert(LogDecode).values(
        event_id=1,
        event_server_ts="2026-08-17T00:00:00+00:00",
        record_index=-1,
        package_name="com.example",
        status="pending",
        decoder_version="1.0.0",
        parsed_at="2026-08-17T00:00:00+00:00",
    )
    assert statement.compile().params["record_index"] == -1
    assert statement.compile().params["status"] == "pending"


def test_init_db_contains_log_analysis_tables_indexes_and_beijing_views():
    sql = open("scripts/init_db.sql", encoding="utf-8").read()

    for table in (
        "sdk_log_decodes",
        "sdk_package_profiles",
        "sdk_admin_preferences",
        "sdk_log_reparse_jobs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    for index in (
        "idx_log_decodes_package_ts",
        "idx_log_decodes_status_ts",
        "idx_log_decodes_decoder_status",
        "idx_log_decodes_event_ts",
        "idx_package_profiles_updated",
        "idx_admin_preferences_updated",
        "idx_log_reparse_jobs_status",
        "idx_log_reparse_jobs_range",
    ):
        assert index in sql

    assert "(server_ts AT TIME ZONE 'Asia/Shanghai')::date AS stat_date" in sql
    assert "date_trunc('hour', server_ts, 'Asia/Shanghai') AS hour" in sql
    assert "date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai') AS hour" not in sql


def test_migration_plan_builds_tables_indexes_and_beijing_views():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(existing_tables=set(), view_summaries={})
    sql = "\n".join(statements)

    assert "CREATE TABLE IF NOT EXISTS sdk_log_decodes" in sql
    assert "PRIMARY KEY (event_id, event_server_ts, record_index)" in sql
    assert "record_index" in sql and "INTEGER" in sql and "NOT NULL" in sql
    assert "status" in sql and "VARCHAR(32)" in sql
    assert "CHECK (status IN ('pending', 'success', 'unsupported', 'failed'))" in sql
    assert "parse_error" in sql and "VARCHAR(512)" in sql
    decode_sql = sql.split("CREATE TABLE IF NOT EXISTS sdk_package_profiles", 1)[0]
    assert "decoder_name" not in decode_sql
    assert "trace_id" not in decode_sql
    assert "decode_status" not in decode_sql
    assert "error_summary" not in decode_sql
    assert "CREATE TABLE IF NOT EXISTS sdk_package_profiles" in sql
    assert "package_name      VARCHAR(255) PRIMARY KEY" in sql
    assert "alias             VARCHAR(255)" in sql
    assert "company           VARCHAR(255)" in sql
    assert "account           VARCHAR(255)" in sql
    assert "display_name" not in sql
    assert "profile           JSONB" not in sql
    assert "CREATE TABLE IF NOT EXISTS sdk_admin_preferences" in sql
    assert "preference_key    VARCHAR(128) PRIMARY KEY" in sql
    assert "value             JSONB" in sql
    assert "preference_value" not in sql
    assert "description" not in sql
    assert "CREATE TABLE IF NOT EXISTS sdk_log_reparse_jobs" in sql
    assert "raw_extra" not in sql
    assert "extra JSONB" not in sql
    assert "status_filter" in sql
    assert "decoder_version_before" in sql
    assert "CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))" in sql
    assert "(server_ts AT TIME ZONE 'Asia/Shanghai')::date" in sql
    assert "date_trunc('hour', server_ts, 'Asia/Shanghai')" in sql
    assert "date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai')" not in sql


def test_hourly_view_uses_timezone_aware_beijing_bucket():
    from scripts.migrate_log_analysis import HOURLY_VIEW_SQL

    assert "date_trunc('hour', server_ts, 'Asia/Shanghai')" in HOURLY_VIEW_SQL
    assert "server_ts AT TIME ZONE 'Asia/Shanghai'" not in HOURLY_VIEW_SQL


def test_old_naive_hour_view_is_rebuilt_without_recreating_log_tables():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(
        existing_tables={
            "sdk_log_decodes",
            "sdk_package_profiles",
            "sdk_admin_preferences",
            "sdk_log_reparse_jobs",
        },
        existing_indexes={
            "idx_log_decodes_package_ts",
            "idx_log_decodes_status_ts",
            "idx_log_decodes_decoder_status",
            "idx_log_decodes_event_ts",
            "idx_package_profiles_updated",
            "idx_admin_preferences_updated",
            "idx_log_reparse_jobs_status",
            "idx_log_reparse_jobs_range",
        },
        view_summaries={
            "mv_daily_event_stats": "sha256:existing|tz:Asia/Shanghai",
            "mv_hourly_trend": "sha256:existing|tz:Asia/Shanghai",
        },
        existing_columns={
            "sdk_log_reparse_jobs": {"status_filter", "decoder_version_before"},
        },
        constraint_definitions={
            "chk_log_reparse_jobs_status": "CHECK ((status)::text = ANY ((ARRAY['pending', 'running', 'success', 'failed', 'cancelled'])::text[]))",
        },
        view_column_types={"mv_hourly_trend.hour": "timestamp without time zone"},
    )

    sql = "\n".join(statements)
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_hourly_trend" in sql
    assert "date_trunc('hour', server_ts, 'Asia/Shanghai')" in sql
    assert "CREATE TABLE" not in sql


def test_legacy_reparse_columns_and_status_constraint_are_upgraded_idempotently():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(
        existing_tables={
            "sdk_log_decodes",
            "sdk_package_profiles",
            "sdk_admin_preferences",
            "sdk_log_reparse_jobs",
        },
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries={
            "mv_daily_event_stats": "sha256:existing|tz:Asia/Shanghai",
            "mv_hourly_trend": "sha256:existing|tz:Asia/Shanghai",
        },
        existing_columns={"sdk_log_reparse_jobs": set()},
        constraint_definitions={
            "chk_log_reparse_jobs_status": "CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))",
        },
        view_column_types={"mv_hourly_trend.hour": "timestamp with time zone"},
    )

    sql = "\n".join(statements)
    assert "ADD COLUMN IF NOT EXISTS status_filter VARCHAR(32)" in sql
    assert "ADD COLUMN IF NOT EXISTS decoder_version_before VARCHAR(32)" in sql
    assert "SET status = 'success' WHERE status = 'succeeded'" in sql
    assert "CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))" in sql


def test_migrated_schema_requires_no_destructive_statements():
    from scripts.migrate_log_analysis import (
        EXPECTED_VIEW_SUMMARIES,
        REQUIRED_TABLES,
        build_migration_statements,
    )

    statements = build_migration_statements(
        existing_tables=set(REQUIRED_TABLES),
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries=EXPECTED_VIEW_SUMMARIES,
    )
    sql = "\n".join(statements)

    assert "CREATE TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "ALTER TABLE sdk_events" not in sql


def test_migrated_schema_with_legacy_utc_views_rebuilds_only_views():
    from scripts.migrate_log_analysis import (
        EXPECTED_VIEW_SUMMARIES,
        REQUIRED_TABLES,
        build_migration_statements,
    )

    statements = build_migration_statements(
        existing_tables=set(REQUIRED_TABLES),
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries={
            "mv_daily_event_stats": "sha256:legacy-utc-daily",
            "mv_hourly_trend": "sha256:legacy-utc-hourly",
        },
    )
    sql = "\n".join(statements)

    assert "CREATE TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "ALTER TABLE sdk_events" not in sql
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats" in sql
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_hourly_trend" in sql
    assert "(server_ts AT TIME ZONE 'Asia/Shanghai')::date" in sql
    assert "date_trunc('hour', server_ts, 'Asia/Shanghai')" in sql


def test_existing_tables_with_missing_indexes_plan_only_safe_index_creation():
    from scripts.migrate_log_analysis import (
        EXPECTED_VIEW_SUMMARIES,
        REQUIRED_TABLES,
        build_migration_statements,
    )

    missing = "idx_log_decodes_status_ts"
    statements = build_migration_statements(
        existing_tables=set(REQUIRED_TABLES),
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES) - {missing},
        view_summaries=EXPECTED_VIEW_SUMMARIES,
    )
    sql = "\n".join(statements)

    assert f"CREATE INDEX IF NOT EXISTS {missing}" in sql
    assert "CREATE TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP MATERIALIZED VIEW" not in sql
    assert all("CREATE INDEX" in statement for statement in statements)


def test_snapshot_includes_counts_partitions_and_view_summaries():
    from scripts.migrate_log_analysis import read_snapshot

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def scalar_one(self):
            return self.rows[0][0]

        def scalars(self):
            return _ScalarRows(self.rows)

        def all(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.queries = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.queries.append(sql)
            if "payload->>'extra' IS NOT NULL" in sql:
                return Result([(2,)])
            if "COUNT(*) FROM sdk_events" in sql:
                return Result([(3,)])
            if "pg_inherits" in sql:
                return Result([("sdk_events_202609",), ("sdk_events_202610",)])
            if "FROM \"sdk_events_202609\"" in sql:
                return Result([(1,)])
            if "FROM \"sdk_events_202610\"" in sql:
                return Result([(2,)])
            if "pg_matviews" in sql:
                return Result([("mv_daily_event_stats", "SELECT old daily"), ("mv_hourly_trend", "SELECT old hourly")])
            if "FROM pg_indexes" in sql:
                return Result([(name,) for name in REQUIRED_LOG_ANALYSIS_INDEXES])
            if "pg_attribute" in sql:
                return Result([("mv_hourly_trend.hour", "timestamp with time zone")])
            if "information_schema.columns" in sql:
                return Result([])
            if "pg_constraint" in sql:
                return Result([])
            if "to_regclass" in sql:
                return Result([(None,)])
            raise AssertionError(sql)

    snapshot = asyncio.run(read_snapshot(Connection()))

    assert snapshot.total_count == 3
    assert snapshot.non_null_extra_count == 2
    assert snapshot.existing_indexes == REQUIRED_LOG_ANALYSIS_INDEXES
    assert snapshot.partition_counts == {"sdk_events_202609": 1, "sdk_events_202610": 2}
    assert set(snapshot.view_summaries) == {"mv_daily_event_stats", "mv_hourly_trend"}
    assert snapshot.view_column_types == {"mv_hourly_trend.hour": "timestamp with time zone"}
    assert all(summary.startswith("sha256:") for summary in snapshot.view_summaries.values())


def test_dry_run_reads_snapshot_but_executes_no_ddl(monkeypatch):
    from scripts import migrate_log_analysis

    class Connection:
        def __init__(self):
            self.executed = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.executed.append(sql)
            if "payload->>'extra' IS NOT NULL" in sql:
                return _Result([(1,)])
            if "COUNT(*) FROM sdk_events" in sql:
                return _Result([(1,)])
            if "pg_inherits" in sql:
                return _Result([])
            if "pg_matviews" in sql:
                return _Result([])
            if "FROM pg_indexes" in sql:
                return _Result([])
            if "pg_attribute" in sql:
                return _Result([])
            if "information_schema.columns" in sql:
                return _Result([])
            if "pg_constraint" in sql:
                return _Result([])
            if "to_regclass" in sql:
                return _Result([(None,)])
            raise AssertionError(f"unexpected dry-run DDL: {sql}")

    class Engine:
        def __init__(self):
            self.connection = Connection()
            self.disposed = False

        def begin(self):
            return _Begin(self.connection)

        async def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr(migrate_log_analysis, "create_async_engine", lambda _url: engine)

    report = asyncio.run(migrate_log_analysis.migrate("postgresql+asyncpg://test", apply=False))

    assert report.after is None
    assert report.statements
    assert not any(sql.lstrip().upper().startswith(("CREATE ", "DROP ", "ALTER ")) for sql in engine.connection.executed)


def test_apply_executes_plan_in_transaction_and_verifies_lossless(monkeypatch):
    from scripts import migrate_log_analysis

    engine = _ApplyEngine(
        existing_tables_before=set(),
        existing_tables_after=set(migrate_log_analysis.REQUIRED_TABLES),
        existing_indexes_after=set(REQUIRED_LOG_ANALYSIS_INDEXES),
    )
    monkeypatch.setattr(migrate_log_analysis, "create_async_engine", lambda _url: engine)

    report = asyncio.run(migrate_log_analysis.migrate("postgresql+asyncpg://test", apply=True))

    ddl = "\n".join(engine.connection.ddl)
    assert report.after is not None
    assert engine.connection.entered_transaction
    assert "CREATE TABLE IF NOT EXISTS sdk_log_decodes" in ddl
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats" in ddl
    assert "sdk_events" not in [sql.split()[2] for sql in engine.connection.ddl if sql.startswith("UPDATE ")]


def test_apply_rolls_back_when_lossless_verification_fails(monkeypatch):
    from scripts import migrate_log_analysis

    engine = _ApplyEngine(
        existing_tables_before=set(),
        existing_tables_after=set(migrate_log_analysis.REQUIRED_TABLES),
        existing_indexes_after=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        after_total=4,
    )
    monkeypatch.setattr(migrate_log_analysis, "create_async_engine", lambda _url: engine)

    with pytest.raises(RuntimeError, match="事件总数"):
        asyncio.run(migrate_log_analysis.migrate("postgresql+asyncpg://test", apply=True))

    assert engine.connection.rolled_back
    assert not engine.connection.committed


def test_snapshot_uses_non_empty_extra_predicate_for_null_blank_and_whitespace():
    from scripts import migrate_log_analysis

    class Connection:
        def __init__(self):
            self.queries = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.queries.append(sql)
            if "payload->>'extra' IS NOT NULL" in sql:
                return _Result([(3,)])
            if "COUNT(*) FROM sdk_events" in sql:
                return _Result([(5,)])
            if "pg_inherits" in sql:
                return _Result([])
            if "pg_matviews" in sql:
                return _Result([])
            if "FROM pg_indexes" in sql:
                return _Result([])
            if "pg_attribute" in sql:
                return _Result([])
            if "information_schema.columns" in sql:
                return _Result([])
            if "pg_constraint" in sql:
                return _Result([])
            if "to_regclass" in sql:
                return _Result([(None,)])
            raise AssertionError(sql)

    connection = Connection()
    snapshot = asyncio.run(migrate_log_analysis.read_snapshot(connection))
    assert snapshot.non_null_extra_count == 3
    predicate = next(query for query in connection.queries if "extra" in query)
    assert "payload->>'extra' IS NOT NULL" in predicate
    assert "BTRIM(payload->>'extra') <> ''" in predicate


def test_snapshot_does_not_use_regclass_cast_when_reparse_table_is_missing():
    from scripts import migrate_log_analysis

    class Connection:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "pg_constraint" in sql:
                assert "::regclass" not in sql
                return _Result([])
            if "payload->>'extra' IS NOT NULL" in sql:
                return _Result([(0,)])
            if "COUNT(*) FROM sdk_events" in sql:
                return _Result([(0,)])
            if "pg_inherits" in sql or "pg_matviews" in sql or "pg_indexes" in sql:
                return _Result([])
            if "pg_attribute" in sql or "information_schema.columns" in sql:
                return _Result([])
            if "to_regclass" in sql:
                return _Result([(None,)])
            raise AssertionError(sql)

    snapshot = asyncio.run(migrate_log_analysis.read_snapshot(Connection()))

    assert snapshot.existing_tables == set()


def test_existing_reparse_table_is_upgraded_when_other_required_tables_are_missing():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(
        existing_tables={"sdk_log_reparse_jobs"},
        existing_indexes=set(),
        view_summaries={},
        existing_columns={"sdk_log_reparse_jobs": set()},
        constraint_definitions={
            "chk_log_reparse_jobs_status":
            "CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))"
        },
    )

    sql = "\n".join(statements)
    assert "ADD COLUMN IF NOT EXISTS status_filter VARCHAR(32)" in sql
    assert "ADD COLUMN IF NOT EXISTS decoder_version_before VARCHAR(32)" in sql
    assert "ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(64)" in sql
    assert "ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ" in sql


def test_status_constraint_migration_drops_updates_then_adds():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(
        existing_tables={"sdk_log_reparse_jobs"},
        existing_indexes=set(),
        view_summaries={},
        existing_columns={
            "sdk_log_reparse_jobs": {
                "status_filter",
                "decoder_version_before",
                "lease_owner",
                "lease_expires_at",
            }
        },
        constraint_definitions={
            "chk_log_reparse_jobs_status":
            "CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))"
        },
    )

    drop = next(i for i, statement in enumerate(statements) if "DROP CONSTRAINT" in statement)
    update = next(i for i, statement in enumerate(statements) if "SET status = 'success'" in statement)
    add = next(i for i, statement in enumerate(statements) if "ADD CONSTRAINT" in statement)
    assert drop < update < add


def test_verify_lossless_requires_reparse_postconditions_and_timezone_hour():
    from scripts.migrate_log_analysis import REQUIRED_TABLES, SchemaSnapshot, verify_lossless

    common = dict(
        total_count=1,
        non_null_extra_count=1,
        partition_counts={"sdk_events_202609": 1},
        existing_tables=set(REQUIRED_TABLES),
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries={},
        existing_columns={
            "sdk_log_reparse_jobs": {
                "status_filter",
                "decoder_version_before",
                "lease_owner",
                "lease_expires_at",
            }
        },
        constraint_definitions={
            "chk_log_reparse_jobs_status":
            "CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))"
        },
        view_column_types={"mv_hourly_trend.hour": "timestamp with time zone"},
    )

    verify_lossless(SchemaSnapshot(**common), SchemaSnapshot(**common))


def test_verify_lossless_rejects_status_constraint_with_extra_value():
    from scripts.migrate_log_analysis import REQUIRED_TABLES, SchemaSnapshot, verify_lossless

    snapshot = SchemaSnapshot(
        total_count=1,
        non_null_extra_count=1,
        partition_counts={"sdk_events_202609": 1},
        existing_tables=set(REQUIRED_TABLES),
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries={},
        existing_columns={
            "sdk_log_reparse_jobs": {
                "status_filter",
                "decoder_version_before",
                "lease_owner",
                "lease_expires_at",
            }
        },
        constraint_definitions={
            "chk_log_reparse_jobs_status":
            "CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled', 'other'))"
        },
        view_column_types={"mv_hourly_trend.hour": "timestamp with time zone"},
    )

    with pytest.raises(RuntimeError, match="状态约束"):
        verify_lossless(snapshot, snapshot)


def test_reverse_status_constraint_is_not_the_target_constraint():
    from scripts import migrate_log_analysis
    from scripts.migrate_log_analysis import REQUIRED_TABLES, SchemaSnapshot

    definition = "CHECK (status NOT IN ('pending', 'running', 'success', 'failed', 'cancelled'))"

    assert not migrate_log_analysis._has_exact_reparse_status_constraint(definition)

    statements = migrate_log_analysis.build_migration_statements(
        existing_tables={"sdk_log_reparse_jobs"},
        existing_columns={
            "sdk_log_reparse_jobs": {
                "status_filter",
                "decoder_version_before",
                "lease_owner",
                "lease_expires_at",
            }
        },
        constraint_definitions={"chk_log_reparse_jobs_status": definition},
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries={
            "mv_daily_event_stats": "sha256:existing|tz:Asia/Shanghai",
            "mv_hourly_trend": "sha256:existing|tz:Asia/Shanghai",
        },
        view_column_types={"mv_hourly_trend.hour": "timestamp with time zone"},
    )

    assert any("DROP CONSTRAINT" in statement for statement in statements)

    snapshot = SchemaSnapshot(
        total_count=1,
        non_null_extra_count=1,
        partition_counts={"sdk_events_202609": 1},
        existing_tables=set(REQUIRED_TABLES),
        existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES),
        view_summaries={},
        existing_columns={
            "sdk_log_reparse_jobs": {
                "status_filter",
                "decoder_version_before",
                "lease_owner",
                "lease_expires_at",
            }
        },
        constraint_definitions={"chk_log_reparse_jobs_status": definition},
        view_column_types={"mv_hourly_trend.hour": "timestamp with time zone"},
    )
    with pytest.raises(RuntimeError, match="状态约束"):
        migrate_log_analysis.verify_lossless(snapshot, snapshot)


def test_log_decode_window_is_quoted_in_raw_install_sql():
    init_sql = open("scripts/init_db.sql", encoding="utf-8").read()
    migration_sql = open("scripts/migrate_log_analysis.py", encoding="utf-8").read()

    assert '"window" VARCHAR(32)' in init_sql
    assert '"window" VARCHAR(32)' in migration_sql


def _snapshot(*, total=3, non_null=3, partitions=None, indexes=None):
    from scripts.migrate_log_analysis import REQUIRED_TABLES, SchemaSnapshot

    values = dict(
        total_count=total,
        non_null_extra_count=non_null,
        partition_counts=partitions or {"sdk_events_202608": 3},
        existing_tables=set(REQUIRED_TABLES),
        view_summaries={},
    )
    try:
        return SchemaSnapshot(
            **values,
            existing_indexes=set(REQUIRED_LOG_ANALYSIS_INDEXES if indexes is None else indexes),
        )
    except TypeError:
        return SchemaSnapshot(**values)


@pytest.mark.parametrize(
    "after,error",
    [
        (_snapshot(total=2), "事件总数"),
        (_snapshot(non_null=2), "非空extra"),
        (_snapshot(partitions={"sdk_events_202608": 2}), "分区行数"),
        (_snapshot(indexes=set()), "索引"),
    ],
)
def test_verify_lossless_rejects_any_changed_snapshot(after, error):
    from scripts.migrate_log_analysis import verify_lossless

    with pytest.raises(RuntimeError, match=error):
        verify_lossless(_snapshot(), after)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one(self):
        return self.rows[0][0]

    def scalars(self):
        return _ScalarRows(self.rows)

    def all(self):
        return self.rows


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return [row[0] for row in self.rows]


class _Begin:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.entered_transaction = True
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.connection.committed = True
        else:
            self.connection.rolled_back = True
        return False


class _ApplyConnection:
    def __init__(self, existing_tables_before, existing_tables_after, existing_indexes_after=None, after_total=3):
        self.existing_tables_before = existing_tables_before
        self.existing_tables_after = existing_tables_after
        self.existing_indexes_before = set()
        self.existing_indexes_after = existing_indexes_after or set()
        self.after_total = after_total
        self.snapshot_reads = 0
        self.ddl = []
        self.entered_transaction = False
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement, params=None):
        sql = str(statement)
        if sql.lstrip().upper().startswith(("CREATE ", "DROP ", "ALTER ")):
            self.ddl.append(sql)
            return _Result([])
        if "payload->>'extra' IS NOT NULL" in sql:
            return _Result([(2,)])
        if "COUNT(*) FROM sdk_events" in sql:
            return _Result([(self.after_total if self.ddl else 3,)])
        if "pg_inherits" in sql:
            return _Result([("sdk_events_202609",)])
        if "FROM \"sdk_events_202609\"" in sql:
            return _Result([(3,)])
        if "pg_matviews" in sql:
            self.snapshot_reads += 1
            return _Result([("mv_daily_event_stats", "SELECT old daily"), ("mv_hourly_trend", "SELECT old hourly")])
        if "FROM pg_indexes" in sql:
            indexes = self.existing_indexes_after if self.ddl else self.existing_indexes_before
            return _Result([(name,) for name in indexes])
        if "pg_attribute" in sql:
            return _Result([("mv_hourly_trend.hour", "timestamp with time zone")])
        if "information_schema.columns" in sql:
            if self.ddl:
                return _Result(
                    [
                        ("sdk_log_reparse_jobs", column)
                        for column in (
                            "status_filter",
                            "decoder_version_before",
                            "lease_owner",
                            "lease_expires_at",
                        )
                    ]
                )
            return _Result([])
        if "pg_constraint" in sql:
            if self.ddl:
                return _Result(
                    [
                        (
                            "chk_log_reparse_jobs_status",
                            "CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))",
                        )
                    ]
                )
            return _Result([])
        if "to_regclass" in sql:
            table = params["relation"].split(".")[-1]
            existing = self.existing_tables_after if self.ddl else self.existing_tables_before
            return _Result([(table if table in existing else None,)])
        raise AssertionError(sql)


class _ApplyEngine:
    def __init__(self, existing_tables_before, existing_tables_after, existing_indexes_after=None, after_total=3):
        self.connection = _ApplyConnection(
            existing_tables_before,
            existing_tables_after,
            existing_indexes_after=existing_indexes_after,
            after_total=after_total,
        )

    def begin(self):
        return _Begin(self.connection)

    async def dispose(self):
        pass
