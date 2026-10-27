# Log / Usage Performance Acceptance — 2026-10-27

## Implementation

- Worktree: `C:\Users\喻远飞\.codex\worktrees\ef23\SDK`
- Implementation HEAD: `1b3deb4de04a7d139ea138cae26c4ab7c9e43cce`
- Evidence-only follow-up HEAD: `5d3ca65bae22156d125f10156d6b4ad7c49fb38f`
- Previously merged master: `0732f4cdd5955b023bc7844408ed6bb71a2d7eb9`
- Production: unchanged; no deployment or further merge performed.
- `PACKAGE_CATALOG_READS_ENABLED=false` keeps the legacy fact-table package
  candidates; `true` reads the catalog. Catalog errors propagate and do not
  silently fall back.
- Shared SDK-version cache tasks own an independent session from
  `async_session_factory`; the request-scoped session is not retained after a
  cancelled waiter. The task closes its session in an async context manager.

## Real PostgreSQL acceptance

The local PostgreSQL 14.22 instance used `127.0.0.1:55432`. An isolated database,
`sdk_log_page_test_20261027`, was cloned from the approved local snapshot and
populated with the package catalog. No production connection was used.

Results:

- HTTP device pagination for `com.ly.sixthshort`: full-day total `1280`; page size `10`, pages 1–3 returned 10 rows each and 30 unique devices; page `128` returned 10 rows and contained `os`; page size `50` returned 50 rows.
- Edge-scope HTTP check (`2026-10-18`, Beijing hours `0–2`): total `284`; page size `20` last page `15` returned 4 rows, previous page returned 20, page size `50` returned 50, and a missing package returned total/items `0/0`.
- New vs baseline `79aef8cceac23682cee6bb7ee18e9dc991e6d5c3`: raw all/package/not-found/deep, summary all/package/short/31-day/empty/deep, and devices page-size-50 results were equal after ignoring the intentionally added `os` field.
- Filter-option gate tests cover both flag branches and the no-fallback catalog
  error path. Cancellation tests cover a cancelled first waiter, a later
  second waiter, independent session ownership, and session close.
- Real PostgreSQL integration: `test_usage_duration_postgres_integration.py` passed 1, and `test_package_catalog_postgres_integration.py` passed 1, using isolated loopback databases cloned from the local snapshot. The default no-URL run remains 2 skipped.

## Performance decision

Ten HTTP samples per case were collected against the same isolated snapshot.
Usage summary improved: all-package p50/p95 `216.39/264.51ms` to
`123.07/163.77ms`; package p50/p95 `46.19/66.03ms` to `23.98/41.51ms`.

The raw-log window-count candidate regressed on the same snapshot (all-package
p50/p95 `51.71/76.18ms` to `95.59/126.85ms`; package `5.81/7.25ms` to
`25.61/51.89ms`), so it was explicitly reverted and is not selected.

Representative `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on the same isolated
database: raw old count + page execution `5.98ms + 40.19ms`, raw window
candidate `18.85ms` (not selected); usage old count + page `77.82ms +
80.53ms`, usage window candidate `78.14ms` (selected).

## Reproduction commands

```powershell
& C:\pgsql\bin\pg_ctl.exe -D C:\Users\喻远飞\.codex\local-pg-admin-login-20261017-pgdata -w start -o "-p 55432"
$env:SDK_LOG_PAGE_TEST_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_log_page_test_20261027"
python scripts/benchmark_log_page_performance.py --iterations 10
$env:SDK_USAGE_DURATION_TEST_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_usage_duration_test_20261027"
python -m pytest backend/tests/test_usage_duration_postgres_integration.py -q
$env:SDK_PACKAGE_CATALOG_TEST_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_package_catalog_test_20261027"
python -m pytest backend/tests/test_package_catalog_postgres_integration.py -q
python -m pytest backend/tests -q
cd frontend; npm test -- --run; npm run build
& C:\pgsql\bin\pg_ctl.exe -D C:\Users\喻远飞\.codex\local-pg-admin-login-20261017-pgdata -w stop
```

The final local state was restored: the temporary PostgreSQL instance is stopped
and no `127.0.0.1:55432` listener remains. The evidence file contains no secret.
