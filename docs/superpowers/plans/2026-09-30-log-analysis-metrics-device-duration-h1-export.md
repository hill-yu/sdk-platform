# 日志解析指标、设备时长与 H1 导出实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将日志解析改为管理员显式创建的后置任务，正确拆分并结构化保存所有 H1 与 `pa`，提供按 `config_id` 的统计、设备时长汇总，以及不会漏日志的 H1 混合 CSV 导出。

**架构：** 原始日志接口只写 `sdk_events`。独立 worker 按 UTC+8 范围读取任务快照，将 H1 声明和点击明细写入任务暂存表，任务成功后原子替换正式表；统计 API 只读正式表。设备时长从 `sdk_usage_durations` 为每台设备选取范围内最新记录后聚合，H1 导出直接复用纯文本拆分器，不依赖解析任务。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.x async、PostgreSQL 16、Vue 3、TypeScript、Axios、Pytest、Vitest、systemd、宝塔 Nginx。

---

## 0. 文件结构与职责

### 后端新增

- `backend/app/models/log_metrics.py`：正式 H1、正式点击、H1 暂存、点击暂存 ORM。
- `backend/app/services/h1_extractor.py`：无 I/O 的 H1 边界识别与导出抽取。
- `backend/app/services/log_parse_job_service.py`：任务创建、领取、分批暂存、取消、续跑、原子发布。
- `backend/app/services/log_metrics_service.py`：总体指标、`config_id` 明细、失败原因和 H1 下钻查询。
- `backend/app/workers/log_parse_worker.py`：独立 worker 入口，不承载业务 SQL。
- `backend/app/api/admin/log_metrics.py`：解析任务和指标 Admin API。
- `backend/app/schemas/log_metrics_schemas.py`：严格请求模型与任务状态类型。
- `scripts/migrate_log_metrics_v2.sql`：生产幂等迁移。
- `deploy/systemd/sdk-log-parse-worker.service`：独立解析 worker 服务单元。
- `backend/tests/test_h1_extractor.py`、`test_log_metrics_migration.py`、`test_log_parse_job_service_v2.py`、`test_log_metrics_service_v2.py`、`test_log_metrics_api_v2.py`：新增能力测试。
- `backend/tests/test_usage_duration_summary.py`、`test_h1_export.py`：时长与导出测试。

### 后端修改

- `backend/app/services/flow_log_decoder.py`：消费拆分后的单条 H1，升级解析器版本。
- `backend/app/api/sdk/log.py`：去掉 pending 解析占位写入。
- `backend/app/models/log_analysis.py`：扩展现有 `sdk_log_reparse_jobs` 为统一显式任务模型。
- `backend/app/models/log_export_job.py`：增加 `export_mode`。
- `backend/app/models/__init__.py`：导出新 ORM。
- `backend/app/services/log_export_service.py`：H1 混合 CSV 行生成。
- `backend/app/services/usage_duration_service.py`：每设备最新值和包名/机型汇总。
- `backend/app/api/admin/usage_duration.py`：新增 summary/devices 路由。
- `backend/app/admin_main.py`：停止内嵌默认解析和重解析循环，注册指标路由。
- `backend/app/core/config.py`：worker 批量、并发、租约配置与范围限制。
- `scripts/init_db.sql`、`scripts/migrate_log_analysis.py`：新安装和旧生产迁移保持一致。

### 前端新增

- `frontend/src/api/logMetrics.ts`：指标与任务 API 类型。
- `frontend/src/api/usageDurations.ts`：时长汇总与设备明细 API。
- `frontend/src/components/LogParseTaskPanel.vue`：范围、任务创建和进度。
- `frontend/src/components/LogMetricsPanel.vue`：总体指标、config_id 表和维度切换。
- `frontend/src/components/LogFailureDrawer.vue`：失败原因下钻。
- `frontend/src/components/UsageDurationPanel.vue`：设备时长汇总和展开明细。
- 对应 `.test.ts` 文件：组件交互和参数测试。

### 前端修改

- `frontend/src/views/LogViewer.vue`：三个页签、默认近 3 天、组合新组件。
- `frontend/src/components/LogAnalysisFilters.vue`：增加开始/结束小时并强制包名用于解析任务。
- `frontend/src/components/LogExportPanel.vue`：增加原始日志/H1 数据模式。
- `frontend/src/api/logExports.ts`：增加 `export_mode`。
- 新增组件使用各自的 scoped style 实现大表内部滚动；复用 `frontend/src/styles/variables.css` 已有变量，不修改全局视觉主题。

## 1. 先建立 H1 边界识别的纯函数

**文件：**
- 创建：`backend/app/services/h1_extractor.py`
- 创建：`backend/tests/test_h1_extractor.py`
- 修改：`backend/app/services/flow_log_decoder.py`
- 修改：`backend/tests/test_flow_log_decoder.py`

- [x] **步骤 1：编写拆分器失败测试**

测试必须覆盖单条、`||H1|`、CRLF/LF、字段普通 `||`、无 H1 和任意数量：

```python
from app.services.h1_extractor import extract_h1_records


def test_extracts_every_h1_without_splitting_plain_double_pipes():
    extra = "prefix||not-a-record\nH1|t=one|p=1||H1|t=two|p=2\r\nH1|t=three|p=3"
    assert extract_h1_records(extra) == [
        "H1|t=one|p=1",
        "H1|t=two|p=2",
        "H1|t=three|p=3",
    ]


def test_no_h1_returns_empty_list():
    assert extract_h1_records("ordinary raw log||still raw") == []
```

