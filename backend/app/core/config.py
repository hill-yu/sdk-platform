"""
SDK 数据中台 + 配置管理系统 — 核心配置
"""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从环境变量/.env 读取"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "SDK Platform"
    DEBUG: bool = False
    DB_PASSWORD: str = Field(default="your_password_here", repr=False)
    DATABASE_URL: str = "postgresql+asyncpg://admin:your_password_here@localhost:5432/sdk_platform"
    SDK_API_PORT: int = 8100
    ADMIN_API_PORT: int = 8101
    ADMIN_TOKEN: str = Field(default="admin-secret-token-change-me", repr=False)

    # 腾讯云 COS
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_REGION: str = "ap-guangzhou"
    COS_BUCKET: str = "sdk-config-bucket"
    CDN_BASE_URL: str = "https://cdn.example.com"

    LOG_LEVEL: str = "INFO"

    @property
    def resolved_database_url(self) -> str:
        return self.DATABASE_URL.replace("${DB_PASSWORD}", self.DB_PASSWORD)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
