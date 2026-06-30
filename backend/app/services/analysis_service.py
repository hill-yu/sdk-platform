from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_summary(db: AsyncSession) -> dict[str, int]:
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
    if range_value == "24h":
        sql = text(
            """
            SELECT hour AS time, event_count AS count, unique_devices AS uv
            FROM mv_hourly_trend
            WHERE hour >= :start_time
              AND (:event_type IS NULL OR event_type = :event_type)
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
              AND (:event_type IS NULL OR event_type = :event_type)
            GROUP BY stat_date
            ORDER BY stat_date ASC
            """
        )
        params = {"start_date": start_date, "event_type": event_type}

    rows = (await db.execute(sql, params)).mappings().all()
    return {"points": [dict(row) for row in rows]}


async def get_breakdown(db: AsyncSession, target_date: date, dimension: str = "event_type") -> list[dict[str, Any]]:
    if dimension == "page":
        dimension_expr = "COALESCE(payload->>'page', 'unknown')"
    elif dimension == "element":
        dimension_expr = "COALESCE(payload->>'element', 'unknown')"
    else:
        dimension_expr = "event_type"

    sql = text(
        f"""
        SELECT {dimension_expr} AS name, COUNT(*) AS count
        FROM sdk_events
        WHERE server_ts >= :start_time AND server_ts < :end_time
        GROUP BY 1
        ORDER BY count DESC
        """
    )

    start_time = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_time = start_time + timedelta(days=1)
    rows = (await db.execute(sql, {"start_time": start_time, "end_time": end_time})).mappings().all()
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
    where_clauses: list[str] = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}

    if event_type:
        where_clauses.append("event_type = :event_type")
        params["event_type"] = event_type
    if app_id:
        where_clauses.append("app_id = :app_id")
        params["app_id"] = app_id
    if device_id:
        where_clauses.append("device_id = :device_id")
        params["device_id"] = device_id
    if date_from:
        params["date_from"] = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        where_clauses.append("server_ts >= :date_from")
    if date_to:
        params["date_to"] = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        where_clauses.append("server_ts < :date_to")

    where_sql = " AND ".join(where_clauses)
    total_sql = text(f"SELECT COUNT(*) AS total FROM sdk_events WHERE {where_sql}")
    list_sql = text(
        f"""
        SELECT id, event_type, app_id, device_id, payload, client_ts, server_ts
        FROM sdk_events
        WHERE {where_sql}
        ORDER BY server_ts DESC
        LIMIT :limit OFFSET :offset
        """
    )
    total = int((await db.execute(total_sql, params)).scalar_one())
    items = (await db.execute(list_sql, params)).mappings().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(row) for row in items]}