- [x] **步骤 2：运行测试确认失败**

运行：

```powershell
cd backend
python -m pytest tests/test_h1_extractor.py -q
```

预期：收集失败，`app.services.h1_extractor` 不存在。

- [x] **步骤 3：实现最小纯函数**

创建：

```python
H1_BOUNDARY = re.compile(r"(?:^|\|\||\r?\n)(H1\|)")


def extract_h1_records(extra: str) -> list[str]:
    if not isinstance(extra, str):
        raise TypeError("extra 必须是字符串")
    starts = [match.start(1) for match in H1_BOUNDARY.finditer(extra)]
    records: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(extra)
        record = extra[start:end].rstrip("|\r\n")
        if record.startswith("H1|"):
            records.append(record)
    return records
```

保持此模块无数据库、网络和 FastAPI 依赖。

- [x] **步骤 4：让解析器逐条消费 H1**

将 `DECODER_VERSION` 升级为 `2.0.0`，`decode_extra()` 调用 `extract_h1_records()`，对每条记录调用 `parse_host_final_result_line()`；非 H1 的旧 L/S 协议继续走现有 `decode_text()`，不得破坏旧测试。

新增回归断言：两个 H1 的 `config_id` 分别存在，前一条不会被后一条覆盖。

- [x] **步骤 5：运行解析测试**

```powershell
python -m pytest tests/test_h1_extractor.py tests/test_flow_log_decoder.py -q
```

预期：全部通过。

- [x] **步骤 6：提交**

```powershell
git add backend/app/services/h1_extractor.py backend/app/services/flow_log_decoder.py backend/tests/test_h1_extractor.py backend/tests/test_flow_log_decoder.py
git commit -m "fix: split every H1 log declaration"
```

## 2. 建立结构化正式表、暂存表和任务字段

**文件：**
- 创建：`backend/app/models/log_metrics.py`
- 创建：`scripts/migrate_log_metrics_v2.sql`
- 创建：`backend/tests/test_log_metrics_migration.py`
- 修改：`backend/app/models/log_analysis.py`
- 修改：`backend/app/models/__init__.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_analysis.py`

- [x] **步骤 1：编写 ORM 和迁移失败测试**

断言四张表、复合唯一键、必要索引和任务字段：

```python
def test_h1_and_click_tables_expose_required_business_keys():
    h1 = inspect(H1Declaration).local_table
    click = inspect(LogClickAttempt).local_table
    assert {"event_id", "event_server_ts", "record_index", "config_id", "declared_click_count"} <= set(h1.c.keys())
    assert {"attempt_index", "target_kind", "did_click", "navigation_code", "failure_category"} <= set(click.c.keys())


def test_task_model_contains_snapshot_and_progress_fields():
    columns = inspect(LogReparseJob).columns
    required = {"snapshot_end", "total_count", "h1_count", "failed_h1_count", "no_h1_count", "batch_size", "concurrency", "cancel_requested_at"}
    assert required <= set(columns.keys())
```

迁移测试读取 `migrate_log_metrics_v2.sql`，断言所有 `CREATE TABLE IF NOT EXISTS`、`ADD COLUMN IF NOT EXISTS` 和索引均幂等。

- [x] **步骤 2：运行确认失败**

```powershell
cd backend
python -m pytest tests/test_log_metrics_migration.py -q
```

预期：新模型/表不存在。

- [x] **步骤 3：实现 ORM**

创建以下类：

```python
class H1Declaration(Base): ...
class LogClickAttempt(Base): ...
class H1DeclarationStage(Base): ...
class LogClickAttemptStage(Base): ...
```

正式 H1 业务键为 `(event_id, event_server_ts, record_index)`；点击键在此基础上增加 `attempt_index`。暂存键前置 `job_id`。`config_id` 使用 `Integer` 可空，缺失值由查询层归入“未知”。

- [x] **步骤 4：扩展统一任务模型**

保留表名 `sdk_log_reparse_jobs` 和兼容路由；新增：

```python
snapshot_end = Column(DateTime(timezone=True), nullable=False)
total_count = Column(BigInteger, nullable=False, default=0)
h1_count = Column(BigInteger, nullable=False, default=0)
failed_h1_count = Column(BigInteger, nullable=False, default=0)
no_h1_count = Column(BigInteger, nullable=False, default=0)
batch_size = Column(Integer, nullable=False, default=200)
concurrency = Column(Integer, nullable=False, default=3)
started_at = Column(DateTime(timezone=True))
finished_at = Column(DateTime(timezone=True))
last_heartbeat_at = Column(DateTime(timezone=True))
cancel_requested_at = Column(DateTime(timezone=True))
```

状态保持 `pending/running/success/failed/cancelled`，避免无必要枚举迁移。

- [x] **步骤 5：同步初始化 SQL 和生产迁移**

`init_db.sql` 与 `migrate_log_metrics_v2.sql` 使用完全一致的字段、约束和索引。`migrate_log_analysis.py` 的无损验证把新表加入后置条件，但不得把旧表不存在误判为可删除历史数据。

- [x] **步骤 6：运行迁移测试**

```powershell
python -m pytest tests/test_log_metrics_migration.py tests/test_log_analysis_migration.py -q
```

预期：全部通过。

- [x] **步骤 7：提交**

