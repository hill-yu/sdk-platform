# 原始日志小时筛选与导出一致性实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为原始日志查询增加北京时间小时范围，并确保列表展示、分页、刷新和 CSV 导出始终使用同一组已应用条件。

**架构：** 后端在 `timezone.py` 提供唯一的日期/小时到 UTC 半开区间转换函数，原始事件查询和异步导出共同调用。前端保留草稿/已应用条件边界，只有点击查询后小时才影响列表及导出。

**技术栈：** Python、FastAPI、Pydantic 2、SQLAlchemy Async、PostgreSQL、pytest、Vue 3、TypeScript、Vitest、Vite。

---

## 范围锁定

只允许修改：

- 原始日志查询 API 与服务；
- 日志导出请求、任务模型、worker 过滤和迁移；
- 原始日志页面筛选与导出参数传递；
- 对应测试。

禁止修改：日志上报、日志解析器、解析统计页、解析任务、Admin 生命周期、独立解析 worker、词库、其他页面和生产部署。

### 任务 1：统一北京时间小时边界并应用到原始日志查询

**文件：**
- 修改：`backend/app/core/timezone.py`
- 修改：`backend/app/services/analysis_service.py`
- 修改：`backend/app/api/admin/dashboard.py`
- 修改：`backend/tests/test_timezone.py`
- 修改：`backend/tests/test_analysis_service.py`
- 修改：`backend/tests/test_admin_api.py`

- [ ] **步骤 1：为时间边界写失败测试**

在 `backend/tests/test_timezone.py` 增加：

```python
from datetime import date, timedelta
import pytest

from app.core.timezone import business_hour_utc_range


def test_business_hour_range_uses_inclusive_end_hour():
    start, end = business_hour_utc_range(
        date(2026, 9, 20), 8,
        date(2026, 9, 22), 17,
    )
    assert start.isoformat() == "2026-09-20T00:00:00+00:00"
    assert end.isoformat() == "2026-09-22T10:00:00+00:00"


def test_business_hour_range_defaults_to_full_days():
    start, end = business_hour_utc_range(
        date(2026, 9, 20), None,
        date(2026, 9, 20), None,
    )
    assert end - start == timedelta(days=1)


@pytest.mark.parametrize("hours", [(8, None), (None, 17), (-1, 17), (8, 24)])
def test_business_hour_range_rejects_invalid_hours(hours):
    with pytest.raises(ValueError):
        business_hour_utc_range(
            date(2026, 9, 20), hours[0],
            date(2026, 9, 20), hours[1],
        )
```

- [ ] **步骤 2：运行时间测试确认失败**

运行：`python -m pytest backend/tests/test_timezone.py -q`

预期：导入 `business_hour_utc_range` 失败。

- [ ] **步骤 3：实现唯一时间函数**

在 `backend/app/core/timezone.py` 增加：

```python
def business_hour_utc_range(
    date_from: date,
    hour_from: int | None,
    date_to: date,
    hour_to: int | None,
) -> tuple[datetime, datetime]:
    if hour_from is None and hour_to is None:
        start, _ = business_day_utc_range(date_from)
        _, end = business_day_utc_range(date_to)
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        return start, end
    if hour_from is None or hour_to is None:
        raise ValueError("hour_from 和 hour_to 必须成对提供")
    if not 0 <= hour_from <= 23 or not 0 <= hour_to <= 23:
        raise ValueError("小时必须在 0 到 23 之间")
    start = datetime.combine(date_from, time(hour_from), BUSINESS_TIMEZONE)
    end = datetime.combine(date_to, time(hour_to), BUSINESS_TIMEZONE) + timedelta(hours=1)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
```

- [ ] **步骤 4：为原始事件查询写失败测试**

在服务和 API 测试中断言：

```python
response = client.get(
    "/api/admin/events",
    params={
        "event_type": "log",
        "date_from": "2026-09-20",
        "hour_from": 8,
        "date_to": "2026-09-22",
        "hour_to": 17,
    },
    headers=admin_headers,
)
assert response.status_code == 200
service_mock.assert_awaited_once_with(
    ANY,
    page=1,
    page_size=20,
    event_type="log",
    log_level=None,
    package_name=None,
    sdk_version=None,
    device_id=None,
    date_from=date(2026, 9, 20),
    hour_from=8,
    date_to=date(2026, 9, 22),
    hour_to=17,
)
```

再覆盖单边小时、小时无完整日期、越界小时返回 HTTP 422。

- [ ] **步骤 5：实现查询参数和服务过滤**

`dashboard.get_events()` 增加：

```python
hour_from: int | None = Query(None, ge=0, le=23),
hour_to: int | None = Query(None, ge=0, le=23),
```

`analysis_service.get_events()` 增加同名参数。仅当日期/小时组合有效时调用 `business_hour_utc_range()`，并应用：

```python
stmt = stmt.where(
    SdkEvent.server_ts >= range_start,
    SdkEvent.server_ts < range_end,
)
```

