"""Asynchronous parsing and persistence for uploaded SDK flow logs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SdkEvent
from app.models.log_analysis import LogDecode
from app.services.flow_log_decoder import decode_extra

MAX_BATCH_SIZE = 50
PARSE_TIMEOUT_SECONDS = 5.0
SUCCESS_FINAL_REASONS = {
    "planned-click-count-exhausted",
    "landing-page-flow-completed",
    "macro-actual-click-limit-reached",
}
FAILED_FINAL_REASONS = {
    "load-timeout",
    "home-page-load-failed",
    "total-time-timeout",
}


@dataclass(frozen=True)
class ParseBatchResult:
    scanned: int = 0
    success: int = 0
    unsupported: int = 0
    failed: int = 0
    last_event_id: int | None = None
    last_event_server_ts: datetime | None = None

    @property
    def processed(self) -> int:
        return self.success + self.unsupported + self.failed


def _row_value(row: Any, name: str, index: int) -> Any:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None and name in mapping:
        return mapping[name]
    if hasattr(row, name):
        return getattr(row, name)
    return row[index]


def _decoded_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _derived_click_metrics(record: dict[str, Any]) -> tuple[int | None, int | None, bool | None]:
    attempts = record.get("planned_click_attempts")
    if isinstance(attempts, list) and all(isinstance(attempt, dict) for attempt in attempts):
        actual_click_count = sum(attempt.get("did_click") is True for attempt in attempts)
        ad_click_count = sum(
            attempt.get("did_click") is True
            and attempt.get("target_kind") in {"banner", "anchored"}
            for attempt in attempts
        )
    else:
        actual_click_count = ad_click_count = None

    if "is_success" in record:
        is_success = record["is_success"]
    else:
        final_reason = record.get("final_reason")
        if final_reason in SUCCESS_FINAL_REASONS:
            is_success = True
        elif final_reason in FAILED_FINAL_REASONS or (
            isinstance(final_reason, str)
            and final_reason.startswith("interaction-execution-failed")
        ):
            is_success = False
        else:
            is_success = None
    return actual_click_count, ad_click_count, is_success


def _project_decoded_record(
    record: dict[str, Any],
    *,
    event: SdkEvent,
    record_index: int,
    decoder_version: str,
) -> dict[str, Any]:
    derived_actual_click_count, derived_ad_click_count, derived_is_success = _derived_click_metrics(record)
    return {
        "event_id": event.id,
        "event_server_ts": event.server_ts,
        "record_index": record_index,
        "package_name": event.package_name,
        "device_id": event.device_id,
        "status": "success",
        "decoder_version": decoder_version,
        "decoded_timestamp": _decoded_timestamp(
            record.get("decoded_timestamp", record.get("timestamp"))
        ),
        "url": record.get("url"),
        "config_id": record.get("config_id"),
        "window": record.get("window"),
        "expected_click_count": record.get("expected_click_count"),
        "actual_click_count": record["actual_click_count"]
        if "actual_click_count" in record
        else derived_actual_click_count,
        "ad_click_count": record["ad_click_count"]
        if "ad_click_count" in record
        else derived_ad_click_count,
        "interstitial_presentation_count": record.get("interstitial_presentation_count"),
        "interstitial_click_count": record.get("interstitial_click_count"),
        "interstitial_close_count": record.get("interstitial_close_count"),
        "duration_ms": record.get("duration_ms"),
        "final_reason": record.get("final_reason"),
        "is_success": derived_is_success,
        "decoded_payload": record,
        "parse_error": None,
        "parsed_at": datetime.now(timezone.utc),
    }


def _safe_parse_error(error: BaseException) -> str:
    error_type = type(error).__name__
    if isinstance(error, asyncio.TimeoutError):
        reason = "decoder timed out"
    elif isinstance(error, TypeError):
        reason = "decoder input is invalid"
    elif isinstance(error, ValueError):
        reason = "decoder rejected input"
    else:
        reason = "decoder execution failed"
    return f"{error_type}: {reason}"[:512]


def _placeholder_key(decode: LogDecode):
    return and_(
        LogDecode.event_id == decode.event_id,
        LogDecode.event_server_ts == decode.event_server_ts,
        LogDecode.record_index == -1,
    )


async def _replace_placeholder(
    db: AsyncSession,
    decode: LogDecode,
    values: list[dict[str, Any]],
) -> None:
    await db.execute(delete(LogDecode).where(_placeholder_key(decode)))
    if values:
        await db.execute(pg_insert(LogDecode).values(values))


async def _decode_with_timeout(extra: str) -> list[dict[str, Any]]:
    result = await asyncio.wait_for(
        asyncio.to_thread(decode_extra, extra),
        timeout=PARSE_TIMEOUT_SECONDS,
    )
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise TypeError("decoder result is invalid")
    return result


async def process_pending_batch(
    db: AsyncSession,
    *,
    batch_size: int = 50,
) -> ParseBatchResult:
    """Claim and process one bounded batch of pending decode placeholders."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    limit = min(batch_size, MAX_BATCH_SIZE)
    statement = (
        select(LogDecode, SdkEvent)
        .join(
            SdkEvent,
            and_(
                SdkEvent.id == LogDecode.event_id,
                SdkEvent.server_ts == LogDecode.event_server_ts,
            ),
        )
        .where(LogDecode.record_index == -1, LogDecode.status == "pending")
        .order_by(LogDecode.event_server_ts, LogDecode.event_id)
        .limit(limit)
        .with_for_update(of=LogDecode, skip_locked=True)
    )
    result = await db.execute(statement)
    rows = result.all()
    successful = unsupported = failed = 0
    last_event_id = None
    last_event_server_ts = None

    for row in rows:
        decode = _row_value(row, "LogDecode", 0)
        event = _row_value(row, "SdkEvent", 1)
        last_event_id = event.id
        last_event_server_ts = event.server_ts
        extra = event.payload.get("extra") if isinstance(event.payload, dict) else None
        try:
            async with db.begin_nested():
                decoded_records = await _decode_with_timeout(extra)
                if not decoded_records:
                    values = [
                        {
                            "event_id": event.id,
                            "event_server_ts": event.server_ts,
                            "record_index": 0,
                            "package_name": event.package_name,
                            "device_id": event.device_id,
                            "status": "unsupported",
                            "decoder_version": decode.decoder_version,
                            "decoded_payload": {},
                            "parsed_at": datetime.now(timezone.utc),
                        }
                    ]
                    await _replace_placeholder(db, decode, values)
                    unsupported += 1
                    continue

                values = [
                    _project_decoded_record(
                        record,
                        event=event,
                        record_index=index,
                        decoder_version=decode.decoder_version,
                    )
                    for index, record in enumerate(decoded_records)
                ]
                await _replace_placeholder(db, decode, values)
                successful += 1
        except Exception as error:
            values = [
                {
                    "event_id": event.id,
                    "event_server_ts": event.server_ts,
                    "record_index": 0,
                    "package_name": event.package_name,
                    "device_id": event.device_id,
                    "status": "failed",
                    "decoder_version": decode.decoder_version,
                    "decoded_payload": {},
                    "parse_error": _safe_parse_error(error),
                    "parsed_at": datetime.now(timezone.utc),
                }
            ]
            async with db.begin_nested():
                await _replace_placeholder(db, decode, values)
            failed += 1

    return ParseBatchResult(
        scanned=len(rows),
        success=successful,
        unsupported=unsupported,
        failed=failed,
        last_event_id=last_event_id,
        last_event_server_ts=last_event_server_ts,
    )