```powershell
git add backend/app/models/log_metrics.py backend/app/models/log_analysis.py backend/app/models/__init__.py scripts/init_db.sql scripts/migrate_log_analysis.py scripts/migrate_log_metrics_v2.sql backend/tests/test_log_metrics_migration.py
git commit -m "feat: add structured H1 metric storage"
```

## 3. 停止日志上报后的自动解析

**文件：**
- 修改：`backend/app/api/sdk/log.py`
- 修改：`backend/app/admin_main.py`
- 修改：`backend/tests/test_log_parse_service.py`
- 修改：`backend/tests/test_sdk_api.py`

- [x] **步骤 1：先写行为测试**

测试一次日志上报只插入 `SdkEvent`，不导入/写入 `LogDecode`；Admin lifespan 只启动 ETL，不启动 `pending_log_parse_loop` 或 `reparse_job_loop`。

核心断言：

```python
assert response.status_code == 200
assert len(event_inserts) == 1
assert decode_inserts == []
assert started == {"etl": True, "parse": False, "reparse": False}
```

- [x] **步骤 2：运行确认旧行为导致失败**

```powershell
python -m pytest tests/test_log_parse_service.py tests/test_sdk_api.py -q
```

预期：测试显示当前仍写 pending 并启动两个解析循环。

- [x] **步骤 3：删除写链路耦合**

`report_log()` 保留批量 `SdkEvent` 插入和返回键完整性校验，删除 `LogDecode`、`DECODER_VERSION`、pending_values 相关代码。写入失败仍整批回滚，解析状态不参与响应。

- [x] **步骤 4：删除 Admin 内嵌解析循环**

`admin_main.py` 移除两个解析任务，只保留 `etl_refresh_loop()`。不要在 Admin 进程中启动新 worker。

- [x] **步骤 5：运行回归测试并提交**

```powershell
python -m pytest tests/test_log_parse_service.py tests/test_sdk_api.py -q
git add backend/app/api/sdk/log.py backend/app/admin_main.py backend/tests/test_log_parse_service.py backend/tests/test_sdk_api.py
git commit -m "refactor: defer log parsing to explicit jobs"
```

预期：测试全部通过。

## 4. 实现严格的解析任务请求、默认范围和 API

**文件：**
- 创建：`backend/app/schemas/log_metrics_schemas.py`
- 创建：`backend/app/api/admin/log_metrics.py`
- 创建：`backend/tests/test_log_metrics_api_v2.py`
- 修改：`backend/app/admin_main.py`
- 修改：`backend/app/core/timezone.py`
- 修改：`backend/app/core/config.py`

- [x] **步骤 1：编写请求校验失败测试**

请求体：

```python
class LogParseJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_name: str = Field(min_length=1, max_length=255)
    date_from: date
    hour_from: int = Field(ge=0, le=23)
    date_to: date
    hour_to: int = Field(ge=0, le=23)
```

测试包名规范化、同日倒序、跨日连续范围、最大 7 天、额外字段拒绝；默认近 3 天只由前端填入，后端创建任务仍要求显式完整范围。

- [x] **步骤 2：编写任务 API 路由测试**

```text
POST /api/admin/log-analysis/parse-jobs
GET  /api/admin/log-analysis/parse-jobs/{id}
POST /api/admin/log-analysis/parse-jobs/{id}/cancel
GET  /api/admin/log-analysis/coverage
```

断言 Admin Token、统一 envelope、409 活跃任务冲突、404 不存在任务、取消终态幂等。

- [x] **步骤 3：运行确认失败**

```powershell
python -m pytest tests/test_log_metrics_api_v2.py -q
```

- [x] **步骤 4：实现统一 UTC+8 小时边界**

在 `core/timezone.py` 添加并复用：

```python
def business_hour_utc_range(date_from: date, hour_from: int, date_to: date, hour_to: int) -> tuple[datetime, datetime]:
    start = datetime.combine(date_from, time(hour_from), BUSINESS_TIMEZONE)
    end = datetime.combine(date_to, time(hour_to), BUSINESS_TIMEZONE) + timedelta(hours=1)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
```

跨度按真实连续区间校验不超过 7 天。

- [x] **步骤 5：实现 API 壳和配置**

配置：`LOG_PARSE_BATCH_SIZE=200`、`LOG_PARSE_CONCURRENCY=3`、`LOG_PARSE_MAX_DAYS=7`、`LOG_PARSE_LEASE_SECONDS=60`，并限制并发 `1..3`。

API 调用下一任务服务，不在请求内执行解析。

- [x] **步骤 6：运行测试并提交**

```powershell
python -m pytest tests/test_log_metrics_api_v2.py tests/test_timezone.py -q
git add backend/app/schemas/log_metrics_schemas.py backend/app/api/admin/log_metrics.py backend/app/admin_main.py backend/app/core/timezone.py backend/app/core/config.py backend/tests/test_log_metrics_api_v2.py backend/tests/test_timezone.py
git commit -m "feat: add explicit log parse job APIs"
```

## 5. 实现任务创建、快照和全局单任务约束

**文件：**
- 创建：`backend/app/services/log_parse_job_service.py`
- 创建：`backend/tests/test_log_parse_job_service_v2.py`

- [x] **步骤 1：编写创建任务失败测试**

断言：

- `snapshot_end=min(range_end, now)`；
- `total_count` 只计算快照内 `event_type=log`、包名和时间匹配的事件；
- 任何 `pending/running` 任务存在时返回领域冲突；
- 创建时固化批量 200、并发 3；
- 初始游标为空、计数为 0。

- [x] **步骤 2：运行确认失败**

