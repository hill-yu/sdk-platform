# 日志分析生产就绪修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。不要部署生产；实现完成后由主任务审查和发布。

**目标：** 修复 24 小时趋势时区类型、包资料部分更新和日志重解析任务闭环，使当前日志分析与批量导出集成分支达到可发布状态。

**架构：** PostgreSQL 以带时区小时桶提供趋势数据；包资料接口根据 Pydantic 实际提交字段做列级 upsert；新增有界重解析 worker，复用现有解码投影函数，以任务行锁、稳定游标和逐批事务驱动执行。数据库变更通过现有幂等迁移脚本完成。

**技术栈：** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2 async、PostgreSQL 16、pytest、Vue 3、Vitest、Vite。

---

## 文件结构

- 修改 `scripts/init_db.sql`：新安装时创建正确的小时视图、重解析筛选列和统一状态约束。
- 修改 `scripts/migrate_log_analysis.py`：识别旧小时列类型、缺失任务列和旧状态约束，生成幂等迁移。
- 修改 `backend/tests/test_log_analysis_migration.py`：覆盖迁移计划与无损校验。
- 修改 `backend/app/services/analysis_service.py`：保持带时区趋势时间的序列化路径。
- 修改 `backend/tests/test_analysis_service.py`：覆盖真实 PostgreSQL aware datetime 契约及 SQL 下界。
- 修改 `backend/app/schemas/log_analysis_schemas.py`：把包资料请求改成至少一个字段的部分更新请求。
- 修改 `backend/app/api/admin/log_analysis.py`：传递实际提交字段。
- 修改 `backend/app/services/log_analysis_service.py`：列级 upsert，并完整持久化重解析筛选条件。
- 修改 `backend/tests/test_log_analysis_service.py`、`backend/tests/test_admin_api.py`：覆盖字段保留、显式清空和请求校验。
- 修改 `backend/app/models/log_analysis.py`：增加重解析筛选字段，统一任务状态约束。
- 创建 `backend/app/services/log_reparse_service.py`：任务领取、筛选查询、单批重解析和状态推进。
- 创建 `backend/tests/test_log_reparse_service.py`：覆盖领取互斥、筛选、游标、计数、成功和失败。
- 修改 `backend/app/admin_main.py`、`backend/tests/test_log_parse_service.py`：启动和关闭重解析循环。
- 修改 `docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md`：记录部分更新和重解析任务真实行为。

### 任务 1：锁定基线并为小时趋势修复建立失败测试

**文件：**
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_log_analysis_migration.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_analysis.py`

- [ ] **步骤 1：运行当前基线测试并保存结果**

运行：

```powershell
Set-Location backend
python -m pytest -q
Set-Location ../frontend
npm test -- --run
npm run build
```

预期：后端 `231 passed`、前端 `112 passed`，构建成功。若计数因新增测试变化，以零失败为准，但必须记录实际计数。

- [ ] **步骤 2：编写能揭示旧小时列类型的失败测试**

在 `backend/tests/test_log_analysis_migration.py` 增加：

```python
def test_hourly_view_uses_timezone_aware_beijing_bucket():
    from scripts.migrate_log_analysis import HOURLY_VIEW_SQL

    assert "date_trunc('hour', server_ts, 'Asia/Shanghai')" in HOURLY_VIEW_SQL
    assert "server_ts AT TIME ZONE 'Asia/Shanghai'" not in HOURLY_VIEW_SQL


def test_old_naive_hour_view_is_rebuilt_without_recreating_log_tables():
    from scripts.migrate_log_analysis import build_migration_statements

    statements = build_migration_statements(
        existing_tables={
            "sdk_log_decodes",
            "sdk_package_profiles",
            "sdk_admin_preferences",
            "sdk_log_reparse_jobs",
        },
        existing_indexes={
            "idx_log_decodes_package_ts",
            "idx_log_decodes_status_ts",
            "idx_log_decodes_decoder_status",
            "idx_log_decodes_event_ts",
            "idx_package_profiles_updated",
            "idx_admin_preferences_updated",
            "idx_log_reparse_jobs_status",
            "idx_log_reparse_jobs_range",
        },
        view_summaries={
            "mv_daily_event_stats": "sha256:existing|tz:Asia/Shanghai",
            "mv_hourly_trend": "sha256:existing|tz:Asia/Shanghai",
        },
        existing_columns={
            "sdk_log_reparse_jobs": {"status_filter", "decoder_version_before"},
        },
        constraint_definitions={
            "chk_log_reparse_jobs_status": "CHECK ((status)::text = ANY ((ARRAY['pending', 'running', 'success', 'failed', 'cancelled'])::text[]))",
        },
        view_column_types={"mv_hourly_trend.hour": "timestamp without time zone"},
    )

    sql = "\n".join(statements)
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_hourly_trend" in sql
    assert "date_trunc('hour', server_ts, 'Asia/Shanghai')" in sql
    assert "CREATE TABLE" not in sql