未传小时继续兼容原有单边日期筛选；传入任意小时则要求两个日期和两个小时全部存在。

- [ ] **步骤 6：验证并提交**

运行：

```bash
python -m pytest backend/tests/test_timezone.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py -q
```

预期：全部通过。

```bash
git add backend/app/core/timezone.py backend/app/services/analysis_service.py backend/app/api/admin/dashboard.py backend/tests/test_timezone.py backend/tests/test_analysis_service.py backend/tests/test_admin_api.py
git commit -m "feat: filter raw logs by Beijing hours"
```

### 任务 2：让异步 CSV 导出持久化并复用小时边界

**文件：**
- 修改：`backend/app/models/log_export_job.py`
- 修改：`backend/app/schemas/log_export_schemas.py`
- 修改：`backend/app/services/log_export_service.py`
- 修改：`scripts/init_db.sql`
- 修改：`scripts/migrate_log_export_jobs.sql`
- 修改：`backend/tests/test_log_export_service.py`
- 修改：`backend/tests/test_log_export_api.py`

- [ ] **步骤 1：写请求模型和迁移失败测试**

加入测试：

```python
def test_export_request_accepts_complete_hour_range():
    body = LogExportCreateRequest(
        package_names=["com.example.app"],
        date_from=date(2026, 9, 20),
        hour_from=8,
        date_to=date(2026, 9, 22),
        hour_to=17,
    )
    assert body.hour_from == 8
    assert body.hour_to == 17


@pytest.mark.parametrize(
    "payload",
    [
        {"date_from": "2026-09-20", "date_to": "2026-09-22", "hour_from": 8},
        {"date_from": "2026-09-20", "hour_from": 8, "hour_to": 17},
        {"date_from": "2026-09-20", "date_to": "2026-09-22", "hour_from": -1, "hour_to": 17},
    ],
)
def test_export_request_rejects_incomplete_or_invalid_hour_range(payload):
    with pytest.raises(ValidationError):
        LogExportCreateRequest(package_names=["com.example.app"], **payload)
```

模型和迁移测试断言 `hour_from/hour_to` 存在、范围为 0..23、两列成对为空或非空，并且迁移使用 `IF NOT EXISTS`。

- [ ] **步骤 2：确认失败**

运行：

```bash
python -m pytest backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py -q
```

预期：缺少小时字段或验证而失败。

- [ ] **步骤 3：实现请求与持久化模型**

`LogExportCreateRequest` 增加：

```python
hour_from: int | None = Field(default=None, ge=0, le=23)
hour_to: int | None = Field(default=None, ge=0, le=23)
```

在 `model_validator` 中要求小时成对，并在小时存在时要求两个日期都存在、组合结束时间晚于开始时间。`LogExportJob` 增加两个 `SmallInteger` 可空列和数据库 CheckConstraint。

- [ ] **步骤 4：实现幂等 DDL**

新安装和迁移包含：

```sql
ALTER TABLE sdk_log_export_jobs
    ADD COLUMN IF NOT EXISTS hour_from SMALLINT,
    ADD COLUMN IF NOT EXISTS hour_to SMALLINT;
```

通过命名约束校验 0..23 及成对关系；迁移使用 PostgreSQL `DO $$` 检查约束名称后再添加，确保重复运行安全。历史任务保留 NULL。

- [ ] **步骤 5：让导出 worker 复用统一时间函数**

`create_job()` 写入小时；`serialize_job()` 返回小时；`apply_job_filters()` 删除日期自己的 `datetime.combine()`，改为在日期完整时统一调用：

```python
range_start, range_end = business_hour_utc_range(
    job.date_from,
    job.hour_from,
    job.date_to,
    job.hour_to,
)
stmt = stmt.where(
    SdkEvent.server_ts >= range_start,
    SdkEvent.server_ts < range_end,
)
```

原有单边日期且无小时的历史任务继续使用原来的单边全天语义。

- [ ] **步骤 6：加入查询和导出边界一致性测试**

用 `2026-09-20 08` 到 `2026-09-22 17` 同时构造 `/events` 服务查询和 export job，断言二者的 SQL 条件均为 UTC `2026-09-20T00:00:00` 到 `2026-09-22T10:00:00`，并测试 23 点结束变成次日 00 点。

- [ ] **步骤 7：验证并提交**

运行步骤 2 命令，预期全部通过。

```bash
git add backend/app/models/log_export_job.py backend/app/schemas/log_export_schemas.py backend/app/services/log_export_service.py scripts/init_db.sql scripts/migrate_log_export_jobs.sql backend/tests/test_log_export_service.py backend/tests/test_log_export_api.py
git commit -m "feat: persist hour filters for log exports"
```

### 任务 3：前端使用同一组已应用小时条件