```powershell
python -m pytest tests/test_log_parse_job_service_v2.py -q
```

- [x] **步骤 3：实现创建与序列化**

定义：

```python
async def create_parse_job(db: AsyncSession, *, package_name: str, range_start: datetime, range_end: datetime, now: datetime) -> LogReparseJob: ...
async def get_parse_job(db: AsyncSession, job_id: int) -> LogReparseJob | None: ...
async def request_cancel(db: AsyncSession, job_id: int) -> LogReparseJob: ...
def serialize_parse_job(job: LogReparseJob) -> dict[str, object]: ...
```

创建操作使用事务级 advisory lock 或锁定活跃任务集合，防止并发请求同时创建两个任务；不能只先查再插。

- [x] **步骤 4：接入路由并验证**

```powershell
python -m pytest tests/test_log_parse_job_service_v2.py tests/test_log_metrics_api_v2.py -q
```

- [x] **步骤 5：提交**

```powershell
git add backend/app/services/log_parse_job_service.py backend/app/api/admin/log_metrics.py backend/tests/test_log_parse_job_service_v2.py backend/tests/test_log_metrics_api_v2.py
git commit -m "feat: create bounded log parse jobs"
```

## 6. 实现分批解析、暂存、续跑和原子发布

**文件：**
- 修改：`backend/app/services/log_parse_job_service.py`
- 创建：`backend/app/workers/log_parse_worker.py`
- 修改：`backend/tests/test_log_parse_job_service_v2.py`
- 创建：`backend/tests/test_log_parse_worker.py`

- [x] **步骤 1：编写批次和事实映射测试**

测试输入一个原始事件，`extra` 含两条 H1 和多个 `pa`；断言生成 2 条 H1 暂存行、正确数量点击行，以及：

```python
assert h1_rows[0]["declared_click_count"] == 2
assert click_rows[0]["did_click"] is True
assert click_rows[0]["navigation_code"] == 1
assert click_rows[0]["failure_category"] is None
```

失败分类测试顺序：`reason` 优先，其次 `error_detail`，再次 `navigation_result`，最后“未知原因”。

- [x] **步骤 2：编写续跑与发布测试**

覆盖：每批 200、`(server_ts,id)` 游标、批次独立提交、租约丢失、取消、连续 10 条超时、处理至少 100 条后失败率超过 20%、服务重启继续、成功后单事务替换、失败不修改正式表。

- [x] **步骤 3：运行确认失败**

```powershell
python -m pytest tests/test_log_parse_job_service_v2.py tests/test_log_parse_worker.py -q
```

- [x] **步骤 4：实现纯映射函数**

```python
def build_h1_and_click_rows(event: SdkEvent, job_id: int) -> tuple[list[dict], list[dict], int]: ...
def choose_failure_category(attempt: dict[str, object]) -> str | None: ...
```

`navigation_code=1` 时 `failure_category=None`。H1 无点击明细时仍保存声明。

- [x] **步骤 5：实现任务领取和批次执行**

使用 `FOR UPDATE SKIP LOCKED` 领取任务和稳定游标读取事件。解析进程只接收可序列化的事件快照；主进程负责数据库写入。每批对同一 `job_id` + 业务键使用幂等 upsert。

- [x] **步骤 6：实现原子发布**

发布事务严格按以下范围删除：

```text
package_name = job.package_name
range_start <= event_server_ts < snapshot_end
```

先删除正式点击，再删除正式 H1；再从暂存插入正式 H1 和点击；最后任务置 `success`。任何异常整笔回滚。

- [x] **步骤 7：实现 worker 循环**

`python -m app.workers.log_parse_worker` 每次领取一个任务；有任务时连续处理，无任务时等待 1 秒。捕获 SIGTERM，在当前批次提交后退出，不强杀事务。

- [x] **步骤 8：运行测试并提交**

```powershell
python -m pytest tests/test_log_parse_job_service_v2.py tests/test_log_parse_worker.py -q
git add backend/app/services/log_parse_job_service.py backend/app/workers/log_parse_worker.py backend/tests/test_log_parse_job_service_v2.py backend/tests/test_log_parse_worker.py
git commit -m "feat: parse logs through resumable staging jobs"
```

## 7. 实现结构化统计查询与下钻 API

**文件：**
- 创建：`backend/app/services/log_metrics_service.py`
- 修改：`backend/app/api/admin/log_metrics.py`
- 创建：`backend/tests/test_log_metrics_service_v2.py`
- 修改：`backend/tests/test_log_metrics_api_v2.py`

- [x] **步骤 1：编写总体指标测试**

构造 H1/点击样本，验证：声明数、`SUM(p)`、`did_click=true`、`navigation_code=1`、banner/anchored/web 分类、广告区域合计、计划声明不一致数和插屏比率。

明确空分母：

```python
assert result["interstitial_close_rate"] is None
assert result["interstitial_non_close_click_rate"] is None
```

- [x] **步骤 2：编写 config_id 和失败原因测试**

断言未知 `config_id` 独立分组；各占比使用 H1 总数；失败原因按固化 `failure_category` 聚合；网页元素和广告区域返回计划、实际、响应成功、失败及比例。

- [x] **步骤 3：运行确认失败**

```powershell
python -m pytest tests/test_log_metrics_service_v2.py -q
```

- [x] **步骤 4：实现统一筛选器和 SQL 聚合**

定义：

