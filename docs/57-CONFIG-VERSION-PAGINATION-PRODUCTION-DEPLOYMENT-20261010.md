# ConfigManager 版本分页生产发布记录（2026-10-10）

## 发布版本

- 业务 SHA：`9e354fda65f73371004b384edd1446d6dc214968`
- 远端 `master`：已推送至同一 SHA。
- 生产 current：`/www/releases/sdk-platform/9e354fda65f73371004b384edd1446d6dc214968`
- 回滚 release：`/www/releases/sdk-platform/54b7c0f3991deb562a71a113c61d00971dc28c73`
- 后端 `backend/app` 与回滚 release 逐文件比较无差异；解析参数修复和七桶实现保留。

## 发布前验证

- 主 checkout 在精确 SHA 上执行 `npm ci`、全量前端测试和构建。
- 全量测试：31 个测试文件，196/196 通过。
- 构建：`vue-tsc --noEmit && vite build` 通过，708 modules transformed。
- 生产新 dist 由该 SHA 全新构建，未复用旧 dist。

## 备份

备份目录：`/root/sdk-deploy-backups/20261010_065957_9e354fd`，目录 700，文件 600。

- PostgreSQL `pg_dump -Fc`：`sdk_platform.dump`，SHA256 `ac1c22389e6bc765c96b6f46ec9c4d4d12be97bd7e6b29a3eb116ba72ac4e80c`。
- `pg_restore -l` 清单：SHA256 `89664252cce070fac5e364cf5bed4450e1f277ee981ad00601632c4dad258a1e`。
- 旧 release、旧 dist、真实 env 快照、四个 systemd unit 及 drop-in 目录、Nginx 配置均已保存。
- env 快照为真实文件，不是 symlink。

## 切换与回滚

首次切换因新 release 将 `.env` 错误复制为 root-only 文件，`www-data` 无法读取，健康 deadline 未通过；已立即原子回滚至 `54b7c0f`，服务恢复正常。

随后修正为复用既有 `/www/wwwroot/sdk-platform/backend/.env` symlink，并验证 `www-data` 可读后再次原子切换成功。新切换后的四个 unit 均 active/running，`NRestarts=0`、`ExecMainStatus=0`，工作目录均为 `current/backend`。健康检查第 5 秒通过：

```text
8100 /health       {"status":"ok"}
8101 /api/admin/health  {"status":"ok"}
```

Nginx 配置测试和 reload 成功；未执行数据库 schema 迁移，未创建配置草稿、解析任务或日志测试数据。

## 静态与 HTTPS 验证

Nginx root 保持 `/www/releases/sdk-platform/current/frontend/dist`。本地构建与真实 HTTPS（`curl --resolve sdk.deeppopgame.xyz:443:127.0.0.1`）响应 hash 一致：

- `index.html`：`3747fd01ea6aa346075f43a8fc0aa3e149932e1e588ad644a321420eeff86524`
- `index-zfrtKv7D.js`：`a962008512d9470575fc52184e7dd95b63eaf55519e9bb0515dcaf1259a21a8e`
- `index-Be68ogoR.css`：`85780398e7435b1d1c814ac840e484016fa2561b98a40c4a77f2b14dab41abca`

HTTPS `/health` 返回 200；带生产 token 的只读 `/api/admin/configs` 返回 `200 application/json`。

## 浏览器说明

本地 Chrome CDP 在最终 CSS 修正后无法稳定建立 websocket，未将旧截图冒充最终视觉证据。分页行为由 23 个 ConfigManager 定向测试、196 个全量前端测试及本地构建验证；生产发布未依赖写入型浏览器操作。