```

在 `backend/tests/test_analysis_service.py` 增加 SQL 契约断言：

```python
@pytest.mark.asyncio
async def test_24_hour_trend_binds_an_aware_utc_lower_bound() -> None:
    db = _CapturingSession()
    await get_trend(db, range_value="24h")  # type: ignore[arg-type]
    assert db.params["start_time"].tzinfo is timezone.utc
```

- [ ] **步骤 3：运行目标测试，确认失败原因正确**

运行：

```powershell
Set-Location backend
python -m pytest tests/test_analysis_service.py tests/test_log_analysis_migration.py -q
```

预期：FAIL；旧 SQL 仍含 `AT TIME ZONE`，迁移函数尚不接受列/约束/视图类型快照。

- [ ] **步骤 4：实现最小小时视图与迁移修复**

在初始化 SQL 和迁移常量中统一使用：

```sql
CREATE MATERIALIZED VIEW mv_hourly_trend AS
SELECT
    date_trunc('hour', server_ts, 'Asia/Shanghai') AS hour,
    event_type,
    COUNT(*) AS event_count,
    COUNT(DISTINCT device_id) AS unique_devices
FROM sdk_events
GROUP BY 1, 2
```

扩展 `SchemaSnapshot` 和 `build_migration_statements()` 参数：

```python
@dataclass(frozen=True)
class SchemaSnapshot:
    total_count: int
    non_null_extra_count: int
    partition_counts: dict[str, int]
    existing_tables: set[str]
    existing_indexes: set[str]
    view_summaries: dict[str, str]
    existing_columns: dict[str, set[str]]
    constraint_definitions: dict[str, str]
    view_column_types: dict[str, str]
```

迁移计划只在小时列不是 `timestamp with time zone` 时重建小时视图：

```python
hourly_view_stale = (
    view_column_types.get("mv_hourly_trend.hour") != "timestamp with time zone"
)
if hourly_view_stale:
    statements.extend([
        "DROP MATERIALIZED VIEW IF EXISTS mv_hourly_trend",
        HOURLY_VIEW_SQL,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly ON mv_hourly_trend (hour, event_type)",
    ])
```

`read_snapshot()` 使用 `pg_attribute`/`pg_class` 查询物化视图列的 `format_type`，键名固定为 `mv_hourly_trend.hour`。保持原事件总数、非空 extra 和分区行数校验不变。

- [ ] **步骤 5：运行目标测试和格式检查**

运行：

```powershell
Set-Location backend
python -m pytest tests/test_analysis_service.py tests/test_log_analysis_migration.py -q
git diff --check
```

预期：全部 PASS，`git diff --check` 无输出。

- [ ] **步骤 6：提交小时趋势修复**

```powershell
git add scripts/init_db.sql scripts/migrate_log_analysis.py backend/tests/test_analysis_service.py backend/tests/test_log_analysis_migration.py
git commit -m "fix: preserve timezone in hourly trend"
```

### 任务 2：把包资料保存改为真正的部分更新

**文件：**
- 修改：`backend/app/schemas/log_analysis_schemas.py`
- 修改：`backend/app/api/admin/log_analysis.py`
- 修改：`backend/app/services/log_analysis_service.py`
- 修改：`backend/tests/test_log_analysis_service.py`
- 修改：`backend/tests/test_admin_api.py`
- 验证：`frontend/src/components/PackageProfileCell.test.ts`

- [ ] **步骤 1：编写失败的服务测试**

增加测试，编译 PostgreSQL upsert 并确认只更新提交列：

```python
def test_partial_profile_update_does_not_overwrite_omitted_fields():
    from app.services import log_analysis_service

    existing = SimpleNamespace(
        package_name="com.example.app",
        alias="Old",
        company="Keep Co",
        account="keep-account",
    )
    db = FakeDb(profile=existing)
    result = asyncio.run(
        log_analysis_service.upsert_package_profile(
            db,
            "com.example.app",
            updates={"alias": "New"},
        )
    )

    statement = next(item for item in db.statements if isinstance(item, Insert))
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "alias = excluded.alias" in compiled.lower()
    assert "company = excluded.company" not in compiled.lower()
    assert "account = excluded.account" not in compiled.lower()
    assert result == {
        "package_name": "com.example.app",
        "alias": "New",
        "company": "Keep Co",
        "account": "keep-account",
    }
