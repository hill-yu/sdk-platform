# SDK 数据中台部署流程

> 日期：2026-07-30  
> 适用项目：`D:\code\SDK`  
> 部署目标：一台 Linux 服务器承载 Nginx、SDK API、Admin API、Vue 管理后台和 PostgreSQL；配置文件与 SDK 包通过腾讯云 COS + CDN 分发。

## 1. 部署拓扑

```text
外部访问
  |
  v
Nginx 80/443
  |-- /api/v1/*     -> SDK API    127.0.0.1:8100
  |-- /api/admin/*  -> Admin API  127.0.0.1:8101
  |-- /             -> Vue dist 静态文件

SDK API / Admin API
  |
  v
PostgreSQL 15+

Admin API 发布配置
  |
  v
腾讯云 COS + CDN
  |-- /config/latest.json
  |-- /config/v*.json
  |-- /sdk/*
```

## 2. 部署前准备

### 2.1 服务器

建议配置：

| 项目 | 建议 |
|---|---|
| 操作系统 | Ubuntu 22.04 LTS / Ubuntu 24.04 LTS |
| CPU / 内存 | 2C4G 起步 |
| 磁盘 | 80 GB 起步，按事件量扩容 |
| Python | 3.11+；Ubuntu 24.04 默认使用 Python 3.12 |
| Node.js | 18+ |
| PostgreSQL | 15+ |
| Nginx | 1.20+ |

### 2.2 域名规划

| 用途 | 示例 |
|---|---|
| 管理后台和 API 域名 | `https://sdk-admin.example.com` |
| CDN 域名 | `https://cdn.example.com` |

### 2.3 安全材料

部署前准备：

- PostgreSQL 用户密码；
- `ADMIN_TOKEN`，至少 32 位强随机字符串；
- 腾讯云 COS `SecretId` 和 `SecretKey`；
- COS Bucket 名称和地域；
- CDN 域名；
- HTTPS 证书，或使用 Let’s Encrypt 自动签发。

生成 `ADMIN_TOKEN`：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 3. 服务器初始化

```bash
sudo apt update
sudo apt upgrade -y

sudo apt install -y \
  nginx \
  postgresql postgresql-contrib \
  python3 python3-venv python3-dev \
  build-essential curl git

curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

sudo systemctl enable nginx postgresql
sudo systemctl start nginx postgresql
```

Ubuntu 24.04 的系统代号是 `noble`，默认 Python 是 3.12，官方仓库通常没有 `python3.11`、`python3.11-venv`、`python3.11-dev`。因此生产部署建议直接使用 `python3`、`python3-venv`、`python3-dev`。本项目依赖兼容 Python 3.12。

如果服务器已经安装了宝塔面板或已有 Nginx，`sudo systemctl enable nginx` / `sudo systemctl start nginx` 可能因为既有 Nginx 配置失败。先执行：

```bash
sudo nginx -t
sudo systemctl status nginx --no-pager
sudo journalctl -xeu nginx.service --no-pager | tail -n 80
```

只有 `nginx -t` 通过后再启动：

```bash
sudo systemctl restart nginx
```

创建部署目录：

```bash
sudo mkdir -p /www/wwwroot/sdk-platform
sudo chown -R "$USER:$USER" /www/wwwroot/sdk-platform
```

## 4. 数据库部署

创建数据库和用户：

```bash
sudo -u postgres psql
```

```sql
CREATE USER sdk_admin WITH PASSWORD '替换为强密码';
CREATE DATABASE sdk_platform OWNER sdk_admin ENCODING 'UTF8';
\c sdk_platform
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
\q
```

初始化表、分区、物化视图和维护函数：

```bash
cd /www/wwwroot/sdk-platform
psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" \
  -f scripts/init_db.sql
```

如果是旧库升级，并且缺少 `cos_upload_status` 字段，再执行：

```bash
psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" \
  -f scripts/migrate_cos_upload_status.sql
```

检查：

```bash
psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" -c "\dt"
psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" -c "\d+ mv_daily_event_stats"
```

## 5. 后端部署

### 5.1 上传代码

推荐使用 Git 拉取：

```bash
cd /www/wwwroot/sdk-platform
git clone <你的仓库地址> .
```

