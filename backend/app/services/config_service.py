from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
import logging

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.config import SdkConfig

logger = logging.getLogger(__name__)

try:
    from qcloud_cos import CosConfig, CosS3Client
except Exception:  # pragma: no cover - import depends on optional runtime deps
    CosConfig = None
    CosS3Client = None


def _cdn_url(cos_key: str) -> str:
    settings = get_settings()
    return f"{settings.CDN_BASE_URL.rstrip('/')}/{cos_key}"


async def list_configs(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(select(SdkConfig).order_by(desc(SdkConfig.created_at), desc(SdkConfig.id)))
    ).scalars().all()
    published = next((item for item in rows if item.status == "published"), None)
    drafts = [item for item in rows if item.status == "draft"]
    history = [item for item in rows if item.status == "archived"]
    return {
        "published": _serialize_config(published) if published else None,
        "drafts": [_serialize_config(item) for item in drafts],
        "history": [_serialize_config(item) for item in history],
    }


async def get_config_detail(db: AsyncSession, config_id: int) -> dict[str, Any] | None:
    config = await db.get(SdkConfig, config_id)
    return _serialize_config(config) if config else None


async def create_config(db: AsyncSession, config_data: dict[str, Any], change_log: str) -> dict[str, Any]:
    config = SdkConfig(
        version=f"draft_{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
        config_data=config_data,
        status="draft",
        change_log=change_log,
        cdn_url=_cdn_url("config/latest.json"),
    )
    db.add(config)
    await db.flush()
    return _serialize_config(config)


async def update_config(db: AsyncSession, config_id: int, config_data: dict[str, Any], change_log: str) -> dict[str, Any]:
    config = await db.get(SdkConfig, config_id)
    if config is None:
        raise ValueError("配置不存在")
    if config.status != "draft":
        raise ValueError("仅可编辑 draft 状态的配置")
    config.config_data = config_data
    config.change_log = change_log
    config.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _serialize_config(config)


async def publish_config(db: AsyncSession, config_id: int, published_by: str) -> dict[str, Any]:
    config = await db.get(SdkConfig, config_id)
    if config is None or config.status != "draft":
        raise ValueError("只能发布草稿状态的配置")

    publish_at = datetime.now(timezone.utc)
    version = publish_at.strftime("%Y%m%d_v%H%M%S")
    cos_key = f"config/v{version}.json"

    # ① 先更新数据库状态
    await db.execute(
        update(SdkConfig).where(SdkConfig.status == "published").values(status="archived")
    )
    config.status = "published"
    config.version = version
    config.publish_at = publish_at
    config.published_by = published_by
    config.cos_key = cos_key
    config.updated_at = publish_at
    await db.flush()

    # ② 再上传 COS
    publish_data = {
        "version": version,
        "updated_at": publish_at.isoformat(),
        "config": config.config_data,
    }
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()

    try:
        await asyncio.to_thread(_upload_config_payload, cos_key, json_bytes)
        await asyncio.to_thread(_upload_config_payload, "config/latest.json", json_bytes)
    except Exception:
        # COS 上传失败 → 回滚 DB 状态
        await db.rollback()
        raise RuntimeError("COS 上传失败，配置发布已回滚")

    cdn_url = _cdn_url(cos_key)
    config.cdn_url = cdn_url

    return {
        "version": version,
        "publish_at": publish_at.isoformat(),
        "cdn_url": cdn_url,
        "cos_key": cos_key,
    }


async def rollback_config(db: AsyncSession, config_id: int, published_by: str) -> dict[str, Any]:
    config = await db.get(SdkConfig, config_id)
    if config is None or config.status != "archived":
        raise ValueError("只能回滚 archived 状态的配置")
    return await _publish_from_record(db, config, published_by)


async def _publish_from_record(db: AsyncSession, config: SdkConfig, published_by: str) -> dict[str, Any]:
    """从已有记录发布（用于回滚和首次发布），DB先 + COS后 + 失败回滚"""
    is_rollback = config.status == "archived"
    publish_at = datetime.now(timezone.utc)
    version = publish_at.strftime("%Y%m%d_v%H%M%S")
    cos_key = f"config/v{version}.json"

    # ① 先更新 DB
    await db.execute(
        update(SdkConfig).where(SdkConfig.status == "published").values(status="archived", updated_at=publish_at)
    )
    config.status = "published"
    config.version = version
    config.publish_at = publish_at
    config.published_by = published_by
    config.cos_key = cos_key
    config.cdn_url = _cdn_url(cos_key)
    config.updated_at = publish_at
    await db.flush()

    # ② 再上传 COS
    publish_data = {"version": version, "updated_at": publish_at.isoformat(), "config": config.config_data}
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode("utf-8")

    try:
        await asyncio.to_thread(_upload_config_payload, cos_key, json_bytes)
        await asyncio.to_thread(_upload_config_payload, "config/latest.json", json_bytes)
    except Exception:
        await db.rollback()
        raise RuntimeError(f"COS 上传失败，配置回滚/发布已撤销: {version}")

    return {
        "version": version,
        "publish_at": publish_at.isoformat(),
        "cdn_url": config.cdn_url,
        "cos_key": cos_key,
        "message": f"已回滚到版本 {version}" if is_rollback else f"已发布版本 {version}",
    }


def _upload_config_payload(cos_key: str, json_bytes: bytes) -> str:
    """上传配置到 COS（同步函数，由调用方通过 to_thread 执行）"""
    settings = get_settings()

    if not settings.COS_SECRET_ID or not settings.COS_SECRET_KEY or not settings.COS_BUCKET:
        raise RuntimeError(
            "COS 凭证未配置，无法上传配置。请在 .env 中设置 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET"
        )
    if CosConfig is None or CosS3Client is None:
        raise RuntimeError("COS SDK 不可用，无法上传配置")

    client = CosS3Client(
        CosConfig(
            Region=settings.COS_REGION,
            SecretId=settings.COS_SECRET_ID,
            SecretKey=settings.COS_SECRET_KEY,
        )
    )
    cache_opts = {}
    if cos_key == "config/latest.json":
        cache_opts["CacheControl"] = "max-age=300"
    client.put_object(Bucket=settings.COS_BUCKET, Key=cos_key, Body=json_bytes, **cache_opts)
    return f"{settings.CDN_BASE_URL.rstrip('/')}/{cos_key}"


def _serialize_config(config: SdkConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "id": config.id,
        "version": config.version,
        "config_data": config.config_data,
        "status": config.status,
        "publish_at": config.publish_at.isoformat() if config.publish_at else None,
        "published_by": config.published_by,
        "cos_key": config.cos_key,
        "cdn_url": config.cdn_url,
        "change_log": config.change_log,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
