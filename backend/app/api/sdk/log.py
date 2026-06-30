"""
SDK 交互 API — 日志上报接口
POST /api/v1/log
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.sdk_schemas import LogReportRequest
from app.services.event_service import build_sdk_event


router = APIRouter(tags=["SDK - Log"])


@router.post("/api/v1/log")
async def report_log(
    request: Request,
    body: LogReportRequest,
    db: AsyncSession = Depends(get_db),
):
    accepted = 0
    rejected = 0
    client_ip = str(request.client.host) if request.client else None
    user_agent = request.headers.get("user-agent")

    for log_entry in body.logs:
        payload = {
            "level": log_entry.level,
            "tag": log_entry.tag,
            "message": log_entry.message,
            "extra": log_entry.extra or {},
        }

        try:
            async with db.begin_nested():
                db.add(
                    build_sdk_event(
                        event_type="log",
                        app_id=body.app_id,
                        device_id=body.device_id,
                        sdk_version=body.sdk_version,
                        session_id=None,
                        payload=payload,
                        timestamp=log_entry.timestamp,
                        client_ip=client_ip,
                        user_agent=user_agent,
                    )
                )
            accepted += 1
        except Exception:
            rejected += 1

    if rejected > 0:
        return {
            "code": 0,
            "message": "partial_success",
            "data": {"accepted": accepted, "rejected": rejected},
        }

    return {"code": 0, "message": "ok", "data": {"accepted": accepted, "rejected": 0}}
