"""Print controlled PostgreSQL plans for the selected log/usage candidates.

Only loopback databases named ``sdk_log_page_test_*`` are accepted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import asyncpg
from sqlalchemy.engine import make_url


def database_url() -> str:
    value = os.environ.get("SDK_LOG_PAGE_TEST_DATABASE_URL")
    if not value:
        raise SystemExit("SDK_LOG_PAGE_TEST_DATABASE_URL is required")
    parsed = make_url(value)
    if parsed.host not in {"127.0.0.1", "::1", "localhost"} or not re.fullmatch(r"sdk_log_page_test_[0-9a-f]{4,32}", parsed.database or ""):
        raise SystemExit("refusing non-loopback or non-sdk_log_page_test_* database")
    return value.replace("+asyncpg", "")


def relations(plan: dict) -> list[str]:
    found: list[str] = []
    if plan.get("Relation Name"):
        found.append(plan["Relation Name"])
    for child in plan.get("Plans", []):
        found.extend(relations(child))
    return sorted(set(found))


async def explain(conn, name: str, sql: str) -> dict[str, object]:
    raw = await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
    document = json.loads(raw) if isinstance(raw, str) else raw
    report = document[0]
    root = report["Plan"]
    return {
        "name": name,
        "planning_ms": report.get("Planning Time"),
        "execution_ms": report.get("Execution Time"),
        "relation_names": relations(root),
        "shared_hit_blocks": root.get("Shared Hit Blocks", 0),
        "shared_read_blocks": root.get("Shared Read Blocks", 0),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    conn = await asyncpg.connect(database_url())
    latest = """SELECT u.*, row_number() OVER (PARTITION BY u.package_name, u.device_id ORDER BY u.server_ts DESC, u.id DESC) AS latest_rank FROM sdk_usage_durations u WHERE u.server_ts >= '2026-09-18T00:00:00+00:00' AND u.server_ts < '2026-10-19T00:00:00+00:00'"""
    grouped = f"SELECT latest_rows.package_name, count(latest_rows.device_id) AS device_count, coalesce(sum(latest_rows.duration_s),0) AS total_duration_s, max(latest_rows.server_ts) AS last_report_at FROM ({latest}) latest_rows WHERE latest_rows.latest_rank=1 GROUP BY latest_rows.package_name"
    statements = {
        "raw_old_count": "SELECT count(*) FROM (SELECT id FROM sdk_events) q",
        "raw_old_page": "SELECT id, server_ts FROM sdk_events ORDER BY server_ts DESC LIMIT 20 OFFSET 0",
        "raw_window_candidate": "SELECT id, server_ts, count(*) OVER() AS total FROM sdk_events ORDER BY server_ts DESC LIMIT 20 OFFSET 0",
        "usage_old_count": f"SELECT count(*) FROM ({grouped}) grouped",
        "usage_old_page": f"SELECT * FROM ({grouped}) grouped ORDER BY package_name ASC LIMIT 20 OFFSET 0",
        "usage_window_candidate": f"SELECT grouped.*, count(*) OVER() AS total FROM ({grouped}) grouped ORDER BY package_name ASC LIMIT 20 OFFSET 0",
        "catalog_candidates": "SELECT package_name FROM sdk_package_catalog WHERE has_log IS TRUE ORDER BY package_name",
    }
    try:
        print(json.dumps([await explain(conn, name, sql) for name, sql in statements.items()], indent=2))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
