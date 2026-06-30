"""
SDK 交互 API — 版本获取接口
GET /api/v1/version
"""
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db_no_commit
from app.models.version import SdkVersion

router = APIRouter(tags=["SDK - Version"])


@router.get("/api/v1/version")
async def get_version(
    platform: str = Query(..., pattern="^(ios|android)$", description="平台"),
    current_version: int = Query(0, description="当前 SDK 版本号(version_code)"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    """
    SDK 版本检查接口。

    SDK 启动时调用，传入当前平台和版本号，
    返回是否有新版本、更新策略（强制/建议/静默）和下载地址。
    """
    result = await db.execute(
        select(SdkVersion)
        .where(
            SdkVersion.platform == platform,
            SdkVersion.status == "active",
        )
        .order_by(desc(SdkVersion.version_code))
        .limit(1)
    )
    latest: SdkVersion | None = result.scalar_one_or_none()

    if not latest:
        return {
            "code": 0,
            "data": {
                "has_update": False,
                "current_version": current_version,
                "message": "暂无可用版本",
            },
        }

    has_update = latest.version_code > current_version
    min_required = latest.min_sdk_version

    if not has_update:
        return {
            "code": 0,
            "data": {
                "has_update": False,
                "current_version": current_version,
                "message": "已是最新版本",
            },
        }

    return {
        "code": 0,
        "data": {
            "has_update": True,
            "update_policy": latest.update_policy,
            "latest_version": {
                "platform": latest.platform,
                "version_code": latest.version_code,
                "version_name": latest.version_name,
                "download_url": latest.download_url,
                "release_notes": latest.release_notes,
                "file_size": latest.file_size,
                "file_hash": latest.file_hash,
            },
            "min_required_version": min_required,
        },
    }
