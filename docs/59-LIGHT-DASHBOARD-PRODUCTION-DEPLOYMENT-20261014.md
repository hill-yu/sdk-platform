# Light Dashboard 生产部署记录（2026-10-14）

## 发布版本

- 业务 SHA：`6d9206c1f14b91cc785e3886b1dd5d995a134a1a`
- 发布前远端 `master`：已通过 GitHub SSH/443 fast-forward 至同一业务 SHA。
- 生产新 release：`/www/releases/sdk-platform/6d9206c1f14b91cc785e3886b1dd5d995a134a1a`
- 旧回滚 release：`/www/releases/sdk-platform/9e354fda65f73371004b384edd1446d6dc214968`
- 后端相对旧 release 逐文件零差异；无数据库迁移、无 parse/config/log 写入。
- 8102 未触碰。

## 发布前验证

- 前端全量测试：33 个测试文件、202/202 通过。
- 前端生产构建：709 modules transformed，`npm run build` 通过。
- 新 dist 由业务 SHA 全新构建，未复用生产旧 dist。
- `git diff --check` 通过；相对 `d15e49e075d6cd7c80d997834be94d395d7c3171` 的 `backend/` 无差异。

构建资产 SHA256：

```text
4736ed2658d9edef223151dcebe6b0593e3c75f7b20978af74895fac5b62b07d  index.html
10a608e91f22a1b56488e09587e2bc2b07dfcbdd42c31a910c500e416eb88157  assets/index-DuqG5LYW.js
53050f24e3f703ea1633e9a775dbc0d87c493ee0662b542609a44c6faba95934  assets/index-B7VNT78I.css
```

## 备份

备份目录：`/root/sdk-deploy-backups/20261014_063209_6d9206c`，目录权限 700。

- `sdk_platform.dump`：285434174 bytes，SHA256 `02e2a0bac99200eebe8dfe884f4bf890d0994ecf336218ccd30a2e9c21814aff`
- `sdk_platform.restore-list`：已由 `pg_restore -l` 校验，SHA256 `f895d912c713d4f6af9433ed17f77814dec152a712fa9c6666e8b2bcd491497f`
- 旧 release archive：SHA256 `1d66d34a382f3be436dc44bd019d0b3674a16f6e4c07794b41f00508a06c27d0`
- 旧 frontend dist archive：SHA256 `68343a3b23a7fb49f3bdfbfbd571cd476db7beb34f4bbe0e9956733ca4e4eb31`
- 真实共享 env 快照：SHA256 `da1830abc833e2907e6ef7202540bc2eee19a6f8f413ea0e05f14a9afee76af9`
- 四个 systemd unit/drop-in、Nginx vhost、`/dev/null` 状态均已保存；`/dev/null` 保持字符设备 666。

数据库备份使用 `runuser -u postgres -- pg_dump -Fc -d sdk_platform`，没有创建临时业务数据。

## 切换与运行态

- 新 release 通过精确 source archive 解包，frontend dist 单独校验后写入。
- 新 release 的 `backend/.env` 复用 `/www/wwwroot/sdk-platform/backend/.env` symlink；venv 复用既有 `/www/releases/sdk-platform/86a03f3f6b532ca3f7cf34485749b240a999e20c/backend/venv` symlink。
- 文件/目录权限按 644/755 处理；`www-data` 实际可读 env、可执行 venv。
- `current` 原子切换至业务 release 后重启四个既有 unit；健康 deadline 60 秒内通过。
- `sdk-api.service`、`sdk-admin.service`、`sdk-log-export-worker.service`、`sdk-log-parse-worker.service` 均 `active/running`、`NRestarts=0`、`ExecMainStatus=0`，工作目录均为 `current/backend`。
- Nginx `-t` 与 reload 成功；root 保持 `/www/releases/sdk-platform/current/frontend/dist`。

## 只读接口与 HTTPS 验证

- `http://127.0.0.1:8100/health`：200。
- `http://127.0.0.1:8101/api/admin/health`：200。
- 带真实 token 的只读 `/api/admin/configs`：200。
- 带真实 token 的只读 usage summary：200。
- 带真实 token、有效北京时间范围的只读 latest parse job：200。
- `curl --resolve sdk.deeppopgame.xyz:443:127.0.0.1 -k` 实域名 HTTPS：200。
- HTTPS 获取的 `index.html`、JS、CSS SHA256 分别与新 release dist 完全一致。
- token 仅在服务器 shell 内存中使用，未输出；未执行写入型 API。

## 前端视觉说明

- 桌面 1536×1024 最终截图可见 SDK 品牌、数据大盘标题、四项指标、双轴趋势、1:3 分布/明细布局、8 条明细与分页。
- 390×844 移动截图仍存在右侧统计卡、趋势第二控件与 UV 轴裁切，移动端限制按审批要求透明保留，不宣称移动端视觉验收通过。
- Chrome headless DOM rect/overflow 测量在本机超时，未伪造测量数据。

## 回滚

如需回滚：

```bash
OLD=/www/releases/sdk-platform/9e354fda65f73371004b384edd1446d6dc214968
CURRENT=/www/releases/sdk-platform/current
ln -s "$OLD" "$CURRENT.rollback.new"
mv -Tf "$CURRENT.rollback.new" "$CURRENT"
systemctl restart sdk-api.service sdk-admin.service sdk-log-export-worker.service sdk-log-parse-worker.service
/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload
```

回滚不覆盖数据库。
