from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.config import SdkConfig
from app.services.config_crypto import decrypt_payload, encrypt_payload, normalize_package_name

logger = logging.getLogger(__name__)
ROOT_KEYS = {
    "main": "mainConfig",
    "new_touch": "newTouchConfig",
    "new_text_rule": "newTextRuleConfig",
}

try:
    from qcloud_cos import CosConfig, CosS3Client
except Exception:  # pragma: no cover
    CosConfig = None
    CosS3Client = None


def _token() -> str:
    return get_settings().SDK_CONFIG_TOKEN


def _is_local_delivery_mode() -> bool:
    return get_settings().CONFIG_DELIVERY_MODE.lower() == "local"


def _object_key(package_name: str, version: str, config_type: str) -> str:
    filename = {"main": "main.json", "new_touch": "new-touch.json", "new_text_rule": "new-text-rule.json"}[config_type]
    return f"config/{package_name}/{version}/{filename}"


def _delivery_url(package_name: str, version: str, config_type: str) -> str:
    settings = get_settings()
    if _is_local_delivery_mode():
        suffix = {"main": "main", "new_touch": "new-touch", "new_text_rule": "new-text-rule"}[config_type]
        return (
            f"{settings.CONFIG_META_LOCAL_BASE_URL.rstrip('/')}/api/v1/config/packages/"
            f"{package_name}/versions/{version}/{suffix}"
        )
    return f"{settings.CDN_BASE_URL.rstrip('/')}/{_object_key(package_name, version, config_type)}"


def _validate_full_config(config_data: dict[str, Any]) -> None:
    missing = [key for key in ROOT_KEYS.values() if key not in config_data]
    if missing:
        raise ValueError(f"配置缺少必填根字段: {', '.join(missing)}")


async def list_configs(db: AsyncSession, package_name: str | None = None) -> dict[str, Any]:
    stmt = select(SdkConfig)
    if package_name:
        stmt = stmt.where(SdkConfig.package_name == normalize_package_name(package_name))
    rows = (await db.execute(stmt.order_by(desc(SdkConfig.created_at), desc(SdkConfig.id)))).scalars().all()
    published = [item for item in rows if item.status == "published"]
    return {
        "published": [_serialize_summary(item) for item in published],
        "drafts": [_serialize_summary(item) for item in rows if item.status == "draft"],
        "history": [_serialize_summary(item) for item in rows if item.status == "archived"],
    }


async def get_config_detail(db: AsyncSession, config_id: int) -> dict[str, Any] | None:
    config = await db.get(SdkConfig, config_id)
    if config is None:
        return None
    result = _serialize_summary(config)
    result["config_data"] = decrypt_payload(config.encrypted_config, _token())
    return result


async def create_config(db: AsyncSession, package_name: str, config_data: dict[str, Any], change_log: str) -> dict[str, Any]:
    package_name = normalize_package_name(package_name)
    _validate_full_config(config_data)
    version = f"draft_{datetime.now(timezone.utc):%Y%m%d%H%M%S_%f}"
    config = SdkConfig(
        package_name=package_name,
        version=version,
        encrypted_config=encrypt_payload(config_data, package_name, version, "full", _token()),
        encryption_key_id="v1",
        status="draft",
        change_log=change_log,
        cdn_url=None,
    )
    db.add(config)
    await db.flush()
    return _serialize_summary(config)


async def update_config(db: AsyncSession, config_id: int, config_data: dict[str, Any], change_log: str) -> dict[str, Any]:
    config = await db.get(SdkConfig, config_id)
    if config is None:
        raise ValueError("配置不存在")
    if config.status != "draft":
        raise ValueError("仅可编辑 draft 状态的配置")
    _validate_full_config(config_data)
    config.encrypted_config = encrypt_payload(config_data, config.package_name, config.version, "full", _token())
    config.change_log = change_log
    config.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _serialize_summary(config)


async def publish_config(db: AsyncSession, config_id: int, published_by: str) -> dict[str, Any]:
    config = await db.get(SdkConfig, config_id)
    if config is None or config.status != "draft":
        raise ValueError("只能发布草稿状态的配置")
    return await _publish_from_record(db, config, published_by)


async def rollback_config(db: AsyncSession, config_id: int, published_by: str) -> dict[str, Any]:
    source = await db.get(SdkConfig, config_id)
    if source is None or source.status != "archived":
        raise ValueError("只能回滚 archived 状态的配置")
    plain = decrypt_payload(source.encrypted_config, _token())
    _validate_full_config(plain)
    draft_version = f"draft_{datetime.now(timezone.utc):%Y%m%d%H%M%S_%f}"
    config = SdkConfig(
        package_name=source.package_name,
        version=draft_version,
        encrypted_config=encrypt_payload(plain, source.package_name, draft_version, "full", _token()),
        encryption_key_id="v1",
        status="draft",
        change_log=f"回滚自历史版本 {source.version}",
        cos_upload_status="pending",
    )
    db.add(config)
    await db.flush()
    return await _publish_from_record(db, config, published_by)


