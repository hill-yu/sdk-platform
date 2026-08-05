"""
SDK 数据中台 + 配置管理系统 — 核心配置
"""
from functools import lru_cache
from urllib.parse import quote_plus
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从环境变量/.env 读取"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 允许 .env 中有未在 Settings 中定义的变量（如 CORS_ORIGINS 被 admin_main 使用）
    )

    APP_NAME: str = "SDK Platform"
    DEBUG: bool = False
    DB_PASSWORD: str = Field(default="your_password_here", repr=False)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sdk_platform"
    SDK_API_PORT: int = 8100
    ADMIN_API_PORT: int = 8101
    ADMIN_TOKEN: str = Field(default="", repr=False)

    # 腾讯云 COS
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = Field(default="", repr=False)
    COS_REGION: str = "ap-guangzhou"
    COS_BUCKET: str = "sdk-config-bucket"
    CDN_BASE_URL: str = "https://cdn.example.com"

    # SDK 配置元信息接口开关与 CDN 地址
    CONFIG_META_IS_OPEN: bool = True
    CONFIG_META_IS_NEWS_TOUCH: bool = True
    CONFIG_META_IS_NEW_TEXT_RULE: bool = True
    CONFIG_META_CDN_URL: str = "https://cdnversion.deeppopgame.xyz/config/latest.json"
    CONFIG_META_CDN_URL2: str = "https://cdnNewtouch.deeppopgame.xyz/config/latest.json"
    CONFIG_META_CDN_URL3: str = "https://cdnNewTextRule.deeppopgame.xyz/config/latest.json"
    CONFIG_DELIVERY_MODE: str = "cos"
    CONFIG_META_LOCAL_BASE_URL: str = "https://sdk.deeppopgame.xyz"

    LOG_LEVEL: str = "INFO"

    @property
    def resolved_database_url(self) -> str:
        encoded_password = quote_plus(self.DB_PASSWORD)
        if "${DB_PASSWORD}" in self.DATABASE_URL:
            return self.DATABASE_URL.replace("${DB_PASSWORD}", encoded_password)
        if "://admin:@" in self.DATABASE_URL and self.DB_PASSWORD:
            return self.DATABASE_URL.replace("://admin:@", f"://admin:{encoded_password}@")
        return self.DATABASE_URL


@lru_cache()
def get_settings() -> Settings:
    return Settings()
