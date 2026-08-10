"""将旧 sdk_configs.config_data 安全迁移为按包名的 AES-GCM 密文。"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.config_crypto import decrypt_payload, encrypt_payload, normalize_package_name  # noqa: E402


REQUIRED_ROOT_KEYS = {"mainConfig", "newTouchConfig", "newTextRuleConfig"}


def prepare_legacy_config(config_data: object, legacy_single_as_main: bool = False) -> dict:
    if not isinstance(config_data, dict):
        raise ValueError("旧配置根节点必须是 JSON 对象")
    missing = sorted(REQUIRED_ROOT_KEYS - set(config_data))
    if missing:
        if legacy_single_as_main and not (REQUIRED_ROOT_KEYS & set(config_data)):
            return {
                "mainConfig": config_data,
                "newTouchConfig": {},
                "newTextRuleConfig": {},
            }
        raise ValueError(f"旧配置缺少必填根字段: {', '.join(missing)}")
    return config_data


async def migrate(
    database_url: str,
    token: str,
    default_package_name: str,
    legacy_single_as_main: bool = False,
) -> None:
    package_name = normalize_package_name(default_package_name)
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE sdk_configs ADD COLUMN IF NOT EXISTS package_name VARCHAR(255)"))
            await connection.execute(text("ALTER TABLE sdk_configs ADD COLUMN IF NOT EXISTS encrypted_config JSONB"))
            await connection.execute(text("ALTER TABLE sdk_configs ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(32) DEFAULT 'v1'"))
            rows = (await connection.execute(text("SELECT id, version, config_data FROM sdk_configs FOR UPDATE"))).mappings().all()
            for row in rows:
                config_data = prepare_legacy_config(row["config_data"], legacy_single_as_main)
                envelope = encrypt_payload(config_data, package_name, row["version"], "full", token)
                if decrypt_payload(envelope, token) != config_data:
                    raise RuntimeError(f"记录 {row['id']} 加密回读校验失败")
                await connection.execute(text("UPDATE sdk_configs SET package_name=:package_name, encrypted_config=CAST(:envelope AS jsonb), encryption_key_id='v1' WHERE id=:id"), {"package_name": package_name, "envelope": __import__("json").dumps(envelope), "id": row["id"]})
            await connection.execute(text("ALTER TABLE sdk_configs ALTER COLUMN package_name SET NOT NULL"))
            await connection.execute(text("ALTER TABLE sdk_configs ALTER COLUMN encrypted_config SET NOT NULL"))
            await connection.execute(text("ALTER TABLE sdk_configs ALTER COLUMN encryption_key_id SET NOT NULL"))
            await connection.execute(text("ALTER TABLE sdk_configs DROP CONSTRAINT IF EXISTS uq_configs_version"))
            await connection.execute(text("ALTER TABLE sdk_configs DROP CONSTRAINT IF EXISTS uq_configs_package_version"))
            await connection.execute(text("DROP INDEX IF EXISTS uq_configs_one_published"))
            await connection.execute(text("DROP INDEX IF EXISTS uq_sdk_configs_published_package"))
            await connection.execute(text("ALTER TABLE sdk_configs ADD CONSTRAINT uq_configs_package_version UNIQUE (package_name, version)"))
            await connection.execute(text("CREATE UNIQUE INDEX uq_sdk_configs_published_package ON sdk_configs(package_name) WHERE status='published'"))
    finally:
        await engine.dispose()


async def cleanup_plaintext(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            invalid = (await connection.execute(text(
                "SELECT COUNT(*) FROM sdk_configs WHERE package_name IS NULL OR encrypted_config IS NULL"
            ))).scalar_one()
            if invalid:
                raise RuntimeError("仍有记录未完成密文迁移，拒绝清理明文字段")
            await connection.execute(text("ALTER TABLE sdk_configs DROP COLUMN IF EXISTS config_data"))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--default-package-name")
    parser.add_argument("--cleanup-plaintext", action="store_true")
    parser.add_argument("--confirm-cleanup")
    parser.add_argument(
        "--legacy-single-as-main",
        action="store_true",
        help="显式将不含三分根字段的旧配置整体映射为 mainConfig",
    )
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    token = os.environ.get("SDK_CONFIG_TOKEN", "")
    if not database_url:
        raise SystemExit("必须设置 DATABASE_URL")
    if args.cleanup_plaintext:
        if args.confirm_cleanup != "DROP_CONFIG_DATA":
            raise SystemExit("清理明文列必须同时传入 --confirm-cleanup DROP_CONFIG_DATA")
        asyncio.run(cleanup_plaintext(database_url))
    else:
        if not token:
            raise SystemExit("首次迁移必须设置 SDK_CONFIG_TOKEN")
        if not args.default_package_name:
            raise SystemExit("首次迁移必须指定 --default-package-name")
        asyncio.run(migrate(database_url, token, args.default_package_name, args.legacy_single_as_main))


if __name__ == "__main__":
    main()
