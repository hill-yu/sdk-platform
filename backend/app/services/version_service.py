from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.version import SdkVersion


async def list_versions(db: AsyncSession, platform: str | None = None) -> list[dict[str, Any]]:
    stmt = select(SdkVersion)
    if platform:
        stmt = stmt.where(SdkVersion.platform == platform)
    stmt = stmt.order_by(SdkVersion.platform.asc(), desc(SdkVersion.version_code))
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_version(item) for item in rows]


async def create_version(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    version = SdkVersion(**payload)
    db.add(version)
    await db.flush()
    return _serialize_version(version)


async def update_version(db: AsyncSession, version_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    version = await db.get(SdkVersion, version_id)
    if version is None:
        raise ValueError("版本不存在")
    for key, value in payload.items():
        setattr(version, key, value)
    await db.flush()
    return _serialize_version(version)


def _serialize_version(version: SdkVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "platform": version.platform,
        "version_code": version.version_code,
        "version_name": version.version_name,
        "update_policy": version.update_policy,
        "download_url": version.download_url,
        "release_notes": version.release_notes,
        "min_sdk_version": version.min_sdk_version,
        "file_size": version.file_size,
        "file_hash": version.file_hash,
        "status": version.status,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
    }
