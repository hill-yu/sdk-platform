# Admin 登录本地验收记录

日期：2026-10-17
worktree：`C:\Users\喻远飞\.codex\worktrees\admin-login-db-audit-20261017\SDK`
分支：`codex/admin-login-db-audit-20261017`
本次实现提交：`49a3527`（后续仅可能追加验收文档元数据提交）

## 已完成的自动化证据

- 后端：`python -m pytest tests/test_admin_auth.py -q` → 15 passed。
- 后端回归：`$env:PYTHONPATH='backend'; python -m pytest backend/tests -q` → 448 passed, 3 skipped。
- 前端：bundled Node 运行 `node_modules/vitest/vitest.mjs --run --pool=threads --poolOptions.threads.singleThread=true` → 39 files / 217 tests passed。
- 前端类型检查：bundled `vue-tsc --noEmit` 退出码 0。
- 前端构建：bundled Vite build 退出码 0；仅有现有产物 chunk >500 kB 提示。
- `git diff --check` 已执行。

新增 auth 测试覆盖：错误账号/密码统一 401 与 no-store、scrypt 参数、Unicode 输入、session 撤销/容量、限流窗口清理、cookie session、CSRF 缺失、Basic/畸形 Authorization 不回退 cookie、logout 无 session 幂等、Origin 拒绝，以及前端 login 错误/内部 returnTo、withCredentials、无 prompt/sessionStorage、写请求 CSRF、401 会话过期事件、退出成功和退出请求失败提示。

## 本地联调状态

已使用全新隔离 PostgreSQL 14.22 data directory `C:\Users\喻远飞\.codex\local-pg-admin-login-20261017-pgdata`、端口 55432、数据库 `sdk_platform_local`；没有触碰未知旧 data 或生产连接。`scripts/init_db.sql` 导入成功。

真实服务当前保持运行：

- backend：`http://localhost:8101`，真实 `backend/app/admin_main.py`，启动 ETL refresh 成功。
- frontend：`http://localhost:5173/login`，真实 Vite app，proxy 指向 8101。
- HTTP 证据：错误密码 401 + `Cache-Control: no-store`；正确密码 200；`/auth/me` 200；真实受保护 `GET /api/admin/package-profiles?package_name=local` 200。
- 浏览器证据：错误密码显示“账号或密码错误”；成功登录进入数据大盘；退出返回 `/login`。退出请求失败时会返回登录页并显示“尚未确认服务端会话注销，请重试”，避免把网络失败误报为已退出。
- 390 宽度证据：浏览器 viewport 390×844 时 `bodyClientWidth=390`、`bodyScrollWidth=390`、`documentScrollWidth=390`，密码框、登录按钮和登录页均可见；截图已通过浏览器验收捕获。
- 桌面宽度证据：浏览器 viewport 1280px 时 `bodyScrollWidth=1280`、`documentScrollWidth=1280`，登录页可见；截图已通过浏览器验收捕获。
- CORS 语义证据：不允许的 Origin 调用 `/api/admin/auth/me` 仍可得到 HTTP 200，但响应不带 `Access-Control-Allow-Origin`，因此浏览器脚本无法读取；服务端不会把该 GET 错误地改成 403。

尚未宣称的项目：真实生产数据、生产 overview 性能、生产多实例 session。当前 DB 是空的专用本地库，页面显示空数据是预期，不代表生产数据质量。

## 本地启动准备

本地强测试凭据已生成在：`C:\Users\喻远飞\.codex\local-admin-login-20261017.txt`。文件已设为只读，不在 Git、代码、文档或终端输出中；不要把其内容复制到日志或提交。

准备专用本地数据库后，复制/设置本地私有环境变量（不要覆盖已有 `.env`），至少包括：

```text
DEBUG=true
ADMIN_PASSWORD_LOGIN_ENABLED=true
ADMIN_SESSION_COOKIE_SECURE=false
ADMIN_AUTH_ALLOWED_ORIGINS=http://localhost:5173
```

启动顺序：在 `backend` 使用本地 Python/uvicorn 启动 admin 8101；再在 `frontend` 使用现有依赖启动 Vite 5173。浏览器只访问 `http://localhost:5173/login`。停止时关闭两个 loopback 进程，并用 `pg_ctl -D C:\Users\喻远飞\.codex\local-pg-admin-login-20261017-pgdata stop` 停止隔离数据库。

## 安全限制

- password login 使用独立 `ADMIN_PASSWORD_HASH`，不复用 SDK_CONFIG_TOKEN/ADMIN_TOKEN；login 不返回 session id 或 legacy token。
- session 只保存 hash、用户、时间和 CSRF；8 小时绝对 TTL，单实例内存，进程重启失效，容量 1000；多实例共享存储不在本轮范围。
- production 必须保持 Secure Cookie；只有显式 DEBUG 本地配置允许非 Secure cookie。
- health 只代表进程存活，不代表登录或数据库可用；验收必须调用 `/auth/me` 和 protected API。
