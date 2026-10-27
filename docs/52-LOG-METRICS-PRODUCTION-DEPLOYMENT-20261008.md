# 日志分析、正式指标与使用时长生产部署记录（2026-10-08）

## 结论

业务 release `726e3ae526391b8c6cd1d7cbc8fef539d4b136b5` 已部署到生产主机
`adsense05-mdqsd.com`。本记录提交的是部署证据，不改变已运行的业务 release；本次文档提交不触发业务重切换。

- 生产 `current`：`/www/releases/sdk-platform/726e3ae526391b8c6cd1d7cbc8fef539d4b136b5`
- 备份目录：`/root/sdk-deploy-backups/20261008_094600_726e3ae52639`
- 数据库：PostgreSQL 16.14；未执行生产迁移、未创建生产解析任务、未注入生产解析数据
- 原旧 release：`/www/releases/sdk-platform/a822891065c7439cfa27cf70c11f26e6ea9cdf71`
- 旧端口 8102 未触碰

## 发布前验证

- 后端全量：`426 passed, 2 skipped`
- 前端单测：`31 passed (31)`；前端测试：`188 passed (188)`
- 前端 clean build：成功（Vite `built in 5.01s`）
- PG16 独立集成测试：`1 passed, 1 warning`；专用测试库和角色已清理，`sdk_platform` / `sdk_admin` 未触碰
- 线上备用数据库恢复清单：217 行

## 线上切换与验收

切换前执行了 `nginx -t`，随后原子更新 `current`，重启以下四个服务并 reload Nginx：

- `sdk-api.service`
- `sdk-admin.service`
- `sdk-log-export-worker.service`
- `sdk-log-parse-worker.service`

切换后四个服务均为 `active/running`，`NRestarts=0`，`ExecMainStatus=0`，且四者的 `ExecStart` / `WorkingDirectory` 均解析到 `/www/releases/sdk-platform/current/backend`。

只读 HTTP 验收结果：

- SDK health：HTTP 200，`{"status":"ok"}`
- Admin health：HTTP 200，`{"status":"ok"}`
- 日志分析 columns、package profiles、latest parse scope、metrics overview：HTTP 200，业务 code 0
- usage summary：HTTP 200，业务 code 0；空数据环境下返回 `total=0`，未伪造数据
- SDK config meta：协议可达且鉴权通过；当前包未发布配置，返回业务 404，未执行写入
- 最近 10 分钟四服务无 warning/alert；切换后 access log 最近分钟无 5xx

Nginx/CDN 资产核对采用服务器原文件、HTML 引用关系及 JS/CSS 内容 SHA256 三项证据。由于 Cloudflare 注入 beacon，公网 index 整体响应不可与构建文件宣称全 hash 相等；服务器原始 index、引用的 JS/CSS 及公网对应 JS/CSS 均匹配构建 manifest。

## 构建资产 manifest

```text
d9e048371e607f3c4a78b6d6c06ea2342f714657e4d087858684d357d5fa0098  assets/index-CZRrYRPq.js
0e5cb667b2dc17ffe739ddbfe33f1618464954173aeea2af85eae50415443320  assets/index-DrrWHy4L.css
7c87ebadf09d484dd08a23a02138a1baef2519fe7e6b651f9a812792774327ce  index.html
```

构建 dist 压缩包本地 SHA256：
`0F0429A5B14C21A2D6B94F295DB86ABFD53DFEC6EBE475A8A5A3F7E247CF5BE5`

## 备份与回滚

数据库 custom dump：

- 文件：`sdk_platform.dump`
- SHA256：`d5e92f421c29800ca69e97aa449367ab5d34d0d60913ad4240ad752e0af66bcb`

回滚目标为旧 release `a822891...`。回滚时恢复 Nginx 配置备份，移除本次新增的两个 `zz-release-current-726e3ae.conf` drop-in，原子恢复 `current`，再执行 daemon-reload、四服务重启和 `nginx -t` / reload。回滚不覆盖数据库。

## 过程偏差与防复发

发布过程中发现并修正了以下 staging/权限问题，均未影响旧 release 或数据库：

1. 首次 source 解包误用了 `--strip-components=1`；新 release 尚未切换即删除并按固定路径重新解包。
2. 一次人工校验误将 SHA 尾部写错；后续统一使用完整 release SHA `726e3ae526391b8c6cd1d7cbc8fef539d4b136b5` 和 manifest 校验。
3. 初始递归权限处理可能影响 tar 文件模式，已限定修正新 release 的 dist 目录：目录 755、文件 644；共享 env 仍为 `www-data:www-data 644`，旧 venv 仍为 `www-data:www-data 755`。
4. 一次远程命令误触 `/dev/null` 模式，已立即恢复为字符设备 `root:root 666 (1,3)`，并纳入部署后的主机检查。

后续命令模板固定使用完整 release 路径、`current` 原子切换、独立 systemd drop-in、先 `nginx -t` 后 reload；禁止使用 strip 解包、禁止依赖手填 SHA 尾部、禁止对 env/venv symlink 递归 chmod，且默认不迁移数据库、不运行生产 parse job。

## Git 状态

- 业务生产 release / 远端 `master`（部署时）：`726e3ae526391b8c6cd1d7cbc8fef539d4b136b5`
- 本文为部署后的 docs-only 记录；提交后 master/docs SHA 将不同于正在运行的业务 release，生产无需因本文档重切业务
- 用户原有脏文档和未跟踪文件保持不变，未 reset、stash、clean 或覆盖
