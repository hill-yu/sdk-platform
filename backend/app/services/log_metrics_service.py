"""Database-side H1 declaration and click-attempt metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import serialize_business_time
from app.models.log_metrics import H1Declaration, LogClickAttempt


TARGET_KINDS = ("banner", "anchored", "web_element")


def build_metric_filters(*, package_name: str, range_start: datetime, range_end: datetime):
    return [
        H1Declaration.package_name == package_name,
        H1Declaration.event_server_ts >= range_start,
        H1Declaration.event_server_ts < range_end,
    ]


def _click_filters(*, package_name: str, range_start: datetime, range_end: datetime):
    return [
        LogClickAttempt.package_name == package_name,
        LogClickAttempt.event_server_ts >= range_start,
        LogClickAttempt.event_server_ts < range_end,
    ]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _row_value(row: Any, name: str, default: Any = None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _target_metrics(row: Any) -> dict[str, object]:
    planned = int(_row_value(row, "planned_count", 0) or 0)
    actual = int(_row_value(row, "actual_count", 0) or 0)
    success = int(_row_value(row, "success_count", 0) or 0)
    failure = int(_row_value(row, "failure_count", 0) or 0)
    return {
        "planned_count": planned,
        "actual_count": actual,
        "success_count": success,
        "failure_count": failure,
        "actual_rate": _ratio(actual, planned),
        "success_rate": _ratio(success, planned),
        "failure_rate": _ratio(failure, planned),
    }


def _target_stmt(*, package_name: str, range_start: datetime, range_end: datetime):
    filters = _click_filters(
        package_name=package_name,
        range_start=range_start,
        range_end=range_end,
    )
    return (
        select(
            LogClickAttempt.target_kind,
            func.count(LogClickAttempt.attempt_index).label("planned_count"),
            func.count(LogClickAttempt.attempt_index)
            .filter(LogClickAttempt.did_click.is_(True))
            .label("actual_count"),
            func.count(LogClickAttempt.attempt_index)
            .filter(LogClickAttempt.navigation_code == 1)
            .label("success_count"),
            func.count(LogClickAttempt.attempt_index)
            .filter(LogClickAttempt.navigation_code.is_distinct_from(1))
            .label("failure_count"),
        )
        .where(*filters)
        .group_by(LogClickAttempt.target_kind)
        .order_by(LogClickAttempt.target_kind)
    )


async def _get_target_rows(
    db: AsyncSession,
    *,
    package_name: str,
    range_start: datetime,
    range_end: datetime,
) -> list[dict[str, object]]:
    rows = (await db.execute(_target_stmt(
        package_name=package_name,
        range_start=range_start,
        range_end=range_end,
    ))).all()
    return [
        {"target_kind": _row_value(row, "target_kind"), **_target_metrics(row)}
        for row in rows
    ]


async def get_overview(
    db: AsyncSession,
    *,
    package_name: str,
    range_start: datetime,
    range_end: datetime,
) -> dict[str, object]:
    h1 = select(H1Declaration).where(*build_metric_filters(
        package_name=package_name,
        range_start=range_start,
        range_end=range_end,
    )).subquery()
    click = select(LogClickAttempt).where(*_click_filters(
        package_name=package_name,
        range_start=range_start,
        range_end=range_end,
    )).subquery()
    attempt_counts = (
        select(
            click.c.event_id,
            click.c.event_server_ts,
            click.c.record_index,
            func.count(click.c.attempt_index).label("attempt_count"),
        )
        .group_by(click.c.event_id, click.c.event_server_ts, click.c.record_index)
        .subquery()
    )
    mismatch = (
        select(func.count())
        .select_from(
            h1.outerjoin(
                attempt_counts,
                and_(
                    h1.c.event_id == attempt_counts.c.event_id,
                    h1.c.event_server_ts == attempt_counts.c.event_server_ts,
                    h1.c.record_index == attempt_counts.c.record_index,
                ),
            )
        )
        .where(
            func.coalesce(h1.c.declared_click_count, 0)
            != func.coalesce(attempt_counts.c.attempt_count, 0)
        )
        .scalar_subquery()
    )
    stmt = select(
        select(func.count(h1.c.event_id)).select_from(h1).scalar_subquery().label("declaration_count"),
        select(func.coalesce(func.sum(h1.c.declared_click_count), 0)).select_from(h1).scalar_subquery().label("planned_click_count"),
        select(func.count(click.c.attempt_index).filter(click.c.did_click.is_(True))).select_from(click).scalar_subquery().label("actual_click_count"),
        select(func.count(click.c.attempt_index).filter(click.c.navigation_code == 1)).select_from(click).scalar_subquery().label("response_success_count"),
        mismatch.label("plan_mismatch_count"),
        select(func.coalesce(func.sum(h1.c.interstitial_presentation_count), 0)).select_from(h1).scalar_subquery().label("interstitial_presentation_count"),
        select(func.coalesce(func.sum(h1.c.interstitial_click_count), 0)).select_from(h1).scalar_subquery().label("interstitial_click_count"),
        select(func.coalesce(func.sum(h1.c.interstitial_close_count), 0)).select_from(h1).scalar_subquery().label("interstitial_close_count"),
    )
    row = (await db.execute(stmt)).mappings().one()
    target_rows = await _get_target_rows(
        db,
        package_name=package_name,
        range_start=range_start,
        range_end=range_end,
    )
    target_map = {str(row["target_kind"]): _target_metrics(row) for row in target_rows}
    for target_kind in TARGET_KINDS:
        target_map.setdefault(target_kind, _target_metrics({}))
    ad_area = {}
    for key in ("planned_count", "actual_count", "success_count", "failure_count"):
        ad_area[key] = sum(target_map[k][key] for k in ("banner", "anchored"))
    ad_area.update({
        "actual_rate": _ratio(ad_area["actual_count"], ad_area["planned_count"]),
        "success_rate": _ratio(ad_area["success_count"], ad_area["planned_count"]),
        "failure_rate": _ratio(ad_area["failure_count"], ad_area["planned_count"]),
    })
    target_map["ad_area"] = ad_area
    presentation = int(row.get("interstitial_presentation_count", 0) or 0)
    return {
        "declaration_count": int(row.get("declaration_count", 0) or 0),
        "planned_click_count": int(row.get("planned_click_count", 0) or 0),
        "actual_click_count": int(row.get("actual_click_count", 0) or 0),
        "response_success_count": int(row.get("response_success_count", 0) or 0),
        "plan_mismatch_count": int(row.get("plan_mismatch_count", 0) or 0),
        "interstitial_presentation_count": presentation,
        "interstitial_click_count": int(row.get("interstitial_click_count", 0) or 0),
        "interstitial_close_count": int(row.get("interstitial_close_count", 0) or 0),
        "interstitial_close_rate": _ratio(int(row.get("interstitial_close_count", 0) or 0), presentation),
        "interstitial_non_close_click_rate": _ratio(int(row.get("interstitial_click_count", 0) or 0), presentation),
        "target_breakdown": target_map,
    }


async def get_config_breakdown(db: AsyncSession, *, package_name: str, range_start: datetime, range_end: datetime):
    filters = build_metric_filters(package_name=package_name, range_start=range_start, range_end=range_end)
    total = int((await db.execute(select(func.count()).select_from(select(H1Declaration.event_id).where(*filters).subquery()))).scalar_one() or 0)
    rows = (await db.execute(
        select(H1Declaration.config_id, func.count(H1Declaration.event_id).label("declaration_count"))
        .where(*filters)
        .group_by(H1Declaration.config_id)
        .order_by(H1Declaration.config_id)
    )).all()
    return {
        "total": total,
        "items": [
            {
                "config_id": _row_value(row, "config_id") if _row_value(row, "config_id") is not None else "unknown",
                "declaration_count": int(_row_value(row, "declaration_count", 0) or 0),
                "share": _ratio(int(_row_value(row, "declaration_count", 0) or 0), total),
            }
            for row in rows
        ],
    }


async def get_target_breakdown(db: AsyncSession, *, package_name: str, range_start: datetime, range_end: datetime):
    return {"items": await _get_target_rows(db, package_name=package_name, range_start=range_start, range_end=range_end)}


async def get_failure_breakdown(
    db: AsyncSession,
    *,
    package_name: str,
    range_start: datetime,
    range_end: datetime,
    target_kind: str | None = None,
    config_id: int | None = None,
):
    filters = _click_filters(package_name=package_name, range_start=range_start, range_end=range_end)
    filters.append(LogClickAttempt.navigation_code.is_distinct_from(1))
    if target_kind:
        filters.append(LogClickAttempt.target_kind == target_kind)
    if config_id is not None:
        filters.append(LogClickAttempt.config_id == config_id)
    total = int((await db.execute(select(func.count(LogClickAttempt.attempt_index)).where(*filters))).scalar_one() or 0)
    rows = (await db.execute(
        select(
            func.coalesce(LogClickAttempt.failure_category, "未知原因").label("failure_category"),
            func.count(LogClickAttempt.attempt_index).label("failure_count"),
        )
        .where(*filters)
        .group_by(func.coalesce(LogClickAttempt.failure_category, "未知原因"))
        .order_by(func.count(LogClickAttempt.attempt_index).desc())
    )).all()
    return [
        {
            "failure_category": _row_value(row, "failure_category"),
            "failure_count": int(_row_value(row, "failure_count", 0) or 0),
            "share": _ratio(int(_row_value(row, "failure_count", 0) or 0), total),
        }
        for row in rows
    ]


def _serialize_h1(row: Any) -> dict[str, object]:
    return {
        "event_id": _row_value(row, "event_id"),
        "event_server_ts": serialize_business_time(_row_value(row, "event_server_ts")),
        "record_index": _row_value(row, "record_index"),
        "package_name": _row_value(row, "package_name"),
        "device_id": _row_value(row, "device_id"),
        "sdk_version": _row_value(row, "sdk_version"),
        "config_id": _row_value(row, "config_id"),
        "declared_click_count": _row_value(row, "declared_click_count"),
        "status": _row_value(row, "status"),
    }


def _serialize_click(row: Any) -> dict[str, object]:
    return {
        "event_id": _row_value(row, "event_id"),
        "event_server_ts": serialize_business_time(_row_value(row, "event_server_ts")),
        "record_index": _row_value(row, "record_index"),
        "attempt_index": _row_value(row, "attempt_index"),
        "target_kind": _row_value(row, "target_kind"),
        "did_click": _row_value(row, "did_click"),
        "navigation_code": _row_value(row, "navigation_code"),
        "failure_category": _row_value(row, "failure_category"),
    }


async def get_h1_details(
    db: AsyncSession,
    *,
    package_name: str,
    range_start: datetime,
    range_end: datetime,
    page: int = 1,
    page_size: int = 20,
    sort_order: str = "desc",
):
    if page < 1 or page_size < 1 or page_size > 100 or sort_order not in {"asc", "desc"}:
        raise ValueError("分页或排序参数无效")
    filters = build_metric_filters(package_name=package_name, range_start=range_start, range_end=range_end)
    total = int((await db.execute(select(func.count()).select_from(select(H1Declaration.event_id).where(*filters).subquery()))).scalar_one() or 0)
    order = H1Declaration.event_server_ts.asc() if sort_order == "asc" else H1Declaration.event_server_ts.desc()
    h1_rows = (await db.execute(
        select(H1Declaration).where(*filters).order_by(order, H1Declaration.event_id).limit(page_size).offset((page - 1) * page_size)
    )).scalars().all()
    clicks = []
    if h1_rows:
        keys = [(row.event_id, row.event_server_ts, row.record_index) for row in h1_rows]
        click_filters = _click_filters(package_name=package_name, range_start=range_start, range_end=range_end)
        click_filters.append(
            tuple_(LogClickAttempt.event_id, LogClickAttempt.event_server_ts, LogClickAttempt.record_index).in_(keys)
        )
        clicks = (await db.execute(select(LogClickAttempt).where(*click_filters).order_by(LogClickAttempt.event_id, LogClickAttempt.attempt_index))).scalars().all()
    by_key: dict[tuple[object, object, object], list[dict[str, object]]] = {}
    for click in clicks:
        key = (click.event_id, click.event_server_ts, click.record_index)
        by_key.setdefault(key, []).append(_serialize_click(click))
    items = []
    for row in h1_rows:
        item = _serialize_h1(row)
        item["click_attempts"] = by_key.get((row.event_id, row.event_server_ts, row.record_index), [])
        items.append(item)
    return {"total": total, "page": page, "page_size": page_size, "items": items}
