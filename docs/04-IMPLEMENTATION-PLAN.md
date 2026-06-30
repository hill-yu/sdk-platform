# SDK 数据中台 + 配置管理系统 — 分期实施计划

> 版本 v1.0 | 给 Codex CLI 的执行文档
>
> **使用方式**：将本文档拆成多个 prompt，逐个喂给 Codex CLI 执行。
> 已确认技术栈：FastAPI + PostgreSQL + Vue3 + 腾讯云COS/CDN

---

## 目录

- [Phase 1：核心链路](#phase-1核心链路) — SDK 4接口 + 数据入库（最优先）
- [Phase 2：数据中台](#phase-2数据中台) — 分析大盘 + 管理后台
- [Phase 3：配置管理](#phase-3配置管理) — 配置表编辑/发布/CDN

---

## Phase 1：核心链路

**目标**：SDK 能连上来，4 个接口全通，数据能正确写入数据库。
**工期**：~2 周

### 前置条件

1. PostgreSQL 15+ 已安装并运行
2. 数据库 `sdk_platform` 已创建（参考 `03-DATABASE.md` 第1节）
3. Python 3.11 + pip 可用
4. Node.js 18+ 可用

### 任务清单（Codex 依次执行）

---

#### Task 1.1：初始化项目结构

```text
CODE PROMPT:
在 D:\code\SDK\ 下创建项目目录结构，参考 01-ARCHITECTURE.md 第4节。
创建以下目录：
  backend/app/core/
  backend/app/models/
  backend/app/schemas/
  backend/app/api/sdk/
  backend/app/api/admin/
  backend/app/services/
  backend/tests/
  frontend/src/views/
  frontend/src/api/
  frontend/src/components/
  frontend/src/router/
  frontend/src/styles/
  scripts/

每个目录下放一个空的 __init__.py（Python目录）或 .gitkeep。
```

---

#### Task 1.2：创建 requirements.txt 和 .env

```text
CODE PROMPT:
1. 在 D:\code\SDK\backend\requirements.txt 写入以下依赖：
   fastapi==0.115.*
   uvicorn[standard]==0.34.*
   pydantic==2.*
   pydantic-settings==2.*
   asyncpg==0.30.*
   sqlalchemy[asyncio]==2.0.*
   alembic==1.14.*
   python-multipart==0.0.*
   httpx==0.28.*

2. 在 D:\code\SDK\backend\.env.example 写入：
   DATABASE_URL=postgresql+asyncpg://admin:${DB_PASSWORD}@localhost:5432/sdk_platform
   DEBUG=true
   LOG_LEVEL=INFO
   DB_PASSWORD=your_password_here
   COS_SECRET_ID=your_secret_id_here
   COS_SECRET_KEY=your_secret_key_here
   COS_REGION=ap-guangzhou
   COS_BUCKET=sdk-config-bucket
   CDN_BASE_URL=https://cdn.example.com

3. 复制 .env.example 为 .env
```

---

#### Task 1.3：创建数据库连接和配置模块

```text
CODE PROMPT:
创建以下两个文件，严格参照 03-DATABASE.md 和以下代码：

1. D:\code\SDK\backend\app\core\config.py
   - 使用 pydantic-settings 的 BaseSettings
   - 包含字段：APP_NAME, DEBUG, DATABASE_URL, SDK_API_PORT(8100), ADMIN_API_PORT(8101),
     COS_SECRET_ID, COS_SECRET_KEY, COS_REGION, COS_BUCKET, CDN_BASE_URL, LOG_LEVEL
   - 提供 get_settings() 函数（带 lru_cache）

2. D:\code\SDK\backend\app\core\database.py
   - 使用 create_async_engine + async_sessionmaker
   - 提供 async def get_db() 依赖（自动 commit/rollback）
   - 提供 async def get_db_no_commit() 依赖（只读，不自动commit）
   - Base = DeclarativeBase
```

---

#### Task 1.4：创建数据库 ORM 模型

```text
CODE PROMPT:
严格按照 03-DATABASE.md 第5节的代码，创建三个 ORM 模型文件：

1. D:\code\SDK\backend\app\models\event.py — SdkEvent 类
2. D:\code\SDK\backend\app\models\config.py — SdkConfig 类
3. D:\code\SDK\backend\app\models\version.py — SdkVersion 类

注意：
- 所有字段类型、nullable、default 严格按文档来
- server_default 使用 func.now()
- SdkEvent 不设 __table_args__（分区由SQL直接管理）
```

---

#### Task 1.5：数据库初始化（建表）

```text
CODE PROMPT:
创建 D:\code\SDK\scripts\init_db.sql，内容是 03-DATABASE.md 中所有 DDL 语句的拼接：
- 第3.1节 sdk_events（分区父表 + 3个月分区 + 索引 + 注释）
- 第3.2节 sdk_configs（含唯一索引 + CHECK约束）
- 第3.3节 sdk_versions（含唯一约束 + CHECK约束）
- 第4.1~4.3节 物化视图 + 刷新函数
- 第6.1~6.2节 分区维护函数
- 第7节 初始数据

然后执行该SQL文件：
  psql -U admin -d sdk_platform -f D:\code\SDK\scripts\init_db.sql

验证：执行后检查所有表和视图是否存在。
```

---

#### Task 1.6：创建 Pydantic Schema

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\schemas\sdk_schemas.py

定义以下 Pydantic v2 模型（参考 02-API-SPEC.md A节）：

1. ClickEvent — 单条点击事件
   - type: str
   - page: Optional[str]
   - element: Optional[str]
   - position: Optional[dict]
   - timestamp: Optional[int]
   - extra: Optional[dict] = {}

2. ClickReportRequest — 点击上报请求
   - app_id: str
   - device_id: str
   - sdk_version: Optional[str]
   - session_id: Optional[str]
   - events: list[ClickEvent]（至少1条，最多100条）

3. LogEntry — 单条日志
   - level: str（需校验为 debug/info/warn/error 之一）
   - tag: Optional[str]
   - message: str
   - timestamp: Optional[int]
   - extra: Optional[dict] = {}

4. LogReportRequest — 日志上报请求
   - app_id: str
   - device_id: str
   - sdk_version: Optional[str]
   - logs: list[LogEntry]（至少1条，最多100条）

5. 统一响应模型 ApiResponse
   - code: int = 0
   - message: str = "ok"
   - data: Optional[Any] = None
```

---

#### Task 1.7：实现 SDK 4 个接口

```text
CODE PROMPT:
严格按照 02-API-SPEC.md A节的 Codex 实现要点，创建以下4个文件：

1. D:\code\SDK\backend\app\api\sdk\version.py
   - router = APIRouter(prefix="/api/v1")
   - GET /version: 查询 sdk_versions 表，比较版本号，返回更新信息
   - 逻辑见 02-API-SPEC.md A1节

2. D:\code\SDK\backend\app\api\sdk\config.py
   - GET /config/meta: 查询 published 配置，支持 ETag/If-None-Match 304
   - 返回 version、updated_at、cdn_url，不返回完整 config JSON
   - 逻辑见 02-API-SPEC.md A2节

3. D:\code\SDK\backend\app\api\sdk\click.py
   - POST /click: 接收 ClickReportRequest，批量写入 sdk_events
   - 每条 event → event_type = 'click', payload = 整条event的JSON
   - 逻辑见 02-API-SPEC.md A3节

4. D:\code\SDK\backend\app\api\sdk\log.py
   - POST /log: 接收 LogReportRequest，批量写入 sdk_events
   - 每条 log → event_type = 'log', payload = 整条log的JSON
   - 逻辑见 02-API-SPEC.md A4节

关键要求：
- 使用 async DB session（get_db / get_db_no_commit）
- 参数校验失败时返回 400
- 数据库写入失败时返回 500
- 仅在明确写入成功时返回 {"code":0, "message":"ok", "data":{"accepted":N}}
- 写入时设置 server_ts=NOW(), client_ts=timestamp转时间戳
- IP 从 request.client.host 获取
```

---

#### Task 1.8：创建 SDK API 入口文件

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\sdk_main.py

内容：
```python
"""SDK API 服务入口 — 端口 8100"""
import uvicorn
from fastapi import FastAPI
from app.api.sdk import version, config, click, log

app = FastAPI(title="SDK API", version="1.0.0")

app.include_router(version.router)
app.include_router(config.router)
app.include_router(click.router)
app.include_router(log.router)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
```
```

---

#### Task 1.9：验证 Phase 1

```text
CODE PROMPT 验证步骤：
1. 启动 SDK API 服务：cd D:\code\SDK\backend && python -m app.sdk_main
2. 测试健康检查：curl http://localhost:8100/health
3. 测试版本接口：curl "http://localhost:8100/api/v1/version?platform=ios&current_version=0"
   （预期返回 has_update=false，因为还没有版本数据）
4. 测试配置元信息接口：curl "http://localhost:8100/api/v1/config/meta?app_id=test"
   （预期返回 code=0，因为初始化数据中已存在 published 配置）
5. 测试点击上报：
   curl -X POST http://localhost:8100/api/v1/click \
     -H "Content-Type: application/json" \
     -d '{"app_id":"test","device_id":"dev1","events":[{"type":"click","page":"home","element":"btn"}]}'
   （预期返回 accepted:1）
6. 测试日志上报：
   curl -X POST http://localhost:8100/api/v1/log \
     -H "Content-Type: application/json" \
     -d '{"app_id":"test","device_id":"dev1","logs":[{"level":"info","message":"test log"}]}'
   （预期返回 accepted:1）
7. 查数据库验证数据是否写入：SELECT count(*) FROM sdk_events;
   （预期返回 2）

如果所有测试通过，Phase 1 完成。
```

---

## Phase 2：数据中台

**目标**：管理后台能查看数据分析大盘（ECharts 图表 + 明细查询 + 事件分布）。
**前置**：Phase 1 全部完成。
**工期**：~2 周

---

#### Task 2.1：创建管理后台 API 入口

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\admin_main.py

```python
"""管理后台 API 服务入口 — 端口 8101"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.admin import dashboard, config_mgr, version_mgr

app = FastAPI(title="Admin API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api/admin")
app.include_router(config_mgr.router, prefix="/api/admin")
app.include_router(version_mgr.router, prefix="/api/admin")

@app.get("/api/admin/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8101)
```

补充要求：
- 管理后台所有 `/api/admin/*` 接口使用固定 Token 鉴权
- 请求头：`Authorization: Bearer <ADMIN_TOKEN>`
- 在 `backend/app/core/config.py` 增加 `ADMIN_TOKEN`
- 在 `backend/app/api/admin/` 路由统一加入鉴权依赖
- 未携带或校验失败时返回 401
```

---

#### Task 2.2：实现数据大盘接口

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\api\admin\dashboard.py

实现以下接口（参考 02-API-SPEC.md B1节）：

1. GET /dashboard/summary — 今日概览
   SQL: SELECT COUNT(*), COUNT(DISTINCT device_id) FROM sdk_events WHERE server_ts >= CURRENT_DATE

2. GET /dashboard/trend — 趋势图数据
   支持参数 range(24h/7d/30d), event_type(可选)
   range=24h → 按小时 GROUP BY（取最近24小时）
   range=7d/30d → 按天 GROUP BY
   返回 [{time, count, uv}, ...]

3. GET /dashboard/breakdown — 事件分布
   支持参数 date, dimension(event_type/page/element)
   当 dimension=event_type → GROUP BY event_type, COUNT(*), 计算百分比
   当 dimension=page → GROUP BY payload->>'page'
   当 dimension=element → GROUP BY payload->>'element'

4. GET /events — 事件明细分页查询
   参数: page, page_size, event_type, app_id, device_id, date_from, date_to
   SQL: SELECT * FROM sdk_events WHERE ... ORDER BY server_ts DESC LIMIT ? OFFSET ?
   返回 {total, page, page_size, items: [...]}

所有查询使用 async DB session。大查询用物化视图 mv_daily_event_stats / mv_hourly_trend。
```

---

#### Task 2.3：创建前端项目

```text
CODE PROMPT:
在 D:\code\SDK\frontend\ 初始化 Vue3 + Vite 项目：

```bash
cd D:\code\SDK\frontend
npm create vite@latest . -- --template vue-ts
npm install
npm install vue-router@4 echarts vue-echarts axios
npm install -D @types/node
```

修改 vite.config.ts：
- 设置 server.proxy 代理 /api/admin → http://localhost:8101
- 设置 resolve.alias '@' → './src'
```

---

#### Task 2.4：创建前端基础结构

```text
CODE PROMPT:
在 frontend/src/ 下创建：

1. src/router/index.ts — Vue Router 配置
   路由：
   - / → Dashboard
   - /config → ConfigManager
   - /version → VersionManager

2. src/api/request.ts — Axios 实例
   - baseURL: '/api/admin'
   - 响应拦截器：提取 res.data

3. src/api/dashboard.ts — 大盘 API 封装
   - getSummary()
   - getTrend(params)
   - getBreakdown(params)
   - getEvents(params)

4. src/components/AppLayout.vue — 整体布局
   - 左侧导航栏（暗色主题）：数据大盘 | 配置管理 | 版本管理
   - 右侧内容区 <router-view>
   - 使用 CSS 变量做暗色主题

5. src/styles/variables.css — 暗色主题 CSS 变量
   --bg-primary: #1a1a2e
   --bg-secondary: #16213e
   --text-primary: #e0e0e0
   --accent: #0f3460
   等等
```

---

#### Task 2.5：实现数据大盘页面

```text
CODE PROMPT:
创建 D:\code\SDK\frontend\src\views\Dashboard.vue

页面布局（从上到下）：
1. 统计卡片行（4个卡片）
   - 今日PV（使用 StatCard 组件）
   - 今日UV
   - 今日事件总数
   - 活跃设备数
   每个卡片显示数值 + 较昨日的涨跌箭头（基于 summary 接口返回的 yesterday_* 字段计算）

2. 趋势图（使用 ECharts）
   - 折线图，支持切换 24小时/7天/30天
   - 双轴：事件数(柱状) + UV(折线)
   - 支持按事件类型筛选（下拉框）

3. 事件分布（饼图）
   - 按事件类型显示占比
   - 支持切换维度（事件类型/页面/按钮）

4. 事件明细表格
   - 分页表格：时间 | 事件类型 | 设备ID | 页面 | 元素 | 操作
   - 顶部筛选栏：日期范围、事件类型、应用ID
   - 点击行可展开查看 payload 完整 JSON

组件：
- src/components/StatCard.vue：接收 title/value/trend 三个 props
- src/components/TrendChart.vue：封装 ECharts 折线图

关键：用 vue-echarts 或直接 echarts.init()
```

---

#### Task 2.6：实现 ETL 定时刷新

```text
CODE PROMPT:
在 admin_main.py 启动时，用 asyncio.create_task 启动一个后台任务：
每 5 分钟执行一次 refresh_materialized_views()

```python
import asyncio
from app.core.database import engine
from sqlalchemy import text

async def etl_refresh_loop():
    while True:
        await asyncio.sleep(300)  # 5分钟
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT refresh_materialized_views()"))
        except Exception as e:
            print(f"ETL refresh failed: {e}")

@app.on_event("startup")
async def startup():
    asyncio.create_task(etl_refresh_loop())
```
```

---

#### Task 2.7：验证 Phase 2

```text
验证步骤：
1. 启动两个服务：
   Terminal 1: cd D:\code\SDK\backend && python -m app.sdk_main
   Terminal 2: cd D:\code\SDK\backend && python -m app.admin_main
   Terminal 3: cd D:\code\SDK\frontend && npm run dev

2. 向 SDK API 写入一些测试数据（用 curl 发几十条 click 和 log）
3. 打开 http://localhost:5173 查看 Dashboard
   - 统计卡片有数据
   - 趋势图正常渲染
   - 饼图有分布
   - 明细表格能查到数据
4. 前端控制台无报错
```

---

## Phase 3：配置管理

**目标**：配置表可以在线编辑、发布到 CDN、支持版本回滚。
**前置**：Phase 1 + Phase 2 完成。
**工期**：~2 周

---

#### Task 3.1：实现配置表管理 API

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\api\admin\config_mgr.py

实现以下接口（参考 02-API-SPEC.md B2节）：

1. GET /configs — 配置列表
   返回 published（1条）+ drafts（多条）+ history（多条archived）

2. GET /configs/{id} — 配置详情
   返回完整 config_data

3. POST /configs — 创建配置（草稿）
   接收 {config_data: JSON, change_log: str}
   存入 sdk_configs，status='draft'，version='draft_{timestamp}'

4. PUT /configs/{id} — 编辑配置
   仅可编辑 status='draft' 的配置
   更新 config_data + change_log

5. POST /configs/{id}/publish — 发布配置 ★核心★
   - 生成正式版本号 (format: YYYYMMDD_vHHMMSS)
   - 构建发布 JSON：{version, updated_at, config: config_data}
   - 上传腾讯云 COS（Phase 3先打印日志，COS接入后续完善）：
     cos://bucket/config/v{version}.json  (历史版本)
     cos://bucket/config/latest.json       (SDK拉取此文件)
   - 更新 DB：旧 published→archived, 当前→published

6. POST /configs/{id}/rollback — 回滚
   将指定 archived 版本重新设为 published，并同步覆盖 `config/latest.json`
```

---

#### Task 3.2：实现配置管理服务层

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\services\config_service.py

实现 publish_config() 函数（参照 02-API-SPEC.md B2.5 节的伪代码）：

```python
async def publish_config(db, config_id: int, published_by: str) -> dict:
    """
    1. 查询配置（必须是 draft）
    2. 生成版本号
    3. 构建发布 JSON
    4. 上传 COS（先 mock，加 TODO 标记后续接入腾讯云 SDK）
    5. 归档旧的 published → 把当前 draft 变为 published
    6. 返回发布结果
    """
```
```

---

#### Task 3.3：实现 SDK 版本管理 API

```text
CODE PROMPT:
创建 D:\code\SDK\backend\app\api\admin\version_mgr.py

实现以下接口（参考 02-API-SPEC.md B3节）：

1. GET /versions?platform=ios — 版本列表
2. POST /versions — 添加新版本
3. PUT /versions/{id} — 编辑版本（如修改 update_policy）
```

---

#### Task 3.4：创建前端配置管理页面

```text
CODE PROMPT:
创建 D:\code\SDK\frontend\src\views\ConfigManager.vue

页面功能：
1. 顶部：当前已发布版本信息（版本号 + 发布时间 + CDN地址）
2. 左侧列表：历史版本 / 草稿列表
3. 主区域：JSON 编辑器
   - 使用 <textarea> 或 Monaco Editor 编辑 JSON
   - 编辑前做 JSON.parse 校验
4. 底部按钮：
   - 新建草稿 → 创建 blank 配置
   - 保存草稿 → PUT /configs/{id}
   - 发布 → POST /configs/{id}/publish（弹确认框）
   - 回滚 → POST /configs/{id}/rollback（仅在选中历史版本时显示）

API 封装：
创建 D:\code\SDK\frontend\src\api\config.ts
- getConfigs(), getConfig(id), createConfig(data), updateConfig(id,data)
- publishConfig(id), rollbackConfig(id)
```

---

#### Task 3.5：创建前端 SDK 版本管理页面

```text
CODE PROMPT:
创建 D:\code\SDK\frontend\src\views\VersionManager.vue

页面功能：
1. 两个 Tab：iOS / Android
2. 表格列表：版本号 | 版本名 | 更新策略 | 状态 | 操作
3. 新增/编辑弹窗表单：
   - platform (下拉)
   - version_code (数字)
   - version_name (文本)
   - update_policy (下拉: force/suggest/silent)
   - download_url
   - release_notes (textarea)
   - file_size, file_hash (可选)
4. 操作按钮：编辑、启用/停用

API 封装：
创建 D:\code\SDK\frontend\src\api\version.ts
- getVersions(params), createVersion(data), updateVersion(id, data)
```

---

#### Task 3.6：接入腾讯云 COS SDK（生产就绪）

```text
CODE PROMPT:
修改 D:\code\SDK\backend\app\services\config_service.py 的 publish_config() 函数

接入腾讯云 COS Python SDK：
```python
from qcloud_cos import CosConfig, CosS3Client

def _get_cos_client():
    settings = get_settings()
    config = CosConfig(
        Region=settings.COS_REGION,
        SecretId=settings.COS_SECRET_ID,
        SecretKey=settings.COS_SECRET_KEY,
    )
    return CosS3Client(config)

async def publish_config(db, config_id: int, published_by: str) -> dict:
    # ... 前面的逻辑不变 ...
    
    # 上传 COS
    client = _get_cos_client()
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()
    
    # 历史版本（永久保留）
    cos_key = f"config/v{version}.json"
    client.put_object(Bucket=settings.COS_BUCKET, Key=cos_key, Body=json_bytes)
    
    # latest（覆盖）
    client.put_object(
        Bucket=settings.COS_BUCKET,
        Key='config/latest.json',
        Body=json_bytes,
        CacheControl='max-age=300'
    )
```
```

---

#### Task 3.7：验证 Phase 3

```text
验证步骤：
1. 打开配置管理页面
2. 创建新草稿 → 编辑 JSON → 保存 → 发布
3. 检查数据库 sdk_configs：旧 published 变 archived，新 draft 变 published
4. 检查 COS bucket：config/v{version}.json 和 config/latest.json 均存在
5. SDK 接口测试：GET /api/v1/config → 返回最新配置
6. 版本回滚测试：选历史版本 → 点击回滚 → 检查 SDK 接口是否返回回滚版本
```

---

## 附录 A：Codex 执行约定

### A.1 项目根目录

所有操作在 `D:\code\SDK\` 下进行。

### A.2 质量要求

- Python 代码用类型注解（大部分地方用 `dict`、`Optional[str]` 等简单写法即可）
- 函数加 docstring 说明用途
- 异常不崩溃，返回友好错误信息
- 前端 console.error 捕获异常

### A.3 不要做的

- ❌ 不要过度抽象（不需要 Repository 模式、不需要 Service 接口层）
- ❌ 不要引入 Redis / Celery / Kafka / ClickHouse
- ❌ 不要过度拆分文件（一个功能一个文件即可）
- ❌ 不要写复杂的单元测试（Phase 1~3 先不写，后续再加）

### A.4 验证标准

每个 Phase 完成后必须通过验证步骤，确保接口可调用、数据可写入、页面可渲染。

---

> 🍔 实施计划完。共 4 份文档：
> - `01-ARCHITECTURE.md` — 总体架构
> - `02-API-SPEC.md` — 接口规格
> - `03-DATABASE.md` — 数据库设计
> - `04-IMPLEMENTATION-PLAN.md` — 分期实施计划（本文档）
>
> 按 Phase 1 → Phase 2 → Phase 3 顺序，把每个 Task 的 CODE PROMPT 喂给 Codex CLI 执行即可。
