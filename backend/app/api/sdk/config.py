"""
SDK 交互 API：配置元信息与配置 JSON 获取接口。
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_no_commit
from app.models.config import SdkConfig

router = APIRouter(tags=["SDK - Config"])


async def _get_published_config(db: AsyncSession) -> SdkConfig | None:
    result = await db.execute(
        select(SdkConfig).where(
            SdkConfig.status == "published",
            SdkConfig.cos_upload_status == "success",
        ).limit(1)
    )
    return result.scalar_one_or_none()


def _local_config_url(query: str = "") -> str:
    settings = get_settings()
    return f"{settings.CONFIG_META_LOCAL_BASE_URL.rstrip('/')}/api/v1/config/latest{query}"


def _select_config_payload(config_data: dict, config_type: str | None) -> dict:
    if not isinstance(config_data, dict):
        return config_data

    type_to_key = {
        None: "mainConfig",
        "": "mainConfig",
        "main": "mainConfig",
        "new_touch": "newTouchConfig",
        "new_text_rule": "newTextRuleConfig",
    }
    selected_key = type_to_key.get(config_type)
    if selected_key and selected_key in config_data:
        return config_data[selected_key]
    return config_data


@router.get("/api/v1/config/meta")
async def get_config_meta(
    request: Request,
    app_id: str | None = Query(None, description="应用 ID（可选，仅用于兼容旧 SDK）"),
    config_version: str = Query("", description="SDK 当前缓存配置版本号"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    """
    配置元信息获取接口。

    SDK 获取当前已发布配置版本，并按返回开关决定是否从对应 URL 拉取 JSON。
    """
    published = await _get_published_config(db)

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
    local_delivery = settings.CONFIG_DELIVERY_MODE.lower() == "local"
    cdn_url = _local_config_url() if local_delivery else settings.CONFIG_META_CDN_URL
    cdn_url2 = _local_config_url("?type=new_touch") if local_delivery else settings.CONFIG_META_CDN_URL2
    cdn_url3 = _local_config_url("?type=new_text_rule") if local_delivery else settings.CONFIG_META_CDN_URL3

    if not cdn_url:
        return JSONResponse(
            status_code=500,
            content={
                "code": 2,
                "message": "配置已发布但主配置地址缺失，请检查环境变量",
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
                "cdn_url": cdn_url,
                "cdn_url2": cdn_url2,
                "cdn_url3": cdn_url3,
            },
        },
        headers={
            "ETag": etag_value,
            "Cache-Control": "max-age=300",
        },
    )


@router.get("/api/v1/config/latest")
async def get_config_latest(
    type: str | None = Query(None, description="配置类型，local 测试模式下暂返回同一份已发布配置"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    """
    local 下发模式使用的完整配置 JSON 接口。

    字段名保持与 CDN latest.json 一致，便于 SDK 端按 URL 拉取。
    """
    published = await _get_published_config(db)

    if not published:
        return JSONResponse(
            status_code=404,
            content={
                "code": 1,
                "message": "暂无已发布的配置",
                "data": None,
            },
        )

    return {
        "version": published.version,
        "updated_at": published.publish_at.isoformat() if published.publish_at else None,
        "config": _select_config_payload(published.config_data, type),
    }
