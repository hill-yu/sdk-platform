"""SDK 使用时长查询服务。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import business_day_utc_range, business_today, serialize_business_time
from app.models.usage_duration import SdkUsageDuration


MAX_QUERY_DAYS = 31


def resolve_usage_date_range(date_from: date | None, date_to: date | None):
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from 和 date_to 必须成对提供")
    if date_from is None:
        date_from = date_to = business_today()
    assert date_to is not None
    if date_to < date_from:
        raise ValueError("结束日期不能早于开始日期")
    if (date_to - date_from).days + 1 > MAX_QUERY_DAYS:
        raise ValueError("单次最多查询 31 天")
    start, _ = business_day_utc_range(date_from)
    _, end = business_day_utc_range(date_to)
    return start, end


def build_usage_filters(
    *,
    package_name: str | None,
    device_id: str | None,
    sdk_version: str | None,
    ver: str | None,
    range_start,
    range_end,
):
    filters = [
        SdkUsageDuration.server_ts >= range_start,
        SdkUsageDuration.server_ts < range_end,
    ]
    if package_name:
        filters.append(SdkUsageDuration.package_name == package_name)
    if device_id:
        filters.append(SdkUsageDuration.device_id == device_id)
    if sdk_version:
        filters.append(SdkUsageDuration.sdk_version == sdk_version)
    if ver:
        filters.append(SdkUsageDuration.app_version == ver)
    return filters


async def get_usage_durations(
    db: AsyncSession,
    *,
    package_name: str | None,
    device_id: str | None,
    sdk_version: str | None,
    ver: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    range_start, range_end = resolve_usage_date_range(date_from, date_to)
    filters = build_usage_filters(
        package_name=package_name,
        device_id=device_id,
        sdk_version=sdk_version,
        ver=ver,
        range_start=range_start,
        range_end=range_end,
    )
    summary_stmt = select(
        func.coalesce(func.sum(SdkUsageDuration.duration_s), 0).label("total_duration_s"),
        func.count(SdkUsageDuration.id).label("report_count"),
        func.count(distinct(SdkUsageDuration.device_id)).label("device_count"),
    ).where(*filters)
    summary_row = (await db.execute(summary_stmt)).mappings().one()

    list_stmt = (
        select(SdkUsageDuration)
        .where(*filters)
        .order_by(SdkUsageDuration.server_ts.desc(), SdkUsageDuration.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await db.execute(list_stmt)).scalars().all()
    items = [
        {
            "id": row.id,
            "package_name": row.package_name,
            "device_id": row.device_id,
            "device_model": row.device_model,
            "os": row.os,
            "ver": row.app_version,
            "sdk_version": row.sdk_version,
            "duration_s": row.duration_s,
            "server_time": serialize_business_time(row.server_ts),
            "ip": str(row.ip) if row.ip is not None else None,
            "user_agent": row.user_agent,
        }
        for row in rows
    ]
    return {
        "summary": {
            "total_duration_s": int(summary_row["total_duration_s"] or 0),
            "report_count": int(summary_row["report_count"] or 0),
            "device_count": int(summary_row["device_count"] or 0),
        },
        "total": int(summary_row["report_count"] or 0),
        "page": page,
        "page_size": page_size,
        "items": items,
    }