```

增加 schema/API 测试：空对象返回 422、`{"alias": ""}` 被接受、未知字段返回 422。

- [ ] **步骤 2：运行目标测试确认旧全量覆盖行为失败**

```powershell
Set-Location backend
python -m pytest tests/test_log_analysis_service.py tests/test_admin_api.py -q
```

预期：FAIL；旧函数要求 alias/company/account 三个参数，并把缺失字段默认成空字符串。

- [ ] **步骤 3：实现请求模型的部分更新语义**

请求模型改为：

```python
class PackageProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    account: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_one_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提交一个包资料字段")
        return self
```

路由仅传递实际提交字段：

```python
updates = {
    field: getattr(payload, field)
    for field in payload.model_fields_set
}
data = await log_analysis_service.upsert_package_profile(
    db,
    normalized,
    updates=updates,
)
```

- [ ] **步骤 4：实现列级 upsert 和完整响应**

服务层验证键集合，只写入提交列：

```python
PROFILE_FIELDS = frozenset({"alias", "company", "account"})


async def upsert_package_profile(
    db: AsyncSession,
    package_name: str,
    *,
    updates: dict[str, str | None],
) -> dict[str, str]:
    normalized = normalize_package_name(package_name)
    unknown = set(updates) - PROFILE_FIELDS
    if unknown or not updates:
        raise ValueError("包资料更新字段无效")
    normalized_updates = {key: _profile_value(value) for key, value in updates.items()}
    statement = pg_insert(PackageProfile).values(
        package_name=normalized,
        **normalized_updates,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[PackageProfile.package_name],
            set_={key: getattr(statement.excluded, key) for key in normalized_updates},
        )
    )
    await db.flush()
    return await get_package_profile(db, normalized)
