# 本地导出下载 404 根因与验收记录

## 根因

任务 `d97d6a6f-f878-47c9-ba12-8e41cf913a08` 的状态为 `success`，`row_count=15349`，CSV 实际存在于：

`SDK/.local-run/exports/d97d6a6f-f878-47c9-ba12-8e41cf913a08.csv`

但当时 `start_snapshot_local.ps1` 只给 export worker launcher 设置了 `LOG_EXPORT_DIR`，没有给 API 进程设置。API 使用默认 `backend/exports`，下载路由的安全父目录校验因此返回：

`404 {"detail":"导出文件不存在"}`

5173 代理和 8101 直连均复现相同响应；未放宽路径校验。

## 修复

启动脚本统一给 API 与本地 export worker 设置同一个绝对目录：`SDK/.local-run/exports`。生产配置清单必须将 API 与 export worker 的 `LOG_EXPORT_DIR` 指向同一持久目录，不能使用 release 私有目录；发布切换前需备份该目录并保留回滚可读路径。

## 本地验收

同一北京时间小时范围内完成并下载：

| 范围 | 模式 | 行数 |
| --- | --- | ---: |
| `com.pivexa.ralume.app` | raw | 62 |
| `com.pivexa.ralume.app` | h1 | 119 |
| 全部包 | raw | 2284 |
| 全部包 | h1 | 4478 |

指定包 raw/H1 的来源事件 ID 均为对应全部包结果的子集；H1 行数因拆分不同而不要求与 raw 相等。原始事件、usage 和旧解析任务未被修改。

修复后通过真实 `http://127.0.0.1:5173` 代理登录下载旧任务，返回 `200`、CSV `9,803,317` bytes；再通过同一代理创建新 raw 任务 `54b69ce7-e314-4148-8354-a2296baab019`，状态 `success`、1 行，下载返回 `200`。新 CSV 表头为 raw 格式，唯一包名为 `com.techflow.note.fight.apppp`，时间为 `2026-10-18 13:35:05`。

## 发布前清单（只读，未执行生产写入）

- 当前生产列、索引、认证配置：本轮未连接生产，现状布尔核验为 `not_verified`；不得用本地 snapshot 结果代替生产核验。
- snapshot 迁移预检：旧任务 `5` 条均为合法非空 JSONB 包列表并保持 `all_packages=false`；全部包任务 `2` 条使用空数组；`chk_log_export_jobs_package_scope` 和原有 queue 主索引存在。
- 认证：保留生产既有 Admin password hash/token 配置；缺少生产 `ADMIN_PASSWORD_HASH` 时停止，不得使用本地测试密码或 SDK token。
- 共享目录：沿用 docs/46 记录的生产持久绝对 `LOG_EXPORT_DIR`，先确认 API 与 export worker 完全一致；不要切到 release 私有目录，避免旧 `file_path` 失效。
- 备份/回滚：沿用 docs/61 的 pg_dump、旧 release、真实 env、systemd unit/drop-in、Nginx 配置备份；先迁移再原子切换 release，健康检查失败回到旧 release，不覆盖数据库。
- 本分支未部署依赖：包含 admin password login、log history、publish safety、usage scope、parse/history metrics、H1/export 与本次 all-scope/download 修复；不能只发布单个下载文件改动。
