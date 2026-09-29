"""SDK 使用时长上报接口。"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import write_limiter
from app.models.usage_duration import SdkUsageDuration
from app.schemas.sdk_schemas import UsageDurationReportRequest


logger = logging.getLogger(__name__)
router = APIRouter(tags=["SDK - Usage Duration"])


@router.post("/api/v1/usage-duration")
async def report_usage_duration(
    request: Request,
    body: UsageDurationReportRequest,
    db: AsyncSession = Depends(get_db),
    _rate=Depends(write_limiter),
):
    record = SdkUsageDuration(
        package_name=body.package_name,
        device_id=body.device_id,
        device_model=body.device_model,
        os=body.os,
        app_version=body.ver,
        sdk_version=body.sdk_version,
        duration_s=body.duration_s,
        server_ts=datetime.now(timezone.utc),
        ip=str(request.client.host) if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    try:
        db.add(record)
        await db.flush()
    except Exception:
        logger.exception("使用时长写入失败，package_name=%s", body.package_name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="数据库写入失败")
    return {
        "code": 0,
        "message": "ok",
        "data": {"accepted": 1, "rejected": 0},
    }
