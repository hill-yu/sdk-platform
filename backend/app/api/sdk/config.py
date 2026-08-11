import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_no_commit
from app.schemas.config_schemas import ConfigMetaRequest
from app.services import config_service

router = APIRouter(tags=["SDK - Config"])


async def require_sdk_config_token(authorization: str | None = Header(None)) -> None:
    expected = get_settings().SDK_CONFIG_TOKEN
    if not expected:
        raise HTTPException(500, "SDK_CONFIG_TOKEN 未配置")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "Invalid SDK config token", headers={"WWW-Authenticate": "Bearer"})


@router.post("/api/v1/config/meta", dependencies=[Depends(require_sdk_config_token)])
async def get_config_meta(body: ConfigMetaRequest, db: AsyncSession = Depends(get_db_no_commit)):
    published = await config_service.get_published_config(db, body.package_name)
    if not published:
        return JSONResponse(status_code=404, content={"code": 1, "message": "该包名暂无已发布配置", "data": None})
    settings = get_settings()
    return {
        "code": 0,
        "data": {
            "package_name": published.package_name,
            "version": published.version,
            "updated_at": published.publish_at.isoformat() if published.publish_at else None,
            "isOpen": settings.CONFIG_META_IS_OPEN,
            "isNewsTouch": settings.CONFIG_META_IS_NEWS_TOUCH,
            "isNewTextRule": settings.CONFIG_META_IS_NEW_TEXT_RULE,
            "cdn_url": config_service._delivery_url(published.package_name, published.version, "main"),
            "cdn_url2": config_service._delivery_url(published.package_name, published.version, "new_touch"),
            "cdn_url3": config_service._delivery_url(published.package_name, published.version, "new_text_rule"),
        },
    }


@router.get(
    "/api/v1/config/packages/{package_name}/versions/{version}/{config_type}",
    dependencies=[Depends(require_sdk_config_token)],
)
async def get_config_payload(
    package_name: str = Path(..., min_length=1, max_length=255),
    version: str = Path(..., min_length=1, max_length=64),
    config_type: str = Path(..., pattern="^(main|new-touch|new-text-rule)$"),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized_type = config_type.replace("-", "_")
    published = await config_service.get_published_config(db, package_name, version)
    if not published:
        return JSONResponse(status_code=404, content={"code": 1, "message": "配置不存在", "data": None})
    return config_service.get_delivery_envelope(published, normalized_type)
