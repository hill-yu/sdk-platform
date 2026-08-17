# UTC+8 时间统一与日志解析统计实施计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实施此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 在不改写历史绝对时间和原始 `extra` 的前提下，将业务日期统一为 `Asia/Shanghai`，接入指定流程日志解析器，提供可下钻的日志聚合页、包名资料编辑和全局指标列配置。

**架构：** PostgreSQL 继续用 `TIMESTAMPTZ` 保存绝对时刻，集中式时间工具负责北京时间边界和 API 序列化。日志上报写入原始事件和待解析占位记录，Admin 后台解析循环异步生成结构化结果；历史数据由幂等回填脚本处理。Admin 新增聚合、明细、资料和列配置 API，前端在现有 `/logs` 页面增加“解析统计 / 原始日志”两层视图。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy 2 Async、PostgreSQL 16、Vue 3、TypeScript、Axios、Vitest、pytest。

---

## 文件结构与职责

### 后端时间与解析

- 创建 `backend/app/core/timezone.py`：唯一业务时区常量、日期边界、UTC+8 序列化。
- 创建 `backend/tests/test_timezone.py`：跨日、跨年、序列化和无时区输入测试。
- 修改 `backend/app/services/analysis_service.py`：北京时间筛选与统计边界、响应时间序列化。
- 修改 `backend/app/api/admin/dashboard.py`：北京时间默认日期。
- 修改 `backend/app/services/config_service.py`、`backend/app/services/version_service.py`、`backend/app/api/sdk/config.py`：统一 API 时间序列化。
- 创建 `backend/app/services/flow_log_decoder.py`：从指定脚本抽取的纯字符串解析核心和词库。
- 创建 `backend/tests/test_flow_log_decoder.py`：固定 H1/旧格式/多记录/异常输入测试向量。

### 数据持久化、后台解析与迁移

- 创建 `backend/app/models/log_analysis.py`：解析结果、包名资料、Admin 全局配置和重解析任务 ORM。
- 修改 `backend/app/models/__init__.py`：导出新增模型。
- 修改 `scripts/init_db.sql`：新建库直接包含三张新表及北京时间物化视图。
- 创建 `scripts/migrate_log_analysis.py`：生产预检、四张表建表、视图切换、无损校验和幂等 apply。
- 创建 `backend/tests/test_log_analysis_migration.py`：迁移 SQL 顺序、幂等性和无损快照测试。
- 修改 `backend/app/api/sdk/log.py`：原始事件插入后创建 pending 占位结果。
- 创建 `backend/app/services/log_parse_service.py`：受限批量领取、解析、成功/失败落库。
- 修改 `backend/app/admin_main.py`：启动/关闭后台解析循环。
- 创建 `backend/tests/test_log_parse_service.py`：pending、成功、多记录、失败、重试和并发领取测试。
- 创建 `scripts/backfill_log_decodes.py`：历史 dry-run、分批回填、断点续跑和重解析 CLI。
- 创建 `backend/tests/test_log_decode_backfill.py`：稳定游标、upsert、范围限制和原文不变测试。

### Admin API

- 创建 `backend/app/schemas/log_analysis_schemas.py`：资料、列配置、重解析请求模型。
- 创建 `backend/app/services/log_analysis_service.py`：聚合、明细、资料、列配置和重解析任务服务。
- 创建 `backend/app/api/admin/log_analysis.py`：新 Admin 路由。
- 修改 `backend/app/admin_main.py`：注册路由。
- 创建 `backend/tests/test_log_analysis_service.py`：SQL 边界、聚合口径、缺失样本和配置 upsert 测试。
- 创建 `backend/tests/test_log_analysis_api.py`：鉴权、参数约束、响应结构和错误契约测试。

### 前端

