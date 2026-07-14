"""
SDK 交互 API — 日志上报接口
POST /api/v1/log
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.event import SdkEvent
from app.schemas.sdk_schemas import LogReportRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SDK - Log"])


@router.post("/api/v1/log")
async def report_log(
    request: Request,
    body: LogReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量上报日志事件"""
    accepted = 0
    rejected = 0
    client_ip = str(request.client.host) if request.client else None
    user_agent = request.headers.get("user-agent")

    values = []
    for log_entry in body.logs:
        values.append({
            "event_type": "log",
            "app_id": body.app_id,
            "device_id": body.device_id,
            "sdk_version": body.sdk_version,
            "session_id": None,
            "payload": {
                "level": log_entry.level,
                "tag": log_entry.tag,
                "message": log_entry.message,
                "extra": log_entry.extra or {},
            },
            "client_ts": datetime.fromtimestamp(log_entry.timestamp / 1000, tz=timezone.utc) if log_entry.timestamp else None,
            "server_ts": datetime.now(timezone.utc),
            "ip": client_ip,
            "user_agent": user_agent,
        })

    if values:
        try:
            stmt = pg_insert(SdkEvent).values(values)
            await db.execute(stmt)
            accepted = len(values)
        except Exception:
            logger.exception("批量写入日志事件失败，app_id=%s, count=%d", body.app_id, len(values))
            rejected = len(values)
            accepted = 0

    # 全部失败
    if accepted == 0 and rejected > 0:
        return {
            "code": 5001,
            "message": "all_events_rejected",
            "data": {"accepted": 0, "rejected": rejected},
        }

    # 部分成功
    if rejected > 0:
        return {
            "code": 0,
            "message": "partial_success",
            "data": {"accepted": accepted, "rejected": rejected},
        }

    # 全部成功
    return {"code": 0, "message": "ok", "data": {"accepted": accepted, "rejected": 0}}
