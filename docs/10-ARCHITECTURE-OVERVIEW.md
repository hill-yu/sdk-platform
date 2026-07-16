# SDK 数据中台 — 项目架构说明

> 五轮 Review 后最终版本 | 2026-07-14

---

## 1. 项目总览

| 项 | 值 |
|----|-----|
| 项目名 | SDK 数据中台 + 配置管理系统 |
| 技术栈 | FastAPI + PostgreSQL + Vue3 + 腾讯云 COS/CDN |
| 代码位置 | `D:\code\SDK\` |
| Python | 3.11+ |
| 数据库 | PostgreSQL 15+ |

---

## 2. 系统架构

```
                    ┌──────────────────────┐
                    │   移动 App SDK        │
                    │   (iOS / Android)     │
                    └──┬──┬──┬──┬──────────┘
        GET            │  │  │ POST    POST
        ▼              ▼  │  ▼        ▼
   ┌─────────────────────────────────────────┐
   │           Nginx (:80/443)               │
   │     限流 · SSL · 路由分发               │
   └──────┬──────────────┬───────────────────┘
          │              │
   ┌──────▼──────┐ ┌─────▼──────────────┐
   │ SDK API     │ │ Admin API          │
   │ :8100       │ │ :8101              │
   │             │ │                    │
   │ /version    │ │ /dashboard/*       │
   │ /config/meta│ │ /configs/*         │
   │ /click      │ │ /versions/*        │
   │ /log        │ │                    │
   └──┬──┬───────┘ └──────┬─────────────┘
      │  │                │
      ▼  ▼                ▼
   ┌──────────┐    ┌──────────────┐
   │PostgreSQL│    │ 腾讯云 COS    │
   │ :5432    │    │ + CDN        │
   │          │    │              │
   │sdk_events│    │config/latest │
   │sdk_conf..│    │sdk/*.zip     │
   │sdk_ver.. │    └──────────────┘
   │mv_*      │
   └────┬─────┘
        │
        ▼
   ┌──────────────┐
   │ 管理后台 Vue3 │
   │ (Nginx 托管)  │
   └──────────────┘
```

---

## 3. 数据库核心表

| 表 | 用途 | 关键设计 |
|----|------|---------|
| `sdk_events` | 原始事件表 | **按月分区** + JSONB 灵活存储 + GIN 索引 |
| `sdk_configs` | 配置表版本 | 部分唯一索引确保唯一 published |
| `sdk_versions` | SDK 版本记录 | (platform, version_code) 联合唯一 |
| `mv_daily_event_stats` | 每日统计 | 物化视图，每 5 分钟刷新 |
| `mv_hourly_trend` | 小时趋势 | 同上 |

---

## 4. API 接口一览

### SDK 侧（端口 8100，无需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/version` | SDK 版本检查 |
| GET | `/api/v1/config/meta` | 配置元信息（版本号 + CDN地址，不返完整配置） |
| POST | `/api/v1/click` | 点击事件上报（批量，最多100条） |
| POST | `/api/v1/log` | 日志上报（批量，最多100条） |

### 管理后台侧（端口 8101，需 Bearer Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/dashboard/summary` | 今日概览 |
| GET | `/api/admin/dashboard/trend` | 趋势图 |
| GET | `/api/admin/dashboard/breakdown` | 事件分布 |
| GET | `/api/admin/events` | 事件明细 |
| GET/POST/PUT | `/api/admin/configs/*` | 配置表 CRUD + 发布/回滚 |
| GET/POST/PUT | `/api/admin/versions/*` | SDK 版本管理 |

---

## 5. 代码分层

```
backend/app/
├── core/           # 配置 + 数据库连接池
├── models/         # SQLAlchemy ORM (event, config, version)
├── schemas/        # Pydantic 校验 (sdk_schemas, admin_schemas)
├── api/
│   ├── sdk/        # SDK 4 接口 (version, config/meta, click, log)
│   └── admin/      # 管理后台接口 (dashboard, config_mgr, version_mgr, deps)
├── services/       # 业务逻辑 (analysis_service, config_service, version_service)
├── sdk_main.py     # SDK API 入口 → :8100
└── admin_main.py   # Admin API 入口 → :8101
```

---

## 6. 关键安全措施

| 措施 | 实现位置 |
|------|---------|
| Token 常量时间比较 | `deps.py` — `hmac.compare_digest()` |
| 请求体大小限制 | `sdk_main.py` 1MB, `admin_main.py` 5MB |
| 敏感字段不出现在日志 | `config.py` — `repr=False` 标记 |
| CORS 限制 | `admin_main.py` — 环境变量 `CORS_ORIGINS` |
| SQL 注入防护 | 全项目 SQLAlchemy ORM + 参数化 `text()` |
| COS 失败回滚 DB | `config_service.py` — DB 先 + COS 后 + 失败 rollback |
| 物化视图并发锁 | `init_db.sql` — `pg_try_advisory_lock(12345)` |

---

## 7. 数据流

```
SDK App → POST /click → Pydantic校验 → 批量INSERT(sdk_events) → 返回accepted
                                                         ↓
                                          每5分钟 ETL 刷新物化视图
                                                         ↓
                                          管理后台 Dashboard 查询视图
```

---

## 8. 部署方式

- 腾讯云轻量服务器
- Systemd 管理两个 uvicorn 进程
- Nginx 反向代理 + 静态前端托管
- PostgreSQL 本地部署
- 配置表通过腾讯云 COS + CDN 分发

---

> 🍔 架构说明完
