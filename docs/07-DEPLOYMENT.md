# SDK 数据中台 + 配置管理系统 — 部署流程文档

> 版本 v1.0 | 2026-06-30

---

## 1. 部署架构

```
┌──────────────────────────────────────────────┐
│              腾讯云轻量服务器                  │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │  Nginx   │  │ SDK API  │  │ Admin API  │ │
│  │  :80/443 │──│  :8100   │  │  :8101     │ │
│  └────┬─────┘  └────┬─────┘  └────┬───────┘ │
│       │             │             │          │
│       │  静态资源    │             │          │
│       ▼             ▼             ▼          │
│  ┌──────────┐  ┌──────────────────────┐      │
│  │ dist/    │  │     PostgreSQL :5432  │      │
│  │ (Vue3)   │  │     sdk_platform     │      │
│  └──────────┘  └──────────────────────┘      │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│           腾讯云 COS + CDN                    │
│  config/latest.json   ← 配置文件             │
│  sdk/ios/*.zip        ← SDK 安装包           │
└──────────────────────────────────────────────┘
```

---

## 2. 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| 操作系统 | Ubuntu 20.04+ / CentOS 7+ | 腾讯云轻量服务器 |
| Python | 3.11+ | 后端运行环境 |
| PostgreSQL | 15+ | 数据库 |
| Nginx | 1.20+ | 反向代理 + 静态资源 |
| Node.js | 18+ | 前端构建 |

---

## 3. 首次部署

### 3.1 服务器初始化

```bash
# 1. 更新系统
sudo apt update && sudo apt upgrade -y

# 2. 安装 PostgreSQL
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql

# 3. 安装 Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 4. 安装 Nginx
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx

# 5. 安装 Node.js 18
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

### 3.2 创建数据库

```bash
# 切换到 postgres 用户
sudo -u postgres psql

-- 创建用户和数据库
CREATE USER sdk_admin WITH PASSWORD 'your_strong_password_here';
CREATE DATABASE sdk_platform OWNER sdk_admin ENCODING 'UTF8';
\c sdk_platform
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
\q
```

### 3.3 部署后端

```bash
# 1. 创建目录
sudo mkdir -p /www/wwwroot/sdk-platform
sudo chown -R $USER:$USER /www/wwwroot/sdk-platform

# 2. 上传代码（从本地打包上传）
# 本地执行：
cd D:\code\SDK
tar -czf backend.tar.gz backend/ scripts/
# 上传到服务器：
scp backend.tar.gz user@your-server:/www/wwwroot/sdk-platform/

# 3. 服务器上解压
cd /www/wwwroot/sdk-platform
tar -xzf backend.tar.gz

# 4. 创建虚拟环境
cd backend
python3.11 -m venv venv
source venv/bin/activate

# 5. 安装依赖
pip install -r requirements.txt

# 6. 配置环境变量
cp .env.example .env
vim .env  # 修改以下内容：
```

**.env 文件内容：**
```env
DATABASE_URL=postgresql+asyncpg://sdk_admin:your_strong_password_here@localhost:5432/sdk_platform
DEBUG=false
LOG_LEVEL=INFO
ADMIN_TOKEN=your_admin_token_here
COS_SECRET_ID=your_tencent_cloud_secret_id
COS_SECRET_KEY=your_tencent_cloud_secret_key
COS_REGION=ap-guangzhou
COS_BUCKET=sdk-config-bucket
CDN_BASE_URL=https://cdn.example.com
```

```bash
# 7. 初始化数据库
psql -U sdk_admin -d sdk_platform -f ../scripts/init_db.sql

# 8. 验证后端能启动
python -m app.sdk_main
# 看到 "Uvicorn running on http://0.0.0.0:8100" 即成功
# Ctrl+C 退出
```

### 3.4 部署前端

```bash
# 1. 本地构建前端
cd D:\code\SDK\frontend
npm install
npm run build

# 2. 上传 dist 目录到服务器
scp -r dist/ user@your-server:/www/wwwroot/sdk-platform/frontend/

