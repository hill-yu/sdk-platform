-- Read-only preflight for a one-day production snapshot.
-- Run through a single SSH session with psql; do not pass secrets on the command line.
-- The caller must provide DATABASE_URL/PGSERVICE through a protected environment.

BEGIN;
SET LOCAL TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '30s';
SET LOCAL TIME ZONE 'UTC';

SELECT 'window' AS section,
       '2026-10-17T16:00:00Z'::timestamptz AS start_utc,
       '2026-10-18T16:00:00Z'::timestamptz AS end_utc,
       now() AS snapshot_now_utc;

-- Exact schema, partitioning, indexes, estimated rows and relation sizes.
SELECT c.relname AS relation,
       c.reltuples::bigint AS estimated_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       CASE c.relkind WHEN 'p' THEN 'partitioned' WHEN 'r' THEN 'table' ELSE c.relkind::text END AS kind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
    'sdk_events', 'sdk_usage_durations', 'sdk_log_reparse_jobs',
    'sdk_log_decodes', 'sdk_log_h1_declarations', 'sdk_log_click_attempts',
    'sdk_log_h1_declaration_stage', 'sdk_log_click_attempt_stage',
    'sdk_configs', 'sdk_versions', 'sdk_package_profiles'
  )
ORDER BY c.relname;

SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'sdk_events', 'sdk_usage_durations', 'sdk_log_reparse_jobs',
    'sdk_log_decodes', 'sdk_log_h1_declarations', 'sdk_log_click_attempts',
    'sdk_log_h1_declaration_stage', 'sdk_log_click_attempt_stage',
    'sdk_configs', 'sdk_versions', 'sdk_package_profiles'
  )
ORDER BY table_name, ordinal_position;

SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN (
    'sdk_events', 'sdk_usage_durations', 'sdk_log_reparse_jobs',
    'sdk_log_decodes', 'sdk_log_h1_declarations', 'sdk_log_click_attempts',
    'sdk_log_h1_declaration_stage', 'sdk_log_click_attempt_stage',
    'sdk_configs', 'sdk_versions', 'sdk_package_profiles'
  )
ORDER BY tablename, indexname;

SELECT child.relname AS partition,
       pg_get_expr(child.relpartbound, child.oid) AS partition_bound,
       child.reltuples::bigint AS estimated_rows,
       pg_size_pretty(pg_total_relation_size(child.oid)) AS total_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = 'public' AND parent.relname = 'sdk_events'
ORDER BY child.relname;

SELECT pid, usename, application_name, client_addr, state,
       wait_event_type, wait_event, query_start,
       left(query, 160) AS query_preview
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
ORDER BY query_start NULLS LAST;

-- Planner-only checks. These must use server_ts/event_server_ts and must not run
-- COUNT(*) or EXPLAIN ANALYZE during the preflight.
EXPLAIN (FORMAT JSON)
SELECT id, server_ts, package_name, event_type, device_id, payload
FROM sdk_events
WHERE server_ts >= '2026-10-17T16:00:00Z'::timestamptz
  AND server_ts <  '2026-10-18T16:00:00Z'::timestamptz
ORDER BY server_ts, id
LIMIT 1000;

EXPLAIN (FORMAT JSON)
SELECT id, server_ts, package_name, device_id, duration_s, app_version, sdk_version
FROM sdk_usage_durations
WHERE server_ts >= '2026-10-17T16:00:00Z'::timestamptz
  AND server_ts <  '2026-10-18T16:00:00Z'::timestamptz
ORDER BY server_ts, id
LIMIT 1000;

EXPLAIN (FORMAT JSON)
SELECT id, package_name, range_start, range_end, snapshot_end, status,
       processed_count, failed_count, created_at, finished_at
FROM sdk_log_reparse_jobs
WHERE range_start < '2026-10-18T16:00:00Z'::timestamptz
  AND range_end >  '2026-10-17T16:00:00Z'::timestamptz
ORDER BY id
LIMIT 1000;

-- Stage/H1/click rows are intentionally not date-filtered by created_at here:
-- after job discovery, export the complete successful job context by job_id and
-- retain event_id + event_server_ts + record_index (+ attempt_index for clicks).
ROLLBACK;
