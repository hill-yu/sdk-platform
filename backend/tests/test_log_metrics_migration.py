from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_h1_and_click_tables_expose_required_business_keys() -> None:
    from app.models.log_metrics import (
        H1Declaration,
        H1DeclarationStage,
        LogClickAttempt,
        LogClickAttemptStage,
    )

    h1 = inspect(H1Declaration).local_table
    click = inspect(LogClickAttempt).local_table
    h1_stage = inspect(H1DeclarationStage).local_table
    click_stage = inspect(LogClickAttemptStage).local_table

    assert {
        "event_id",
        "event_server_ts",
        "record_index",
        "config_id",
        "declared_click_count",
    } <= set(h1.c.keys())
    assert {
        "attempt_index",
        "target_kind",
        "did_click",
        "navigation_code",
        "failure_category",
    } <= set(click.c.keys())
    assert [column.name for column in h1.primary_key] == [
        "event_id",
        "event_server_ts",
        "record_index",
    ]
    assert [column.name for column in click.primary_key] == [
        "event_id",
        "event_server_ts",
        "record_index",
        "attempt_index",
    ]
    assert {"job_id", "event_id", "record_index"} <= set(h1_stage.c.keys())
    assert {"job_id", "attempt_index"} <= set(click_stage.c.keys())


def test_log_metrics_models_define_required_indexes() -> None:
    from app.models.log_metrics import H1Declaration, LogClickAttempt

    index_names = {
        index.name
        for model in (H1Declaration, LogClickAttempt)
        for index in model.__table__.indexes
    }

    assert {
        "idx_log_h1_package_ts_config",
        "idx_log_click_package_ts_config_target",
    } <= index_names


def test_task_model_contains_snapshot_and_progress_fields() -> None:
    from app.models.log_analysis import LogReparseJob

    columns = inspect(LogReparseJob).columns
    required = {
        "snapshot_end",
        "total_count",
        "h1_count",
        "failed_h1_count",
        "no_h1_count",
        "batch_size",
        "concurrency",
        "started_at",
        "finished_at",
        "last_heartbeat_at",
        "cancel_requested_at",
    }

    assert required <= set(columns.keys())


def test_log_metrics_migration_is_idempotent_and_preserves_old_tables() -> None:
    sql = (REPOSITORY_ROOT / "scripts" / "migrate_log_metrics_v2.sql").read_text(
        encoding="utf-8"
    )

    for table in (
        "sdk_log_h1_declarations",
        "sdk_log_click_attempts",
        "sdk_log_h1_declaration_stage",
        "sdk_log_click_attempt_stage",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    for column in (
        "snapshot_end",
        "total_count",
        "h1_count",
        "failed_h1_count",
        "no_h1_count",
        "batch_size",
        "concurrency",
        "cancel_requested_at",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql

    assert "CREATE INDEX IF NOT EXISTS idx_log_h1_package_ts_config" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_log_click_package_ts_config_target" in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql


def test_init_db_contains_log_metrics_tables_and_indexes() -> None:
    sql = (REPOSITORY_ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8")

    for table in (
        "sdk_log_h1_declarations",
        "sdk_log_click_attempts",
        "sdk_log_h1_declaration_stage",
        "sdk_log_click_attempt_stage",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "idx_log_h1_package_ts_config" in sql
    assert "idx_log_click_package_ts_config_target" in sql


def test_unified_migration_requires_metric_tables_and_indexes() -> None:
    from scripts import migrate_log_analysis

    required_tables = {
        "sdk_log_h1_declarations",
        "sdk_log_click_attempts",
        "sdk_log_h1_declaration_stage",
        "sdk_log_click_attempt_stage",
    }
    required_indexes = {
        "idx_log_h1_package_ts_config",
        "idx_log_click_package_ts_config_target",
        "idx_log_h1_stage_job",
        "idx_log_click_stage_job",
    }

    assert required_tables <= set(migrate_log_analysis.REQUIRED_TABLES)
    assert required_indexes <= set(migrate_log_analysis.REQUIRED_INDEXES)

    statements = migrate_log_analysis.build_migration_statements(
        existing_tables=set(),
        existing_indexes=set(),
        view_summaries={},
    )
    sql = "\n".join(statements)
    assert all(f"CREATE TABLE IF NOT EXISTS {table}" in sql for table in required_tables)
    assert all(f"CREATE INDEX IF NOT EXISTS {index}" in sql for index in required_indexes)


def test_metrics_migration_plan_does_not_touch_missing_reparse_table() -> None:
    from scripts import migrate_log_analysis

    statements = migrate_log_analysis.build_log_metrics_migration_statements(
        existing_tables=set(), existing_indexes=set(), existing_columns={}
    )

    assert not any("sdk_log_reparse_jobs" in statement for statement in statements)
    assert any("sdk_log_h1_declarations" in statement for statement in statements)


def test_metrics_migration_plan_is_empty_after_schema_is_present() -> None:
    from scripts import migrate_log_analysis

    statements = migrate_log_analysis.build_log_metrics_migration_statements(
        existing_tables=set(migrate_log_analysis.LOG_METRICS_TABLES),
        existing_indexes=set(migrate_log_analysis.LOG_METRICS_INDEX_NAMES),
        existing_columns={},
    )

    assert statements == []
