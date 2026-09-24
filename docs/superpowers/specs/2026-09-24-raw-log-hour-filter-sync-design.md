# 原始日志小时筛选与导出一致性设计

> 日期：2026-09-24
> 状态：设计已确认，待用户审阅正式规格
> 时区：`Asia/Shanghai`（UTC+8）

## 1. 目标

在原始日志页面增加开始小时和结束小时，使以下行为始终使用同一组已经生效的筛选条件：

1. 原始日志查询；
2. 原始日志列表展示、分页和刷新；
3. 原始日志 CSV 导出。

本次只解决原始日志筛选与导出一致性，不实施日志后置解析、解析任务、独立解析 worker、解析统计小时筛选或解析性能优化。

## 2. 当前行为

原始日志目前支持包名、SDK 版本、设备 ID、日志级别、开始日期和结束日期筛选。前端把这些条件传给：

- `GET /api/admin/events` 查询原始日志；
- `POST /api/admin/log-exports` 创建 CSV 导出任务。

当前没有小时字段，日期范围只能按北京时间自然日筛选。

## 3. 统一筛选条件

原始日志的统一筛选集合为：

- `package_name`；
- `sdk_version`；
- `device_id`；
- `log_level`；
- `date_from`；
- `hour_from`；
- `date_to`；
- `hour_to`。

前端继续区分“草稿条件”和“已应用条件”：

- 用户修改输入框或下拉框时，只更新草稿；
- 用户点击“查询”后，草稿成为已应用条件；
- 列表查询、分页、刷新和 CSV 导出只能读取已应用条件；
- 未点击“查询”的小时修改不得提前影响导出。

这样可以避免页面展示一组日志，却导出另一组范围。

## 4. 时间语义

所有日期和小时都按北京时间解释，并转换为 UTC 半开区间查询。

例如：

```text
date_from=2026-09-20
hour_from=8
date_to=2026-09-22
hour_to=17
```

实际筛选范围为：

```text
2026-09-20 08:00:00 +08:00 <= server_ts
server_ts < 2026-09-22 18:00:00 +08:00
```

结束小时包含该小时内的全部数据。跨日期时是一个连续时间段，不是每天重复相同小时段。

兼容规则：

- `hour_from` 和 `hour_to` 都不传：保持原有自然日全天行为；
- 只传其中一个：请求无效，返回 HTTP 422；
- 小时必须是整数 `0..23`；
- 组合后的结束时间必须晚于开始时间；
- 现有日期校验继续保留。

## 5. 前端设计

原始日志筛选栏新增两个小时下拉框：

- 开始小时：`00:00–00:59` 至 `23:00–23:59`；
- 结束小时：`00:00–00:59` 至 `23:00–23:59`。

交互规则：

- 两个小时默认均为空，表示全天；
- 点击查询时，如果只选择一个小时，前端显示明确错误并且不发请求；
- 重置操作同时清空日期、小时及其他原始日志条件；
- 分页和刷新保留当前已应用小时；
- `LogExportPanel` 接收已应用的 `hourFrom`、`hourTo`，不得直接读取尚未应用的表单草稿；
- 导出任务创建成功后的轮询和下载流程保持不变。

本次不修改解析统计筛选组件 `LogAnalysisFilters.vue`。

## 6. API 设计

### 6.1 原始日志查询

```http
GET /api/admin/events
```

新增可选查询参数：

```text
hour_from: integer 0..23
hour_to: integer 0..23
```

后端将日期和小时集中转换为 UTC 边界后应用到 `SdkEvent.server_ts`。

### 6.2 CSV 导出

```http
POST /api/admin/log-exports
```

请求体新增：

```json
{
  "date_from": "2026-09-20",
  "hour_from": 8,
  "date_to": "2026-09-22",
  "hour_to": 17
}
```

导出任务必须持久化两个小时值，使异步 worker 不依赖前端状态。导出 worker 使用与 `/events` 完全相同的 UTC 时间边界函数。

## 7. 后端边界

在 `backend/app/core/timezone.py` 增加唯一的日期/小时范围转换函数。原始日志查询和导出服务都必须调用该函数，禁止各自使用 `datetime.combine()` 重复实现。

涉及的后端文件限定为：

- `backend/app/core/timezone.py`；
- `backend/app/api/admin/dashboard.py`；
- `backend/app/services/analysis_service.py`；
- `backend/app/schemas/log_export_schemas.py`；
- `backend/app/models/log_export_job.py`；
- `backend/app/services/log_export_service.py`；
- `scripts/init_db.sql`；
- `scripts/migrate_log_export_jobs.sql`；
- 对应测试文件。

不修改 SDK 上报接口、日志解析器、解析结果模型和 Admin 后台解析循环。

## 8. 数据库迁移

`sdk_log_export_jobs` 增加：

```sql
hour_from SMALLINT NULL
hour_to   SMALLINT NULL
```

约束要求：

- 每个非空小时都在 `0..23`；
- 两列必须同时为空或同时非空。

迁移使用 `ADD COLUMN IF NOT EXISTS`，并可重复执行。历史任务两列为空，继续表示全天，不回填、不重建任务、不删除历史导出记录。

## 9. 错误处理

- 前端在单边小时、非法时间组合时阻止请求并显示中文错误；
- 后端仍独立验证所有条件，不能依赖前端；
- 查询接口参数无效返回 HTTP 422；
- 导出创建请求无效返回 HTTP 422，不创建任务；
- 异步导出失败仍沿用现有 failed 状态和脱敏错误信息；
- 不改变现有 Admin Token 鉴权。

## 10. 测试与验收

后端测试必须覆盖：

- 同日小时范围；
- 跨日连续范围；
- 结束 23 点；
- 两个小时均缺省的全天兼容；
- 单边小时和越界小时拒绝；
- `/events` 和导出生成完全相同的 UTC 边界；
- 导出任务序列化和迁移幂等。

前端测试必须覆盖：

- 小时下拉显示和重置；
- 只选择一个小时不发查询和导出请求；
- 查询后分页、刷新保留小时；
- 未点击查询的草稿小时不影响导出；
- 查询和导出收到同一组已应用条件；
- 原有不带小时的查询和导出保持通过。

全量验收：

```bash
python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run build
```

本功能完成只形成候选代码；推送、合并和生产部署不属于本次实施授权。
