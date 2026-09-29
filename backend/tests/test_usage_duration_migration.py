from pathlib import Path
import re

from sqlalchemy import CheckConstraint

from app.models.usage_duration import SdkUsageDuration


ROOT = Path(__file__).resolve().parents[2]


def test_usage_duration_model_has_expected_table_and_check_constraint():
    assert SdkUsageDuration.__tablename__ == "sdk_usage_durations"
    columns = SdkUsageDuration.__table__.columns
    assert columns["package_name"].nullable is False
    assert columns["device_id"].nullable is False
    assert columns["app_version"].nullable is False
    assert columns["duration_s"].nullable is False
    checks = {
        str(constraint.sqltext)
        for constraint in SdkUsageDuration.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "duration_s BETWEEN 1 AND 3600" in checks


def _assert_usage_duration_ddl(sql: str):
    assert "CREATE TABLE IF NOT EXISTS sdk_usage_durations" in sql
    assert re.search(r"duration_s\s+INTEGER", sql)
    assert "CHECK (duration_s BETWEEN 1 AND 3600)" in sql
    assert "idx_usage_durations_server_ts" in sql
    assert "idx_usage_durations_package_ts" in sql
    assert "idx_usage_durations_package_device_ts" in sql


def test_init_db_contains_usage_duration_table_and_indexes():
    _assert_usage_duration_ddl((ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8"))


def test_incremental_migration_is_idempotent_by_construction():
    sql = (ROOT / "scripts" / "migrate_usage_durations.sql").read_text(encoding="utf-8")
    _assert_usage_duration_ddl(sql)
    assert sql.count("CREATE TABLE IF NOT EXISTS sdk_usage_durations") == 1
    assert sql.count("CREATE INDEX IF NOT EXISTS") == 3
