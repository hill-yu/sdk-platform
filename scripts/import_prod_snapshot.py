"""Import private JSONL snapshot files into a fresh local PostgreSQL database."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local-run"
EVENTS = PRIVATE / "prod-events-20261018.jsonl"
USAGE = PRIVATE / "prod-usage-20261018.jsonl"
DATABASE_URL = os.environ.get("LOCAL_SNAPSHOT_DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/sdk_prod_snapshot_20261018_001")


def rows(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if line.strip():
            yield json.loads(line)


async def main() -> None:
    if not EVENTS.exists() or not USAGE.exists():
        raise SystemExit("snapshot JSONL files are missing")
    event_rows = list(rows(EVENTS))
    usage_rows = list(rows(USAGE))
    if len(event_rows) > 100000 or len(usage_rows) > 100000:
        raise SystemExit("snapshot row limit exceeded")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.executemany(
                """INSERT INTO sdk_events
                (id, event_type, package_name, device_id, sdk_version, session_id, payload, client_ts, server_ts)
                VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::timestamptz,$9::timestamptz)""",
                [
                    (r["id"], r["event_type"], r["package_name"], r.get("device_id"), r.get("sdk_version"), r.get("session_id"), json.dumps(r["payload"], ensure_ascii=False), r.get("client_ts"), r["server_ts"])
                    for r in event_rows
                ],
            )
            await conn.executemany(
                """INSERT INTO sdk_usage_durations
                (id, package_name, device_id, device_model, os, app_version, sdk_version, duration_s, server_ts)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::timestamptz)""",
                [
                    (r["id"], r["package_name"], r["device_id"], r["device_model"], r["os"], r["app_version"], r["sdk_version"], r["duration_s"], r["server_ts"])
                    for r in usage_rows
                ],
            )
            for table in ("sdk_events", "sdk_usage_durations"):
                sequence = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'id')", table)
                if sequence:
                    max_id = await conn.fetchval(f"SELECT COALESCE(max(id),0) FROM {table}")
                    await conn.execute("SELECT setval($1::regclass, $2, $3)", sequence, max_id or 1, bool(max_id))
        checks = {}
        for table, timestamp in (("sdk_events", "server_ts"), ("sdk_usage_durations", "server_ts")):
            checks[table] = await conn.fetchrow(
                f"SELECT count(*) AS rows, min({timestamp}) AS min_ts, max({timestamp}) AS max_ts FROM {table}"
            )
        print(f"events={checks['sdk_events']['rows']} usage={checks['sdk_usage_durations']['rows']}")
        print(f"events_min={checks['sdk_events']['min_ts']} events_max={checks['sdk_events']['max_ts']}")
        print(f"usage_min={checks['sdk_usage_durations']['min_ts']} usage_max={checks['sdk_usage_durations']['max_ts']}")
        print("stage_rows=0 history_jobs=0 configs_imported=0 secrets_imported=0")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
