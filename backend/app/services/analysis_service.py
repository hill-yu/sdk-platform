from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SdkEvent


async def get_summary(db: AsyncSession) -> dict[str, int]:
    """获取今日/昨日汇总数据（PV/UV/事件数/错误数）"""
    today = date.today()
    yesterday = today - timedelta(days=1)

    summary_sql = text(
        """
        SELECT
            COUNT(*) FILTER (WHERE server_ts >= :today AND event_type = 'click') AS today_pv,
            COUNT(*) FILTER (WHERE server_ts >= :today) AS today_events,
            COUNT(DISTINCT device_id) FILTER (WHERE server_ts >= :today) AS today_uv,
            COUNT(*) FILTER (WHERE server_ts >= :yesterday AND server_ts < :today AND event_type = 'click') AS yesterday_pv,
            COUNT(*) FILTER (WHERE server_ts >= :yesterday AND server_ts < :today) AS yesterday_events,
            COUNT(DISTINCT device_id) FILTER (WHERE server_ts >= :yesterday AND server_ts < :today) AS yesterday_uv,
            COUNT(*) FILTER (WHERE server_ts >= :today AND event_type = 'log' AND payload->>'level' = 'error') AS error_count
        FROM sdk_events
        """
    )
    result = await db.execute(summary_sql, {"today": today, "yesterday": yesterday})
    row = result.mappings().one()

    today_events = int(row["today_events"] or 0)
    yesterday_events = int(row["yesterday_events"] or 0)
    today_uv = int(row["today_uv"] or 0)
    yesterday_uv = int(row["yesterday_uv"] or 0)

    return {
        "today_pv": int(row["today_pv"] or 0),
        "yesterday_pv": int(row["yesterday_pv"] or 0),
        "today_uv": today_uv,
        "yesterday_uv": yesterday_uv,
        "today_events": today_events,
        "yesterday_events": yesterday_events,
        "active_devices": today_uv,
        "yesterday_active_devices": yesterday_uv,
        "error_count": int(row["error_count"] or 0),
    }


async def get_trend(db: AsyncSession, range_value: str = "24h", event_type: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """获取趋势数据（24小时/7天/30天）"""
    if range_value == "24h":
        sql = text(
            """
            SELECT hour AS time, event_count AS count, unique_devices AS uv
            FROM mv_hourly_trend
            WHERE hour >= :start_time
              AND (CAST(:event_type AS varchar) IS NULL OR event_type = CAST(:event_type AS varchar))
            ORDER BY hour ASC
            """
        )
        start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        params = {"start_time": start_time, "event_type": event_type}
    else:
        start_date = date.today() - timedelta(days=6 if range_value == "7d" else 29)
        sql = text(
            """
            SELECT stat_date::text AS time, SUM(event_count) AS count, SUM(unique_devices) AS uv
            FROM mv_daily_event_stats
            WHERE stat_date >= :start_date
              AND (CAST(:event_type AS varchar) IS NULL OR event_type = CAST(:event_type AS varchar))
            GROUP BY stat_date
            ORDER BY stat_date ASC
            """
        )
        params = {"start_date": start_date, "event_type": event_type}

    rows = (await db.execute(sql, params)).mappings().all()
    return {"points": [dict(row) for row in rows]}


async def get_breakdown(db: AsyncSession, target_date: date, dimension: str = "event_type") -> list[dict[str, Any]]:
    """按维度（event_type/page/element）拆分某日事件分布"""
    if dimension == "page":
        name_col = func.coalesce(SdkEvent.payload['page'].astext, 'unknown')
    elif dimension == "element":
        name_col = func.coalesce(SdkEvent.payload['element'].astext, 'unknown')
    else:
        name_col = SdkEvent.event_type

    start_time = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_time = start_time + timedelta(days=1)

    stmt = (
        select(
            name_col.label('name'),
            func.count().label('count')
        )
        .where(SdkEvent.server_ts >= start_time, SdkEvent.server_ts < end_time)
        .group_by(name_col)
        .order_by(text('count DESC'))
    )

    rows = (await db.execute(stmt)).mappings().all()
    total = sum(int(row["count"]) for row in rows) or 1
    return [
        {"name": row["name"], "count": int(row["count"]), "percentage": round(int(row["count"]) * 100 / total, 2)}
        for row in rows
    ]


async def get_events(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    event_type: str | None,
    app_id: str | None,
    device_id: str | None,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    """分页查询原始事件列表，支持多条件筛选"""
    stmt = select(SdkEvent)

    if event_type:
        stmt = stmt.where(SdkEvent.event_type == event_type)
    if app_id:
        stmt = stmt.where(SdkEvent.app_id == app_id)
    if device_id:
        stmt = stmt.where(SdkEvent.device_id == device_id)
    if date_from:
        stmt = stmt.where(SdkEvent.server_ts >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(SdkEvent.server_ts < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Paginated list
    list_stmt = stmt.order_by(SdkEvent.server_ts.desc()).limit(page_size).offset((page - 1) * page_size)
    rows = (await db.execute(list_stmt)).scalars().all()

    items = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "app_id": e.app_id,
            "device_id": e.device_id,
            "payload": e.payload,
            "client_ts": e.client_ts,
            "server_ts": e.server_ts,
        }
        for e in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}