```python
def build_metric_filters(*, package_name: str, range_start: datetime, range_end: datetime): ...
async def get_overview(db: AsyncSession, **scope) -> dict[str, object]: ...
async def get_config_breakdown(db: AsyncSession, **scope) -> dict[str, object]: ...
async def get_target_breakdown(db: AsyncSession, **scope) -> dict[str, object]: ...
async def get_failure_breakdown(db: AsyncSession, **scope) -> list[dict[str, object]]: ...
async def get_h1_details(db: AsyncSession, **scope) -> dict[str, object]: ...
```

所有聚合在 PostgreSQL 完成，不把全量点击明细加载进 Python。总体和明细调用同一筛选器。

- [x] **步骤 5：增加路由**

```text
GET /api/admin/log-analysis/metrics/overview
GET /api/admin/log-analysis/metrics/configs
GET /api/admin/log-analysis/metrics/targets
GET /api/admin/log-analysis/metrics/failures
GET /api/admin/log-analysis/metrics/h1
```

路由统一要求完整包名和完整时间范围；分页、排序使用白名单。

- [x] **步骤 6：运行测试并提交**

```powershell
python -m pytest tests/test_log_metrics_service_v2.py tests/test_log_metrics_api_v2.py -q
git add backend/app/services/log_metrics_service.py backend/app/api/admin/log_metrics.py backend/tests/test_log_metrics_service_v2.py backend/tests/test_log_metrics_api_v2.py
git commit -m "feat: expose structured log metrics"
```

## 8. 实现设备时长汇总和设备明细接口

**文件：**
- 修改：`backend/app/services/usage_duration_service.py`
- 修改：`backend/app/api/admin/usage_duration.py`
- 创建：`backend/tests/test_usage_duration_summary.py`
- 修改：`backend/tests/test_usage_duration_admin_api.py`

- [x] **步骤 1：编写每设备最新记录测试**

同一设备插入 120、240、360 秒，只允许 360 进入汇总；另一个设备 180 秒，汇总为 540、设备数 2、平均 270。

使用 SQL 窗口函数的编译断言或集成测试确保：

```sql
row_number() over (partition by package_name, device_id order by server_ts desc, id desc)
```

- [x] **步骤 2：编写分布边界测试**

输入 `300,301,600,601,899,900`，预期四档分别为 `1,2,2,1`。比例分母为当前包名 + 机型的设备数。

- [x] **步骤 3：运行确认失败**

```powershell
python -m pytest tests/test_usage_duration_summary.py tests/test_usage_duration_admin_api.py -q
```

- [x] **步骤 4：实现服务和 API**

新增：

```python
async def get_usage_summary(db: AsyncSession, *, package_name, range_start, range_end, page, page_size, sort_by, sort_order): ...
async def get_usage_devices(db: AsyncSession, *, package_name, device_model, range_start, range_end, page, page_size): ...
```

平均时长使用 `ROUND(total_duration_s / device_count)`；无设备返回 `null`。路由：

```text
GET /api/admin/usage-durations/summary
GET /api/admin/usage-durations/devices
```

筛选支持可选包名和完整 UTC+8 日期/小时范围。

- [x] **步骤 5：运行测试并提交**

```powershell
python -m pytest tests/test_usage_duration_summary.py tests/test_usage_duration_admin_api.py tests/test_usage_duration_service.py -q
git add backend/app/services/usage_duration_service.py backend/app/api/admin/usage_duration.py backend/tests/test_usage_duration_summary.py backend/tests/test_usage_duration_admin_api.py backend/tests/test_usage_duration_service.py
git commit -m "feat: summarize latest device usage durations"
```

## 9. 实现 H1 混合 CSV 导出

**文件：**
- 修改：`backend/app/models/log_export_job.py`
- 修改：`backend/app/schemas/log_export_schemas.py`
- 修改：`backend/app/services/log_export_service.py`
- 修改：`frontend/src/api/logExports.ts`（前端接入在任务 12 完成）
- 创建：`backend/tests/test_h1_export.py`
- 修改：`backend/tests/test_log_export_service.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_export_jobs.sql`

- [x] **步骤 1：编写请求和模型测试**

`export_mode` 只接受 `raw/h1`，默认 `raw`；数据库列有 `raw/h1` 检查约束，迁移幂等。

- [x] **步骤 2：编写 CSV 行测试**

有三条 H1 输出三行 `record_type=h1`；无 H1 输出一行 `record_type=raw` 且 content 为原始 extra。测试 CSV 逗号、双引号、换行和以 `=,+,-,@` 开头内容的公式注入保护。

```python
rows = export_rows_for_event(event, export_mode="h1")
assert [row.record_type for row in rows] == ["h1", "h1", "h1"]
assert [row.record_index for row in rows] == [1, 2, 3]
```

- [x] **步骤 3：运行确认失败**

```powershell
python -m pytest tests/test_h1_export.py tests/test_log_export_service.py -q
```

- [x] **步骤 4：实现混合行生成**

定义：

```python
def export_rows_for_event(event: SdkEvent, export_mode: str) -> list[ExportRow]: ...
```

H1 模式调用 `extract_h1_records()`；无 H1 时只输出原始 `payload.extra`，不输出完整 payload。公共元数据独立列输出。

- [x] **步骤 5：确保筛选完全复用**

`apply_job_filters()` 继续统一处理包名、SDK、设备、级别、日期和小时；两种 export_mode 只能改变行展开，不得改变筛选 SQL。

- [x] **步骤 6：运行测试并提交**