也可以本地打包上传：

```bash
cd D:\code\SDK
tar -czf sdk-platform.tar.gz backend scripts frontend docs
scp sdk-platform.tar.gz user@服务器:/www/wwwroot/sdk-platform/
```

服务器解压：

```bash
cd /www/wwwroot/sdk-platform
tar -xzf sdk-platform.tar.gz
```

### 5.2 创建 Python 环境

```bash
cd /www/wwwroot/sdk-platform/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.3 配置环境变量

创建 `/www/wwwroot/sdk-platform/backend/.env`：

```env
APP_NAME=SDK Platform
DEBUG=false
LOG_LEVEL=INFO

DB_PASSWORD=替换为数据库密码
DATABASE_URL=postgresql+asyncpg://sdk_admin:${DB_PASSWORD}@127.0.0.1:5432/sdk_platform

SDK_API_PORT=8100
ADMIN_API_PORT=8101
ADMIN_TOKEN=替换为强随机Token

COS_SECRET_ID=替换为腾讯云SecretId
COS_SECRET_KEY=替换为腾讯云SecretKey
COS_REGION=ap-guangzhou
COS_BUCKET=替换为真实Bucket
CDN_BASE_URL=https://cdn.example.com

CORS_ORIGINS=https://sdk-admin.example.com
```

注意：

- `ADMIN_TOKEN` 不能为空，不能太短，不能包含 `admin` 或 `change-me`。
- `COS_BUCKET` 和 `CDN_BASE_URL` 不能保留示例值，否则 Admin API 会拒绝启动。
- 生产环境不要把 `.env` 提交到 Git。

### 5.4 本地启动验证

```bash
cd /www/wwwroot/sdk-platform/backend
source venv/bin/activate

python -m uvicorn app.sdk_main:app --host 127.0.0.1 --port 8100
```

另开终端验证：

```bash
curl http://127.0.0.1:8100/health
```

Admin API 验证：

```bash
python -m uvicorn app.admin_main:app --host 127.0.0.1 --port 8101
curl http://127.0.0.1:8101/api/admin/health
```

## 6. systemd 服务

### 6.1 SDK API

创建 `/etc/systemd/system/sdk-api.service`：

```ini
[Unit]
Description=SDK Platform SDK API
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/www/wwwroot/sdk-platform/backend
EnvironmentFile=/www/wwwroot/sdk-platform/backend/.env
Environment=PATH=/www/wwwroot/sdk-platform/backend/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/www/wwwroot/sdk-platform/backend/venv/bin/python -m uvicorn app.sdk_main:app --host 127.0.0.1 --port 8100
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 6.2 Admin API

创建 `/etc/systemd/system/sdk-admin.service`：

```ini
[Unit]
Description=SDK Platform Admin API
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/www/wwwroot/sdk-platform/backend
EnvironmentFile=/www/wwwroot/sdk-platform/backend/.env
Environment=PATH=/www/wwwroot/sdk-platform/backend/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/www/wwwroot/sdk-platform/backend/venv/bin/python -m uvicorn app.admin_main:app --host 127.0.0.1 --port 8101
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

授权并启动：

```bash
sudo chown -R www-data:www-data /www/wwwroot/sdk-platform/backend
sudo systemctl daemon-reload
sudo systemctl enable sdk-api sdk-admin
sudo systemctl start sdk-api sdk-admin