async def _publish_from_record(db: AsyncSession, config: SdkConfig, published_by: str) -> dict[str, Any]:
    lock_key = int.from_bytes(hashlib.sha256(config.package_name.encode()).digest()[:8], "big", signed=True)
    result = await db.execute(text("SELECT pg_try_advisory_xact_lock(:lock_key)").bindparams(lock_key=lock_key))
    if not result.scalar():
        raise HTTPException(status_code=409, detail="同一包名的另一发布操作正在进行，请稍后重试")

    plain = decrypt_payload(config.encrypted_config, _token())
    _validate_full_config(plain)
    version = datetime.now(timezone.utc).strftime("%Y%m%d_v%H%M%S_%f")
    envelopes = {
        config_type: encrypt_payload(plain[root_key], config.package_name, version, config_type, _token())
        for config_type, root_key in ROOT_KEYS.items()
    }
    if not _is_local_delivery_mode():
        for config_type, envelope in envelopes.items():
            body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            await _upload_with_retry(_object_key(config.package_name, version, config_type), body)

    await db.execute(
        update(SdkConfig).where(
            SdkConfig.package_name == config.package_name,
            SdkConfig.status == "published",
            SdkConfig.id != config.id,
        ).values(status="archived")
    )
    config.version = version
    config.encrypted_config = encrypt_payload(plain, config.package_name, version, "full", _token())
    config.status = "published"
    config.publish_at = datetime.now(timezone.utc)
    config.published_by = published_by
    config.cos_key = "local" if _is_local_delivery_mode() else _object_key(config.package_name, version, "main")
    config.cos_upload_status = "success"
    config.cdn_url = _delivery_url(config.package_name, version, "main")
    await db.flush()
    return {
        "package_name": config.package_name,
        "version": version,
        "publish_at": config.publish_at.isoformat(),
        "cdn_url": config.cdn_url,
        "cdn_url2": _delivery_url(config.package_name, version, "new_touch"),
        "cdn_url3": _delivery_url(config.package_name, version, "new_text_rule"),
        "cos_key": config.cos_key,
    }


async def get_published_config(db: AsyncSession, package_name: str, version: str | None = None) -> SdkConfig | None:
    stmt = select(SdkConfig).where(
        SdkConfig.package_name == normalize_package_name(package_name),
        SdkConfig.status == "published",
        SdkConfig.cos_upload_status == "success",
    )
    if version:
        stmt = stmt.where(SdkConfig.version == version)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


def get_delivery_envelope(config: SdkConfig, config_type: str) -> dict[str, str]:
    plain = decrypt_payload(config.encrypted_config, _token())
    root_key = ROOT_KEYS[config_type]
    return encrypt_payload(plain[root_key], config.package_name, config.version, config_type, _token())


async def _upload_with_retry(cos_key: str, json_bytes: bytes, max_retries: int = 2) -> None:
    for attempt in range(max_retries + 1):
        try:
            await asyncio.to_thread(_upload_config_payload, cos_key, json_bytes)
            return
        except Exception:
            if attempt == max_retries:
                raise
            await asyncio.sleep(1)


def _upload_config_payload(cos_key: str, json_bytes: bytes) -> str:
    settings = get_settings()
    if not settings.COS_SECRET_ID or not settings.COS_SECRET_KEY or not settings.COS_BUCKET:
        raise RuntimeError("COS 凭证未配置，无法上传配置")
    if CosConfig is None or CosS3Client is None:
        raise RuntimeError("COS SDK 不可用，无法上传配置")
    client = CosS3Client(CosConfig(Region=settings.COS_REGION, SecretId=settings.COS_SECRET_ID, SecretKey=settings.COS_SECRET_KEY))
    client.put_object(Bucket=settings.COS_BUCKET, Key=cos_key, Body=json_bytes)
    return f"{settings.CDN_BASE_URL.rstrip('/')}/{cos_key}"


def _serialize_summary(config: SdkConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "package_name": config.package_name,
        "version": config.version,
        "status": config.status,
        "publish_at": config.publish_at.isoformat() if config.publish_at else None,
        "published_by": config.published_by,
        "cos_key": config.cos_key,
        "cdn_url": config.cdn_url,
        "cos_upload_status": config.cos_upload_status,
        "change_log": config.change_log,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
