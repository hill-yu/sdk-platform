# 日志历史与配置发布验收记录

## 代码状态

- Worktree：`C:\Users\喻远飞\.codex\worktrees\log-history-publish-safety-20261018\SDK`
- 分支：`codex/log-history-publish-safety-20261018`
- 最终提交：以本文件最后一次提交后的 `git rev-parse HEAD` 为准。
- 生产环境未写入、未重启、未部署、未合并或推送。

## 可复跑 PostgreSQL 验收

测试文件：

- `backend/tests/test_log_history_postgres_integration.py`
- `backend/tests/test_config_publish_postgres_integration.py`

两者都要求专用数据库名白名单，避免误连生产：

```powershell
$env:SDK_LOG_HISTORY_TEST_DATABASE_URL = "postgresql+asyncpg://.../sdk_log_history_test_<id>"
python -m pytest backend/tests/test_log_history_postgres_integration.py -q -rs

$env:SDK_CONFIG_PUBLISH_TEST_DATABASE_URL = "postgresql+asyncpg://.../sdk_config_publish_test_<id>"
python -m pytest backend/tests/test_config_publish_postgres_integration.py -q -rs
```

本次使用临时 PostgreSQL 14 实例 `127.0.0.1:55432`：

- `test_log_history_postgres_integration.py`：1 passed；额外创建正式 H1/click 表并写入 B 的覆盖行，验证历史读取仍只使用 stage 表。
- 任务 A/B 使用同包同范围、不同 `job_id` 和不同 click 结果；overview、configs、targets、failures、H1+click 全部按 job 隔离。实际 SQL 中没有正式 H1/click 表引用，stage 表和 `job_id` 绑定均存在。
- 新增真实 FastAPI ASGI + PostgreSQL 覆盖：五个 `/api/admin/log-analysis/parse-jobs/{job_id}/metrics/{overview,configs,targets,failures,h1}` 端点均实际请求；A/B 返回不同 click 结果，未知 job 返回 404，failed/incomplete job 返回 409；路由 SQL 仍只命中 stage 表并包含 `job_id`。
- `test_config_publish_postgres_integration.py`：1 passed。
- 两个真实异步会话中，保存会话持有草稿行锁；发布会话等待锁释放后用旧 `expected_updated_at` 得到冲突，状态仍为 draft、版本未递增、COS 状态仍为 pending。
- 临时实例当前为本地验收服务使用中的 disposable PostgreSQL（`127.0.0.1:55432`）；临时目录因执行策略禁止递归删除而保留在 `%TEMP%`，不含生产数据。停止命令：`C:\pgsql\bin\pg_ctl.exe -D <该临时目录> -w stop`。

## 自动化验证

```powershell
cd frontend
<bundled-node> ...\vitest.mjs run --pool=threads --poolOptions.threads.singleThread=true
```

- 前端最终全量：42 files / 230 tests passed。
- `vue-tsc --noEmit`：passed。
- `vite build`：passed；仅有既有的 bundle 大小提示。

```powershell
python -m pytest backend/tests -q -rs --disable-warnings
```

- 后端：在专用历史/发布 PostgreSQL 环境变量下 `458 passed，3 skipped`；未设置的 3 项仍是既有专用真实数据库测试。
- 跳过原因：`SDK_PARSE_STAGE_TEST_DATABASE_URL` 未设置、`SDK_LOG_SCOPE_TEST_DATABASE_URL` 未设置、`SDK_PARTITION_TEST_DATABASE_URL` 未设置；均为专用真实数据库集成测试，不是失败。
- 仓库根目录 `python -m pytest` 还会收集 `backend/test_api2.py`，该文件在收集阶段直接访问未启动的本地 API 并因连接拒绝失败；它不是 `backend/tests` 标准套件的一部分，本次未启动该外部依赖来掩盖问题。

可复跑入口：`scripts/run_log_history_acceptance.ps1`。它从私有、未跟踪的 env 文件读取且只允许两个变量：

```powershell
powershell -NoProfile -File .\scripts\run_log_history_acceptance.ps1 -EnvFile <private-env-file>
```

脚本强制要求两个 URL 使用 `127.0.0.1:55432` 和 `sdk_log_history_test_*` / `sdk_config_publish_test_*` disposable 数据库名，不打印 URL 或凭据。本次实际运行输出：`3 passed in 0.84s`；其中历史测试函数为 `test_two_successful_jobs_are_isolated_across_all_history_metric_surfaces`、`test_http_history_metrics_use_job_id_and_reject_unavailable_jobs`，发布并发函数为 `test_save_holding_row_lock_invalidates_preview_without_publish_side_effects`。

## 本地服务与浏览器验收

- 独立本地开发库：`sdk_local_acceptance_20261018`，监听 `127.0.0.1:55432`；使用 `scripts/init_db.sql`、`scripts/migrate_cos_upload_status.sql`、`migrate_log_analysis.py --apply`、`migrate_event_package_name.py --apply`、`migrate_config_versions.py --apply` 完成正式初始化/迁移，公开表数量为 16，包含事件、配置、版本、使用时长、日志分析、stage 和导出相关表。
- 私有本地配置文件：`SDK/.local-run/local-dev.env`，未跟踪、未提交；凭据内容不记录在本文档中。
- 前端：`http://127.0.0.1:5173/`，HTTP 200。
- 管理 API：`http://127.0.0.1:8101/api/admin/health`，HTTP 200，返回 `{"status":"ok"}`。
- 真实授权业务 API：使用本地登录会话调用 `/api/admin/auth/login`、`/api/admin/auth/me`、`/api/admin/log-analysis/parse-jobs/history?package_name=com.example.local`、`/api/admin/log-analysis/parse-jobs/9001/metrics/overview` 和 `/metrics/configs`，结果为 `login_username=admin me_username=admin history_items=1 history_job=9001 overview_actual_clicks=1 configs_status=0`。
- 浏览器验收边界：IAB 打开本机地址返回 `ERR_BLOCKED_BY_CLIENT`；随后本机 Chrome 的 Computer Use 状态读取因“could not determine the current browser URL on Windows with enough confidence to enforce policy”被安全策略停止。未执行后续点击/输入，也未绕过策略，因此桌面/390px 交互验收未宣称通过。
