import asyncio, hashlib, json
from datetime import datetime
from pathlib import Path
import pytest

from import_prod_snapshot import DB_URL, ensure_empty_target, import_rows, validate_database_url, validate_file

START = "2026-10-17T16:00:00Z"
END = "2026-10-18T14:58:52Z"

def write_snapshot(tmp_path: Path, rows: list[dict], suffix=".jsonl") -> tuple[Path, dict]:
    path = tmp_path / ("events" + suffix)
    path.write_text(json.dumps({"table": "events", "snapshot_start": START, "snapshot_end": END}) + "\n" + "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    min_ts = min((item["server_ts"] for item in rows), default=None)
    max_ts = max((item["server_ts"] for item in rows), default=None)
    return path, {"table": "events", "rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "min_ts": min_ts, "max_ts": max_ts}

def row(ts=END.replace("14:58:52", "14:00:00")):
    return {"id": 1, "server_ts": ts}

def test_rejects_partial_and_corrupt_hash(tmp_path):
    path, expected = write_snapshot(tmp_path, [row()], ".partial")
    start, end = datetime.fromisoformat(START.replace("Z", "+00:00")), datetime.fromisoformat(END.replace("Z", "+00:00"))
    with pytest.raises(RuntimeError, match="partial"):
        validate_file(path, expected, start, end)
    path, expected = write_snapshot(tmp_path, [row()])
    expected["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="hash"):
        validate_file(path, expected, start, end)

def test_rejects_out_of_range_and_row_limit(tmp_path):
    path, expected = write_snapshot(tmp_path, [row("2026-10-18T14:58:52Z")])
    start, end = datetime.fromisoformat(START.replace("Z", "+00:00")), datetime.fromisoformat(END.replace("Z", "+00:00"))
    with pytest.raises(RuntimeError, match="outside"):
        validate_file(path, expected, start, end)
    rows = [{"id": i, "server_ts": "2026-10-18T14:00:00Z"} for i in range(100001)]
    path, expected = write_snapshot(tmp_path, rows)
    with pytest.raises(RuntimeError, match="row limit"):
        validate_file(path, expected, start, end)

def test_rejects_wrong_start_and_header_table(tmp_path):
    path, expected = write_snapshot(tmp_path, [row()])
    start, end = datetime.fromisoformat(START.replace("Z", "+00:00")), datetime.fromisoformat(END.replace("Z", "+00:00"))
    expected["table"] = "usage"
    with pytest.raises(RuntimeError, match="header range"):
        validate_file(path, expected, start, end)
    path.write_text(path.read_text(encoding="utf-8").replace(START, "2026-10-17T15:00:00Z"), encoding="utf-8")
    expected["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    expected["table"] = "events"
    with pytest.raises(RuntimeError, match="header range"):
        validate_file(path, expected, start, end)

def test_rejects_wrong_database():
    with pytest.raises(RuntimeError, match="approved localhost"):
        validate_database_url("postgresql://other-host/other-db")
    validate_database_url(DB_URL)

class FakeConn:
    def __init__(self, rows, counts): self.rows, self.counts = rows, iter(counts)
    async def fetch(self, *_): return self.rows
    async def fetchval(self, *_): return next(self.counts)

def test_rejects_nonempty_or_uninitialized_database():
    with pytest.raises(RuntimeError, match="schema"):
        asyncio.run(ensure_empty_target(FakeConn([{"relation": None}], [])))
    with pytest.raises(RuntimeError, match="not empty"):
        rows = [{"relation": "all"}] * 13
        asyncio.run(ensure_empty_target(FakeConn(rows, [0, 0, 0, 1])))

def test_real_local_import_fault_rolls_back_and_preserves_sequence():
    async def run():
        import asyncpg
        conn = await asyncpg.connect(DB_URL)
        event_ts = "2026-10-18T14:00:00Z"
        usage_ts = "2026-10-18T14:01:00Z"
        event_dt = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
        usage_dt = datetime.fromisoformat(usage_ts.replace("Z", "+00:00"))
        events = Path(__file__).parent / ".local-test-events.jsonl"
        usage = Path(__file__).parent / ".local-test-usage.jsonl"
        try:
            await ensure_empty_target(conn)
            events.write_text(json.dumps({"table": "events", "snapshot_start": START, "snapshot_end": END}) + "\n" + json.dumps({"id": 900001, "event_type": "test", "package_name": "com.example.test", "payload": {}, "server_ts": event_ts}) + "\n", encoding="utf-8")
            usage.write_text(json.dumps({"table": "usage", "snapshot_start": START, "snapshot_end": END}) + "\n" + json.dumps({"id": 900001, "package_name": "com.example.test", "device_id": "device", "device_model": "model", "os": "android", "app_version": "1", "sdk_version": "1", "duration_s": "fault", "server_ts": usage_ts}) + "\n", encoding="utf-8")
            files = {
                "events": {"rows": 1, "min_ts": event_ts, "max_ts": event_ts},
                "usage": {"rows": 1, "min_ts": usage_ts, "max_ts": usage_ts},
            }
            with pytest.raises(Exception):
                async with conn.transaction():
                    await import_rows(conn, events, usage, files)
            assert await conn.fetchval("SELECT count(*) FROM sdk_events") == 0
            assert await conn.fetchval("SELECT count(*) FROM sdk_usage_durations") == 0

            usage.write_text(json.dumps({"table": "usage", "snapshot_start": START, "snapshot_end": END}) + "\n" + json.dumps({"id": 900001, "package_name": "com.example.test", "device_id": "device", "device_model": "model", "os": "android", "app_version": "1", "sdk_version": "1", "duration_s": 1, "server_ts": usage_ts}) + "\n", encoding="utf-8")
            async with conn.transaction():
                await import_rows(conn, events, usage, files)
                assert await conn.fetchval("SELECT nextval(pg_get_serial_sequence('sdk_events','id'))") == 900002
                assert await conn.fetchval("SELECT nextval(pg_get_serial_sequence('sdk_usage_durations','id'))") == 900002
                assert await conn.fetchval("SELECT min(server_ts) FROM sdk_events") == event_dt
                raise RuntimeError("rollback test")
        except RuntimeError as exc:
            assert str(exc) == "rollback test"
            assert await conn.fetchval("SELECT count(*) FROM sdk_events") == 0
            assert await conn.fetchval("SELECT count(*) FROM sdk_usage_durations") == 0
        finally:
            events.unlink(missing_ok=True)
            usage.unlink(missing_ok=True)
            await conn.close()
    asyncio.run(run())
