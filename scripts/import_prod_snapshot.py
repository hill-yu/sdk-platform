"""Stream a complete private snapshot into the one approved local database."""
from __future__ import annotations

import asyncio, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
import asyncpg

ROOT = Path(__file__).resolve().parents[1]
DB_URL = "postgresql://postgres@127.0.0.1:55432/sdk_prod_snapshot_20261018_001"
MAX_ROWS = 100000
MAX_BYTES = 200 * 1024 * 1024
BATCH = 500
BUSINESS_TABLES = ("sdk_events", "sdk_usage_durations", "sdk_configs", "sdk_versions", "sdk_log_reparse_jobs", "sdk_log_decodes", "sdk_log_h1_declarations", "sdk_log_click_attempts", "sdk_log_h1_declaration_stage", "sdk_log_click_attempt_stage", "sdk_package_profiles", "sdk_admin_preferences", "sdk_log_export_jobs")

def validate_database_url(value: str) -> None:
    if value != DB_URL: raise RuntimeError("snapshot import database is not the approved localhost database")

async def ensure_empty_target(conn) -> None:
    tables = await conn.fetch("SELECT x, to_regclass(x) AS relation FROM unnest($1::text[]) AS x", [f"public.{table}" for table in BUSINESS_TABLES])
    if any(row["relation"] is None for row in tables): raise RuntimeError("local schema is not initialized")
    for table in BUSINESS_TABLES:
        if await conn.fetchval(f"SELECT count(*) FROM {table}"): raise RuntimeError(f"local target database is not empty: {table}")

def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

async def import_rows(conn, events_path: Path, usage_path: Path, files: dict) -> None:
    """Import both files and verify manifest counts/bounds before commit."""
    for path, table in ((events_path, "events"), (usage_path, "usage")):
        batch = []
        with path.open(encoding="utf-8") as stream:
            next(stream)
            for line in stream:
                row = json.loads(line)
                if table == "events":
                    batch.append((row["id"], row["event_type"], row["package_name"], row.get("device_id"), row.get("sdk_version"), row.get("session_id"), json.dumps(row["payload"], ensure_ascii=False), parse_ts(row["client_ts"]) if row.get("client_ts") else None, parse_ts(row["server_ts"])))
                    sql = "INSERT INTO sdk_events (id,event_type,package_name,device_id,sdk_version,session_id,payload,client_ts,server_ts) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::timestamptz,$9::timestamptz)"
                else:
                    batch.append((row["id"], row["package_name"], row["device_id"], row["device_model"], row["os"], row["app_version"], row["sdk_version"], row["duration_s"], parse_ts(row["server_ts"])))
                    sql = "INSERT INTO sdk_usage_durations (id,package_name,device_id,device_model,os,app_version,sdk_version,duration_s,server_ts) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::timestamptz)"
                if len(batch) == BATCH:
                    await conn.executemany(sql, batch)
                    batch = []
            if batch:
                await conn.executemany(sql, batch)
    for table in ("sdk_events", "sdk_usage_durations"):
        seq = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'id')", table)
        if seq:
            max_id = await conn.fetchval(f"SELECT COALESCE(max(id),0) FROM {table}")
            await conn.execute("SELECT setval($1::regclass,$2,$3)", seq, max_id or 1, bool(max_id))
    for table, expected in (("sdk_events", files["events"]), ("sdk_usage_durations", files["usage"])):
        check = await conn.fetchrow(f"SELECT count(*) AS rows, min(server_ts) AS min_ts, max(server_ts) AS max_ts FROM {table}")
        expected_min = parse_ts(expected["min_ts"]) if expected.get("min_ts") else None
        expected_max = parse_ts(expected["max_ts"]) if expected.get("max_ts") else None
        if int(check["rows"]) != int(expected["rows"]) or check["min_ts"] != expected_min or check["max_ts"] != expected_max:
            raise RuntimeError(f"post-import boundary mismatch: {table}")

def validate_file(path: Path, expected: dict, start: datetime, end: datetime) -> int:
    if path.name.endswith(".partial") or not path.exists(): raise RuntimeError("missing or partial snapshot file")
    if path.stat().st_size > MAX_BYTES: raise RuntimeError("snapshot file exceeds 200MB")
    if hashlib.sha256(path.read_bytes()).hexdigest().upper() != expected["sha256"].upper(): raise RuntimeError("snapshot hash mismatch")
    count = 0
    with path.open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        if header.get("table") != expected["table"] or header.get("snapshot_start") != start.isoformat().replace("+00:00", "Z") or header.get("snapshot_end") != end.isoformat().replace("+00:00", "Z"):
            raise RuntimeError("snapshot header range mismatch")
        for line in stream:
            row = json.loads(line); ts = parse_ts(row["server_ts"])
            if not (start <= ts < end): raise RuntimeError("row timestamp outside fixed snapshot")
            count += 1
            if count > MAX_ROWS: raise RuntimeError("snapshot row limit exceeded")
    if count != int(expected["rows"]): raise RuntimeError("manifest row count mismatch")
    return count

async def main() -> None:
    run_dir = Path(os.environ.get("LOCAL_SNAPSHOT_RUN_DIR", ""))
    if not run_dir.is_absolute(): raise SystemExit("LOCAL_SNAPSHOT_RUN_DIR must be an absolute private run directory")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists(): raise SystemExit("complete manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("complete") is not True: raise SystemExit("snapshot is not complete")
    if manifest.get("snapshot_start") != "2026-10-17T16:00:00Z" or manifest.get("snapshot_end") != "2026-10-18T14:58:52Z": raise SystemExit("snapshot bounds are not the approved fixed bounds")
    if any(p.name.endswith(".partial") for p in run_dir.iterdir()): raise SystemExit("partial snapshot file present")
    start, end = parse_ts(manifest["snapshot_start"]), parse_ts(manifest["snapshot_end"])
    manifest_tables = manifest.get("tables", [])
    if len(manifest_tables) != 2 or len({item.get("table") for item in manifest_tables}) != 2: raise SystemExit("manifest must contain exactly two unique tables")
    files = {item["table"]: item for item in manifest_tables}
    if set(files) != {"events", "usage"}: raise SystemExit("manifest table set is invalid")
    events_path, usage_path = run_dir / files["events"]["file"], run_dir / files["usage"]["file"]
    event_count = validate_file(events_path, files["events"], start, end); usage_count = validate_file(usage_path, files["usage"], start, end)
    if event_count + usage_count > 2 * MAX_ROWS or events_path.stat().st_size + usage_path.stat().st_size > MAX_BYTES: raise SystemExit("snapshot total limit exceeded")
    validate_database_url(os.environ.get("LOCAL_SNAPSHOT_DATABASE_URL", DB_URL))
    conn = await asyncpg.connect(DB_URL)
    try:
        async with conn.transaction():
            await ensure_empty_target(conn)
            await import_rows(conn, events_path, usage_path, files)
        for table in ("sdk_events", "sdk_usage_durations"):
            check = await conn.fetchrow(f"SELECT count(*) AS rows, min(server_ts) AS min_ts, max(server_ts) AS max_ts FROM {table}")
            print(f"{table} rows={check['rows']} min={check['min_ts']} max={check['max_ts']}")
        print("stage_rows=0 history_jobs=0 configs_imported=0 secrets_imported=0")
    finally: await conn.close()

if __name__ == "__main__": asyncio.run(main())
