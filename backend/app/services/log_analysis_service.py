from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import Date, and_, cast, distinct, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import business_day_utc_range, business_today, serialize_business_time
from app.models.event import SdkEvent
from app.models.log_analysis import AdminPreference, LogDecode, LogReparseJob, PackageProfile
from app.services.config_crypto import normalize_package_name

LOG_ANALYSIS_PREFERENCE_KEY = "log_analysis_columns"
LOG_ANALYSIS_COLUMNS = (
    "date",
    "package_name",
    "alias",
    "url",
    "company",
    "account",
    "user_count",
    "flow_count",
    "expected_click_count",
    "actual_click_count",
    "ad_click_count",
    "interstitial_presentation_count",
    "interstitial_click_count",
    "average_duration_ms",
    "success_rate",
    "parse_failure_count",
)
DEFAULT_LOG_ANALYSIS_COLUMNS = LOG_ANALYSIS_COLUMNS
MAX_ANALYSIS_DATE_SPAN_DAYS = 31
SUMMARY_SORT_COLUMNS = {
    "date": "date",
    "package_name": "package_name",
    "user_count": "user_count",
    "flow_count": "flow_count",
    "success_rate": "success_rate",
    "average_duration_ms": "average_duration_ms",
    "parse_failure_count": "parse_failure_count",
}
DETAIL_SORT_COLUMNS = {
    "event_server_ts": LogDecode.event_server_ts,
    "event_id": LogDecode.event_id,
    "status": LogDecode.status,
    "package_name": LogDecode.package_name,
}
DECODER_VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
PROFILE_FIELDS = frozenset({"alias", "company", "account"})


def _profile_value(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _serialize_profile(profile: PackageProfile | None, package_name: str) -> dict[str, str]:
    return {
        "package_name": package_name,
        "alias": profile.alias if profile and profile.alias is not None else "",
        "company": profile.company if profile and profile.company is not None else "",
        "account": profile.account if profile and profile.account is not None else "",
    }


async def get_package_profile(db: AsyncSession, package_name: str) -> dict[str, str]:
    normalized = normalize_package_name(package_name)
    result = await db.execute(
        select(PackageProfile).where(PackageProfile.package_name == normalized)
    )
    return _serialize_profile(result.scalar_one_or_none(), normalized)


async def upsert_package_profile(
    db: AsyncSession,
    package_name: str,
    *,
    updates: dict[str, str | None],
) -> dict[str, str]:
    normalized = normalize_package_name(package_name)
    unknown = set(updates) - PROFILE_FIELDS
    if unknown or not updates:
        raise ValueError("包资料更新字段无效")
    normalized_updates = {key: _profile_value(value) for key, value in updates.items()}
    statement = pg_insert(PackageProfile).values(
        package_name=normalized,
        **normalized_updates,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[PackageProfile.package_name],
            set_={key: getattr(statement.excluded, key) for key in normalized_updates},
        )
    )
    await db.flush()
    return await get_package_profile(db, normalized)


def validate_column_selection(columns: Sequence[str]) -> list[str]:
    selected = list(columns)
    if not selected:
        raise ValueError("列配置不能为空")
    if len(selected) > len(LOG_ANALYSIS_COLUMNS):
        raise ValueError("列配置超过目录总数")
    if any(not isinstance(column, str) or len(column) > 64 for column in selected):
        raise ValueError("列 ID 长度无效")
    unknown = [column for column in selected if column not in LOG_ANALYSIS_COLUMNS]
    if unknown:
        raise ValueError("列配置包含未知列")
    if len(set(selected)) != len(selected):
        raise ValueError("列配置不能重复")
    if "date" not in selected or "package_name" not in selected:
        raise ValueError("列配置必须包含 date 和 package_name")
    return selected


def parse_decoder_version(value: str) -> tuple[int, int, int]:
    match = DECODER_VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("decoder_version_before 必须是 x.y.z 三段非负整数")
    return tuple(int(part) for part in match.groups())