- 创建 `frontend/src/api/logAnalysis.ts`：聚合、明细、资料和全局列配置 API 类型。
- 创建 `frontend/src/api/logAnalysis.test.ts`：Axios 参数及请求体契约。
- 创建 `frontend/src/utils/dateTime.ts`：UTC+8 展示函数。
- 创建 `frontend/src/utils/dateTime.test.ts`：带 Z/偏移时间、空值和跨日测试。
- 创建 `frontend/src/components/LogAnalysisFilters.vue`：北京时间筛选和当前生效条件。
- 创建 `frontend/src/components/LogColumnSettings.vue`：全局列显示、隐藏、排序和恢复默认。
- 创建 `frontend/src/components/PackageProfileCell.vue`：别名/公司/账户行内 upsert。
- 创建 `frontend/src/components/LogAnalysisDetail.vue`：解析明细与完整 JSON/原文详情。
- 创建对应组件测试文件。
- 修改 `frontend/src/views/LogViewer.vue`：解析统计与原始日志双视图、聚合表和下钻。
- 修改 `frontend/src/views/LogViewer.test.ts`、`frontend/src/components/LogDetail.vue`、`frontend/src/components/LogDetail.test.ts`：页面集成和 UTC+8 展示。
- 修改 `frontend/src/views/Dashboard.vue`：既有时间显示统一 UTC+8。

### 文档

- 修改 `docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md`：UTC+8 契约与新 Admin API。
- 修改 `docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md`：日志解析和筛选口径。
- 创建 `docs/47-UTC8-LOG-ANALYSIS-IMPLEMENTATION-20260817.md`：迁移、回填、部署、验证和回滚记录。

---

### 任务 1：建立统一 UTC+8 时间基础设施

**文件：**
- 创建：`backend/app/core/timezone.py`
- 创建：`backend/tests/test_timezone.py`
- 修改：`backend/app/services/analysis_service.py`
- 修改：`backend/app/api/admin/dashboard.py`
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_admin_api.py`

- [ ] **步骤 1：先写时间工具和事件筛选失败测试**

在 `backend/tests/test_timezone.py` 写固定时刻测试：

```python
from datetime import date, datetime, timezone

from app.core.timezone import business_day_utc_range, serialize_business_time


def test_business_day_maps_to_utc_half_open_range():
    start, end = business_day_utc_range(date(2026, 8, 17))
    assert start == datetime(2026, 8, 16, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 17, 16, 0, tzinfo=timezone.utc)


def test_serialize_business_time_uses_explicit_plus_eight_offset():
    value = datetime(2026, 8, 17, 1, 30, tzinfo=timezone.utc)
    assert serialize_business_time(value) == "2026-08-17T09:30:00+08:00"
```

扩展 `test_analysis_service.py`，断言 `date_from=date(2026, 8, 17)` 绑定参数为前一天 16:00 UTC，`date_to` 使用下一天 16:00 UTC。扩展 Admin 测试，固定当前 UTC 时刻后断言默认 breakdown 日期为北京时间日期。

- [ ] **步骤 2：运行测试确认 RED**

运行：

```powershell
py -m pytest -q backend/tests/test_timezone.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py
```

预期：FAIL，`app.core.timezone` 不存在，现有筛选仍绑定 UTC 零点。

- [ ] **步骤 3：实现集中式时间工具并替换事件边界**

`backend/app/core/timezone.py` 最小接口：

```python
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def business_today(now: datetime | None = None) -> date:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("datetime 必须包含时区")
    return current.astimezone(BUSINESS_TIMEZONE).date()


