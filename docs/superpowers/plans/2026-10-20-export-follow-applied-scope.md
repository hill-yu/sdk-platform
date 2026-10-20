# 导出跟随已生效筛选：短规格与验收计划

## 规格

- `all_packages` 是显式布尔字段，默认 `false`。
- `all_packages=false` 时 `package_names` 必须为 1–50 个去重包名。
- `all_packages=true` 时 `package_names` 必须省略或为空；禁止矛盾输入。
- 旧任务迁移为 `all_packages=false`，raw/H1、日期/小时、SDK、设备、级别筛选、队列鉴权和既有批次读取方式保持不变。
- 前端移除导出专用包名多选；导出只读取 raw 视图的 applied scope。draft 与 applied 不一致、查询中或查询失败时禁用并提示先查询。
- 本地 export worker 通过任务专属 launcher 固定 snapshot DB 与 `.local-run/exports`，单实例锁定；不连接生产或 COS。

## TDD / 验收

1. 先以失败测试锁定 schema/API 的 all-scope 规则、worker 全包过滤、前端 applied 门控与 launcher 隔离。
2. 迁移 snapshot schema，保留旧任务与原始事件/usage 数据。
3. 用同一小时范围分别执行指定包与全部包的 raw/H1 导出，完成轮询和本地下载。
4. 验证 raw 指定包事件 ID 集是 raw 全包子集；H1 来源事件 ID 集同样是全包子集，但 H1 行数允许因拆分不同。