```

显式空字符串经 `_profile_value()` 变为 NULL，API 响应仍序列化为空字符串。

- [ ] **步骤 5：运行后端和前端目标测试**

```powershell
Set-Location backend
python -m pytest tests/test_log_analysis_service.py tests/test_admin_api.py -q
Set-Location ../frontend
npm test -- --run src/components/PackageProfileCell.test.ts src/views/LogViewer.test.ts
```

预期：全部 PASS；前端断言仍为单字段 payload。

- [ ] **步骤 6：提交部分更新修复**

```powershell
git add backend/app/schemas/log_analysis_schemas.py backend/app/api/admin/log_analysis.py backend/app/services/log_analysis_service.py backend/tests/test_log_analysis_service.py backend/tests/test_admin_api.py
git commit -m "fix: preserve omitted package profile fields"
```

### 任务 3：持久化重解析筛选条件并统一状态

**文件：**
- 修改：`backend/app/models/log_analysis.py`
- 修改：`backend/app/services/log_analysis_service.py`
- 修改：`backend/tests/test_log_analysis_service.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_analysis.py`
- 修改：`backend/tests/test_log_analysis_migration.py`

- [ ] **步骤 1：编写失败测试**

扩展创建任务测试：

```python
assert db.added[0].status_filter == "failed"
assert db.added[0].decoder_version_before == "1.2.3"
```

扩展迁移测试，断言现有表缺列和旧约束时生成：

```python
assert "ADD COLUMN IF NOT EXISTS status_filter VARCHAR(32)" in sql
assert "ADD COLUMN IF NOT EXISTS decoder_version_before VARCHAR(32)" in sql
assert "SET status = 'success' WHERE status = 'succeeded'" in sql
assert "CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))" in sql
```

- [ ] **步骤 2：运行测试确认失败**

```powershell
Set-Location backend
python -m pytest tests/test_log_analysis_service.py tests/test_log_analysis_migration.py -q
```

预期：FAIL；ORM 和表结构没有筛选列，约束仍使用 `succeeded`。

- [ ] **步骤 3：修改 ORM、新建 SQL 和创建任务逻辑**

`LogReparseJob` 增加：

```python
status_filter = Column(String(32))
decoder_version_before = Column(String(32))
```

模型增加与 SQL 一致的检查约束：

```python
CheckConstraint(
    "status IN ('pending', 'running', 'success', 'failed', 'cancelled')",
    name="chk_log_reparse_jobs_status",
)
```

创建任务时写入：

```python
status_filter=status,
decoder_version_before=decoder_version_before,
```

并在 API 创建响应中返回这两个字段。

- [ ] **步骤 4：实现幂等升级语句**

现有表缺列时分别追加：

```sql
ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS status_filter VARCHAR(32)
ALTER TABLE sdk_log_reparse_jobs ADD COLUMN IF NOT EXISTS decoder_version_before VARCHAR(32)
```

旧约束不是目标约束时按顺序追加：

```sql
UPDATE sdk_log_reparse_jobs SET status = 'success' WHERE status = 'succeeded'
ALTER TABLE sdk_log_reparse_jobs DROP CONSTRAINT IF EXISTS chk_log_reparse_jobs_status
ALTER TABLE sdk_log_reparse_jobs ADD CONSTRAINT chk_log_reparse_jobs_status CHECK (status IN ('pending', 'running', 'success', 'failed', 'cancelled'))
```

`read_snapshot()` 从 `information_schema.columns` 和 `pg_constraint` 读取现状；新安装的 `CREATE TABLE` 直接包含两列和新约束，不再生成 ALTER。

- [ ] **步骤 5：运行目标测试**

```powershell
Set-Location backend
python -m pytest tests/test_log_analysis_service.py tests/test_log_analysis_migration.py -q
```

预期：全部 PASS。

- [ ] **步骤 6：提交任务持久化修复**

```powershell
git add backend/app/models/log_analysis.py backend/app/services/log_analysis_service.py backend/tests/test_log_analysis_service.py scripts/init_db.sql scripts/migrate_log_analysis.py backend/tests/test_log_analysis_migration.py
git commit -m "fix: persist reparse job filters"
```

### 任务 4：实现有界重解析 worker

**文件：**
- 创建：`backend/app/services/log_reparse_service.py`
- 创建：`backend/tests/test_log_reparse_service.py`
- 修改：`backend/app/admin_main.py`
- 修改：`backend/tests/test_log_parse_service.py`

- [ ] **步骤 1：编写任务领取失败测试**

测试领取 SQL 包含互斥锁并把状态改为 running：

```python
def test_claim_pending_job_uses_skip_locked_and_marks_running():
    db = ReparseDb(job=make_job(status="pending"))
    job = asyncio.run(claim_pending_job(db))
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql
    assert job.status == "running"
```

- [ ] **步骤 2：编写批处理失败测试**

在测试文件定义确定性的 job/event 工厂：

```python
EVENT_TS = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)


