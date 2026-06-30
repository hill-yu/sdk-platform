# SDK 数据中台 + 配置管理系统 — 总体架构设计

> 版本 v1.0 | 2026-06-30 | 给 Codex 的执行文档

---

## 1. 项目概述

为移动 App SDK（iOS/Android）提供后端支撑，三大功能模块：

| 功能 | 说明 | 用户 |
|------|------|------|
| SDK 交互 API | 版本获取、配置拉取、点击上报、日志上报 | SDK 进程 |
| 数据中台 | 点击/日志数据多维分析与大盘展示 | 运营/产品 |
| 配置表管理 | 远程配置编辑→发布→CDN分发→版本回滚 | 运营/开发 |

### 规模

- DAU ~3,000，日请求数万级，QPS < 1
- 数据增量：约 5-10 万条/天

### 技术栈（铁定）

| 层 | 选型 |
|----|------|
| 后端 | **FastAPI** (Python 3.11) |
| 数据库 | **PostgreSQL 15+** |
| 前端 | **Vue 3 + Vite + ECharts** |
| CDN | **腾讯云 COS + CDN** |
| 部署 | **腾讯云服务器** |

---

## 2. 系统架构图

```text
                           移动 App SDK (iOS/Android)
                              │   同事负责
            GET          GET  │  POST        POST
            ▼            ▼    │   ▼           ▼
       ┌────────────────────────────────────────┐
       │          Nginx (反向代理)               │
       │   限流 · SSL · 日志 · 路由分发          │
       └──────┬────────────────┬────────────────┘
              │                │
   ┌──────────▼──────┐  ┌─────▼──────────────┐
   │ SDK API Service │  │ Admin API Service  │
   │ FastAPI  :8100  │  │ FastAPI  :8101     │
   │                 │  │                    │
   │ GET /version    │  │ GET /dashboard/*   │
   │ GET /config/meta│  │ POST /configs/*    │
   │ POST /click     │  │ POST /publish      │
   │ POST /log       │  │ GET /versions      │
   └───┬───┬─────────┘  └──┬─────────────────┘
       │   │               │
       ▼   ▼               ▼
   ┌────────────┐   ┌──────────────────┐
   │ PostgreSQL │   │ 腾讯云 COS + CDN  │
   │            │   │                  │
   │ sdk_events │   │ /config/latest   │
   │ sdk_configs│   │ /config/vX.json  │
   │ sdk_version│   │ /sdk/*.zip       │
   │ mv_*       │   └──────────────────┘
   └─────┬──────┘
         │
         ▼
   ┌──────────────────┐
   │ 管理后台 Vue3    │
   │ (Nginx静态托管)  │
   │                  │
   │ 📊 数据大盘      │
   │ ⚙️ 配置表管理    │
   │ 📦 版本管理      │
   └──────────────────┘
```

### 端口规划

| 端口 | 服务 | 说明 |
|------|------|------|
| 80/443 | Nginx | 统一入口，SSL 终结 |
| 8100 | SDK API | SDK 直连（内部转发） |
| 8101 | Admin API | 管理后台调用 |
| 5432 | PostgreSQL | 数据库 |

### Nginx 路由规则

```nginx
# SDK 接口 → :8100
location /api/v1/ {
    proxy_pass http://127.0.0.1:8100;
}

# 管理后台 API → :8101
location /api/admin/ {
    proxy_pass http://127.0.0.1:8101;
}

# 管理后台前端静态文件
location / {
    root /www/wwwroot/sdk-platform/dist;
    try_files $uri $uri/ /index.html;
}
```

---

## 3. 关键设计决策（给 Codex 的约束）

### 决策 1：SDK API 与管理后台 API 两个独立 FastAPI 进程

- **位置**：`backend/app/sdk_main.py` 和 `backend/app/admin_main.py` 两个入口
- **原因**：隔离故障域；SDK API 挂了不影响运营后台
- **实现方式**：两个 uvicorn 进程，不同端口

