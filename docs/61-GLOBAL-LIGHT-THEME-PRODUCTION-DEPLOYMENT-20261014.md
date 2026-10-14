# Global Light Theme Production Deployment

日期：2026-10-14  
业务源码 SHA：`937da4ee8e5d24ff70cb47195372caec3f793848`  
最终 master/doc HEAD：`36c18d625993a7b4c45aa7a5aa4bd2af26f48def`  
生产 release：`/www/releases/sdk-platform/36c18d625993a7b4c45aa7a5aa4bd2af26f48def`  
旧 release：`/www/releases/sdk-platform/6d9206c1f14b91cc785e3886b1dd5d995a134a1a`

## 发布前验证

- 主 checkout 已从 `689a92a` fast-forward 到 `36c18d6`；原有 dirty/untracked 文件保留。
- SSH GitHub 443 推送成功，远端 `master` 已核验为 `36c18d6`。
- 业务源码独立验证：34 个测试文件、206 个测试通过；`npm run build` 通过。
- backend 相对旧 release 的 `app` 目录逐文件比较无差异。
- 新 dist 由最终源码重新构建，709 modules transformed。

构建资产 SHA256：

```text
780fec0beef0873f3af5e189d18559932aed0514fa84f7422f6a46232b8bcc68  index.html
0d6f6511b13da9e1435e1588fdf5cd02bf56c203fb4da88936ad51fa985726b2  assets/index-JdilbtdR.js
2174d2f952f2cf2d31e9702f3de744ebe38344b7e176612db785c1e3a37934cc  assets/index-WHxw2r5Y.css
```

## 备份

备份目录：`/root/sdk-deploy-backups/20261014_074026_36c18d6`，目录及文件权限已收敛为目录 700、文件 600，四个 systemd drop-in 目录可遍历。

- PostgreSQL `pg_dump -Fc`：285801709 bytes；SHA256 `2f5420b503660ab23c6fe6be033e1a56be002286ca532f88dee7dcdfd93e62f5`。
- `pg_restore -l`：217 项；restore-list SHA256 `90680eafac78d3d752b3e424516cc7de845fda23e84230f44ddb53b58522d705`。
- 旧 release/dist、真实 env、四个 unit/drop-in、Nginx vhost 和 `/dev/null` 状态均已保存。

## 切换与运行态

- 新 release 使用共享 `/www/wwwroot/sdk-platform/backend/.env` symlink，并复用既有 `venv` symlink；`www-data` 实测可读 env、可执行 venv。
- `current` 已原子切换至新 release。
- `sdk-api.service`、`sdk-admin.service`、`sdk-log-export-worker.service`、`sdk-log-parse-worker.service` 均 active/running，`NRestarts=0`、`ExecMainStatus=0`、工作目录为 `current/backend`。
- `http://127.0.0.1:8100/health` 与 `http://127.0.0.1:8101/api/admin/health` 均返回 200 `{"status":"ok"}`。
- Nginx `-t` 成功并已 reload。

## HTTPS 与只读 API

使用 `curl --resolve sdk.deeppopgame.xyz:443:127.0.0.1 -k` 验证，HTTPS 获取的 index/JS/CSS SHA 与新 release dist 完全一致。

带服务器内存 token 的只读请求均返回 200：

- `/api/admin/configs`
- `/api/admin/usage-durations/summary`
- `/api/admin/log-analysis/parse-jobs/latest`

未执行写入型 config/parse/log API，未执行数据库 schema 迁移，8102 未触碰。

## 部署脚本收尾说明

首次部署脚本已完成备份、构建资产校验、原子切换和服务恢复；脚本尾部的相对 glob hash 输出未作为成功依据，随后已用绝对 release 路径重新核验三项资产 SHA。备份目录中的 drop-in 目录权限也已在切换后按 700 重新收敛并通过遍历校验；这些修正不改变生产 release 内容或服务状态。

## 回滚

回滚目标为旧 release `6d9206c1f14b91cc785e3886b1dd5d995a134a1a`，按既有 systemd restart、health、Nginx test/reload 流程执行，不覆盖数据库。