```powershell
python -m pytest tests/test_h1_export.py tests/test_log_export_service.py tests/test_log_export_api.py -q
git add backend/app/models/log_export_job.py backend/app/schemas/log_export_schemas.py backend/app/services/log_export_service.py scripts/init_db.sql scripts/migrate_log_export_jobs.sql backend/tests/test_h1_export.py backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py
git commit -m "feat: export H1 records without dropping raw logs"
```

## 10. 建立前端 API 类型和默认最近三天工具

**文件：**
- 创建：`frontend/src/api/logMetrics.ts`
- 创建：`frontend/src/api/usageDurations.ts`
- 创建：`frontend/src/utils/logDateRange.ts`
- 创建：`frontend/src/utils/logDateRange.test.ts`
- 修改：`frontend/src/api/logExports.ts`

- [x] **步骤 1：编写默认范围测试**

固定当前时间为 2026-09-30，断言：

```ts
expect(defaultRecentThreeDays()).toEqual({
  date_from: "2026-09-28", hour_from: 0,
  date_to: "2026-09-30", hour_to: 23,
});
```

测试使用本地 UTC+8 日历语义，不从浏览器 UTC 日期字符串截取。

- [x] **步骤 2：运行确认失败**

```powershell
cd frontend
npm test -- --run src/utils/logDateRange.test.ts
```

- [x] **步骤 3：实现工具和接口类型**

`logMetrics.ts` 定义 `LogMetricScope`、`ParseJob`、`MetricOverview`、`ConfigMetricItem`、`TargetBreakdown`、`FailureBreakdownItem` 及调用函数；`usageDurations.ts` 定义四档分布、summary 和 devices；`LogExportFilters` 增加：

```ts
export_mode?: "raw" | "h1";
```

- [x] **步骤 4：运行测试和类型检查并提交**

```powershell
npm test -- --run src/utils/logDateRange.test.ts
npm run type-check
git add frontend/src/api/logMetrics.ts frontend/src/api/usageDurations.ts frontend/src/api/logExports.ts frontend/src/utils/logDateRange.ts frontend/src/utils/logDateRange.test.ts
git commit -m "feat: add frontend log metric contracts"
```

## 11. 实现解析任务筛选与任务进度组件

**文件：**
- 修改：`frontend/src/components/LogAnalysisFilters.vue`
- 创建：`frontend/src/components/LogParseTaskPanel.vue`
- 修改：`frontend/src/components/LogAnalysisFilters.test.ts`
- 创建：`frontend/src/components/LogParseTaskPanel.test.ts`

- [x] **步骤 1：编写交互失败测试**

覆盖默认最近 3 天、小时下拉 0..23、包名必填、超过 7 天阻止提交、“查询已有结果”不 POST、“开始解析”只 POST 一次、取消按钮状态和完成后发出 refresh。

- [x] **步骤 2：运行确认失败**

```powershell
cd frontend
npm test -- --run src/components/LogAnalysisFilters.test.ts src/components/LogParseTaskPanel.test.ts
```

- [x] **步骤 3：实现组件**

筛选值统一为：

```ts
interface LogAnalysisFilterValues {
  package_name: string;
  date_from: string;
  hour_from: number;
  date_to: string;
  hour_to: number;
}
```

任务面板轮询仅在 `pending/running` 时开启，组件卸载时清理定时器；错误和取消保留现有统计数据。

- [x] **步骤 4：运行测试并提交**

```powershell
npm test -- --run src/components/LogAnalysisFilters.test.ts src/components/LogParseTaskPanel.test.ts
npm run type-check
git add frontend/src/components/LogAnalysisFilters.vue frontend/src/components/LogParseTaskPanel.vue frontend/src/components/LogAnalysisFilters.test.ts frontend/src/components/LogParseTaskPanel.test.ts
git commit -m "feat: add explicit log parse controls"
```

## 12. 实现解析统计、失败原因和 H1 下钻界面

**文件：**
- 创建：`frontend/src/components/LogMetricsPanel.vue`
- 创建：`frontend/src/components/LogFailureDrawer.vue`
- 创建：`frontend/src/components/LogMetricsPanel.test.ts`
- 创建：`frontend/src/components/LogFailureDrawer.test.ts`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/views/LogViewer.test.ts`

- [x] **步骤 1：编写展示测试**

断言总体指标不混用：计划取 `declared_click_count`、实际点击和响应成功分列；插屏空分母显示 `-`；未知 config_id 可见；计划声明不一致提示存在。

- [x] **步骤 2：编写维度和失败抽屉测试**

切换网页元素/广告区域时发出相同 scope；点击失败数打开抽屉并传递 `target_kind/config_id`；抽屉显示数量和百分比。

- [x] **步骤 3：运行确认失败**

```powershell
npm test -- --run src/components/LogMetricsPanel.test.ts src/components/LogFailureDrawer.test.ts src/views/LogViewer.test.ts
```

- [x] **步骤 4：实现三个页签中的“解析统计”**

`LogViewer.vue` 的 view 改为：

```ts
type View = "analysis" | "raw" | "usage";
```

解析统计组合筛选、任务卡、指标面板和失败抽屉。大表容器使用固定内容高度和 `overflow:auto`，不改变全站布局。

- [x] **步骤 5：运行测试并提交**

```powershell
npm test -- --run src/components/LogMetricsPanel.test.ts src/components/LogFailureDrawer.test.ts src/views/LogViewer.test.ts
npm run type-check
git add frontend/src/components/LogMetricsPanel.vue frontend/src/components/LogFailureDrawer.vue frontend/src/components/LogMetricsPanel.test.ts frontend/src/components/LogFailureDrawer.test.ts frontend/src/views/LogViewer.vue frontend/src/views/LogViewer.test.ts
git commit -m "feat: display structured log analysis metrics"
```

## 13. 实现设备时长页签

**文件：**
- 创建：`frontend/src/components/UsageDurationPanel.vue`
- 创建：`frontend/src/components/UsageDurationPanel.test.ts`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/views/LogViewer.test.ts`