# 3. 或直接在服务器上构建：
# cd /www/wwwroot/sdk-platform/frontend && npm install && npm run build
```

### 3.5 配置 Nginx

```bash
sudo vim /etc/nginx/sites-available/sdk-platform
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 管理后台前端静态文件
    root /www/wwwroot/sdk-platform/frontend/dist;
    index index.html;

    # SDK API → :8100
    location /api/v1/ {
        client_max_body_size 1m;
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 管理后台 API → :8101
    location /api/admin/ {
        client_max_body_size 5m;
        proxy_pass http://127.0.0.1:8101;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 前端路由（SPA fallback）
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 日志
    access_log /var/log/nginx/sdk-platform-access.log;
    error_log /var/log/nginx/sdk-platform-error.log;
}
```

```bash
# 启用站点
sudo ln -s /etc/nginx/sites-available/sdk-platform /etc/nginx/sites-enabled/
sudo nginx -t          # 测试配置
sudo nginx -s reload   # 重载
```

### 3.6 配置 Systemd 服务

#### SDK API 服务

```bash
sudo vim /etc/systemd/system/sdk-api.service
```

```ini
[Unit]
Description=SDK Platform - SDK API Service
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/www/wwwroot/sdk-platform/backend
Environment=PATH=/www/wwwroot/sdk-platform/backend/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/www/wwwroot/sdk-platform/backend/venv/bin/python -m uvicorn app.sdk_main:app --host 0.0.0.0 --port 8100
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Admin API 服务

```bash
sudo vim /etc/systemd/system/sdk-admin.service
```

```ini
[Unit]
Description=SDK Platform - Admin API Service
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/www/wwwroot/sdk-platform/backend
Environment=PATH=/www/wwwroot/sdk-platform/backend/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/www/wwwroot/sdk-platform/backend/venv/bin/python -m uvicorn app.admin_main:app --host 0.0.0.0 --port 8101
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 启用并启动服务
sudo systemctl daemon-reload
sudo systemctl enable sdk-api sdk-admin
sudo systemctl start sdk-api sdk-admin

# 检查状态
sudo systemctl status sdk-api
sudo systemctl status sdk-admin
```

---

## 4. 日常运维

### 4.1 服务管理

```bash
# 启动
sudo systemctl start sdk-api sdk-admin

# 停止
sudo systemctl stop sdk-api sdk-admin

# 重启
sudo systemctl restart sdk-api sdk-admin

# 查看状态
sudo systemctl status sdk-api sdk-admin

# 查看日志
sudo journalctl -u sdk-api -f    # 实时
sudo journalctl -u sdk-api -n 50 # 最近 50 行
```

### 4.2 代码更新流程

```bash
# === 后端更新 ===

# 1. 本地打包
cd D:\code\SDK
tar -czf backend.tar.gz backend/

# 2. 上传到服务器
scp backend.tar.gz user@your-server:/www/wwwroot/sdk-platform/

# 3. 服务器上更新
ssh user@your-server
cd /www/wwwroot/sdk-platform
tar -xzf backend.tar.gz
cd backend
source venv/bin/activate
pip install -r requirements.txt  # 如有新增依赖

# 4. 执行数据库迁移
psql -U sdk_admin -d sdk_platform -f ../scripts/migrate_cos_upload_status.sql
if [ $? -ne 0 ]; then
    echo "数据库迁移失败，禁止重启服务"
    exit 1
fi

# 5. 重启服务
sudo systemctl restart sdk-api sdk-admin

# 6. 验证
curl http://localhost:8100/health
curl http://localhost:8101/api/admin/health \
  -H "Authorization: Bearer your_admin_token_here"

# === 前端更新 ===

# 1. 本地构建
cd D:\code\SDK\frontend
npm run build

# 2. 上传
scp -r dist/ user@your-server:/www/wwwroot/sdk-platform/frontend/

# 3. 替换旧文件
ssh user@your-server
cd /www/wwwroot/sdk-platform/frontend
rm -rf dist-old && mv dist dist-new && mv dist-old dist 2>/dev/null; mv dist-new dist

# Nginx 不需要重启（静态文件直接生效）
```

### 4.3 PostgreSQL 维护

```bash
# 备份数据库
pg_dump -U sdk_admin sdk_platform > /backup/sdk_platform_$(date +%Y%m%d).sql

# 恢复数据库
psql -U sdk_admin sdk_platform < /backup/sdk_platform_20260630.sql

# 设置定时备份（crontab）
0 2 * * * pg_dump -U sdk_admin sdk_platform > /backup/sdk_platform_$(date +\%Y\%m\%d).sql

# 清理过期分区（保留 90 天数据）
psql -U sdk_admin -d sdk_platform -c "SELECT cleanup_old_partitions(90);"

# 创建下月分区（每月 25 号执行）
psql -U sdk_admin -d sdk_platform -c "SELECT create_next_partition();"
```

---

## 5. HTTPS 配置（Let's Encrypt）

```bash
# 安装 certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期（已自动配置）
sudo certbot renew --dry-run
```

---

## 6. 监控 & 健康检查

### 6.1 健康检查接口

| 服务 | 地址 | 预期响应 |
|------|------|---------|
| SDK API | `GET /health` | `{"status":"ok"}` |
| Admin API | `GET /api/admin/health` | `{"status":"ok"}` |

### 6.2 基础监控脚本

```bash
#!/bin/bash
# /opt/scripts/health-check.sh

SDK_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/health)
ADMIN_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8101/api/admin/health)

if [ "$SDK_HEALTH" != "200" ]; then
    echo "[ERROR] SDK API health check failed: $SDK_HEALTH"
    sudo systemctl restart sdk-api
fi

if [ "$ADMIN_HEALTH" != "200" ]; then
    echo "[ERROR] Admin API health check failed: $ADMIN_HEALTH"
    sudo systemctl restart sdk-admin
fi
```

```bash
# 每 5 分钟检查一次
*/5 * * * * /opt/scripts/health-check.sh >> /var/log/health-check.log 2>&1
```

---

## 7. 腾讯云 COS + CDN 配置

### 7.1 COS 存储桶

1. 登录腾讯云控制台 → 对象存储 COS
2. 创建存储桶：`sdk-config-bucket`，区域选择 `ap-guangzhou`
3. 设置公共读权限（CDN 回源需要）
4. 获取 SecretId 和 SecretKey，填入 `.env`

### 7.2 CDN 加速

1. 腾讯云控制台 → CDN → 添加域名
2. 源站类型：COS 源
3. 源站地址：选择 `sdk-config-bucket`
4. 回源 Host：保持默认
5. 缓存配置：`/config/latest.json` 缓存 5 分钟
6. CNAME 解析：将域名指向 CDN 提供的 CNAME

---

## 8. 环境变量参考

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://user:pass@localhost:5432/sdk_platform` |
| `DEBUG` | 调试模式 | `false`（生产）/ `true`（开发） |
| `LOG_LEVEL` | 日志级别 | `INFO` / `WARNING` / `ERROR` |
| `ADMIN_TOKEN` | 管理后台鉴权 Token | 随机字符串，建议 32 位以上 |
| `COS_SECRET_ID` | 腾讯云 SecretId | 从控制台获取 |
| `COS_SECRET_KEY` | 腾讯云 SecretKey | 从控制台获取 |
| `COS_REGION` | COS 区域 | `ap-guangzhou` |
| `COS_BUCKET` | COS 存储桶名 | `sdk-config-bucket` |
| `CDN_BASE_URL` | CDN 域名 | `https://cdn.example.com` |

---

## 9. 快速检查清单

部署完成后逐项验证：

- [ ] PostgreSQL 运行中：`sudo systemctl status postgresql`
- [ ] 数据库表已创建：`psql -U sdk_admin -d sdk_platform -c "\dt"`
- [ ] SDK API 运行中：`curl http://localhost:8100/health`
- [ ] Admin API 运行中：`curl http://localhost:8101/api/admin/health -H "Authorization: Bearer <token>"`
- [ ] Nginx 运行中：`curl http://localhost/health`
- [ ] 前端可访问：浏览器打开 `http://your-domain.com`
- [ ] 配置表接口正常：`curl http://localhost:8101/api/admin/configs -H "Authorization: Bearer <token>"`
- [ ] 点击上报可写入：`curl -X POST http://localhost:8100/api/v1/click ...`
- [ ] 定时备份已配置：`crontab -l | grep pg_dump`

---

> 🍔 部署文档完。有问题随时找汉堡包（喻远飞）。
