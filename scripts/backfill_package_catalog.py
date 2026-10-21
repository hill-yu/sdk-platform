"""Backfill the package source directory in committed, resumable batches."""

from __future__ import annotations

import argparse
import asyncio
import os
from urllib.parse import quote_plus
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@dataclass(frozen=True)
class BackfillReport:
    source: str
    rows: int
    batches: int
    last_cursor: tuple[datetime, int] | None


def resolve_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL", "")
    if "${DB_PASSWORD}" in database_url:
        database_url = database_url.replace("${DB_PASSWORD}", quote_plus(os.environ.get("DB_PASSWORD", "")))
    return database_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="从受保护文件加载环境变量")
    parser.add_argument("--source", choices=("log", "usage"), required=True)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--statement-timeout-ms", type=int, default=5000)
    parser.add_argument("--resume-server-ts")
    parser.add_argument("--resume-id", type=int, default=0)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--apply", action="store_true", help="执行写入；默认仅输出预检信息")
    return parser


def load_env_file(path: Path | None) -> None:
    if path is None:
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_source_query(source: str, *, has_cursor: bool) -> str:
    if source == "log":
        source_condition = "event_type = 'log'"
        table = "sdk_events"
    elif source == "usage":
        source_condition = "TRUE"
        table = "sdk_usage_durations"
    else:
        raise ValueError("source 必须是 log 或 usage")
    cursor_condition = "AND (server_ts, id) > (:cursor_server_ts, :cursor_id)" if has_cursor else ""
    return f"""
        SELECT package_name, server_ts, id
        FROM {table}
        WHERE {source_condition}
          AND package_name IS NOT NULL
          AND package_name <> ''
          {cursor_condition}
        ORDER BY server_ts, id
        LIMIT :batch_size
    """


def advance_cursor(
    current: tuple[object, int] | None,
    candidate: tuple[object, int],
    *,
    committed: bool,
) -> tuple[object, int] | None:
    return candidate if committed else current


UPSERT_SQL = """
    INSERT INTO sdk_package_catalog (package_name, has_log, has_usage)
    SELECT name, :has_log, :has_usage
    FROM unnest(CAST(:package_names AS text[])) AS names(name)
    ON CONFLICT (package_name) DO UPDATE
    SET has_log = sdk_package_catalog.has_log OR EXCLUDED.has_log,
        has_usage = sdk_package_catalog.has_usage OR EXCLUDED.has_usage,
        updated_at = NOW()
    WHERE (sdk_package_catalog.has_log IS FALSE AND EXCLUDED.has_log IS TRUE)
       OR (sdk_package_catalog.has_usage IS FALSE AND EXCLUDED.has_usage IS TRUE)
"""


async def backfill_source(
    connection,
    source: str,
    *,
    batch_size: int,
    statement_timeout_ms: int,
    resume_cursor: tuple[datetime, int] | None = None,
    max_batches: int | None = None,
) -> BackfillReport:
    if batch_size < 1 or statement_timeout_ms < 1:
        raise ValueError("batch_size 和 statement_timeout_ms 必须为正数")
    cursor = resume_cursor
    total_rows = 0
    batches = 0
    while max_batches is None or batches < max_batches:
        query = text(build_source_query(source, has_cursor=cursor is not None))
        params = {"batch_size": batch_size}
        if cursor is not None:
            params.update({"cursor_server_ts": cursor[0], "cursor_id": cursor[1]})
        async with connection.begin():
            await connection.execute(text(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'"))
            rows = (await connection.execute(query, params)).mappings().all()
            if not rows:
                committed = True
                candidate = cursor
            else:
                names = sorted({str(row["package_name"]).strip() for row in rows if str(row["package_name"]).strip()})
                await connection.execute(
                    text(UPSERT_SQL),
                    {"package_names": names, "has_log": source == "log", "has_usage": source == "usage"},
                )
                candidate = (rows[-1]["server_ts"], int(rows[-1]["id"]))
                committed = True
        cursor = advance_cursor(cursor, candidate, committed=committed)
        if not rows:
            break
        total_rows += len(rows)
        batches += 1
    return BackfillReport(source=source, rows=total_rows, batches=batches, last_cursor=cursor)


async def run(args: argparse.Namespace) -> BackfillReport:
    load_env_file(args.env_file)
    database_url = resolve_database_url()
    if not database_url:
        raise RuntimeError("必须通过环境变量或 --env-file 设置 DATABASE_URL")
    if not args.apply:
        return BackfillReport(args.source, 0, 0, None)
    engine = create_async_engine(database_url)
    try:
        resume = None
        if args.resume_server_ts:
            resume = (datetime.fromisoformat(args.resume_server_ts), args.resume_id)
        async with engine.connect() as connection:
            return await backfill_source(
                connection,
                args.source,
                batch_size=args.batch_size,
                statement_timeout_ms=args.statement_timeout_ms,
                resume_cursor=resume,
                max_batches=args.max_batches,
            )
    finally:
        await engine.dispose()


def main() -> None:
    args = build_parser().parse_args()
    report = asyncio.run(run(args))
    print(f"source={report.source} rows={report.rows} batches={report.batches} last_cursor={report.last_cursor}")


if __name__ == "__main__":
    main()
