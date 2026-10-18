import asyncio, hashlib, json
from pathlib import Path
import pytest

from import_prod_snapshot import DB_URL, ensure_empty_target, validate_database_url, validate_file

START = "2026-10-17T16:00:00Z"
END = "2026-10-18T14:58:52Z"

def write_snapshot(tmp_path: Path, rows: list[dict], suffix=".jsonl") -> tuple[Path, dict]:
    path = tmp_path / ("events" + suffix)
    path.write_text(json.dumps({"snapshot_start": START, "snapshot_end": END}) + "\n" + "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path, {"rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

def row(ts=END.replace("14:58:52", "14:00:00")):
    return {"id": 1, "server_ts": ts}

def test_rejects_partial_and_corrupt_hash(tmp_path):
    path, expected = write_snapshot(tmp_path, [row()], ".partial")
    with pytest.raises(RuntimeError, match="partial"):
        validate_file(path, expected, __import__("datetime").datetime.fromisoformat(START.replace("Z", "+00:00")), __import__("datetime").datetime.fromisoformat(END.replace("Z", "+00:00")))
    path, expected = write_snapshot(tmp_path, [row()])
    expected["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="hash"):
        validate_file(path, expected, __import__("datetime").datetime.fromisoformat(START.replace("Z", "+00:00")), __import__("datetime").datetime.fromisoformat(END.replace("Z", "+00:00")))

def test_rejects_out_of_range_and_row_limit(tmp_path):
    path, expected = write_snapshot(tmp_path, [row("2026-10-18T14:58:52Z")])
    with pytest.raises(RuntimeError, match="outside"):
        validate_file(path, expected, __import__("datetime").datetime.fromisoformat(START.replace("Z", "+00:00")), __import__("datetime").datetime.fromisoformat(END.replace("Z", "+00:00")))
    rows = [{"id": i, "server_ts": "2026-10-18T14:00:00Z"} for i in range(100001)]
    path, expected = write_snapshot(tmp_path, rows)
    with pytest.raises(RuntimeError, match="row limit"):
        validate_file(path, expected, __import__("datetime").datetime.fromisoformat(START.replace("Z", "+00:00")), __import__("datetime").datetime.fromisoformat(END.replace("Z", "+00:00")))

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
        asyncio.run(ensure_empty_target(FakeConn([{"relation": "sdk_events"}, {"relation": "sdk_usage_durations"}], [1])))