def _resolve_date_range(
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date, datetime, datetime]:
    today = business_today()
    if date_from is None and date_to is None:
        date_to = today
        date_from = today - timedelta(days=6)
    elif date_from is None:
        date_from = date_to - timedelta(days=6)
    elif date_to is None:
        date_to = date_from + timedelta(days=6)
    if date_from > date_to:
        raise ValueError("date_from 不能晚于 date_to")
    if (date_to - date_from).days + 1 > MAX_ANALYSIS_DATE_SPAN_DAYS:
        raise ValueError("日期范围不能超过 31 天")
    start, _ = business_day_utc_range(date_from)
    _, end = business_day_utc_range(date_to)
    return date_from, date_to, start, end


def _business_date_expression():
    return cast(
        SdkEvent.server_ts.op("AT TIME ZONE")(
            literal_column("'Asia/Shanghai'")
        ),
        Date,
    )


def _summary_columns():
    business_date = _business_date_expression().label("date")
    success_count = func.count(LogDecode.is_success).filter(LogDecode.is_success.is_(True))
    success_samples = func.count(LogDecode.is_success)
    success_rate = (
        success_count / func.nullif(success_samples, 0)
    ).label("success_rate")
    return (
        business_date,
        SdkEvent.package_name.label("package_name"),
        func.coalesce(PackageProfile.alias, "").label("alias"),
        func.coalesce(PackageProfile.company, "").label("company"),
        func.coalesce(PackageProfile.account, "").label("account"),
        func.min(LogDecode.url).label("primary_url"),
        func.count(distinct(LogDecode.url)).label("url_count"),
        func.count(distinct(SdkEvent.device_id)).label("user_count"),
        func.count(LogDecode.event_id).filter(LogDecode.status == "success").label("flow_count"),
        func.coalesce(func.sum(LogDecode.expected_click_count), 0).label("expected_click_count"),
        func.coalesce(func.sum(LogDecode.actual_click_count), 0).label("actual_click_count"),
        func.coalesce(func.sum(LogDecode.ad_click_count), 0).label("ad_click_count"),
        func.coalesce(
            func.sum(LogDecode.interstitial_presentation_count), 0
        ).label("interstitial_presentation_count"),
        func.coalesce(func.sum(LogDecode.interstitial_click_count), 0).label("interstitial_click_count"),
        func.avg(LogDecode.duration_ms).label("average_duration_ms"),
        func.count(LogDecode.duration_ms).label("duration_sample_count"),
        success_count.label("success_count"),
        success_samples.label("success_sample_count"),
        success_rate,
        func.count(LogDecode.event_id).filter(LogDecode.status == "failed").label("failed_count"),
        func.count(LogDecode.event_id).filter(LogDecode.status == "unsupported").label("unsupported_count"),
        (
            func.count(LogDecode.event_id).filter(LogDecode.status.in_(["failed", "unsupported"]))
        ).label("parse_failure_count"),
    )


def _normalize_aggregate_row(row) -> dict:
    data = dict(row)
    data["alias"] = data.get("alias") or ""
    data["company"] = data.get("company") or ""
    data["account"] = data.get("account") or ""
    if data.get("date") is not None:
        data["date"] = data["date"].isoformat()
    if data.get("average_duration_ms") is not None:
        data["average_duration_ms"] = float(data["average_duration_ms"])
    for key in (
        "url_count", "user_count", "flow_count", "expected_click_count",
        "actual_click_count", "ad_click_count", "interstitial_presentation_count",
        "interstitial_click_count", "duration_sample_count", "success_sample_count",
        "failed_count", "unsupported_count", "parse_failure_count",
    ):
        if data.get(key) is not None:
            data[key] = int(data[key])
    success_samples = data.get("success_sample_count", 0)
    data["success_rate"] = (
        float(data.get("success_count", 0)) / success_samples
        if success_samples
        else None
    )
    data.pop("success_count", None)
    return data


def _validate_summary_options(page: int, page_size: int, sort_by: str, sort_order: str) -> None:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("分页参数无效")
    if sort_by not in SUMMARY_SORT_COLUMNS:
        raise ValueError("排序字段无效")
    if sort_order not in {"asc", "desc"}:
        raise ValueError("排序方向无效")