### 决策 2：事件存储用 PostgreSQL JSONB（不预先定义字段）

- **原因**：SDK 上报字段由同事后续确定，JSONB 不需要预设 schema
- **演进策略**：字段确定后 → 创建生成列或物化视图提取关键字段 → 加索引

### 决策 3：配置表走 COS + CDN，SDK 不通过业务 API 拉取完整配置

- **SDK 获取配置的路径**：`https://cdn.example.com/config/latest.json`
- **更新流程**：后台编辑 → 生成 JSON → 上传腾讯云 COS → CDN 边缘节点自动分发
- **API 接口 `/api/v1/config/meta` 的职责**：仅用于返回配置元信息与缓存协商结果，不返回完整配置内容
- **推荐行为**：
  - SDK 优先直接请求 CDN 的 `latest.json`
  - 如需轻量版本探测，可调用 `/api/v1/config/meta`
- **推荐行为**：
  - SDK 优先直接请求 CDN 的 `latest.json`
  - 如需轻量版本探测，再调用 `/api/v1/config/meta`

### 决策 4：不引入 Redis、ClickHouse、消息队列

- 量级太小，PG 完全胜任；CDN 解决配置分发缓存

---

## 4. 项目目录结构（Codex 严格按此创建）

```text
D:\code\SDK\
├── docs/                           ← 设计文档（本目录）
│   ├── 01-ARCHITECTURE.md          ← 本文档
│   ├── 02-API-SPEC.md              ← 接口规格
│   ├── 03-DATABASE.md              ← 数据库设计
│   └── 04-IMPLEMENTATION-PLAN.md   ← 分期实施计划
│
├── backend/                        ← FastAPI 后端项目
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── sdk_main.py             ← SDK API 入口 (端口8100)
│   │   ├── admin_main.py           ← 管理后台 API 入口 (端口8101)
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py           ← 配置（环境变量/DATABASE_URL等）
│   │   │   └── database.py         ← SQLAlchemy async engine + get_db 依赖
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── event.py            ← SdkEvent ORM
│   │   │   ├── config.py           ← SdkConfig ORM
│   │   │   └── version.py          ← SdkVersion ORM
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── sdk_schemas.py      ← SDK 接口的 Pydantic 请求/响应
│   │   │   └── admin_schemas.py    ← 管理后台的 Pydantic 请求/响应
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── sdk/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── version.py      ← GET  /api/v1/version
│   │   │   │   ├── config.py       ← GET  /api/v1/config
│   │   │   │   ├── click.py        ← POST /api/v1/click
│   │   │   │   └── log.py          ← POST /api/v1/log
│   │   │   └── admin/
│   │   │       ├── __init__.py
│   │   │       ├── dashboard.py    ← 数据大盘接口
│   │   │       ├── config_mgr.py   ← 配置表管理接口
│   │   │       └── version_mgr.py  ← SDK版本管理接口
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── event_service.py    ← 事件写入（批量+异步）
│   │       ├── config_service.py   ← 配置 CRUD + COS发布
│   │       ├── version_service.py  ← 版本管理
│   │       └── analysis_service.py ← 数据聚合分析
│   ├── migrations/                 ← Alembic 迁移文件
│   └── tests/
│       ├── test_sdk_api.py
│       └── test_admin_api.py
│
├── frontend/                       ← Vue3 前端项目
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/index.ts
│       ├── api/                    ← Axios 封装
│       │   ├── request.ts          ← axios 实例 + 拦截器
│       │   ├── dashboard.ts        ← 大盘数据 API
│       │   ├── config.ts           ← 配置表 API
│       │   └── version.ts          ← 版本管理 API
│       ├── views/
│       │   ├── Dashboard.vue       ← 数据大盘页面
│       │   ├── ConfigManager.vue   ← 配置表管理页面
│       │   └── VersionManager.vue  ← SDK版本管理页面
│       ├── components/
│       │   ├── AppLayout.vue       ← 整体布局（侧边栏+顶栏+内容区）
│       │   ├── StatCard.vue        ← 统计卡片
│       │   └── TrendChart.vue      ← 趋势图封装
│       └── styles/
│           └── variables.css       ← CSS 变量（暗色主题）
│
└── scripts/                        ← 运维脚本
    ├── deploy.sh                   ← 部署脚本
    └── init_db.sql                 ← 数据库初始化 SQL
```