**文件：**
- 修改：`frontend/src/api/dashboard.ts`
- 修改：`frontend/src/api/logExports.ts`
- 修改：`frontend/src/components/LogExportPanel.vue`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/api/dashboard.test.ts`
- 修改：`frontend/src/api/logExports.test.ts`
- 修改：`frontend/src/components/LogExportPanel.test.ts`
- 修改：`frontend/src/views/LogViewer.test.ts`

- [ ] **步骤 1：写 API 类型和参数失败测试**

```typescript
await getEvents({
  page: 1,
  page_size: 20,
  event_type: "log",
  date_from: "2026-09-20",
  hour_from: 8,
  date_to: "2026-09-22",
  hour_to: 17,
});
expect(request.get).toHaveBeenCalledWith("/events", {
  params: expect.objectContaining({ hour_from: 8, hour_to: 17 }),
});

await createLogExport({
  package_names: ["com.example.app"],
  date_from: "2026-09-20",
  hour_from: 8,
  date_to: "2026-09-22",
  hour_to: 17,
});
expect(request.post).toHaveBeenCalledWith(
  "/log-exports",
  expect.objectContaining({ hour_from: 8, hour_to: 17 }),
);
```

- [ ] **步骤 2：写页面行为失败测试**

测试以下顺序：先把草稿小时改为 8/17，但不点击查询，导出仍使用旧 applied 值；点击查询后列表和导出都收到 8/17；分页和刷新继续携带 8/17；重置后不发送小时；只有一个小时被选择时不调用 `getEvents`/`createLogExport` 并显示错误。

- [ ] **步骤 3：确认失败**

工作目录 `frontend`，运行：

```bash
npm test -- --run src/api/dashboard.test.ts src/api/logExports.test.ts src/components/LogExportPanel.test.ts src/views/LogViewer.test.ts
```

- [ ] **步骤 4：扩展类型和原始日志筛选 UI**

`EventQuery`、`LogExportFilters` 增加：

```typescript
hour_from?: number;
hour_to?: number;
```

`LogViewer.vue` 的 `rawFilters` 和单独的 `appliedRawFilters` 均增加小时字符串字段。小时下拉渲染 0..23，标签格式为 `08:00–08:59`；构造 API 参数时把非空字符串转换为 number。

- [ ] **步骤 5：锁定草稿/已应用边界**

`queryRaw()` 先校验日期/小时完整性，通过后复制草稿到 `appliedRawFilters` 并从第一页查询。`rawQueryParams()`、分页、刷新全部读取 `appliedRawFilters`。只在成功应用查询后更新导出面板 props：

```vue
<LogExportPanel
  :date-from="appliedRawFilters.date_from"
  :hour-from="appliedRawFilters.hour_from"
  :date-to="appliedRawFilters.date_to"
  :hour-to="appliedRawFilters.hour_to"
  ...
/>
```

- [ ] **步骤 6：导出组件发送同一条件**

`LogExportPanel` 增加 `hourFrom/hourTo` props，并在 `createLogExport()` 中仅对非空值执行 `Number()`。组件不创建第二套小时输入，不读取 `rawFilters` 草稿。

- [ ] **步骤 7：验证并提交**

运行步骤 3，预期全部通过；再运行 `npm run build`，预期退出码 0。

```bash
git add frontend/src/api/dashboard.ts frontend/src/api/logExports.ts frontend/src/components/LogExportPanel.vue frontend/src/views/LogViewer.vue frontend/src/api/dashboard.test.ts frontend/src/api/logExports.test.ts frontend/src/components/LogExportPanel.test.ts frontend/src/views/LogViewer.test.ts
git commit -m "feat: sync raw log hour filters with exports"
```

### 任务 4：全量验证与独立审查

**文件：**
- 检查：任务 1–3 修改的全部文件
- 不修改：本计划范围外文件

- [ ] **步骤 1：后端全量验证**

运行：`python -m pytest backend/tests -q`

预期：0 failed，测试通过数不低于当前基线 272。

- [ ] **步骤 2：前端全量验证**

工作目录 `frontend`：

```bash
npm test -- --run
npm run build
```

预期：0 failed，构建退出码 0。

- [ ] **步骤 3：范围和迁移检查**

```bash
git diff --check
git diff --name-only 0a69a14..HEAD
```

预期：只出现本计划列出的业务文件、测试、窄范围规格和计划；不得出现解析统计、解析 worker、SDK 上报或 Admin 生命周期文件。

- [ ] **步骤 4：独立审查**

独立验收窗口逐条验证：小时成对、日期完整、UTC+8 连续范围、结束小时包含完整一小时、草稿不影响导出、查询/分页/刷新/导出条件一致、全天兼容、迁移幂等。发现问题只允许在本计划文件范围内修复。

- [ ] **步骤 5：交回主会话**

提交代码、测试输出、迁移检查和独立审查结论。未经用户再次明确授权，不推送、不合并、不部署。

## 执行方式

- 使用新的 `gpt-5.6-luna` 执行窗口实现任务 1–3。
- 使用另一个独立窗口执行任务 4 验收。
- 当前主会话只做决策、调度和最终判断，不直接实施业务代码。
