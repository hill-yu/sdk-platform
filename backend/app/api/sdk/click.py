"""
SDK 交互 API — 点击上报接口
POST /api/v1/click
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.sdk_schemas import ClickReportRequest
from app.services.event_service import build_sdk_event


router = APIRouter(tags=["SDK - Click"])


@router.post("/api/v1/click")
async def report_click(
    request: Request,
    body: ClickReportRequest,
    db: AsyncSession = Depends(get_db),
):
    accepted = 0
    rejected = 0
    client_ip = str(request.client.host) if request.client else None
    user_agent = request.headers.get("user-agent")

    for event in body.events:
        if not event.element and not event.page:
            rejected += 1
            continue

        payload = {
            "type": event.type,
            "page": event.page,
            "element": event.element,
            "position": event.position,
            "extra": event.extra or {},
        }

        try:
            async with db.begin_nested():
                db.add(
                    build_sdk_event(
                        event_type="click",
                        app_id=body.app_id,
                        device_id=body.device_id,
                        sdk_version=body.sdk_version,
                        session_id=body.session_id,
                        payload=payload,
                        timestamp=event.timestamp,
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