---

## 5. 数据流

### 5.1 SDK 事件上报流程

```
SDK App
  │
  │ POST /api/v1/click  (JSON body)
  ▼
Nginx (限流 10r/s per IP)
  │
  ▼
SDK API Service (:8100)
  │
  │ ① 参数校验 (Pydantic)
  │ ② 批量 INSERT INTO sdk_events (异步不阻塞响应)
  │ ③ 返回 {"code":0, "message":"ok", "data":{"accepted":N}}
  ▼
PostgreSQL sdk_events 表
  │
  │ 定时任务 (每5分钟)
  ▼
REFRESH MATERIALIZED VIEW mv_daily_event_stats
  │
  ▼
管理后台 Dashboard 查询物化视图 → ECharts 渲染
```

### 5.2 配置表发布流程

```
运营在管理后台编辑配置
  │
  │ POST /api/admin/configs  (创建草稿)
  ▼
Admin API Service (:8101)
  │
  │ ① 存入 sdk_configs 表 (status='draft')
  │ ② 运营点击"发布"
  │ ③ POST /api/admin/configs/{id}/publish
  ▼
config_service.py:
  │ ① 生成版本号 (时间戳)
  │ ② 构建 JSON: {"version":"...", "updated_at":"...", "config":{...}}
  │ ③ 上传腾讯云 COS:
  │      cos://bucket/config/v20260630_001.json  (历史版本)
  │      cos://bucket/config/latest.json          (覆盖最新, Cache-Control: max-age=300)
  │ ④ 更新 sdk_configs 表: 旧 published→archived, 新 draft→published
  │ ⑤ (可选) 刷新 CDN 缓存
  ▼
CDN 全网边缘节点更新 (5分钟内生效)
  │
  ▼
SDK 下次启动 GET https://cdn.xxx.com/config/latest.json → 获取新配置
```

### 5.3 SDK 版本管理流程

```
开发上传新 SDK 包到 COS
  │
  │ POST /api/admin/versions
  ▼
Admin API Service (:8101)
  │ 存入 sdk_versions 表
  ▼
SDK 启动时 GET /api/v1/version?platform=ios&current_version=110
  │ 返回最新版本信息 + 更新策略
```

---

## 6. 与同事的协作界面

SDK 同事需要知道的接口契约（最小集）：

```yaml
通信协议: HTTPS + JSON
鉴权: 暂时不做（后续可加 App Secret → HMAC 签名）

version 接口:
  请求: GET /api/v1/version?platform=ios&current_version=110
  响应: {code, data: {has_update, update_policy, latest_version, min_required_version}}

config 接口:
  请求: GET /api/v1/config/meta?app_id=xxx&config_version=v1
  响应: {code, data: {version, updated_at, cdn_url}}
  缓存: 支持 ETag/If-None-Match 304
  注意: 此接口仅返回配置元信息，完整配置请从 CDN 拉取

click 接口:
  请求: POST /api/v1/click
        {app_id, device_id, sdk_version, session_id, events:[{type,page,element,...}]}
  响应: {code:0, message:"ok", data:{accepted:N}}

log 接口:
  请求: POST /api/v1/log
        {app_id, device_id, sdk_version, logs:[{level,tag,message,...}]}
  响应: {code:0, message:"ok", data:{accepted:N}}

配置格式（CDN 上的 JSON）:
  {
    "version": "20260630_v3",
    "updated_at": "2026-06-30T10:00:00Z",
    "config": { ... }   ← 内部结构由同事定义，后台透传
  }
```

---

> 🍔 架构文档完。下一份文档 → `02-API-SPEC.md` 接口详细规格