async def get_log_analysis_summary(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    package_name: str | None = None,
    device_id: str | None = None,
    log_level: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "date",
    sort_order: str = "desc",
) -> dict:
    _validate_summary_options(page, page_size, sort_by, sort_order)
    _, _, start, end = _resolve_date_range(date_from, date_to)
    conditions = [
        SdkEvent.event_type == "log",
        SdkEvent.server_ts >= start,
        SdkEvent.server_ts < end,
    ]
    if package_name:
        conditions.append(SdkEvent.package_name == normalize_package_name(package_name))
    if device_id:
        conditions.append(SdkEvent.device_id == device_id)
    if log_level:
        conditions.extend((SdkEvent.payload["level"].astext == log_level,))
    group_stmt = (
        select(*_summary_columns())
        .select_from(SdkEvent)
        .outerjoin(
            LogDecode,
            and_(
                LogDecode.event_id == SdkEvent.id,
                LogDecode.event_server_ts == SdkEvent.server_ts,
            ),
        )
        .outerjoin(PackageProfile, PackageProfile.package_name == SdkEvent.package_name)
        .where(*conditions)
        .group_by(
            _business_date_expression(),
            SdkEvent.package_name,
            PackageProfile.alias,
            PackageProfile.company,
            PackageProfile.account,
        )
    )
    sort_expression = SUMMARY_SORT_COLUMNS[sort_by]
    order_clause = literal_column(sort_expression)
    group_stmt = group_stmt.order_by(order_clause.desc() if sort_order == "desc" else order_clause.asc())
    count_stmt = select(func.count()).select_from(group_stmt.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(group_stmt.limit(page_size).offset((page - 1) * page_size))
    ).mappings().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_normalize_aggregate_row(row) for row in rows],
    }


def _decode_item(decode: LogDecode) -> dict:
    def value(name: str):
        if isinstance(decode, dict):
            return decode.get(name)
        return getattr(decode, name, None)

    return {
        "event_id": value("event_id"),
        "event_server_ts": serialize_business_time(value("event_server_ts")),
        "record_index": value("record_index"),
        "package_name": value("package_name"),
        "device_id": value("device_id"),
        "status": value("status"),
        "decoder_version": value("decoder_version"),
        "decoded_timestamp": serialize_business_time(value("decoded_timestamp")),
        "url": value("url"),
        "config_id": value("config_id"),
        "window": value("window"),
        "expected_click_count": value("expected_click_count"),
        "actual_click_count": value("actual_click_count"),
        "ad_click_count": value("ad_click_count"),
        "interstitial_presentation_count": value("interstitial_presentation_count"),
        "interstitial_click_count": value("interstitial_click_count"),
        "interstitial_close_count": value("interstitial_close_count"),
        "duration_ms": value("duration_ms"),
        "final_reason": value("final_reason"),
        "is_success": value("is_success"),
        "decoded_payload": value("decoded_payload"),
        "parse_error": value("parse_error"),
        "parsed_at": serialize_business_time(value("parsed_at")),
    }