- [x] **步骤 1：编写汇总展示测试**

断言表格显示包名、机型、设备数、汇总时长、平均时长、四档“数量 + 占比”和最后上报时间；秒数同时格式化成易读时间。

- [x] **步骤 2：编写展开明细测试**

点击汇总行只请求该包名、机型和当前 scope；显示设备 ID、最新时长、SDK、应用版本和最后上报时间；折叠不重复请求，筛选变化清空旧明细。

- [x] **步骤 3：运行确认失败**

```powershell
npm test -- --run src/components/UsageDurationPanel.test.ts src/views/LogViewer.test.ts
```

- [x] **步骤 4：实现设备时长页签**

复用同一 UTC+8 日期小时筛选，但包名可为空。默认最近 3 天。前端不得自行合并设备或计算最新记录，只展示服务端结果。

- [x] **步骤 5：运行测试并提交**

```powershell
npm test -- --run src/components/UsageDurationPanel.test.ts src/views/LogViewer.test.ts
npm run type-check
git add frontend/src/components/UsageDurationPanel.vue frontend/src/components/UsageDurationPanel.test.ts frontend/src/views/LogViewer.vue frontend/src/views/LogViewer.test.ts
git commit -m "feat: display device usage duration summaries"
```

## 14. 在原始日志导出面板接入 H1 模式

**文件：**
- 修改：`frontend/src/components/LogExportPanel.vue`
- 修改：`frontend/src/components/LogExportPanel.test.ts`
- 修改：`frontend/src/views/LogViewer.vue`

- [x] **步骤 1：编写模式选择测试**

默认 `raw`；选择 H1 后请求包含 `export_mode:"h1"`；提示文本明确“有 H1 按条拆行，无 H1 保留原始 extra”；所有已应用筛选继续传递。

- [x] **步骤 2：运行确认失败**

```powershell
npm test -- --run src/components/LogExportPanel.test.ts src/views/LogViewer.test.ts
```

- [x] **步骤 3：实现选择和请求参数**

使用 select 或单选按钮，不新增额外边界选项。任务进行中禁用模式切换，防止页面状态与已创建任务不一致。

- [x] **步骤 4：运行测试并提交**

```powershell
npm test -- --run src/components/LogExportPanel.test.ts src/views/LogViewer.test.ts
npm run type-check
git add frontend/src/components/LogExportPanel.vue frontend/src/components/LogExportPanel.test.ts frontend/src/views/LogViewer.vue
git commit -m "feat: select H1 log export mode"
```

## 15. 增加独立 worker 服务、性能基准和运维文档

**文件：**
- 创建：`deploy/systemd/sdk-log-parse-worker.service`
- 创建：`scripts/benchmark_log_parse.py`
- 创建：`backend/tests/test_log_parse_benchmark_contract.py`
- 修改：`backend/.env.example`
- 修改：`docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md`
- 创建：`docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md`

- [x] **步骤 1：编写 worker 配置契约测试**

断言 unit 使用后端虚拟环境、正确工作目录、自动重启，并包含：

```ini
CPUQuota=300%
MemoryMax=1536M
Nice=5
```

断言 `.env.example` 有批量、并发、租约和最大天数，且无真实凭据。

- [x] **步骤 2：实现 systemd unit 和基准脚本**

基准脚本生成或加载 10,000 条脱敏真实结构事件，创建显式任务并轮询到终态，输出 JSON：

```json
{"events":10000,"elapsed_seconds":28.443,"h1_count":19000,"click_count":47500,"no_h1_count":500,"failed_h1_count":0,"passed":true}
```

只有 `elapsed_seconds <= 60`、任务成功且计数一致时 `passed=true`，失败返回非零退出码。

- [x] **步骤 3：更新接口与实施文档**

记录所有新路由、指标公式、UTC+8 范围、默认最近 3 天、H1 CSV 列、迁移、备份、发布、验证和回滚命令。不得写真实 Token、VPS 密码或原始生产日志。

- [x] **步骤 4：运行契约测试并提交**

```powershell
cd backend
python -m pytest tests/test_log_parse_benchmark_contract.py -q
git add deploy/systemd/sdk-log-parse-worker.service scripts/benchmark_log_parse.py backend/tests/test_log_parse_benchmark_contract.py backend/.env.example docs/42-PRODUCTION-SYSTEM-API-BASELINE-20260811.md docs/50-LOG-METRICS-DEVICE-DURATION-H1-EXPORT-IMPLEMENTATION-20260930.md
git commit -m "docs: add log metric worker operations"
```

## 16. 全量验证、审查与集成门禁

**文件：**
- 检查所有本计划修改文件；不新增功能。

### 2026-09-30 本地验收记录

