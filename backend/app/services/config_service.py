from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
import logging

from fastapi import HTTPException
from sqlalchemy import desc, select, text, update
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
        version=f"draft_{datetime.now(timezone.utc):%Y%m%d%H%M%S_%f}",
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

    # 获取发布排他锁
    result = await db.execute(text("SELECT pg_try_advisory_xact_lock(9999)"))
    if not result.scalar():
        raise HTTPException(status_code=409, detail="另一发布操作正在进行，请稍后重试")

    version = datetime.now().strftime("%Y%m%d_v%H%M%S_%f")
    publish_data = {"version": version, "updated_at": datetime.now().isoformat(), "config": config.config_data}
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()

    # ① 先上传 COS（版本文件 + latest.json），带重试
    await _upload_with_retry(f"config/v{version}.json", json_bytes)
    await _upload_with_retry("config/latest.json", json_bytes)

    # ② COS 成功 → 归档旧 + 当前变 published
    await db.execute(
        update(SdkConfig).where(SdkConfig.status == "published").values(status="archived")
    )
    config.status = "published"
    config.version = version
    config.publish_at = datetime.now()
    config.published_by = published_by
    config.cos_key = f"config/v{version}.json"
    config.cos_upload_status = "success"
    config.cdn_url = _cdn_url(config.cos_key)

    # COS 上传成功后立即 commit
    try:
        await db.commit()
        logger.info("配置发布完成: version=%s", version)
    except Exception:
        logger.exception("数据库提交失败，COS已更新但DB状态不一致: version=%s", version)
        config.cos_upload_status = "failed"
        raise HTTPException(status_code=500, detail="配置发布部分完成，请联系管理员检查CDN与数据库一致性")

    return {
        "version": version,
        "publish_at": config.publish_at.isoformat(),
        "cdn_url": config.cdn_url,
        "cos_key": config.cos_key,
    }


async def rollback_config(db: AsyncSession, config_id: int, published_by: str) -> dict[str, Any]:
    config = await db.get(SdkConfig, config_id)
    if config is None or config.status != "archived":
        raise ValueError("只能回滚 archived 状态的配置")

    result = await db.execute(text("SELECT pg_try_advisory_xact_lock(9999)"))
    if not result.scalar():
        raise HTTPException(status_code=409, detail="另一配置操作正在进行，请稍后重试")

    return await _publish_from_record(db, config, published_by)


async def _publish_from_record(db: AsyncSession, config: SdkConfig, published_by: str) -> dict[str, Any]:
    """从已有记录发布（用于回滚和首次发布），先COS后DB"""
    result = await db.execute(text("SELECT pg_try_advisory_xact_lock(9999)"))
    if not result.scalar():
        raise HTTPException(status_code=409, detail="另一配置操作正在进行，请稍后重试")

    is_rollback = config.status == "archived"
    version = datetime.now().strftime("%Y%m%d_v%H%M%S_%f")
    cos_key = f"config/v{version}.json"

    # ① 先上传 COS，带重试
    publish_data = {"version": version, "updated_at": datetime.now().isoformat(), "config": config.config_data}
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()
    await _upload_with_retry(cos_key, json_bytes)
    await _upload_with_retry("config/latest.json", json_bytes)

    # ② COS 成功 → 归档旧 + 当前变 published
    await db.execute(
        update(SdkConfig).where(SdkConfig.status == "published").values(status="archived")
    )
    config.status = "published"
    config.version = version
    config.publish_at = datetime.now()
    config.published_by = published_by
    config.cos_key = cos_key
    config.cos_upload_status = "success"
    config.cdn_url = _cdn_url(cos_key)

    # COS 上传成功后立即 commit
    try:
        await db.commit()
        logger.info("配置发布完成: version=%s", version)
    except Exception:
        logger.exception("数据库提交失败，COS已更新但DB状态不一致: version=%s", version)
        config.cos_upload_status = "failed"
        raise HTTPException(status_code=500, detail="配置发布部分完成，请联系管理员检查CDN与数据库一致性")

    return {
        "version": version,
        "publish_at": config.publish_at.isoformat(),
        "cdn_url": config.cdn_url,
        "cos_key": cos_key,
        "message": f"已回滚到版本 {version}" if is_rollback else f"已发布版本 {version}",
    }


async def _upload_with_retry(cos_key: str, json_bytes: bytes, max_retries: int = 2):
    """上传配置到 COS，失败自动重试"""
    for attempt in range(max_retries + 1):
        try:
            await asyncio.to_thread(_upload_config_payload, cos_key, json_bytes)
            return
        except Exception:
            if attempt == max_retries:
                raise
            await asyncio.sleep(1)


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
        "cos_upload_status": config.cos_upload_status,
        "change_log": config.change_log,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
