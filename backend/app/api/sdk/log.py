"""
SDK 交互 API — 日志上报接口
POST /api/v1/log
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import SimpleRateLimiter
from app.models.event import SdkEvent
from app.schemas.sdk_schemas import LogReportRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SDK - Log"])

write_limiter = SimpleRateLimiter(max_requests=10, window_seconds=1)


@router.post("/api/v1/log")
async def report_log(
    request: Request,
    body: LogReportRequest,
    db: AsyncSession = Depends(get_db),
    _rate=Depends(write_limiter),
):
    """批量上报日志事件"""
    accepted = 0
    rejected = 0
    client_ip = str(request.client.host) if request.client else None
    user_agent = request.headers.get("user-agent")

    values = []
    for log_entry in body.logs:
        client_ts = None
        if log_entry.timestamp is not None and log_entry.timestamp > 0:
            try:
                client_ts = datetime.fromtimestamp(log_entry.timestamp / 1000, tz=timezone.utc)
            except (OSError, ValueError, OverflowError):
                client_ts = None  # 非法时间戳 → 跳过，不用该字段

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
            "client_ts": client_ts,
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
            logger.exception("批量写入失败，app_id=%s", body.app_id)
            await db.rollback()
            raise HTTPException(status_code=500, detail="数据库写入失败")

    # 部分成功
    if rejected > 0:
        return {
            "code": 0,
            "message": "partial_success",
            "data": {"accepted": accepted, "rejected": rejected},
        }

    # 全部成功
    return {"code": 0, "message": "ok", "data": {"accepted": accepted, "rejected": 0}}
