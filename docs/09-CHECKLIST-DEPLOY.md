# SDK 数据中台 — 上线检查清单

> 版本 v1.0 | 2026-07-14 | 部署前逐项确认

---

## 1. 安全配置（⚠️ 最高优先级）

- [ ] **数据库密码**：`.env` 中 `DATABASE_URL` 密码已从 `postgres` 改为强随机密码
- [ ] **ADMIN_TOKEN**：已用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成 ≥32 字符随机串，替换 `.env` 中的弱值
- [ ] **COS_SECRET_KEY**：`config.py` 已设 `repr=False`，不会出现在日志/错误输出中
- [ ] **DEBUG=false**：生产 `.env` 中 `DEBUG=false`（否则 SQL 语句会打印到日志）
- [ ] **CORS_ORIGINS**：生产环境已设置为实际前端域名（非 localhost）

## 2. 数据库

- [ ] PostgreSQL 已安装并运行（`systemctl status postgresql`）
- [ ] `sdk_platform` 数据库已创建
- [ ] `init_db.sql` 已执行（三张表 + 三个分区 + 两个物化视图）
- [ ] 初始数据已插入（`SELECT * FROM sdk_configs` 有 1 条 published 记录）
- [ ] 定时备份已配置（`crontab -l | grep pg_dump`）

## 3. 后端服务

- [ ] Python 虚拟环境已创建，依赖已安装（`pip install -r requirements.txt`）
- [ ] SDK API 服务已启动（`:8100`），`curl /health` 返回 `{"status":"ok"}`
- [ ] Admin API 服务已启动（`:8101`），`curl /api/admin/health` 返回 `{"status":"ok"}`
- [ ] Systemd 服务已配置并 enable（`sdk-api.service` + `sdk-admin.service`）
- [ ] 启动日志无报错（`journalctl -u sdk-api -n 20`）

## 4. Nginx

- [ ] 配置文件已创建（`/etc/nginx/sites-available/sdk-platform`）
- [ ] 站点已启用（`ln -s` 到 `sites-enabled`）
- [ ] `nginx -t` 语法检查通过
- [ ] `nginx -s reload` 重载成功
- [ ] HTTPS 证书已配置（Let's Encrypt certbot）

## 5. 前端

- [ ] 前端已构建（`npm run build`）并部署到 Nginx 静态目录
- [ ] 浏览器访问域名能正常打开管理后台
- [ ] 前端控制台无报错

## 6. 接口验证

- [ ] `GET /api/v1/version?platform=ios` — SDK 版本接口正常
- [ ] `GET /api/v1/config/meta?app_id=test` — 配置元信息接口正常
- [ ] `POST /api/v1/click` — 点击上报写入成功，DB 有数据
- [ ] `POST /api/v1/log` — 日志上报写入成功，DB 有数据
- [ ] `GET /api/admin/dashboard/summary` — 大盘数据正常（带正确 Admin Token）
- [ ] `GET /api/admin/configs` — 配置管理正常

## 7. 腾讯云 COS/CDN（Phase 3）

- [ ] COS 存储桶已创建
- [ ] COS SecretId/SecretKey 已填入 `.env`
- [ ] CDN 域名已配置
- [ ] 配置发布功能验证：新建草稿 → 发布 → CDN `latest.json` 可访问

## 8. 监控

- [ ] 健康检查脚本已部署（`/opt/scripts/health-check.sh`）
- [ ] 健康检查 cron 已配置（每 5 分钟）

---

> ✅ 全部打勾后即可上线 🍔