def make_job(**overrides):
    values = {
        "id": 7,
        "package_name": "com.example.app",
        "range_start": EVENT_TS - timedelta(days=1),
        "range_end": EVENT_TS + timedelta(days=1),
        "status_filter": "failed",
        "decoder_version_before": "2.0.0",
        "cursor_server_ts": EVENT_TS,
        "cursor_event_id": 10,
        "processed_count": 0,
        "decoded_count": 0,
        "failed_count": 0,
        "status": "running",
        "error_summary": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_event(event_id: int, minute: int):
    return SimpleNamespace(
        id=event_id,
        server_ts=EVENT_TS + timedelta(minutes=minute),
        event_type="log",
        package_name="com.example.app",
        device_id=f"device-{event_id}",
        payload={"extra": "H1|test"},
    )
```

然后实现三个可执行测试：

```python
def test_build_query_applies_filters_and_stable_cursor():
    statement = build_reparse_event_query(make_job(), batch_size=50)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "sdk_events.server_ts >=" in sql
    assert "sdk_events.server_ts <" in sql
    assert "sdk_events.package_name =" in sql
    assert "EXISTS" in sql
    assert "split_part" in sql
    assert "sdk_events.server_ts >" in sql
    assert "sdk_events.id >" in sql
    assert "ORDER BY sdk_events.server_ts, sdk_events.id" in sql
    assert statement._limit_clause.value == 50


def test_batch_counts_success_and_unsupported_and_advances_cursor(monkeypatch):
    job = make_job(status_filter=None, decoder_version_before=None)
    first = make_event(11, 1)
    second = make_event(12, 2)
    db = BatchDb(job=job, events=[first, second])
    outcomes = iter([
        ("success", [{"event_id": 11, "event_server_ts": first.server_ts, "record_index": 0}]),
        ("unsupported", [{"event_id": 12, "event_server_ts": second.server_ts, "record_index": 0}]),
    ])

    async def fake_build(_event, *, decoder_version):
        assert decoder_version == DECODER_VERSION
        return next(outcomes)

    async def fake_upsert(_db, values):
        db.upserted.append(values)

    monkeypatch.setattr(reparse_service, "build_decoded_values", fake_build)
    monkeypatch.setattr(reparse_service, "upsert_decoded_values", fake_upsert)
    result = asyncio.run(reparse_service.process_reparse_job_batch(db, job.id))

    assert result.scanned == 2
    assert job.processed_count == 2
    assert job.decoded_count == 1
    assert job.failed_count == 1
    assert (job.cursor_server_ts, job.cursor_event_id) == (second.server_ts, 12)


def test_empty_batch_marks_job_success():
    job = make_job(cursor_server_ts=None, cursor_event_id=None)
    db = BatchDb(job=job, events=[])
    result = asyncio.run(reparse_service.process_reparse_job_batch(db, job.id))
    assert result.done is True
    assert job.status == "success"


def test_worker_failure_marks_job_failed_with_redacted_summary():
    secret = "postgres://admin:password@example.test/db RAW_EXTRA_SECRET"
    assert safe_job_error(RuntimeError(secret)) == "RuntimeError: reparse batch failed"
    job = make_job()
    asyncio.run(mark_reparse_job_failed(FailureDb(job), job.id, RuntimeError(secret)))
    assert job.status == "failed"
    assert secret not in job.error_summary
    assert "postgres://" not in job.error_summary
```

`BatchDb`/`FailureDb` fake session 必须实现 `execute()`、`flush()` 和 `begin_nested()`，按“查询 job、查询事件、删除旧记录”的固定顺序返回结果；它们只记录 SQL 和 upsert 值，不访问真实数据库。

测试文件内必须实现有确定返回顺序的 fake session；错误摘要断言不包含数据库 URL、原始 extra 或异常消息中的测试密钥。

- [ ] **步骤 3：运行新测试确认模块尚不存在**

```powershell
Set-Location backend
python -m pytest tests/test_log_reparse_service.py -q
```

预期：FAIL，`app.services.log_reparse_service` 不存在。

- [ ] **步骤 4：实现任务领取和查询构造**

新服务定义：

```python
REPARSE_BATCH_SIZE = 50
REPARSE_LOOP_INTERVAL_SECONDS = 1.0


async def claim_pending_job(db: AsyncSession) -> LogReparseJob | None:
    job = (
        await db.execute(
            select(LogReparseJob)
            .where(LogReparseJob.status == "pending")
            .order_by(LogReparseJob.created_at, LogReparseJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is not None:
        job.status = "running"
        job.error_summary = None
        await db.flush()
    return job
```

`build_reparse_event_query(job, batch_size=50)` 固定包含：

```python
conditions = [
    SdkEvent.event_type == "log",
    SdkEvent.server_ts >= job.range_start,
    SdkEvent.server_ts < job.range_end,
    text("jsonb_typeof(sdk_events.payload -> 'extra') = 'string'"),
]
```

按需追加 package、现有解析状态 `EXISTS`、三段整数版本 `EXISTS` 和 `(server_ts,id)` 游标条件；最终按 `server_ts,id` 升序、limit 最大 50。

- [ ] **步骤 5：实现单批处理和状态推进**

核心循环必须复用现有函数：

```python
status, values = await build_decoded_values(
    event,
    decoder_version=DECODER_VERSION,
)
await db.execute(
    delete(LogDecode).where(
        LogDecode.event_id == event.id,
        LogDecode.event_server_ts == event.server_ts,
    )
)
await upsert_decoded_values(db, values)
```

计数定义固定为：`processed_count` 统计所有处理事件，`decoded_count` 统计 status=success，`failed_count` 统计 failed 和 unsupported。每条事件使用 savepoint；批次完成后把游标更新到最后一条。空批次把任务置为 `success`。

失败摘要只保留异常类型和固定原因：

```python
def safe_job_error(error: BaseException) -> str:
    return f"{type(error).__name__}: reparse batch failed"[:512]
```

- [ ] **步骤 6：实现 worker 循环**

worker 每次使用新事务：先领取并提交，再循环处理已领取 job 的有界批次；每批提交，异常时新事务把任务置 failed。没有 pending job 时等待 1 秒。取消必须原样抛出 `asyncio.CancelledError`。

- [ ] **步骤 7：把 worker 接入 admin lifespan**

`admin_main.py` 新增 `reparse_job_loop()`，lifespan 创建 `reparse_task`；关闭时对 `(etl_task, parse_task, reparse_task)` 逐一 cancel 和 await。

扩展 lifespan 测试状态：

```python
started = {"etl": False, "parse": False, "reparse": False}
cancelled = {"etl": False, "parse": False, "reparse": False}
```

- [ ] **步骤 8：运行 worker 与生命周期测试**

```powershell
Set-Location backend
python -m pytest tests/test_log_reparse_service.py tests/test_log_parse_service.py tests/test_log_analysis_service.py -q
```

预期：全部 PASS；无挂起协程警告。

- [ ] **步骤 9：提交 worker 实现**

```powershell
git add backend/app/services/log_reparse_service.py backend/tests/test_log_reparse_service.py backend/app/admin_main.py backend/tests/test_log_parse_service.py
git commit -m "fix: execute queued log reparse jobs"
```

### 任务 5：文档、全量验证与执行窗口交接

**文件：**
- 修改：`docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md`

- [ ] **步骤 1：更新接口基线文档**

明确记录：

```text
PUT /api/admin/package-profiles/{package_name}
请求体至少包含 alias/company/account 中一个字段，只更新提交字段；空字符串表示清空。

POST /api/admin/log-analysis/reparse
创建有界异步任务；任务保存全部筛选条件，由 admin 后台 worker 分批执行。
任务状态：pending/running/success/failed/cancelled。
```

文档不得写入真实 token、密码、数据库连接串或原始日志内容。

- [ ] **步骤 2：运行后端全量测试**

```powershell
Set-Location backend
python -m pytest -q
```

预期：全部 PASS，无 error/failed。

- [ ] **步骤 3：运行前端全量测试与构建**

```powershell
Set-Location frontend
npm test -- --run
npm run build
```

预期：全部 PASS，构建成功；Vite chunk size warning 可记录但不得误报为失败。

- [ ] **步骤 4：执行静态差异检查**

```powershell
Set-Location ..
git diff --check
git status --short
git log --oneline --decorate -8
```

预期：`git diff --check` 无输出；除接口基线文档外无未提交修改。

- [ ] **步骤 5：提交文档并输出执行报告**

```powershell
git add docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md
git commit -m "docs: update log analysis production baseline"
```

执行报告必须列出：最终 commit、每个提交、后端测试结果、前端测试结果、构建结果、迁移计划摘要，以及所有已知 warning。不得推送、合并 master 或连接生产服务器。

## 主任务审查与生产发布清单

以下步骤由主任务执行，不属于执行窗口权限：

1. 对执行窗口最终 diff 逐文件审查三项规格覆盖和回归风险；
2. 在干净 worktree 重新运行后端全量测试、前端全量测试和构建；
3. 确认无 Critical/Important 后，把准确 commit 集成到发布分支；
4. 只读检查生产主机当前 commit、目录、systemd 单元、PostgreSQL 版本、数据库大小和磁盘余量；
5. 创建带北京时间戳的 PostgreSQL custom-format 备份，执行 `pg_restore --list` 校验；
6. 备份应用目录、前端 dist、环境文件和 systemd 单元，生成 SHA-256 清单；
7. 运行 `python scripts/migrate_log_analysis.py` dry-run，人工核对只包含预期列、约束和物化视图变更；
8. 使用 `--apply --confirm MIGRATE_LOG_ANALYSIS` 执行迁移并核对无损报告；
9. 部署准确 commit，重启 API/admin/导出 worker，检查服务状态和错误日志；
10. smoke 验证健康、鉴权、24h 趋势 `+08:00`、包资料单字段保留、小范围重解析成功、日志查询和批量导出；
11. 任一步失败则停止投入生产，恢复数据库与应用版本备份；全部通过后才宣布生产可用。
