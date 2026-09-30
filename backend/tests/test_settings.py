from app.core.config import Settings
from pydantic import ValidationError
import pytest


def test_database_url_expands_db_password_placeholder():
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://admin:${DB_PASSWORD}@localhost:5432/sdk_platform",
        DB_PASSWORD="secret123",
    )

    assert settings.resolved_database_url == "postgresql+asyncpg://admin:secret123@localhost:5432/sdk_platform"


def test_database_url_restores_password_when_env_interpolation_removes_it():
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://admin:@localhost:5432/sdk_platform",
        DB_PASSWORD="Admin@123456",
    )

    assert (
        settings.resolved_database_url
        == "postgresql+asyncpg://admin:Admin%40123456@localhost:5432/sdk_platform"
    )


def test_parse_worker_settings_keep_the_formal_safety_caps():
    settings = Settings(
        LOG_PARSE_BATCH_SIZE=200,
        LOG_PARSE_CONCURRENCY=3,
        LOG_PARSE_MAX_DAYS=7,
        LOG_PARSE_LEASE_SECONDS=75,
    )

    assert settings.LOG_PARSE_BATCH_SIZE == 200
    assert settings.LOG_PARSE_CONCURRENCY == 3
    assert settings.LOG_PARSE_MAX_DAYS == 7
    assert settings.LOG_PARSE_LEASE_SECONDS == 75

    with pytest.raises(ValidationError):
        Settings(LOG_PARSE_BATCH_SIZE=201)
    with pytest.raises(ValidationError):
        Settings(LOG_PARSE_CONCURRENCY=4)
    with pytest.raises(ValidationError):
        Settings(LOG_PARSE_MAX_DAYS=8)