sudo systemctl status sdk-api
sudo systemctl status sdk-admin
```

查看日志：

```bash
sudo journalctl -u sdk-api -f
sudo journalctl -u sdk-admin -f
```

## 7. 前端部署

在服务器构建：

```bash
cd /www/wwwroot/sdk-platform/frontend
npm ci
npm run build
```

构建产物路径：

```text
/www/wwwroot/sdk-platform/frontend/dist
```

如果在本地构建后上传，只需要上传 `frontend/dist`。

## 8. Nginx 配置

在 `/etc/nginx/nginx.conf` 的 `http` 块中加入限流区：

```nginx
limit_req_zone $binary_remote_addr zone=sdk_write_api:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=sdk_conn:10m;
```

创建 `/etc/nginx/sites-available/sdk-platform`：

```nginx
server {
    listen 80;
    server_name sdk-admin.example.com;

    root /www/wwwroot/sdk-platform/frontend/dist;
    index index.html;

    client_max_body_size 5m;

    location /api/v1/ {
        limit_req zone=sdk_write_api burst=5 nodelay;
        limit_conn sdk_conn 10;
        client_max_body_size 1m;

        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/admin/ {
        client_max_body_size 5m;

        proxy_pass http://127.0.0.1:8101;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    access_log /var/log/nginx/sdk-platform-access.log;
    error_log /var/log/nginx/sdk-platform-error.log;
}
```

启用：

```bash
sudo ln -s /etc/nginx/sites-available/sdk-platform /etc/nginx/sites-enabled/sdk-platform
sudo nginx -t
sudo systemctl reload nginx
```

## 9. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d sdk-admin.example.com
sudo certbot renew --dry-run
```

签发成功后，确认：

```bash
curl -I https://sdk-admin.example.com
curl https://sdk-admin.example.com/health
```

## 10. COS + CDN 配置

### 10.1 COS

1. 创建 Bucket，例如 `sdk-config-bucket`。
2. 地域与 `.env` 中 `COS_REGION` 保持一致。
3. 授权 Admin API 使用的腾讯云密钥具备对象上传、覆盖、读取权限。
4. 配置 CDN 回源需要的访问权限。

### 10.2 CDN

1. 新增 CDN 域名，例如 `cdn.example.com`。
2. 源站选择 COS Bucket。
3. 配置缓存规则：
   - `/config/latest.json`：建议 300 秒；
   - `/config/v*.json`：可设置较长缓存；
   - `/sdk/*`：可设置较长缓存。
4. DNS CNAME 指向腾讯云 CDN 提供的地址。
5. `.env` 中设置：

```env
CDN_BASE_URL=https://cdn.example.com
```

## 11. 发布后验证

### 11.1 基础健康检查

```bash
curl https://sdk-admin.example.com/health
curl https://sdk-admin.example.com/api/admin/health
```

预期：

```json
{"status":"ok"}
```

### 11.2 SDK API

版本接口：

```bash
curl "https://sdk-admin.example.com/api/v1/version?platform=ios&current_version=0"
```

配置元信息接口：

```bash
curl "https://sdk-admin.example.com/api/v1/config/meta?app_id=test"
```

点击上报：

```bash
curl -X POST "https://sdk-admin.example.com/api/v1/click" \
  -H "Content-Type: application/json" \
  -d '{"app_id":"test","device_id":"dev-001","events":[{"type":"click","page":"home","element":"button"}]}'
```

日志上报：

```bash
curl -X POST "https://sdk-admin.example.com/api/v1/log" \
  -H "Content-Type: application/json" \
  -d '{"app_id":"test","device_id":"dev-001","logs":[{"level":"info","message":"hello"}]}'
```

### 11.3 Admin API

```bash
curl "https://sdk-admin.example.com/api/admin/configs" \
  -H "Authorization: Bearer 替换为ADMIN_TOKEN"
```

```bash
curl "https://sdk-admin.example.com/api/admin/versions?platform=ios" \
  -H "Authorization: Bearer 替换为ADMIN_TOKEN"
```

### 11.4 前端

浏览器访问：

```text
https://sdk-admin.example.com
```

首次进入会提示输入 `ADMIN_TOKEN`。输入后确认：

- 数据大盘页面可打开；
- 配置管理页面可列出配置；
- 版本管理页面可列出版本；
- 新建配置并发布时 COS 上传成功。

## 12. 日常发布流程

### 12.1 后端更新

```bash
cd /www/wwwroot/sdk-platform
git pull

cd backend
source venv/bin/activate
pip install -r requirements.txt

cd /www/wwwroot/sdk-platform
python -m pytest backend/tests -q

sudo systemctl restart sdk-api sdk-admin
sudo systemctl status sdk-api sdk-admin
```

### 12.2 前端更新

```bash
cd /www/wwwroot/sdk-platform/frontend
npm ci
npm run build
sudo systemctl reload nginx
```

### 12.3 数据库变更

```bash
pg_dump "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" \
  > /backup/sdk_platform_before_change_$(date +%Y%m%d_%H%M%S).sql

psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" \
  -f scripts/需要执行的迁移.sql

sudo systemctl restart sdk-api sdk-admin
```

## 13. 定时维护

### 13.1 数据库备份

```bash
sudo mkdir -p /backup/sdk-platform
```

crontab：

```cron
0 2 * * * pg_dump "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" > /backup/sdk-platform/sdk_platform_$(date +\%Y\%m\%d).sql
```

### 13.2 分区维护

每月 25 日创建下月分区：

```cron
0 3 25 * * psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" -c "SELECT create_next_partition();"
```

按保留期清理旧分区：

```cron
30 3 * * * psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" -c "SELECT cleanup_old_partitions(90);"
```

### 13.3 物化视图刷新

Admin API 进程启动后会每 5 分钟执行：

```sql
SELECT refresh_materialized_views();
```

如果 Admin API 未运行，大盘数据不会自动刷新。可临时手动执行：

```bash
psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" \
  -c "SELECT refresh_materialized_views();"
```

## 14. 回滚流程

### 14.1 后端回滚

```bash
cd /www/wwwroot/sdk-platform
git log --oneline -5
git checkout <上一个稳定提交>

cd backend
source venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart sdk-api sdk-admin
curl http://127.0.0.1:8100/health
curl http://127.0.0.1:8101/api/admin/health
```

### 14.2 前端回滚

建议每次部署前保留上一版：

```bash
cd /www/wwwroot/sdk-platform/frontend
cp -a dist dist_backup_$(date +%Y%m%d_%H%M%S)
```

回滚：

```bash
rm -rf dist
cp -a dist_backup_YYYYMMDD_HHMMSS dist
sudo systemctl reload nginx
```

### 14.3 数据库回滚

仅在迁移失败或数据污染时执行：

```bash
psql "postgresql://sdk_admin:替换为强密码@127.0.0.1:5432/sdk_platform" \
  < /backup/sdk_platform_before_change_YYYYMMDD_HHMMSS.sql

sudo systemctl restart sdk-api sdk-admin
```

## 15. 故障排查

| 现象 | 排查命令 | 常见原因 |
|---|---|---|
| SDK API 502 | `sudo journalctl -u sdk-api -n 100` | 服务未启动、依赖安装失败、数据库连接失败 |
| Admin API 启动失败 | `sudo journalctl -u sdk-admin -n 100` | `ADMIN_TOKEN` 太弱、COS/CDN 仍是占位符 |
| 前端空白 | `sudo tail -n 100 /var/log/nginx/sdk-platform-error.log` | `dist` 路径错误、构建失败 |
| 管理后台 401 | 浏览器重新输入 Token | `ADMIN_TOKEN` 不一致 |
| 大盘无数据 | `SELECT refresh_materialized_views();` | 事件表无数据、物化视图未刷新 |
| 配置发布失败 | 查看 Admin API 日志 | COS 密钥、Bucket、地域或权限错误 |
| SDK 写入 429 | 查看 Nginx 和应用日志 | 单 IP 超过 10 次/秒写入限制 |

## 16. 上线检查清单

- [ ] PostgreSQL 已创建 `sdk_platform` 数据库。
- [ ] `scripts/init_db.sql` 已执行成功。
- [ ] `.env` 使用真实 `ADMIN_TOKEN`、COS、CDN、数据库配置。
- [ ] `sdk-api.service` 和 `sdk-admin.service` 均为 `active`。
- [ ] Nginx `nginx -t` 通过。
- [ ] HTTPS 证书可用。
- [ ] `/health` 返回 200。
- [ ] `/api/admin/health` 返回 200。
- [ ] 前端管理后台可访问。
- [ ] Admin API 请求携带 Token 后可访问。
- [ ] click/log 上报可以写入。
- [ ] COS + CDN 发布配置成功。
- [ ] 数据库备份和分区维护 crontab 已配置。

## 17. 本地发布前验证

在本地或 CI 中执行：

```bash
cd D:\code\SDK
python -m pytest backend/tests -q

cd D:\code\SDK\frontend
npm ci
npm run build
```

也可以执行项目已有脚本：

```bash
cd D:\code\SDK
bash scripts/deploy.sh
```

该脚本当前只负责构建前端和运行后端测试，不会自动上传或重启服务器。
