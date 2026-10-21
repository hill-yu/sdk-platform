from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_package_catalog_model_matches_directory_contract():
    from app.models.package_catalog import PackageCatalog

    columns = PackageCatalog.__table__.columns
    assert list(columns.keys()) == ["package_name", "has_log", "has_usage", "created_at", "updated_at"]
    assert columns["package_name"].primary_key is True
    assert columns["package_name"].type.length == 255
    assert columns["has_log"].nullable is False
    assert columns["has_usage"].nullable is False
    assert columns["created_at"].nullable is False
    assert columns["updated_at"].nullable is False


def test_package_catalog_migration_is_idempotent_and_searchable():
    sql = (ROOT / "scripts" / "migrate_package_catalog.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in sql
    assert "CREATE TABLE IF NOT EXISTS sdk_package_catalog" in sql
    assert "package_name VARCHAR(255) PRIMARY KEY" in sql
    assert "has_log BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "has_usage BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_package_catalog_name_trgm" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "lock_timeout" in sql
    assert "statement_timeout" in sql

    init_sql = (ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS sdk_package_catalog" in init_sql
    assert "CREATE INDEX IF NOT EXISTS idx_package_catalog_name_trgm" in init_sql

