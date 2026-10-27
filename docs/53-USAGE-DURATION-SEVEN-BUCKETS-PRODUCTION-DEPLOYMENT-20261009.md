# 使用时长七桶生产部署记录（2026-10-09）

## 结果

七桶功能已从远端最新 `master` 合并并部署生产，未改变上传协议、日志解析、配置接口或数据库 schema。

- 业务 release：`7f4c233df33f28cb94ef2b669d187cc166800ae7`
- 合并前 master：`04c7e8a2b751ba1934249afd2564db0211f3826d`
- 生产 `current`：`/www/releases/sdk-platform/7f4c233df33f28cb94ef2b669d187cc166800ae7`
- 旧回滚 release：`/www/releases/sdk-platform/726e3ae526391b8c6cd1d7cbc8fef539d4b136b5`
- 生产数据库：PostgreSQL 16.14；无迁移、无生产 parse job、无伪造日志/usage 数据
- 8102 保持原状；本次仅处理 8100、8101 和四个既有 systemd 服务

## 发布前证据

- 合并后后端：`427 passed, 2 skipped in 11.13s`
- 合并后前端：`31 passed (31)`、`188 passed (188)`
- 合并后 build：`708 modules transformed`，`built in 4.32s`
- PG14.22 本机集成：`1 passed`；独立临时 cluster、数据库已停止
- PG16 生产 loopback 专用集成：`1 passed, 1 warning in 1.21s`；专用数据库和角色已由 trap 精确清理

## 受控构建与资产

构建来自干净 detached worktree 的精确业务 SHA，source 使用 Git 原生 `git archive --format=tar.gz --output`，无顶层 prefix、无 `--strip-components`。

- source archive SHA256：`9acad14c3b41eb560bbbba6eb8e026d206b4905aef9f502f0e97286bd267ab6d`
- dist archive SHA256：`a3dec4e4bad3eadd1f7c375f562e94442e4b444c1a46ccccc596d2ffa6c5dc53`
- manifest SHA256：`891fd9bbdc70733bff01ab50e11841935f078fbc23902a44fa9c1f3359146264`

```text
ac803a9a5efe59524da622d9ab1a95a646aab6d71225eebaad0952fab711d664  assets/index-vvW1K-iP.js
1e835134433d13b6c9adb35d41b5a59e65321469ea7dbed38153b78d8662f3d1  assets/index-BNhNyNPT.css
5dac514b2aeba38904bbc9fb389bad87e66956eab11d41a033de29c686df2e60  index.html
```

生产新 release 的 manifest 校验三项均为 `OK`。本机 manifest、服务器文件及 loopback HTTPS 获取的 JS/CSS SHA256 一致；HTML 引用的 JS/CSS 路径一致。公网经过 Cloudflare 时可能注入 beacon，因此不将公网 index 整体响应声明为全 hash 相等。

## 备份

备份目录：`/root/sdk-deploy-backups/20261009_140000_7f4c233`

- 目录权限：`root:root 700`
- `sdk_platform.dump`：119638977 bytes，SHA256 `a396b4274e3af1d93c3f8b7f7ba2aa762fd56fcda9a006fbec41aaed956c0bf0`
- restore list：217 行，SHA256 `a44e1b8c57ecd50fab2f41aa3d63e65c1a662779c74f2d6c92268aba91686527`
- current release archive SHA256：`d79f9412f6b5544e587a33e012c79646782681a7f46be92165b412fc86025d9a`
- frontend dist archive SHA256：`019feb417ed6b79053193820fdd5eef8ceb24972130f1f69f682647ca804a4ba`
- env snapshot SHA256：`da1830abc833e2907e6ef7202540bc2eee19a6f8f413ea0e05f14a9afee76af9`
- systemd 按 unit 分目录保存，避免同名 drop-in 覆盖；Nginx 配置单独保存

共享 env 和兼容 venv 未递归 chmod；新 dist 文件为 644、目录为 755；`/dev/null` 核验为字符设备 `root:root 666 (1,3)`。

## 切换与运行态

首次切换因立即 curl 早于应用监听触发自动 rollback，未造成数据变更。只读日志确认是 readiness race：服务随后正常启动。第二次切换加入 60 秒 deadline 和 1 秒轮询，约第 7 秒通过 8100 `/health` 与 8101 `/api/admin/health`，随后完成 Nginx test/reload。

切换后：

- `sdk-api.service`、`sdk-admin.service`、`sdk-log-export-worker.service`、`sdk-log-parse-worker.service` 均 `active/running`
- 四服务 `NRestarts=0`、`ExecMainStatus=0`，工作目录均为 `/www/releases/sdk-platform/current/backend`
- SDK health 200；Admin health 200
- usage summary 200，2 个包的七桶顺序、count/share/total 逐包不变量全部通过
- 空包 summary 返回 200、零行；31 日越界返回 422；按需 devices 返回 200
- columns、package profile、latest parse job、metrics overview 均 200/code 0
- SDK config meta 通过鉴权到达，当前测试包无已发布配置，返回 404/code 1
- 最近 5 分钟四服务无 warning/alert；当前分钟 Nginx access log 5xx 为 0

## 回滚

如需回滚，使用备份的 Nginx 配置（当前 root 已指向 `current`），将 `current` 原子恢复至旧 release：

```bash
OLD=/www/releases/sdk-platform/726e3ae526391b8c6cd1d7cbc8fef539d4b136b5
CURRENT=/www/releases/sdk-platform/current
ln -s "$OLD" "$CURRENT.rollback.new"
mv -Tf "$CURRENT.rollback.new" "$CURRENT"
systemctl restart sdk-api.service sdk-admin.service sdk-log-export-worker.service sdk-log-parse-worker.service
/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload
```

回滚不覆盖数据库。

## Git 记录

本次业务提交已合并到本地 master；本文件是后续 docs-only 记录，提交并推送后 master/docs SHA 会领先生产业务 SHA，生产无需因文档重切换。主工作区原有 docs33、docs42、untracked 文件及旧 ef23 工作树 docs50 均未清理、未 reset、未 stash。