async def get_log_analysis_details(
    db: AsyncSession,
    *,
    target_date: date,
    package_name: str,
    device_id: str | None = None,
    log_level: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "event_server_ts",
    sort_order: str = "desc",
) -> dict:
    _validate_summary_options(page, page_size, "date", "desc")
    if sort_by not in DETAIL_SORT_COLUMNS or sort_order not in {"asc", "desc"}:
        raise ValueError("详情排序参数无效")
    _, _, start, end = _resolve_date_range(target_date, target_date)
    conditions = [
        SdkEvent.event_type == "log",
        SdkEvent.package_name == normalize_package_name(package_name),
        SdkEvent.server_ts >= start,
        SdkEvent.server_ts < end,
        _business_date_expression() == target_date,
    ]
    if device_id:
        conditions.append(SdkEvent.device_id == device_id)
    if log_level:
        conditions.append(SdkEvent.payload["level"].astext == log_level)
    if status:
        conditions.append(LogDecode.status == status)
    base = (
        select(LogDecode)
        .join(
            SdkEvent,
            and_(
                LogDecode.event_id == SdkEvent.id,
                LogDecode.event_server_ts == SdkEvent.server_ts,
            ),
        )
        .where(*conditions)
    )
    count = int((await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one() or 0)
    order = DETAIL_SORT_COLUMNS[sort_by]
    ordered = base.order_by(order.desc() if sort_order == "desc" else order.asc())
    rows = (await db.execute(ordered.limit(page_size).offset((page - 1) * page_size))).scalars().all()
    return {
        "total": count,
        "page": page,
        "page_size": page_size,
        "items": [_decode_item(row) for row in rows],
    }


async def get_log_analysis_detail(
    db: AsyncSession,
    *,
    event_id: int,
    event_server_ts: datetime,
    record_index: int,
) -> dict | None:
    decode = (
        await db.execute(
            select(LogDecode).where(
                LogDecode.event_id == event_id,
                LogDecode.event_server_ts == event_server_ts,
                LogDecode.record_index == record_index,
            )
        )
    ).scalar_one_or_none()
    if decode is None:
        return None
    event = (
        await db.execute(
            select(SdkEvent).where(
                SdkEvent.id == event_id,
                SdkEvent.server_ts == event_server_ts,
            )
        )
    ).scalar_one_or_none()
    if event is None:
        return None
    result = _decode_item(decode)
    result["extra"] = event.payload.get("extra") if isinstance(event.payload, dict) else None
    return result


def _reparse_range(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    if date_from is None and date_to is None:
        today = business_today()
        date_from = today - timedelta(days=6)
        date_to = today
    _, _, start, end = _resolve_date_range(date_from, date_to)
    return start, end


async def create_reparse_job(
    db: AsyncSession,
    *,
    date_from: date | None,
    date_to: date | None,
    package_name: str | None,
    status: str | None,
    decoder_version_before: str | None,
    created_by: str,
) -> dict:
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from 和 date_to 必须成对提供")
    if not any(value is not None for value in (date_from, date_to, package_name, status, decoder_version_before)):
        raise ValueError("reparse 必须指定范围或筛选条件")
    if decoder_version_before is not None:
        parse_decoder_version(decoder_version_before)
    range_start, range_end = _reparse_range(date_from, date_to)
    job = LogReparseJob(
        package_name=normalize_package_name(package_name) if package_name else None,
        range_start=range_start,
        range_end=range_end,
        processed_count=0,
        decoded_count=0,
        failed_count=0,
        status="pending",
        created_by=created_by,
    )
    db.add(job)
    await db.flush()
    return {
        "id": job.id,
        "package_name": job.package_name,
        "range_start": serialize_business_time(job.range_start),
        "range_end": serialize_business_time(job.range_end),
        "cursor_event_id": job.cursor_event_id,
        "cursor_server_ts": serialize_business_time(job.cursor_server_ts),
        "processed_count": job.processed_count,
        "decoded_count": job.decoded_count,
        "failed_count": job.failed_count,
        "status": job.status,
    }


def _columns_response(columns: Sequence[str]) -> dict[str, list[str]]:
    return {
        "available_columns": list(LOG_ANALYSIS_COLUMNS),
        "default_columns": list(DEFAULT_LOG_ANALYSIS_COLUMNS),
        "columns": list(columns),
    }


async def get_log_analysis_columns(db: AsyncSession) -> dict[str, list[str]]:
    result = await db.execute(
        select(AdminPreference).where(
            AdminPreference.preference_key == LOG_ANALYSIS_PREFERENCE_KEY
        )
    )
    preference = result.scalar_one_or_none()
    if preference is None:
        return _columns_response(DEFAULT_LOG_ANALYSIS_COLUMNS)
    return _columns_response(validate_column_selection(preference.value))


async def save_log_analysis_columns(
    db: AsyncSession,
    columns: Sequence[str],
) -> dict[str, list[str]]:
    selected = validate_column_selection(columns)
    values = {
        "preference_key": LOG_ANALYSIS_PREFERENCE_KEY,
        "value": selected,
    }
    statement = pg_insert(AdminPreference).values(values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AdminPreference.preference_key],
            set_={"value": statement.excluded.value},
        )
    )
    return _columns_response(selected)
