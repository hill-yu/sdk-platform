BEGIN;
SET TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '1s';
SET LOCAL TIME ZONE 'UTC';

-- Fixed snapshot upper bound: 2026-10-18T14:58:52Z.
-- Events: compare the existing PK (id, server_ts) for first and later cursors.
EXPLAIN (FORMAT JSON)
SELECT id, server_ts, package_name, event_type, device_id, payload
FROM sdk_events
WHERE server_ts >= '2026-10-17T16:00:00Z'::timestamptz
  AND server_ts <  '2026-10-18T14:58:52Z'::timestamptz
  AND (id > 0 OR (id = 0 AND server_ts > '1970-01-01T00:00:00Z'::timestamptz))
ORDER BY id, server_ts
LIMIT 500;

EXPLAIN (FORMAT JSON)
SELECT id, server_ts, package_name, event_type, device_id, payload
FROM sdk_events
WHERE server_ts >= '2026-10-17T16:00:00Z'::timestamptz
  AND server_ts <  '2026-10-18T14:58:52Z'::timestamptz
  AND (id > 123456789 OR (id = 123456789 AND server_ts > '2026-10-18T10:00:00Z'::timestamptz))
ORDER BY id, server_ts
LIMIT 500;

-- Usage: compare the existing server_ts index for first and later cursors.
EXPLAIN (FORMAT JSON)
SELECT id, server_ts, package_name, device_id, duration_s, app_version, sdk_version
FROM sdk_usage_durations
WHERE server_ts >= '2026-10-17T16:00:00Z'::timestamptz
  AND server_ts <  '2026-10-18T14:58:52Z'::timestamptz
ORDER BY server_ts, id
LIMIT 500;

EXPLAIN (FORMAT JSON)
SELECT id, server_ts, package_name, device_id, duration_s, app_version, sdk_version
FROM sdk_usage_durations
WHERE server_ts >= '2026-10-17T16:00:00Z'::timestamptz
  AND server_ts <  '2026-10-18T14:58:52Z'::timestamptz
  AND (server_ts > '2026-10-18T10:00:00Z'::timestamptz
       OR (server_ts = '2026-10-18T10:00:00Z'::timestamptz AND id > 123456789))
ORDER BY server_ts, id
LIMIT 500;

ROLLBACK;
