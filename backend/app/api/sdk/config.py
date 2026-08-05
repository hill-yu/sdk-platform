"""
SDK 交互 API：配置元信息获取接口 GET /api/v1/config/meta

注意：此接口仅返回配置元信息与 CDN 地址，不返回完整配置 JSON。
完整配置内容由 SDK 根据开关直接从对应 CDN 拉取。
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_no_commit
from app.models.config import SdkConfig

router = APIRouter(tags=["SDK - Config"])


@router.get("/api/v1/config/meta")
async def get_config_meta(
    request: Request,
    app_id: str | None = Query(None, description="应用 ID（可选，仅用于兼容旧 SDK）"),
    config_version: str = Query("", description="SDK 当前缓存配置版本号"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    """
    配置元信息获取接口。

    SDK 获取当前已发布配置的版本信息，并按返回的开关决定是否从对应 CDN 拉取 JSON。
    此接口不返回完整 config JSON。
    """
    result = await db.execute(
        select(SdkConfig).where(
            SdkConfig.status == "published",
            SdkConfig.cos_upload_status == "success",
        ).limit(1)
    )
    published: SdkConfig | None = result.scalar_one_or_none()

    if not published:
        return JSONResponse(
            status_code=200,
            content={
                "code": 1,
                "message": "暂无已发布的配置",
                "data": None,
            },
        )

    etag_value = f'"{published.version}"'

    if_none_match = request.headers.get("If-None-Match", "")
    if if_none_match == etag_value or config_version == published.version:
        headers = {"ETag": etag_value, "Cache-Control": "max-age=300"}
        return Response(status_code=304, headers=headers)

    settings = get_settings()
    if not settings.CONFIG_META_CDN_URL:
        return JSONResponse(
            status_code=500,
            content={
                "code": 2,
                "message": "配置已发布但主 CDN 地址缺失，请检查环境变量 CONFIG_META_CDN_URL",
                "data": None,
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "code": 0,
            "data": {
                "version": published.version,
                "updated_at": published.publish_at.isoformat() if published.publish_at else None,
                "isOpen": settings.CONFIG_META_IS_OPEN,
                "isNewsTouch": settings.CONFIG_META_IS_NEWS_TOUCH,
                "isNewTextRule": settings.CONFIG_META_IS_NEW_TEXT_RULE,
                "cdn_url": settings.CONFIG_META_CDN_URL,
                "cdn_url2": settings.CONFIG_META_CDN_URL2,
                "cdn_url3": settings.CONFIG_META_CDN_URL3,
            },
        },
        headers={
            "ETag": etag_value,
            "Cache-Control": "max-age=300",
        },
    )
