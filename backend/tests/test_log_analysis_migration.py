import asyncio

import pytest
from sqlalchemy import inspect


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

    assert [column.name for column in inspect(PackageProfile).primary_key] == ["package_name"]
    assert [column.name for column in inspect(AdminPreference).primary_key] == ["preference_key"]

    reparse_columns = set(LogReparseJob.__table__.c.keys())
    assert {"range_start", "range_end", "cursor_event_id", "cursor_server_ts", "processed_count", "failed_count", "status", "error_summary"} <= reparse_columns
    assert "extra" not in reparse_columns
    assert "raw_extra" not in reparse_columns


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
        "idx_log_decodes_trace_id",
        "idx_package_profiles_updated",
        "idx_admin_preferences_updated",
        "idx_log_reparse_jobs_status",
        "idx_log_reparse_jobs_range",
    ):
        assert index in sql

    assert "(server_ts AT TIME ZONE 'Asia/Shanghai')::date AS stat_date" in sql
    assert "date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai') AS hour" in sql


def test_migration_plan_builds_tables_indexes_and_beijing_views():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(existing_tables=set(), view_summaries={})
    sql = "\n".join(statements)

    assert "CREATE TABLE IF NOT EXISTS sdk_log_decodes" in sql
    assert "PRIMARY KEY (event_id, event_server_ts, record_index)" in sql
    assert "record_index      INTEGER      NOT NULL" in sql
    assert "CREATE TABLE IF NOT EXISTS sdk_package_profiles" in sql
    assert "package_name      VARCHAR(255) PRIMARY KEY" in sql
    assert "CREATE TABLE IF NOT EXISTS sdk_admin_preferences" in sql
    assert "preference_key    VARCHAR(128) PRIMARY KEY" in sql
    assert "CREATE TABLE IF NOT EXISTS sdk_log_reparse_jobs" in sql
    assert "raw_extra" not in sql
    assert "extra JSONB" not in sql
    assert "(server_ts AT TIME ZONE 'Asia/Shanghai')::date" in sql
    assert "date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai')" in sql


def test_migrated_schema_requires_no_destructive_statements():
    from scripts.migrate_log_analysis import (
        EXPECTED_VIEW_SUMMARIES,
        REQUIRED_TABLES,
        build_migration_statements,
    )

    statements = build_migration_statements(
        existing_tables=set(REQUIRED_TABLES),
        view_summaries=EXPECTED_VIEW_SUMMARIES,
    )
    sql = "\n".join(statements)

    assert "CREATE TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "ALTER TABLE sdk_events" not in sql


def test_migrated_schema_with_legacy_utc_views_rebuilds_only_views():
    from scripts.migrate_log_analysis import REQUIRED_TABLES, build_migration_statements

    statements = build_migration_statements(
        existing_tables=set(REQUIRED_TABLES),
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
    assert "date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai')" in sql


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
            if "COUNT(*) FROM sdk_events WHERE payload ? 'extra'" in sql:
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
            if "to_regclass" in sql:
                return Result([(None,)])
            raise AssertionError(sql)

    snapshot = asyncio.run(read_snapshot(Connection()))

    assert snapshot.total_count == 3
    assert snapshot.non_null_extra_count == 2
    assert snapshot.partition_counts == {"sdk_events_202609": 1, "sdk_events_202610": 2}
    assert set(snapshot.view_summaries) == {"mv_daily_event_stats", "mv_hourly_trend"}
    assert all(summary.startswith("sha256:") for summary in snapshot.view_summaries.values())


def test_dry_run_reads_snapshot_but_executes_no_ddl(monkeypatch):
    from scripts import migrate_log_analysis

    class Connection:
        def __init__(self):
            self.executed = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.executed.append(sql)
            if "COUNT(*) FROM sdk_events WHERE payload ? 'extra'" in sql:
                return _Result([(1,)])
            if "COUNT(*) FROM sdk_events" in sql:
                return _Result([(1,)])
            if "pg_inherits" in sql:
                return _Result([])
            if "pg_matviews" in sql:
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

    engine = _ApplyEngine(existing_tables_before=set(), existing_tables_after=set(migrate_log_analysis.REQUIRED_TABLES))
    monkeypatch.setattr(migrate_log_analysis, "create_async_engine", lambda _url: engine)

    report = asyncio.run(migrate_log_analysis.migrate("postgresql+asyncpg://test", apply=True))

    ddl = "\n".join(engine.connection.ddl)
    assert report.after is not None
    assert engine.connection.entered_transaction
    assert "CREATE TABLE IF NOT EXISTS sdk_log_decodes" in ddl
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_daily_event_stats" in ddl
    assert "sdk_events" not in [sql.split()[2] for sql in engine.connection.ddl if sql.startswith("UPDATE ")]


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
        return False


class _ApplyConnection:
    def __init__(self, existing_tables_before, existing_tables_after):
        self.existing_tables_before = existing_tables_before
        self.existing_tables_after = existing_tables_after
        self.snapshot_reads = 0
        self.ddl = []
        self.entered_transaction = False

    async def execute(self, statement, params=None):
        sql = str(statement)
        if sql.lstrip().upper().startswith(("CREATE ", "DROP ", "ALTER ")):
            self.ddl.append(sql)
            return _Result([])
        if "COUNT(*) FROM sdk_events WHERE payload ? 'extra'" in sql:
            return _Result([(2,)])
        if "COUNT(*) FROM sdk_events" in sql:
            return _Result([(3,)])
        if "pg_inherits" in sql:
            return _Result([("sdk_events_202609",)])
        if "FROM \"sdk_events_202609\"" in sql:
            return _Result([(3,)])
        if "pg_matviews" in sql:
            self.snapshot_reads += 1
            return _Result([("mv_daily_event_stats", "SELECT old daily"), ("mv_hourly_trend", "SELECT old hourly")])
        if "to_regclass" in sql:
            table = params["relation"].split(".")[-1]
            existing = self.existing_tables_after if self.ddl else self.existing_tables_before
            return _Result([(table if table in existing else None,)])
        raise AssertionError(sql)


class _ApplyEngine:
    def __init__(self, existing_tables_before, existing_tables_after):
        self.connection = _ApplyConnection(existing_tables_before, existing_tables_after)

    def begin(self):
        return _Begin(self.connection)

    async def dispose(self):
        pass
