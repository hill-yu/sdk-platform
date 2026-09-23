# 日志查看与导出筛选同步设计

## 问题

原始日志查看会将 `package_name`、`sdk_version`、`device_id`、`log_level`、`date_from`、`date_to` 发送给查询接口，但 CSV 导出链路没有接收或持久化 `sdk_version`。因此用户在页面选择 SDK 版本后，列表只显示该版本，导出任务却包含所选包名下全部 SDK 版本。

## 目标

让日志查看和 CSV 导出使用相同的筛选值，同时保留现有多包名批量导出能力。

## 前端行为

- `LogViewer` 将当前查看筛选中的 `package_name` 和 `sdk_version` 传给 `LogExportPanel`；现有设备 ID、日志级别和日期继续传递。
- 页面已经选择 `package_name` 时，导出范围强制为该单一包名，隐藏独立多包选择器，并显示当前导出包名。
- 页面未选择 `package_name` 时，保留现有 `PackageMultiSelect`，用户必须选择至少一个包名才能创建任务。
- 创建导出任务时使用点击瞬间的筛选值，不复用旧任务状态。
- 不增加新的 SDK 版本控件；导出直接复用页面现有 SDK 版本下拉值。

## 后端行为

- `LogExportCreateRequest` 增加可选 `sdk_version`，最大长度与事件模型一致，为 20。
- `sdk_log_export_jobs` 增加可空 `sdk_version VARCHAR(20)`，旧任务保持 `NULL`。
- 创建任务时持久化 `sdk_version`。
- 工作器生成 CSV 时，如果任务 `sdk_version` 非空，增加精确过滤：`SdkEvent.sdk_version == job.sdk_version`；为空则保持原行为。
- 其余筛选继续保持精确匹配和北京时间日期边界。

## 数据库迁移

- `scripts/init_db.sql` 和 `scripts/migrate_log_export_jobs.sql` 均包含 `sdk_version VARCHAR(20)`。
- 迁移脚本补充 `ALTER TABLE sdk_log_export_jobs ADD COLUMN IF NOT EXISTS sdk_version VARCHAR(20)`，允许对已有表重复执行。
- 不更新历史任务，不重建导出文件。

## 兼容性

- 旧前端不传 `sdk_version`：后端接受，导出行为不变。
- 旧任务 `sdk_version IS NULL`：工作器不添加版本条件。
- 页面选择包名：该包名优先于导出面板之前选择的多包列表，避免查看与导出范围不一致。
- 页面清空包名：重新显示多包选择器，保留用户此前选择，只有点击导出时才生效。

## 测试

1. 前端创建导出任务时包含当前 `sdk_version`。
2. 页面选择包名时导出请求只含该包名；清空时恢复多包选择。
3. 后端请求模型接收、校验并保存 `sdk_version`。
4. 工作器仅在值非空时生成 SDK 版本精确过滤 SQL。
5. 初始化 SQL和迁移脚本可支持新旧数据库。
6. 旧任务和未选 SDK 版本时行为不变。
7. 前后端全量测试和前端构建通过。

## 不在范围内

- 不修改 CSV 列内容。
- 不增加新的筛选条件。
- 不改变日志查看查询逻辑。
- 不修改设备元数据功能分支。
- 不推送或部署，除非用户后续明确要求。