- 后端专项与受影响测试已通过；从仓库根目录运行 `python -m pytest backend/tests -q`：402 passed。直接在 `backend` 目录运行默认收集仍会遇到既有 `test_api2.py` 外部服务连接和根目录 `scripts` 导入问题。
- 前端全量测试为 30 个文件、169 个测试通过；`vue-tsc --noEmit` 和生产构建通过，构建仅有既有 chunk size warning。
- 临时 PostgreSQL 验收库的初始化与三项增量迁移均已各执行两次并通过。
- P0 同一完整 H1+`pa` 样本耗时 75.023 秒；P1 任务级进程池复用后为 28.443 秒。最终结果为 `success`、10,000 条处理、19,000 条 H1、47,500 条点击、500 条无 H1 fallback、0 条失败 H1，60 秒门禁在该本地环境通过。
- 上述基准运行于本地 PostgreSQL 14.22、UTF-8/C/Asia Shanghai、6-core 临时验收环境，不等同于生产同规格 4 vCPU 门禁；生产性能、API 健康检查和 SDK 日志上报验证仍待执行。
- 最后复审确认 worker 续跑使用任务保存的 `batch_size` 快照而非当前全局配置；独立复测耗时 `34.538s`，受影响专项测试通过。

- [x] **步骤 1：后端专项测试**

```powershell
cd backend
python -m pytest tests/test_h1_extractor.py tests/test_flow_log_decoder.py tests/test_log_metrics_migration.py tests/test_log_parse_job_service_v2.py tests/test_log_parse_worker.py tests/test_log_metrics_service_v2.py tests/test_log_metrics_api_v2.py tests/test_usage_duration_summary.py tests/test_usage_duration_admin_api.py tests/test_h1_export.py tests/test_log_export_service.py tests/test_log_export_api.py -q
```

预期：全部通过。

- [x] **步骤 2：后端全量测试**

```powershell
python -m pytest -q
```

预期：全部通过，无跳过的新失败。

- [x] **步骤 3：前端测试与构建**

```powershell
cd ..\frontend
npm test -- --run
npm run type-check
npm run build
```

预期：全部测试通过，类型检查退出 0，生产构建成功。

- [x] **步骤 4：迁移幂等验证**

在一次性测试数据库连续执行两次 `migrate_log_metrics_v2.sql` 和日志导出迁移；第二次退出 0，四张新表、任务字段、export_mode、约束和索引各只有一份。

- [x] **步骤 5：真实结构 10,000 条性能门禁（本地验收环境）**

在 4 vCPU 同规格环境运行：

```bash
python scripts/benchmark_log_parse.py --events 10000 --max-seconds 60
```

预期：退出 0，`passed=true`，同时健康检查和一笔 SDK 日志上报成功。未达到 60 秒时不得部署，先用基准输出定位解析、IPC 或数据库写入瓶颈。

- [x] **步骤 6：独立代码审查**

使用 `superpowers:requesting-code-review`，至少审查：指标公式、边界拆分、范围删除条件、失败不污染正式结果、时长去重、导出不漏 raw、迁移无损和凭据泄露。

- [x] **步骤 7：修复审查问题并重复受影响测试**

只修复审查确认的问题，不附带新功能。每一组修复单独提交。

- [x] **步骤 8：最终工作区检查**

```powershell
git status --short
git log --oneline origin/master..HEAD
git diff --check origin/master...HEAD
```

预期：无未提交文件，diff check 无输出，提交均属于本规格范围。

## 17. 生产部署检查点（实现验收通过后执行）

本节截至 2026-09-30 均未执行；本次工作未部署、未启动生产 worker、未合并发布。生产同规格性能、API 健康、SDK 上报和真实发布回滚演练仍为待办。

- [ ] 读取并总结此前部署失败经验；确认采用 Paramiko 密码连接时关闭 agent/key 查找。
- [ ] 先决定是否包含前端；本功能包含前端，必须构建并备份/替换前端 dist。
- [ ] 备份 PostgreSQL、当前 release、前端 dist、systemd 和宝塔 Nginx 配置，记录文件大小和路径。
- [ ] 上传新的 release，不覆盖旧 release；执行迁移 dry-run/对象检查后再 apply。
- [ ] 安装并 daemon-reload `sdk-log-parse-worker.service`，启动 API、Admin 和 worker。
- [ ] 按最多 30 秒轮询 8100/8101 和 worker 状态，不因服务启动瞬间未就绪误回滚。
- [ ] 验证内部端口、带 Host/SNI 的本机 Nginx HTTPS 和公网边缘；公网临时 403 必须与内部/旧基线对比，不单独作为回滚依据。
- [ ] 使用一个包名、一小时范围创建小任务，核对 H1 数、config_id、点击指标和任务原子发布。
- [ ] 验证设备时长最新值、平均值和四档边界。
- [ ] 验证 H1 导出既拆出 H1，也保留无 H1 原始 extra。
- [ ] 执行 10,000 条一分钟门禁；只有全部通过才投入生产。
- [ ] 删除所有受控冒烟数据，复查业务历史数据未减少。

## 18. 计划完成定义

以下条件必须全部满足才能声明完成：

1. 原始日志上报不再触发默认解析；
2. 管理员可按包名和小时范围显式创建任务，默认最近 3 天，最大 7 天；
3. `||H1|` 和换行 H1 全部独立保存；
4. 每次任务使用暂存并原子替换，失败/取消不污染正式结果；
5. 所有已确认指标按文档公式返回并在前端展示；
6. 设备时长按每设备最新值汇总，平均值和四档分布正确；
7. H1 导出按条拆行且无 H1 原始日志不丢失；
8. 全量测试、迁移幂等、生产构建和独立审查通过；
9. 10,000 条正常日志端到端解析不超过 60 秒；
10. 实施记录、接口基线、部署和回滚文档已更新。
