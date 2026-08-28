from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.models.event import SdkEvent

SHANGHAI = ZoneInfo("Asia/Shanghai")
CSV_HEADER = ["id", "package_name", "device_id", "sdk_version", "level", "tag", "message", "extra", "client_ts", "server_ts"]


def _csv_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _local_time(value: datetime | None) -> str:
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def csv_row_for_event(event: SdkEvent) -> list[str]:
    payload = event.payload or {}
    return [
        str(event.id), _csv_text(event.package_name), _csv_text(event.device_id), _csv_text(event.sdk_version),
        _csv_text(payload.get("level")), _csv_text(payload.get("tag")), _csv_text(payload.get("message")),
        _csv_text(payload.get("extra")), _local_time(event.client_ts), _local_time(event.server_ts),
    ]
