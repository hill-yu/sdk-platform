"""Single-connection read-only snapshot stream; also imported by local tests."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import asyncpg

ENV_FILE = "/www/releases/sdk-platform/current/backend/.env"
START = "2026-10-17T16:00:00Z"
END = "2026-10-18T14:58:52Z"
START_TS = datetime.fromisoformat(START.replace("Z", "+00:00"))
END_TS = datetime.fromisoformat(END.replace("Z", "+00:00"))
BATCH = 500


def env_value(name: str) -> str:
    with open(ENV_FILE, encoding="utf-8") as stream:
        for line in stream:
            if line.startswith(name + "="):
                return line.rstrip("\n").split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def db_url() -> str:
    raw = env_value("DATABASE_URL").replace("${DB_PASSWORD}", quote(env_value("DB_PASSWORD"), safe=""))
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


def json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(type(value).__name__)


def emit(message: dict) -> None:
    print(json.dumps(message, default=json_default, separators=(",", ":")), flush=True)


async def configure_json_codecs(conn) -> None:
    await conn.set_type_codec("json", schema="pg_catalog", encoder=json.dumps, decoder=json.loads)
    await conn.set_type_codec("jsonb", schema="pg_catalog", encoder=json.dumps, decoder=json.loads)


async def read_table(conn, table: str, emit_line=emit, batch_size: int = BATCH, delay_seconds: float = 0.25) -> dict:
    rows = 0
    last_id = 0
    last_ts = datetime(1970, 1, 1, tzinfo=timezone.utc)
    minimum = None
    maximum = None
    while True:
        if table == "events":
            sql = """SELECT id, server_ts, package_name, event_type, device_id, sdk_version, session_id, payload, client_ts
                     FROM sdk_events WHERE server_ts >= $1 AND server_ts < $2
                       AND (id > $3 OR (id = $3 AND server_ts > $4))
                     ORDER BY id, server_ts LIMIT $5"""
        elif table == "usage":
            sql = """SELECT id, server_ts, package_name, device_id, device_model, os, app_version, sdk_version, duration_s
                     FROM sdk_usage_durations WHERE server_ts >= $1 AND server_ts < $2
                       AND (server_ts > $4 OR (server_ts = $4 AND id > $3))
                     ORDER BY server_ts, id LIMIT $5"""
        else:
            raise ValueError("unsupported table")
        async with conn.transaction():
            await conn.execute("SET TRANSACTION READ ONLY")
            await conn.execute("SET LOCAL statement_timeout = '5s'")
            await conn.execute("SET LOCAL lock_timeout = '1s'")
            batch = await conn.fetch(sql, START_TS, END_TS, last_id, last_ts, batch_size)
        for record in batch:
            row = dict(record)
            current_ts = row["server_ts"]
            emit_line({"kind": "row", "table": table, "row": row})
            last_id = int(row["id"])
            last_ts = current_ts
            minimum = current_ts if minimum is None or current_ts < minimum else minimum
            maximum = current_ts if maximum is None or current_ts > maximum else maximum
            rows += 1
        if len(batch) < batch_size:
            result = {"kind": "table_complete", "table": table, "rows": rows, "min_ts": minimum, "max_ts": maximum}
            emit_line(result)
            return result
        await asyncio.sleep(delay_seconds)


async def run_stream(emit_line=emit) -> None:
    conn = await asyncpg.connect(db_url(), timeout=5)
    try:
        await configure_json_codecs(conn)
        events = await read_table(conn, "events", emit_line)
        usage = await read_table(conn, "usage", emit_line)
        emit_line({"kind": "complete", "snapshot_start": START, "snapshot_end": END, "tables": [events, usage]})
    finally:
        await conn.close()


async def main() -> int:
    phase = "connect"
    try:
        conn = await asyncpg.connect(db_url(), timeout=5)
        try:
            await configure_json_codecs(conn)
            phase = "events"
            events = await read_table(conn, "events")
            phase = "usage"
            usage = await read_table(conn, "usage")
            emit({"kind": "complete", "snapshot_start": START, "snapshot_end": END, "tables": [events, usage]})
        finally:
            await conn.close()
        return 0
    except Exception as exc:
        emit({"kind": "error", "phase": phase, "error": type(exc).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
