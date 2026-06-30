from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.event import SdkEvent


def build_sdk_event(
    *,
    event_type: str,
    app_id: str,
    device_id: str,
    sdk_version: str | None,
    session_id: str | None,
    payload: dict[str, Any],
    timestamp: int | None,
    client_ip: str | None,
    user_agent: str | None,
) -> SdkEvent:
    client_ts = None
    if timestamp:
        client_ts = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)

    return SdkEvent(
        event_type=event_type,
        app_id=app_id,
        device_id=device_id,
        sdk_version=sdk_version,
        session_id=session_id,
        payload=payload,
        client_ts=client_ts,
        server_ts=datetime.now(timezone.utc),
        ip=client_ip,
        user_agent=user_agent,
    )
