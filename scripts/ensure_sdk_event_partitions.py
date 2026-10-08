"""Ensure the current UTC month and the next two months have event partitions."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


class PartitionSafetyError(RuntimeError):
    """Raised when the catalog is not safe for an automatic partition change."""


@dataclass(frozen=True)
class PartitionReport:
    current_month: date
    target_months: tuple[date, ...]
    missing: tuple[str, ...]
    created: tuple[str, ...]
    applied: bool
    verified: bool
    committed: bool


BOUND_PATTERN = re.compile(
    r"FOR VALUES FROM \('(?P<start>[^']+)'\) TO \('(?P<end>[^']+)'\)"
)


def normalize_catalog_text(value: object) -> str:
    """Normalize asyncpg catalog values without ever guessing an encoding."""

    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    if isinstance(value, str):
        return value
    return str(value)


def parse_partition_bound(value: object) -> tuple[date, date]:
    """Parse PostgreSQL's explicit UTC range bound representation."""

    match = BOUND_PATTERN.fullmatch(normalize_catalog_text(value).strip())
    if match is None:
        raise PartitionSafetyError(
            f"无法解析 sdk_events 分区边界: {normalize_catalog_text(value)!r}"
        )

    starts_at = _parse_utc_midnight(match.group("start"))
    ends_at = _parse_utc_midnight(match.group("end"))
    if ends_at <= starts_at:
        raise PartitionSafetyError("分区边界不是递增的 UTC 月区间")
    return starts_at.date(), ends_at.date()


