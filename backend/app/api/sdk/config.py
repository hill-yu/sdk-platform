"""
SDK 交互 API — 配置元信息获取接口
GET /api/v1/config/meta

注意：此接口仅返回配置元信息（version + updated_at + cdn_url），
完整配置内容由 SDK 直接从 CDN 拉取。
"""
from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db_no_commit
from app.models.config import SdkConfig

router = APIRouter(tags=["SDK - Config"])


@router.get("/api/v1/config/meta")
async def get_config_meta(
    request: Request,
    app_id: str = Query(..., description="应用 ID"),
    config_version: str = Query("", description="SDK 当前缓存配置版本号"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    """
    配置元信息获取接口。

    SDK 获取当前已发布配置的版本信息，用于判断是否需要重新从 CDN 拉取配置。
    此接口不返回完整 config JSON。
    """
    result = await db.execute(
        select(SdkConfig).where(SdkConfig.status == "published").limit(1)
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

    # 检查 If-None-Match 头
    if_none_match = request.headers.get("If-None-Match", "")
    if if_none_match == etag_value or config_version == published.version:
        headers = {"ETag": etag_value, "Cache-Control": "max-age=300"}
        return Response(status_code=304, headers=headers)

    if not published.cdn_url:
        return JSONResponse(status_code=500, content={
            "code": 2, "message": "配置已发布但 CDN 地址缺失，请联系管理员", "data": None
        })
    cdn_url = published.cdn_url

    return JSONResponse(
        status_code=200,
        content={
            "code": 0,
            "data": {
                "version": published.version,
                "updated_at": published.publish_at.isoformat() if published.publish_at else None,
                "cdn_url": cdn_url,
            },
        },
        headers={
            "ETag": etag_value,
            "Cache-Control": "max-age=300",
        },
    )
