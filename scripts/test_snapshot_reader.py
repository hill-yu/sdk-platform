import asyncio
from datetime import datetime, timezone

import asyncpg

from import_prod_snapshot import DB_URL, ensure_empty_target
from remote_snapshot_reader import configure_json_codecs, read_table


async def run():
    conn = await asyncpg.connect(DB_URL)
    event_id, usage_id = 990001, 990001
    event_ts = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
    usage_ts = datetime(2026, 10, 18, 14, 1, tzinfo=timezone.utc)
    messages = []
    try:
        await ensure_empty_target(conn)
        await configure_json_codecs(conn)
        await conn.execute("INSERT INTO sdk_events (id,event_type,package_name,payload,server_ts) VALUES ($1,'test','com.example.test',$2,$3)", event_id, {"nested": {"text": "中文"}}, event_ts)
        await conn.execute("INSERT INTO sdk_usage_durations (id,package_name,device_id,device_model,os,app_version,sdk_version,duration_s,server_ts) VALUES ($1,'com.example.test','device','model','android','1','1',1,$2)", usage_id, usage_ts)
        event_meta = await read_table(conn, "events", messages.append, batch_size=1, delay_seconds=0)
        usage_meta = await read_table(conn, "usage", messages.append, batch_size=1, delay_seconds=0)
        event_rows = [m["row"] for m in messages if m["kind"] == "row" and m["table"] == "events"]
        usage_rows = [m["row"] for m in messages if m["kind"] == "row" and m["table"] == "usage"]
        assert event_rows[0]["payload"] == {"nested": {"text": "中文"}}
        assert event_meta["rows"] == usage_meta["rows"] == 1
        assert event_meta["min_ts"] == event_meta["max_ts"] == event_ts
        assert usage_meta["min_ts"] == usage_meta["max_ts"] == usage_ts
    finally:
        await conn.execute("DELETE FROM sdk_events WHERE id=$1", event_id)
        await conn.execute("DELETE FROM sdk_usage_durations WHERE id=$1", usage_id)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
    print("snapshot reader local PostgreSQL fixture passed")
