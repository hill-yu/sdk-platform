from app.core.config import Settings


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
