"""Transactional package source catalog operations."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.package_catalog import PackageCatalog


def _clean_names(package_names: Iterable[str]) -> list[str]:
    return sorted({name.strip() for name in package_names if name and name.strip()})


async def ensure_package_sources(
    db: AsyncSession,
    package_names: Iterable[str],
    *,
    has_log: bool = False,
    has_usage: bool = False,
) -> list[str]:
    """Ensure only missing package source flags, without touching hot rows."""
    if not (has_log or has_usage):
        raise ValueError("至少指定一个 package source")
    names = _clean_names(package_names)
    if not names:
        return []

    existing_result = await db.execute(
        select(PackageCatalog.package_name, PackageCatalog.has_log, PackageCatalog.has_usage)
        .where(PackageCatalog.package_name.in_(names))
    )
    existing = {row["package_name"]: row for row in existing_result.mappings().all()}
    missing = [
        name
        for name in names
        if name not in existing
        or (has_log and not existing[name]["has_log"])
        or (has_usage and not existing[name]["has_usage"])
    ]
    if not missing:
        return []

    values = [{"package_name": name, "has_log": has_log, "has_usage": has_usage} for name in missing]
    statement = pg_insert(PackageCatalog).values(values)
    update_values = {
        "has_log": or_(PackageCatalog.has_log, statement.excluded.has_log),
        "has_usage": or_(PackageCatalog.has_usage, statement.excluded.has_usage),
        "updated_at": func.now(),
    }
    changed_conditions = []
    if has_log:
        changed_conditions.append(and_(PackageCatalog.has_log.is_(False), statement.excluded.has_log.is_(True)))
    if has_usage:
        changed_conditions.append(and_(PackageCatalog.has_usage.is_(False), statement.excluded.has_usage.is_(True)))
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[PackageCatalog.package_name],
            set_=update_values,
            where=or_(*changed_conditions),
        )
    )
    return missing


async def search_packages(
    db: AsyncSession,
    keyword: str | None,
    limit: int,
    *,
    source: str,
) -> list[str]:
    if source == "log":
        source_column = PackageCatalog.has_log
    elif source == "usage":
        source_column = PackageCatalog.has_usage
    else:
        raise ValueError("source 必须是 log 或 usage")

    statement = select(PackageCatalog.package_name).where(source_column.is_(True))
    normalized_keyword = keyword.strip() if keyword else ""
    if normalized_keyword:
        statement = statement.where(PackageCatalog.package_name.ilike(f"%{normalized_keyword}%"))
    result = await db.execute(statement.order_by(PackageCatalog.package_name).limit(limit))
    return list(result.scalars().all())
