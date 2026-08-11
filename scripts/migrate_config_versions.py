"""将已发布配置按包名迁移到 1.0.0 起步的版本序列。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.config_crypto import decrypt_payload, encrypt_payload  # noqa: E402
from app.services.config_version import next_version, parse_version  # noqa: E402


REQUIRED_ROOT_KEYS = {"mainConfig", "newTouchConfig", "newTextRuleConfig"}


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, Any, int]:
    created_at = row["created_at"]
    return row["publish_at"] or created_at, created_at, int(row["id"])


def build_version_mapping(rows: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """按包和发布时间生成稳定的历史版本映射。"""
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["package_name"])].append(row)

    mapping: dict[int, str] = {}
    for package_rows in grouped.values():
        expected: list[str] = []
        version: str | None = None
        for _ in package_rows:
            version = next_version(version)
            expected.append(version)
        try:
            existing = sorted((str(row["version"]) for row in package_rows), key=parse_version)
        except ValueError:
            existing = []
        if existing == expected:
            mapping.update({int(row["id"]): str(row["version"]) for row in package_rows})
            continue

        version = None
        for row in sorted(package_rows, key=_sort_key):
            version = next_version(version)
            mapping[int(row["id"])] = version
    return mapping


def local_delivery_url(base_url: str, package_name: str, version: str) -> str:
    return (
        f"{base_url.rstrip('/')}/api/v1/config/packages/"
        f"{package_name}/versions/{version}/main"
    )


def prepare_migration(rows: Sequence[Mapping[str, Any]], token: str) -> list[dict[str, Any]]:
    """在产生任何数据库写入前解密并准备全部目标信封。"""
    mapping = build_version_mapping(rows)
    prepared: list[dict[str, Any]] = []
    for row in rows:
        plain = decrypt_payload(row["encrypted_config"], token)
        if not isinstance(plain, dict):
            raise ValueError(f"记录 {row['id']} 的配置根节点不是 JSON 对象")
        missing = sorted(REQUIRED_ROOT_KEYS - set(plain))
        if missing:
            raise ValueError(f"记录 {row['id']} 缺少必填根字段: {', '.join(missing)}")

        target_version = mapping[int(row["id"])]
        envelope = row["encrypted_config"]
        changed = str(row["version"]) != target_version or str(envelope.get("version")) != target_version
        if changed:
            envelope = encrypt_payload(plain, str(row["package_name"]), target_version, "full", token)
            if decrypt_payload(envelope, token) != plain:
                raise RuntimeError(f"记录 {row['id']} 使用新版本重加密后回读失败")
        prepared.append(
            {
                "id": int(row["id"]),
                "package_name": str(row["package_name"]),
                "old_version": str(row["version"]),
                "version": target_version,
                "envelope": envelope,
                "changed": changed,
            }
        )
    return prepared


async def migrate(
    database_url: str,
    token: str,
    *,
    apply: bool,
    local_base_url: str = "",
) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT id, package_name, version, status, publish_at, created_at, encrypted_config "
                        "FROM sdk_configs WHERE status IN ('published', 'archived') "
                        "ORDER BY package_name, COALESCE(publish_at, created_at), created_at, id FOR UPDATE"
                    )
                )
            ).mappings().all()
            prepared = prepare_migration(rows, token)
            if not apply:
                return prepared
            await apply_prepared(connection, prepared, local_base_url)
            return prepared
    finally:
        await engine.dispose()


async def apply_prepared(connection, prepared: Sequence[Mapping[str, Any]], local_base_url: str) -> None:
    """在调用方事务内安装准备好的版本和信封。"""
    await connection.execute(
        text("ALTER TABLE sdk_configs DROP CONSTRAINT IF EXISTS chk_configs_formal_version")
    )
    changed = [item for item in prepared if item["changed"]]
    for item in changed:
        await connection.execute(
            text("UPDATE sdk_configs SET version=:temporary WHERE id=:id"),
            {"temporary": f"__version_migration_{item['id']}", "id": item["id"]},
        )
    for item in changed:
        await connection.execute(
            text(
                "UPDATE sdk_configs SET version=:version, encrypted_config=CAST(:envelope AS jsonb), "
                "cdn_url=:cdn_url, cos_key='local', updated_at=NOW() WHERE id=:id"
            ),
            {
                "version": item["version"],
                "envelope": json.dumps(item["envelope"], ensure_ascii=False),
                "cdn_url": local_delivery_url(
                    local_base_url, item["package_name"], item["version"]
                ),
                "id": item["id"],
            },
        )
    await connection.execute(
        text(
            "ALTER TABLE sdk_configs ADD CONSTRAINT chk_configs_formal_version "
            "CHECK (status = 'draft' OR version ~ '^[0-9]+\\.[0-9]\\.[0-9]$')"
        )
    )
    invalid = (
        await connection.execute(
            text(
                "SELECT COUNT(*) FROM sdk_configs WHERE status IN ('published', 'archived') "
                "AND version !~ '^[0-9]+\\.[0-9]\\.[0-9]$'"
            )
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(f"迁移后仍有 {invalid} 条非法正式版本")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行数据库写入；默认只预检")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    token = os.environ.get("SDK_CONFIG_TOKEN", "")
    delivery_mode = os.environ.get("CONFIG_DELIVERY_MODE", "local").lower()
    local_base_url = os.environ.get("CONFIG_META_LOCAL_BASE_URL", "")
    if not database_url or not token:
        raise SystemExit("必须设置 DATABASE_URL 和 SDK_CONFIG_TOKEN")
    if delivery_mode != "local":
        raise SystemExit("版本迁移当前只支持 local 下发模式；COS 模式需要先迁移版本化对象")
    if not local_base_url:
        raise SystemExit("local 下发模式必须设置 CONFIG_META_LOCAL_BASE_URL")
    if args.apply and args.confirm != "MIGRATE_CONFIG_VERSIONS":
        raise SystemExit("正式迁移必须同时传入 --confirm MIGRATE_CONFIG_VERSIONS")

    prepared = asyncio.run(
        migrate(database_url, token, apply=args.apply, local_base_url=local_base_url)
    )
    changes = [item for item in prepared if item["changed"]]
    packages = sorted({item["package_name"] for item in prepared})
    mode = "已迁移" if args.apply else "预检通过"
    print(f"{mode}: packages={len(packages)}, records={len(prepared)}, changes={len(changes)}")
    for package_name in packages:
        versions = [item["version"] for item in prepared if item["package_name"] == package_name]
        print(f"{package_name}: records={len(versions)}, range={versions[0]}..{versions[-1]}")


if __name__ == "__main__":
    main()
