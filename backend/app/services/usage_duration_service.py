"""SDK 使用时长查询服务。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import case, cast, distinct, func, select
from sqlalchemy.sql.sqltypes import Numeric
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import business_day_utc_range, business_hour_utc_range, business_today, serialize_business_time
from app.models.usage_duration import SdkUsageDuration


MAX_QUERY_DAYS = 31
SUMMARY_SORT_COLUMNS = {"package_name", "device_model", "device_count", "total_duration_s", "average_duration_s", "last_report_at"}


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
    if package_name is not None:
        filters.append(SdkUsageDuration.package_name == package_name)
    if device_id is not None:
        filters.append(SdkUsageDuration.device_id == device_id)
    if sdk_version is not None:
        filters.append(SdkUsageDuration.sdk_version == sdk_version)
    if ver is not None:
        filters.append(SdkUsageDuration.app_version == ver)
    return filters


def build_latest_usage_query(
    *,
    package_name: str | None,
    device_model: str | None,
    range_start,
    range_end,
):
    filters = [
        SdkUsageDuration.server_ts >= range_start,
        SdkUsageDuration.server_ts < range_end,
    ]
    if package_name is not None:
        filters.append(SdkUsageDuration.package_name == package_name)
    if device_model is not None:
        filters.append(SdkUsageDuration.device_model == device_model)
    latest_rank = func.row_number().over(
        partition_by=(SdkUsageDuration.package_name, SdkUsageDuration.device_id),
        order_by=(SdkUsageDuration.server_ts.desc(), SdkUsageDuration.id.desc()),
    ).label("latest_rank")
    return select(SdkUsageDuration, latest_rank).where(*filters)


def resolve_usage_summary_range(
    date_from: date | None,
    date_to: date | None,
    hour_from: int | None,
    hour_to: int | None,
):
    if date_from is None and date_to is None:
        today = business_today()
        date_from, date_to = today.fromordinal(today.toordinal() - 2), today
    elif (date_from is None) != (date_to is None):
        raise ValueError("date_from 和 date_to 必须成对提供")
    assert date_from is not None and date_to is not None
    if date_to < date_from:
        raise ValueError("结束日期不能早于开始日期")
    if (date_to - date_from).days + 1 > MAX_QUERY_DAYS:
        raise ValueError("单次最多查询 31 天")
    return business_hour_utc_range(date_from, hour_from, date_to, hour_to)


def _value(row: Any, name: str, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _bucket_items(row: Any, device_count: int) -> list[dict[str, object]]:
    return [
        {"key": key, "count": int(_value(row, column, 0) or 0), "share": (int(_value(row, column, 0) or 0) / device_count if device_count else None)}
        for key, column in (
            ("le_300", "le_300_count"),
            ("301_600", "between_301_600_count"),
            ("601_899", "between_601_899_count"),
            ("ge_900", "ge_900_count"),
        )
    ]


async def get_usage_summary(
    db: AsyncSession,
    *,
    package_name: str | None,
    range_start,
    range_end,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("分页参数无效")
    if sort_by not in SUMMARY_SORT_COLUMNS or sort_order not in {"asc", "desc"}:
        raise ValueError("排序参数无效")
    latest = build_latest_usage_query(
        package_name=package_name,
        device_model=None,
        range_start=range_start,
        range_end=range_end,
    ).subquery()
    latest_rows = select(latest).where(latest.c.latest_rank == 1).subquery()
    device_count = func.count(latest_rows.c.device_id)
    total_duration = func.coalesce(func.sum(latest_rows.c.duration_s), 0)
    average_duration = func.round(
        cast(total_duration, Numeric) / func.nullif(device_count, 0)
    )
    grouped = select(
        latest_rows.c.package_name,
        latest_rows.c.device_model,
        device_count.label("device_count"),
        total_duration.label("total_duration_s"),
        average_duration.label("average_duration_s"),
        func.sum(case((latest_rows.c.duration_s <= 300, 1), else_=0)).label("le_300_count"),
        func.sum(case((latest_rows.c.duration_s.between(301, 600), 1), else_=0)).label("between_301_600_count"),
        func.sum(case((latest_rows.c.duration_s.between(601, 899), 1), else_=0)).label("between_601_899_count"),
        func.sum(case((latest_rows.c.duration_s >= 900, 1), else_=0)).label("ge_900_count"),
        func.max(latest_rows.c.server_ts).label("last_report_at"),
    ).group_by(latest_rows.c.package_name, latest_rows.c.device_model)
    total = int((await db.execute(select(func.count()).select_from(grouped.subquery()))).scalar_one() or 0)
    sort_expression = getattr(grouped.selected_columns, sort_by, grouped.selected_columns.package_name)
    ordered = grouped.order_by(sort_expression.desc() if sort_order == "desc" else sort_expression.asc())
    rows = (await db.execute(ordered.limit(page_size).offset((page - 1) * page_size))).mappings().all()
    items = []
    for row in rows:
        count = int(_value(row, "device_count", 0) or 0)
        items.append({
            "package_name": _value(row, "package_name"),
            "device_model": _value(row, "device_model"),
            "device_count": count,
            "total_duration_s": int(_value(row, "total_duration_s", 0) or 0),
            "average_duration_s": int(_value(row, "average_duration_s")) if _value(row, "average_duration_s") is not None else None,
            "buckets": _bucket_items(row, count),
            "last_report_at": serialize_business_time(_value(row, "last_report_at")),
        })
    return {"total": total, "page": page, "page_size": page_size, "items": items}


async def get_usage_devices(
    db: AsyncSession,
    *,
    package_name: str,
    device_model: str,
    range_start,
    range_end,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("分页参数无效")
    latest = build_latest_usage_query(
        package_name=package_name,
        device_model=device_model,
        range_start=range_start,
        range_end=range_end,
    ).subquery()
    latest_rows = select(latest).where(latest.c.latest_rank == 1).subquery()
    total = int((await db.execute(select(func.count()).select_from(latest_rows))).scalar_one() or 0)
    rows = (await db.execute(
        select(latest_rows)
        .order_by(latest_rows.c.server_ts.desc(), latest_rows.c.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )).mappings().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "package_name": _value(row, "package_name"),
                "device_id": _value(row, "device_id"),
                "device_model": _value(row, "device_model"),
                "duration_s": _value(row, "duration_s"),
                "sdk_version": _value(row, "sdk_version"),
                "app_version": _value(row, "app_version"),
                "last_report_at": serialize_business_time(_value(row, "server_ts")),
            }
            for row in rows
        ],
    }


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