def _parse_utc_midnight(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PartitionSafetyError(f"非法分区时间边界: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PartitionSafetyError(f"分区边界不是显式 UTC: {value!r}")
    if parsed.time().replace(tzinfo=None) != datetime.min.time():
        raise PartitionSafetyError(f"分区边界不是 UTC 月初: {value!r}")
    return parsed


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, count: int) -> date:
    month_index = value.year * 12 + value.month - 1 + count
    return date(month_index // 12, month_index % 12 + 1, 1)


def target_months(current_day: date) -> list[date]:
    """Return the current UTC month and the next two UTC months."""

    current_month = _month_start(current_day)
    return [_add_months(current_month, offset) for offset in range(3)]


def build_plan(
    current_day: date,
    existing: Mapping[str, tuple[date, date]],
) -> list[tuple[str, date, date]]:
    """Build a fail-closed create plan from already-normalized catalog bounds."""

    plan: list[tuple[str, date, date]] = []
    for start in target_months(current_day):
        end = _add_months(start, 1)
        name = f"sdk_events_{start:%Y%m}"
        if name in existing and existing[name] != (start, end):
            raise PartitionSafetyError(f"同名分区 {name} 的 bounds 不匹配")
        for other_name, (other_start, other_end) in existing.items():
            if other_name != name and other_start < end and start < other_end:
                raise PartitionSafetyError(
                    f"已有分区 {other_name} 与目标月份 {name} 重叠"
                )
        if name not in existing:
            plan.append((name, start, end))
    return plan


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def build_create_partition_sql(name: str, start: date, end: date) -> str:
    """Build DDL from generated month values, never from user input."""

    if not re.fullmatch(r"sdk_events_\d{6}", name):
        raise PartitionSafetyError(f"非法分区名: {name!r}")
    return (
        f"CREATE TABLE IF NOT EXISTS public.{_quoted_identifier(name)} "
        f"PARTITION OF public.\"sdk_events\" "
        f"FOR VALUES FROM ('{start.isoformat()} 00:00:00+00') "
        f"TO ('{end.isoformat()} 00:00:00+00')"
    )


async def _read_catalog(
    connection: AsyncConnection,
) -> tuple[int, str, str, dict[str, tuple[date, date]], dict[str, str], dict[str, str]]:
    parent_rows = (
        await connection.execute(
            text(
                "SELECT c.oid, c.relkind, p.partstrat, pg_get_userbyid(c.relowner) AS owner, "
                "coalesce(c.relacl::text, '') AS acl "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_partitioned_table p ON p.partrelid=c.oid "
                "WHERE n.nspname='public' AND c.relname='sdk_events'"
            )
        )
    ).mappings().all()
    if len(parent_rows) != 1:
        raise PartitionSafetyError("public.sdk_events 父表不存在或不唯一")
    if normalize_catalog_text(parent_rows[0]["relkind"]) != "p":
        raise PartitionSafetyError("public.sdk_events 不是 PostgreSQL range partition 父表")
    if normalize_catalog_text(parent_rows[0]["partstrat"]) != "r":
        raise PartitionSafetyError("public.sdk_events 不是 PostgreSQL range partition 父表")
    parent_oid = int(parent_rows[0]["oid"])
    key_rows = (
        await connection.execute(
            text(
                "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS data_type "
                "FROM pg_partitioned_table p "
                "JOIN LATERAL unnest(p.partattrs) WITH ORDINALITY "
                "AS keys(attnum, ordinal) ON true "
                "JOIN pg_attribute a ON a.attrelid=p.partrelid "
                "AND a.attnum=keys.attnum "
                "WHERE p.partrelid=:parent_oid "
                "ORDER BY keys.ordinal"
            ),
            {"parent_oid": parent_oid},
        )
    ).mappings().all()
    if len(key_rows) != 1:
        raise PartitionSafetyError("sdk_events 必须只有一个分区键")
    if normalize_catalog_text(key_rows[0]["attname"]) != "server_ts":
        raise PartitionSafetyError("sdk_events 分区键不是 server_ts")
    if normalize_catalog_text(key_rows[0]["data_type"]).lower() != "timestamp with time zone":
        raise PartitionSafetyError("sdk_events.server_ts 不是 timestamptz")
    parent_owner = normalize_catalog_text(parent_rows[0]["owner"])
    parent_acl = normalize_catalog_text(parent_rows[0]["acl"])

    rows = (
        await connection.execute(
            text(
                "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) AS bound, "
                "pg_get_userbyid(c.relowner) AS owner, "
                "coalesce(c.relacl::text, '') AS acl "
                "FROM pg_inherits i "
                "JOIN pg_class p ON p.oid=i.inhparent "
                "JOIN pg_namespace pn ON pn.oid=p.relnamespace "
                "JOIN pg_class c ON c.oid=i.inhrelid "
                "JOIN pg_namespace cn ON cn.oid=c.relnamespace "
                "WHERE pn.nspname='public' AND p.oid=:parent_oid "
                "AND cn.nspname='public' ORDER BY c.relname"
            ),
            {"parent_oid": parent_oid},
        )
    ).mappings().all()
    existing: dict[str, tuple[date, date]] = {}
    owners: dict[str, str] = {}
    acls: dict[str, str] = {}
    for row in rows:
        name = normalize_catalog_text(row["relname"])
        if name in existing:
            raise PartitionSafetyError(f"catalog 中存在重复子分区名: {name}")
        existing[name] = parse_partition_bound(row["bound"])
        owners[name] = normalize_catalog_text(row["owner"])
        acls[name] = normalize_catalog_text(row["acl"])
    if any(owner != parent_owner for owner in owners.values()):
        raise PartitionSafetyError("现有 sdk_events 分区 owner 与父表不一致")
    if len({parent_acl, *acls.values()}) > 1:
        raise PartitionSafetyError("父表与现有 sdk_events 分区 ACL 不一致")
    return parent_oid, parent_owner, parent_acl, existing, owners, acls


async def _current_utc_day(connection: AsyncConnection) -> date:
    value = (
        await connection.execute(
            text("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")
        )
    ).scalar_one()
    if not isinstance(value, date):
        raise PartitionSafetyError("无法读取数据库 UTC 日期")
    return value


async def _verify_privileges(
    connection: AsyncConnection,
    names: Sequence[str],
    parent_owner: str,
    parent_acl: str,
) -> None:
    privileges = (
        await connection.execute(
            text(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS can_create, "
                "has_table_privilege(current_user, 'public.sdk_events', 'INSERT') AS can_insert"
            )
        )
    ).mappings().one()
    if not privileges["can_create"] or not privileges["can_insert"]:
        raise PartitionSafetyError("当前数据库角色没有创建分区所需的 ACL")
    for name in names:
        row = (
            await connection.execute(
                text(
                    "SELECT pg_get_userbyid(c.relowner) AS owner, "
                    "coalesce(c.relacl::text, '') AS acl, "
                    "has_table_privilege(current_user, :relation, 'INSERT') AS can_insert, "
                    "has_table_privilege(current_user, :relation, 'SELECT') AS can_select "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname=:name"
                ),
                {"relation": f"public.{name}", "name": name},
            )
        ).mappings().one()
        if (
            normalize_catalog_text(row["owner"]) != parent_owner
            or normalize_catalog_text(row["acl"]) != parent_acl
            or not row["can_insert"]
            or not row["can_select"]
        ):
            raise PartitionSafetyError(f"新分区 ACL 不完整: {name}")


async def _verify_indexes(
    connection: AsyncConnection,
    parent_oid: int,
    names: Sequence[str],
) -> dict[str, int]:
    table_names = ", ".join("'" + name.replace("'", "''") + "'" for name in names)
    parent_rows = (
        await connection.execute(
            text(
                "SELECT parent_index.relname "
                "FROM pg_class parent_index "
                "JOIN pg_index parent_definition "
                "ON parent_definition.indexrelid=parent_index.oid "
                "WHERE parent_definition.indrelid=:parent_oid"
            ),
            {"parent_oid": parent_oid},
        )
    ).scalars().all()
    parent_indexes = {normalize_catalog_text(value) for value in parent_rows}
    if not parent_indexes:
        raise PartitionSafetyError("sdk_events 没有可验证的父表索引")
    rows = (
        await connection.execute(
            text(
                "SELECT parent_index.relname AS parent_index, "
                "child_table.relname AS child_table, child_index.relname AS child_index, "
                "child_definition.indisvalid "
                "FROM pg_class parent_index "
                "JOIN pg_index parent_definition "
                "ON parent_definition.indexrelid=parent_index.oid "
                "JOIN pg_inherits index_inheritance "
                "ON index_inheritance.inhparent=parent_index.oid "
                "JOIN pg_class child_index "
                "ON child_index.oid=index_inheritance.inhrelid "
                "JOIN pg_index child_definition "
                "ON child_definition.indexrelid=child_index.oid "
                "JOIN pg_class child_table "
                "ON child_table.oid=child_definition.indrelid "
                "WHERE parent_definition.indrelid=:parent_oid "
                f"AND child_table.relname IN ({table_names})"
            ),
            {"parent_oid": parent_oid},
        )
    ).mappings().all()
    result: dict[str, int] = {name: 0 for name in names}
    for name in names:
        child_rows = [
            row for row in rows if normalize_catalog_text(row["child_table"]) == name
        ]
        actual = {
            normalize_catalog_text(row["parent_index"]): row for row in child_rows
        }
        if set(actual) != parent_indexes or any(
            not bool(row["indisvalid"]) for row in actual.values()
        ):
            raise PartitionSafetyError(f"{name} 的 parent-child 附属索引不完整或无效")
        result[name] = len(actual)
    return result


async def ensure_partitions(
    database_url: str,
    *,
    apply: bool,
    current_day: date | None = None,
) -> PartitionReport:
    engine = create_async_engine(
        database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=3,
        connect_args={
            "timeout": 10,
            "server_settings": {
                "statement_timeout": "10000",
                "lock_timeout": "3000",
                "timezone": "UTC",
            }
        },
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                if not apply:
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                await connection.execute(text("SET LOCAL lock_timeout='3s'"))
                await connection.execute(text("SET LOCAL statement_timeout='10s'"))
                actual_day = current_day or await _current_utc_day(connection)
                parent_oid, parent_owner, parent_acl, existing, owners, acls = await _read_catalog(
                    connection
                )
                del owners, acls
                plan = build_plan(actual_day, existing)
                created = tuple(name for name, _, _ in plan) if apply else ()
                verified = False

                if apply:
                    locked = bool(
                        (
                            await connection.execute(
                                text(
                                    "SELECT pg_try_advisory_xact_lock(" \
                                    "hashtextextended('sdk_events_partition_maintenance', 0))"
                                )
                            )
                        ).scalar_one()
                    )
                    if not locked:
                        raise PartitionSafetyError("分区维护 advisory lock 正忙")
                    after_lock_parent_oid, _, _, existing, _, _ = await _read_catalog(connection)
                    if after_lock_parent_oid != parent_oid:
                        raise PartitionSafetyError("advisory lock 后父表 OID 发生变化")
                    plan = build_plan(actual_day, existing)
                    created = tuple(name for name, _, _ in plan)
                    for name, start, end in plan:
                        await connection.execute(text(build_create_partition_sql(name, start, end)))

                    (
                        after_parent_oid,
                        after_parent_owner,
                        after_parent_acl,
                        after,
                        after_owners,
                        after_acls,
                    ) = await _read_catalog(connection)
                    if (
                        after_parent_oid != parent_oid
                        or after_parent_owner != parent_owner
                        or after_parent_acl != parent_acl
                        or any(acl != parent_acl for acl in after_acls.values())
                    ):
                        raise PartitionSafetyError("创建后父表或 ACL 基线发生变化")
                    expected_names = [
                        f"sdk_events_{month:%Y%m}" for month in target_months(actual_day)
                    ]
                    for month in target_months(actual_day):
                        name = f"sdk_events_{month:%Y%m}"
                        if after.get(name) != (month, _add_months(month, 1)):
                            raise PartitionSafetyError(f"创建后 bounds 校验失败: {name}")
                        if after_owners.get(name) != parent_owner:
                            raise PartitionSafetyError(f"创建后 owner 校验失败: {name}")
                    await _verify_privileges(connection, expected_names, parent_owner, parent_acl)
                    await _verify_indexes(connection, parent_oid, expected_names)
                    verified = True
                await transaction.commit()
                return PartitionReport(
                    current_month=_month_start(actual_day),
                    target_months=tuple(target_months(actual_day)),
                    missing=tuple(name for name, _, _ in plan),
                    created=created,
                    applied=apply,
                    verified=verified,
                    committed=apply,
                )
            except Exception:
                await transaction.rollback()
                raise
    finally:
        await engine.dispose()


def _database_url() -> str:
    try:
        from app.core.config import get_settings
    except ImportError as exc:
        raise SystemExit("需通过 PYTHONPATH 提供当前 release 的 backend settings") from exc
    return get_settings().resolved_database_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="创建缺失分区")
    parser.add_argument("--confirm")
    parser.add_argument("--as-of", type=date.fromisoformat, help="仅用于受控 dry-run 的 UTC 日期")
    args = parser.parse_args()
    if args.apply and args.as_of is not None:
        raise SystemExit("--apply 不能与 --as-of 同时使用")
    if args.apply and args.confirm != "ENSURE_SDK_EVENT_PARTITIONS":
        raise SystemExit("正式执行必须传入 --confirm ENSURE_SDK_EVENT_PARTITIONS")
    try:
        report = asyncio.run(
            ensure_partitions(_database_url(), apply=args.apply, current_day=args.as_of)
        )
    except Exception as exc:
        message = re.sub(r"(?i)(postgresql(?:\+\w+)?://)\S+", r"\1<redacted>", str(exc))
        message = re.sub(r"(?i)password\s*=\s*\S+", "password=<redacted>", message)
        print(f"分区维护失败: {type(exc).__name__}: {message[:500]}", file=sys.stderr)
        raise SystemExit(1) from None
    mode = "应用" if report.applied else "dry-run"
    print(f"{mode}: current_month={report.current_month.isoformat()}")
    print("targets=" + ",".join(month.isoformat() for month in report.target_months))
    print("missing=" + (",".join(report.missing) or "none"))
    print("created=" + (",".join(report.created) or "none"))
    print("verified=" + str(report.verified).lower())
    print("committed=" + str(report.committed).lower())


if __name__ == "__main__":
    main()