def business_day_utc_range(value: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(value, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def serialize_business_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("datetime 必须包含时区")
    return value.astimezone(BUSINESS_TIMEZONE).isoformat()
```

`analysis_service.get_events` 使用 `business_day_utc_range` 构造半开区间；`dashboard.get_breakdown` 默认日期通过依赖函数调用 `business_today()`，便于测试固定时间。

- [ ] **步骤 4：验证 GREEN 并跑后端回归**

```powershell
py -m pytest -q backend/tests/test_timezone.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py
py -m pytest -q backend/tests
```

预期：定点测试和当前后端全量测试均 PASS。

- [ ] **步骤 5：提交**

```powershell
git add backend/app/core/timezone.py backend/app/services/analysis_service.py backend/app/api/admin/dashboard.py backend/tests/test_timezone.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py
git commit -m "feat(time): use UTC+8 business date boundaries"
```

---

### 任务 2：统一现有 API 时间序列化与 Dashboard 统计

**文件：**
- 修改：`backend/app/services/analysis_service.py`
- 修改：`backend/app/services/config_service.py`
- 修改：`backend/app/services/version_service.py`
- 修改：`backend/app/api/sdk/config.py`
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_config_service.py`
- 修改：`backend/tests/test_admin_api.py`
- 修改：`backend/tests/test_sdk_api.py`

- [ ] **步骤 1：写 UTC+8 响应和统计边界失败测试**

新增断言：

```python
assert item["server_ts"] == "2026-08-17T18:00:00+08:00"
assert item["client_ts"] == "2026-08-17T17:59:00+08:00"
assert config["updated_at"].endswith("+08:00")
assert version["created_at"].endswith("+08:00")
```

对 summary SQL 参数断言北京时间今日起点对应 UTC 16:00；对 breakdown 断言同一北京时间自然日半开区间。不要只断言 SQL 字符串，要断言绑定值。

- [ ] **步骤 2：运行定点测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_analysis_service.py backend/tests/test_config_service.py backend/tests/test_admin_api.py backend/tests/test_sdk_api.py
```

预期：FAIL，现有服务返回 datetime/UTC `isoformat()`，summary 使用 `date.today()`。

- [ ] **步骤 3：最小替换所有外部时间序列化**

所有响应使用 `serialize_business_time()`。`get_summary` 使用 `business_today()` 及 `business_day_utc_range()` 生成绝对时间参数；24 小时滚动窗口仍表示真实过去 24 小时，不人为加八小时。

- [ ] **步骤 4：验证定点和后端全量**

```powershell
py -m pytest -q backend/tests/test_analysis_service.py backend/tests/test_config_service.py backend/tests/test_admin_api.py backend/tests/test_sdk_api.py
py -m pytest -q backend/tests
```

- [ ] **步骤 5：提交**

```powershell
git add backend/app/services/analysis_service.py backend/app/services/config_service.py backend/app/services/version_service.py backend/app/api/sdk/config.py backend/tests
git commit -m "feat(time): serialize API timestamps as UTC+8"
```

---

### 任务 3：抽取并锁定纯日志解析器

**文件：**
- 创建：`backend/app/services/flow_log_decoder.py`
- 创建：`backend/tests/fixtures/flow_log_vectors.json`
- 创建：`backend/tests/test_flow_log_decoder.py`

- [ ] **步骤 1：建立固定测试向量与失败测试**

将用户提供脚本中的代表样例和已验证 H1 样例写入 UTF-8 fixture。至少覆盖：单条 H1、多条 H1、旧 `FINAL_FLOW_RESULT`、未知格式、异常字段、中文展示值。

测试公共接口：

```python
from app.services.flow_log_decoder import DECODER_VERSION, decode_extra


def test_decode_h1_matches_reference_vector(vector):
    result = decode_extra(vector["raw"])
    assert DECODER_VERSION == "1.0.0"
    assert result[0]["config_id"] == 1004
    assert result[0]["expected_click_count"] == 2
    assert result[0]["final_reason"] == "planned-click-count-exhausted"
    assert result[0]["duration_ms"] == 58576
```

- [ ] **步骤 2：运行测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_flow_log_decoder.py
```

预期：FAIL，模块不存在。

- [ ] **步骤 3：从指定脚本复制后收窄在线边界**

从：

```text
D:/software/WX_doc/xwechat_files/wxid_bio9320eiwsk22_f321/temp/RWTemp/2026-08/9429f9b08d538593b6776e36ce6dfa32/flow_log_decoder.py
```

复制解析核心和词库。删除 argparse、stdin、任意路径读取、XLSX/zip 输出和 `main()`；公开接口固定为：

```python
DECODER_VERSION = "1.0.0"
MAX_EXTRA_LENGTH = 1_000_000
MAX_RECORDS_PER_EXTRA = 500


def decode_extra(extra: str) -> list[dict[str, object]]:
    if not isinstance(extra, str):
        raise TypeError("extra 必须是字符串")
    if len(extra) > MAX_EXTRA_LENGTH:
        raise ValueError("extra 超过解析长度限制")
    summaries = decode_text(extra)
    if len(summaries) > MAX_RECORDS_PER_EXTRA:
        raise ValueError("extra 中记录数超过限制")
    return [asdict(item) for item in summaries]
```

保持词库 UTF-8，不用控制台输出验证中文；直接断言 Python 字符串。

- [ ] **步骤 4：验证与参考脚本一致**

```powershell
py -m pytest -q backend/tests/test_flow_log_decoder.py
py -m pytest -q backend/tests
```

- [ ] **步骤 5：提交**

```powershell
git add backend/app/services/flow_log_decoder.py backend/tests/fixtures/flow_log_vectors.json backend/tests/test_flow_log_decoder.py
git commit -m "feat(logs): add sandboxed flow log decoder"
```

---

### 任务 4：新增解析、资料和全局配置数据模型及迁移

**文件：**
- 创建：`backend/app/models/log_analysis.py`
- 修改：`backend/app/models/__init__.py`
- 修改：`scripts/init_db.sql`
- 创建：`scripts/migrate_log_analysis.py`
- 创建：`backend/tests/test_log_analysis_migration.py`

- [ ] **步骤 1：写模型与迁移失败测试**

测试需断言：

- `sdk_log_decodes` 唯一键为 `(event_id, event_server_ts, record_index)`；
- `record_index` 允许 `-1` 作为唯一 pending 占位，成功解析后删除；
- `sdk_log_decodes`、`sdk_package_profiles`、`sdk_admin_preferences`、`sdk_log_reparse_jobs` 四张表和全部索引存在；
- dry-run 只读快照，不执行 DDL；
- apply 在同一事务建表、重建北京时间视图并执行前后无损校验；
- 已迁移环境再次 dry-run/apply 不产生破坏性语句；
- 快照包括事件总数、非空 extra 数、逐分区行数和旧视图定义摘要。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_log_analysis_migration.py
```

- [ ] **步骤 3：实现 ORM 与新库 SQL**

`LogDecode` 显式定义复合主键；`PackageProfile.package_name` 为主键；`AdminPreference.preference_key` 为主键；`LogReparseJob` 保存范围、游标、计数、状态和错误摘要，禁止保存原始 `extra`。`scripts/init_db.sql` 的日/小时视图使用：

```sql
(server_ts AT TIME ZONE 'Asia/Shanghai')::date
date_trunc('hour', server_ts AT TIME ZONE 'Asia/Shanghai')
```

- [ ] **步骤 4：实现安全迁移 CLI**

接口：

```powershell
py scripts/migrate_log_analysis.py
py scripts/migrate_log_analysis.py --apply --confirm MIGRATE_LOG_ANALYSIS
```

dry-run 输出脱敏计数和计划 SQL 类型；apply 前后比较事件总数、非空 extra 数和逐分区行数。任一不一致抛错并回滚。迁移不更新任何 `sdk_events` 行。

- [ ] **步骤 5：运行迁移与后端回归**

```powershell
py -m pytest -q backend/tests/test_log_analysis_migration.py backend/tests/test_event_package_migration.py
py -m pytest -q backend/tests
```

- [ ] **步骤 6：提交**

```powershell
git add backend/app/models/log_analysis.py backend/app/models/__init__.py scripts/init_db.sql scripts/migrate_log_analysis.py backend/tests/test_log_analysis_migration.py
git commit -m "feat(logs): add decoded log persistence schema"
```

---

### 任务 5：日志接收创建 pending，占位解析循环异步落库

**文件：**
- 修改：`backend/app/api/sdk/log.py`
- 创建：`backend/app/services/log_parse_service.py`
- 修改：`backend/app/admin_main.py`
- 修改：`backend/tests/test_sdk_api.py`
- 创建：`backend/tests/test_log_parse_service.py`

- [ ] **步骤 1：写 pending 和解析状态机失败测试**

覆盖：

- 插入日志使用 `RETURNING id, server_ts`；
- 同事务为每个原始事件插入 `record_index=-1/status=pending`；
- 解析成功时删除占位并按稳定顺序插入 `record_index=0..n-1`；
- 无支持记录写 `record_index=0/status=unsupported`；
- 异常写 failed 与最长 512 字符脱敏错误；
- 两个 worker 使用 `FOR UPDATE SKIP LOCKED` 不重复领取；
- 单批上限和超时生效；
- 日志上报响应不等待实际解码完成。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_sdk_api.py backend/tests/test_log_parse_service.py
```

- [ ] **步骤 3：实现原始写入与 pending 创建**

`report_log` 通过 PostgreSQL `INSERT ... RETURNING` 取得复合事件键，并在当前事务插入 pending。不得在 API 内调用 `decode_extra()`。

- [ ] **步骤 4：实现受限解析服务与 Admin 生命周期循环**

核心接口：

```python
async def process_pending_batch(db: AsyncSession, *, batch_size: int = 50) -> ParseBatchResult: ...
```

Admin lifespan 创建解析循环；每轮新建 session，成功 commit，失败 rollback 并退避。关闭时取消任务。解析失败不能终止循环。

- [ ] **步骤 5：验证定点与全量**

```powershell
py -m pytest -q backend/tests/test_sdk_api.py backend/tests/test_log_parse_service.py
py -m pytest -q backend/tests
```

- [ ] **步骤 6：提交**

```powershell
git add backend/app/api/sdk/log.py backend/app/services/log_parse_service.py backend/app/admin_main.py backend/tests/test_sdk_api.py backend/tests/test_log_parse_service.py
git commit -m "feat(logs): parse uploaded logs asynchronously"
```

---

### 任务 6：实现历史回填、断点续跑和受限重解析

**文件：**
- 创建：`scripts/backfill_log_decodes.py`
- 创建：`backend/tests/test_log_decode_backfill.py`
- 修改：`backend/app/services/log_parse_service.py`
- 修改：`backend/tests/test_log_parse_service.py`

- [ ] **步骤 1：写回填失败测试**

覆盖稳定游标 `(server_ts, id)`、只选 `event_type=log` 且 `payload.extra` 为字符串、日期/包名/状态/旧版本范围、批次事务、upsert 幂等、dry-run 不写库、原文哈希不变和无条件全量请求拒绝。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_log_decode_backfill.py backend/tests/test_log_parse_service.py
```

- [ ] **步骤 3：实现 CLI 与共享批处理函数**

命令必须显式范围：

```powershell
py scripts/backfill_log_decodes.py --date-from 2026-08-01 --date-to 2026-08-17
py scripts/backfill_log_decodes.py --date-from 2026-08-01 --date-to 2026-08-17 --apply --confirm BACKFILL_LOG_DECODES
py scripts/backfill_log_decodes.py --status failed --decoder-version-before 1.0.0 --apply --confirm BACKFILL_LOG_DECODES
```

输出每批扫描、成功、unsupported、failed、最后游标和累计数，不输出原始 `extra`。

- [ ] **步骤 4：验证幂等与后端全量**

```powershell
py -m pytest -q backend/tests/test_log_decode_backfill.py backend/tests/test_log_parse_service.py
py -m pytest -q backend/tests
```

- [ ] **步骤 5：提交**

```powershell
git add scripts/backfill_log_decodes.py backend/app/services/log_parse_service.py backend/tests/test_log_decode_backfill.py backend/tests/test_log_parse_service.py
git commit -m "feat(logs): backfill decoded logs safely"
```

---

### 任务 7：实现包名资料和全局指标列配置 API

**文件：**
- 创建：`backend/app/schemas/log_analysis_schemas.py`
- 创建：`backend/app/services/log_analysis_service.py`
- 创建：`backend/app/api/admin/log_analysis.py`
- 修改：`backend/app/admin_main.py`
- 创建：`backend/tests/test_log_analysis_service.py`
- 创建：`backend/tests/test_log_analysis_api.py`

- [ ] **步骤 1：写资料和列配置失败测试**

测试请求：

```json
{"alias":"","company":"示例公司","account":"account-1"}
```

断言空字符串入库为 NULL、响应为空字符串、包名规范化、首次 PUT 创建、再次 PUT 更新。列配置只接受后端白名单、有序去重、必须包含 `date` 和 `package_name`，拒绝未知列、重复列和空列表。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
```

- [ ] **步骤 3：实现 schema、service 和路由**

列目录由后端常量定义：

```python
LOG_ANALYSIS_COLUMNS = (
    "date", "package_name", "alias", "url", "company", "account",
    "user_count", "flow_count", "expected_click_count", "actual_click_count",
    "ad_click_count", "interstitial_presentation_count", "interstitial_click_count",
    "average_duration_ms", "success_rate", "parse_failure_count",
)
```

实现 `GET/PUT /package-profiles` 和 `GET/PUT /log-analysis/columns`，注册到 Admin app。

- [ ] **步骤 4：验证鉴权、错误契约和全量**

```powershell
py -m pytest -q backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py backend/tests/test_admin_api.py
py -m pytest -q backend/tests
```

- [ ] **步骤 5：提交**

```powershell
git add backend/app/schemas/log_analysis_schemas.py backend/app/services/log_analysis_service.py backend/app/api/admin/log_analysis.py backend/app/admin_main.py backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
git commit -m "feat(logs): manage package profiles and global columns"
```

---

### 任务 8：实现聚合、明细、原文追溯和重解析 API

**文件：**
- 修改：`backend/app/services/log_analysis_service.py`
- 修改：`backend/app/api/admin/log_analysis.py`
- 修改：`backend/app/schemas/log_analysis_schemas.py`
- 修改：`backend/tests/test_log_analysis_service.py`
- 修改：`backend/tests/test_log_analysis_api.py`

- [ ] **步骤 1：写聚合口径和 API 失败测试**

测试需用明确数据覆盖：两个设备、一个 NULL 设备、缺失 duration、无法判定 success、多 URL、一个 failed 和一个 unsupported。断言：

- 用户数只去重非空设备；
- 平均耗时只使用有效样本并返回样本数；
- 成功率分母只含 `is_success IS NOT NULL`；
- 无样本比例为 NULL；
- 失败和 unsupported 分项及合计正确；
- 日期 SQL 使用 `AT TIME ZONE 'Asia/Shanghai'`；
- 日期跨度、page_size、sort_by 白名单受限；
- 详情必须含 `event_server_ts` 和 `record_index`；
- 原始 `extra` 只在单条详情返回；
- reparse 无任何范围返回 422。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
py -m pytest -q backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
```

- [ ] **步骤 3：实现 summary/details/detail/reparse**

summary 使用数据库聚合和白名单排序，不把全部解析 JSON 拉入 Python。URL 多值返回 `primary_url` 与 `url_count`。details 使用相同北京时间边界。单条详情先按复合键查询 decode，再按 `(event_id, event_server_ts)` 查询原始事件。

reparse 首期不引入通用任务平台：在 `sdk_log_reparse_jobs` 创建限定范围的任务记录并返回任务 ID，由现有解析循环消费；不得在 HTTP 请求内同步跑全量。任务状态限定为 pending/running/success/failed/cancelled，按稳定游标更新进度。

- [ ] **步骤 4：验证定点、全量和 SQL 编译**

```powershell
py -m pytest -q backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
py -m pytest -q backend/tests
```

- [ ] **步骤 5：提交**

```powershell
git add backend/app/services/log_analysis_service.py backend/app/api/admin/log_analysis.py backend/app/schemas/log_analysis_schemas.py backend/tests/test_log_analysis_service.py backend/tests/test_log_analysis_api.py
git commit -m "feat(logs): expose decoded log analysis APIs"
```

---

### 任务 9：建立前端 UTC+8 工具与日志分析 API 客户端

**文件：**
- 创建：`frontend/src/utils/dateTime.ts`
- 创建：`frontend/src/utils/dateTime.test.ts`
- 创建：`frontend/src/api/logAnalysis.ts`
- 创建：`frontend/src/api/logAnalysis.test.ts`
- 修改：`frontend/src/components/LogDetail.vue`
- 修改：`frontend/src/components/LogDetail.test.ts`
- 修改：`frontend/src/views/Dashboard.vue`

- [ ] **步骤 1：写时间显示与 Axios 契约失败测试**

```typescript
expect(formatBusinessTime("2026-08-17T01:30:00Z")).toBe("2026-08-17 09:30:00");
expect(formatBusinessTime(null)).toBe("-");
```

API 测试断言 summary、details、profile PUT 和 columns PUT 的路径、参数和请求体完整透传。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
npm test -- --run src/utils/dateTime.test.ts src/api/logAnalysis.test.ts src/components/LogDetail.test.ts
```

- [ ] **步骤 3：实现纯时间工具和 API 类型**

前端只格式化后端返回的带时区 ISO 值，不自行给无偏移字符串猜时区：

```typescript
export function formatBusinessTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", hour12: false,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(date).replaceAll("/", "-");
}
```

定义 `LogAnalysisSummaryItem`、`LogDecodeItem`、`LogColumnDefinition`、`PackageProfile` 和分页响应类型。

- [ ] **步骤 4：替换现有日志详情和 Dashboard 时间显示并验证**

```powershell
npm test -- --run src/utils/dateTime.test.ts src/api/logAnalysis.test.ts src/components/LogDetail.test.ts
npm test -- --run
npm run build
```

- [ ] **步骤 5：提交**

```powershell
git add frontend/src/utils/dateTime.ts frontend/src/utils/dateTime.test.ts frontend/src/api/logAnalysis.ts frontend/src/api/logAnalysis.test.ts frontend/src/components/LogDetail.vue frontend/src/components/LogDetail.test.ts frontend/src/views/Dashboard.vue
git commit -m "feat(time): display admin timestamps as UTC+8"
```

---

### 任务 10：实现聚合筛选、全局指标配置和包名资料编辑组件

**文件：**
- 创建：`frontend/src/components/LogAnalysisFilters.vue`
- 创建：`frontend/src/components/LogAnalysisFilters.test.ts`
- 创建：`frontend/src/components/LogColumnSettings.vue`
- 创建：`frontend/src/components/LogColumnSettings.test.ts`
- 创建：`frontend/src/components/PackageProfileCell.vue`
- 创建：`frontend/src/components/PackageProfileCell.test.ts`

- [ ] **步骤 1：先写三个组件的失败测试**

筛选器覆盖北京时间标签、生效条件、查询、刷新、重置和完全匹配说明。列配置覆盖添加、移除、排序、强制列、恢复默认、保存失败保留选择。资料单元格覆盖空值、首次创建、编辑、清空、并发禁用和失败保留输入。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
npm test -- --run src/components/LogAnalysisFilters.test.ts src/components/LogColumnSettings.test.ts src/components/PackageProfileCell.test.ts
```

- [ ] **步骤 3：实现受控组件**

组件不自行请求 summary；通过 props/emits 与页面协调。`PackageProfileCell` 可以调用 profile API，但用请求序号防止较旧保存响应覆盖较新输入。列配置保存成功后才更新全局有效配置。

- [ ] **步骤 4：验证组件及全量**

```powershell
npm test -- --run src/components/LogAnalysisFilters.test.ts src/components/LogColumnSettings.test.ts src/components/PackageProfileCell.test.ts
npm test -- --run
npm run build
```

- [ ] **步骤 5：提交**

```powershell
git add frontend/src/components/LogAnalysisFilters.vue frontend/src/components/LogAnalysisFilters.test.ts frontend/src/components/LogColumnSettings.vue frontend/src/components/LogColumnSettings.test.ts frontend/src/components/PackageProfileCell.vue frontend/src/components/PackageProfileCell.test.ts
git commit -m "feat(logs): configure analysis filters and columns"
```

---

### 任务 11：集成解析统计、下钻明细与原始日志双视图

**文件：**
- 创建：`frontend/src/components/LogAnalysisDetail.vue`
- 创建：`frontend/src/components/LogAnalysisDetail.test.ts`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/views/LogViewer.test.ts`

- [ ] **步骤 1：写页面集成失败测试**

覆盖：

- 默认进入解析统计，原始日志视图仍可切换；
- 首次加载并行读取全局列配置和 summary；
- 动态列顺序与隐藏列；
- 横向表格、NULL 指标、样本数和成功率显示；
- 别名/公司/账户编辑后同包名行同步；
- 点击聚合行以日期 + 包名加载 details；
- 点击明细以复合键加载完整 JSON 和原始 `extra`；
- 筛选、分页、排序和快速切换请求乱序保护；
- summary/details 失败保留上一批有效结果；
- 原始日志继续完全匹配筛选，日期标注北京时间。

- [ ] **步骤 2：运行测试确认 RED**

```powershell
npm test -- --run src/views/LogViewer.test.ts src/components/LogAnalysisDetail.test.ts
```

- [ ] **步骤 3：实现页面状态协调和明细组件**

页面分别维护 summary、details 和 detail 的请求序号；只有最新请求可提交。动态列只从后端列目录渲染，单元格格式使用显式 formatter 映射，不使用动态 HTML。

- [ ] **步骤 4：验证定点、全量和生产构建**

```powershell
npm test -- --run src/views/LogViewer.test.ts src/components/LogAnalysisDetail.test.ts
npm test -- --run
npm run build
```

- [ ] **步骤 5：提交**

```powershell
git add frontend/src/views/LogViewer.vue frontend/src/views/LogViewer.test.ts frontend/src/components/LogAnalysisDetail.vue frontend/src/components/LogAnalysisDetail.test.ts
git commit -m "feat(logs): add drill-down decoded log dashboard"
```

---

### 任务 12：文档、真实 PostgreSQL 迁移演练和端到端验收

**文件：**
- 修改：`docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md`
- 修改：`docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md`
- 创建：`docs/47-UTC8-LOG-ANALYSIS-IMPLEMENTATION-20260817.md`

- [ ] **步骤 1：更新接口与实施文档**

记录 UTC+8 响应示例、北京时间日期参数、完全匹配、summary/details/profile/columns/reparse API、指标口径、解析器版本、迁移命令、回填命令、备份和回滚。不得写入真实 Token、密码、原始敏感日志或连接串。

- [ ] **步骤 2：运行全量自动验证**

```powershell
py -m pytest -q backend/tests
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
rg -n "date\.today\(|timezone\.utc|isoformat\(\)" backend/app
rg -n "flow_log_decoder|log-analysis|Asia/Shanghai" backend frontend scripts docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md docs/47-UTC8-LOG-ANALYSIS-IMPLEMENTATION-20260817.md
```

对 UTC 使用扫描逐项判断：存储绝对时间和客户端 epoch 转换仍应使用 UTC；业务日期和外部序列化不得绕过统一工具。

- [ ] **步骤 3：在本地真实 PostgreSQL 做迁移 dry-run/apply/重复执行**

执行：

```powershell
py scripts/migrate_log_analysis.py
py scripts/migrate_log_analysis.py --apply --confirm MIGRATE_LOG_ANALYSIS
py scripts/migrate_log_analysis.py
py scripts/migrate_log_analysis.py --apply --confirm MIGRATE_LOG_ANALYSIS
```

记录事件总数、非空 extra 数、逐分区行数、表/索引/视图状态。第二次 apply 必须安全无变化。

- [ ] **步骤 4：用专用本地样本完成端到端 smoke**

使用专用测试包名，不使用生产包名：

1. POST 一条含固定 H1 `extra` 的日志；
2. 确认 SDK API 快速返回 accepted；
3. 等待解析循环把 pending 变为 success；
4. summary 按北京时间日期 + 包名返回预期指标；
5. details 和单条 detail 可追溯到原始 `extra`；
6. 更新别名/公司/账户并清空一次；
7. 修改全局列后恢复默认；
8. 验证跨 UTC 16:00 的两个样本归属不同北京时间日期；
9. 删除所有 smoke 事件、解析结果、资料和偏好测试数据；
10. 确认未调用配置发布接口。

- [ ] **步骤 5：生产部署计划门禁**

文档明确生产顺序：备份并验证 → 迁移 dry-run → 停止解析写入窗口 → apply → 后端 → 健康检查 → 前端 → 小范围历史回填 → 指标核对 → 分批回填。准备旧 commit、旧 dist、数据库备份和旧物化视图定义；未经用户明确授权不得执行生产部署。

- [ ] **步骤 6：最终独立审阅与提交**

完成规格审阅、代码质量审阅，修复全部 Critical/Important 后重新运行步骤 2～4。

```powershell
git add docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md docs/45-PACKAGE-NAME-LOG-INTEGRATION-20260811.md docs/47-UTC8-LOG-ANALYSIS-IMPLEMENTATION-20260817.md
git commit -m "docs: record UTC+8 log analysis rollout"
```

---

## 完成定义

- 12 个任务均按 RED → GREEN → 回归 → commit 完成；
- 后端、前端全量测试和生产构建通过；
- 解析器固定向量与用户脚本关键字段一致且中文无乱码；
- 真实 PostgreSQL 迁移和重复执行通过；
- 原始事件、分区和非空 `extra` 数量在迁移/回填前后不变；
- 北京时间跨日筛选、统计和前端显示通过；
- 聚合、下钻、资料编辑和全局列配置端到端通过；
- 无真实凭据、原始敏感日志或数据库连接串进入提交；
- 最终独立审阅无 Critical/Important；
- 生产部署只能在用户另行明确授权后执行。
