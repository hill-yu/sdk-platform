# SDK 数据中台 + 配置管理系统 — 接口详细规格

> 版本 v1.0 | 给 Codex 的执行文档

---

## 目录

- [A. SDK 侧接口（端口 8100）](#a-sdk-侧接口端口-8100)
  - [A1. 版本获取](#a1-版本获取-get-apiv1version)
  - [A2. 配置获取](#a2-配置获取-get-apiv1config)
  - [A3. 点击上报](#a3-点击上报-post-apiv1click)
  - [A4. 日志上报](#a4-日志上报-post-apiv1log)
- [B. 管理后台接口（端口 8101）](#b-管理后台接口端口-8101)
  - [B1. 数据大盘](#b1-数据大盘)
  - [B2. 配置表管理](#b2-配置表管理)
  - [B3. SDK 版本管理](#b3-sdk-版本管理)
- [C. 通用规范](#c-通用规范)

---

## A. SDK 侧接口（端口 8100）

**Base URL**: `http://127.0.0.1:8100/api/v1`

所有 SDK 接口均无需鉴权（Phase 1）。

---

### A1. 版本获取 `GET /api/v1/version`

SDK 启动时调用，检查是否有新版本。

#### 请求

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| platform | string | 是 | `ios` 或 `android` |
| current_version | integer | 否 | 当前 SDK 的 version_code，默认 0 |

```
GET /api/v1/version?platform=ios&current_version=110
```

#### 响应

**有更新时 (200)**：
```json
{
  "code": 0,
  "data": {
    "has_update": true,
    "update_policy": "suggest",
    "latest_version": {
      "platform": "ios",
      "version_code": 120,
      "version_name": "1.2.0",
      "download_url": "https://cdn.example.com/sdk/ios/1.2.0.zip",
      "release_notes": "- 修复了xxx问题\n- 新增了xxx功能",
      "file_size": 5242880,
      "file_hash": "sha256:abc123def456..."
    },
    "min_required_version": 100
  }
}
```

**无更新时 (200)**：
```json
{
  "code": 0,
  "data": {
    "has_update": false,
    "current_version": 120,
    "message": "已是最新版本"
  }
}
```

**无可用版本时 (200)**：
```json
{
  "code": 0,
  "data": {
    "has_update": false,
    "current_version": 0,
    "message": "暂无可用版本"
  }
}
```

#### update_policy 说明

| 值 | SDK 行为 |
|----|---------|
| `force` | 强制更新，用户无法跳过，必须升级后才能继续使用 |
| `suggest` | 建议更新，弹窗提示但可跳过 |
| `silent` | 静默更新，后台下载，下次启动生效 |

#### Codex 实现要点

```python
# backend/app/api/sdk/version.py
# 逻辑：
# 1. 查询 sdk_versions 表中 platform=xxx AND status='active'，按 version_code DESC 取第1条
# 2. 比较 latest.version_code > current_version → has_update
# 3. 若 current_version < min_sdk_version → 返回 min_required_version
# 4. 若无 active 版本 → 返回 has_update=false
```

---

### A2. 配置元信息获取 `GET /api/v1/config/meta`

SDK 获取当前已发布配置的版本信息，用于判断是否需要重新拉取 CDN 配置文件。

#### 请求

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | string | 是 | 应用标识 |
| config_version | string | 否 | SDK 当前缓存的配置版本号 |

```
GET /api/v1/config/meta?app_id=com.example.app&config_version=20260630_v2
```

#### 请求头

```
If-None-Match: "20260630_v2"
```

#### 响应

**版本已最新 (304 Not Modified)**：
```
HTTP/1.1 304 Not Modified
ETag: "20260630_v2"
Cache-Control: max-age=300
```
> Body 为空，SDK 继续使用本地缓存的 CDN 配置。

**有新版本 (200)**：
```json
{
  "code": 0,
  "data": {
    "version": "20260630_v3",
    "updated_at": "2026-06-30T10:00:00+08:00",
    "cdn_url": "https://cdn.example.com/config/latest.json"
  }
}
```

**无已发布配置 (200)**：
```json
{
  "code": 1,
  "message": "暂无已发布的配置",
  "data": null
}
```

#### Codex 实现要点

```python
# backend/app/api/sdk/config.py
# 逻辑：
# 1. 查询 sdk_configs WHERE status='published' LIMIT 1
# 2. 若不存在 → 返回 code=1
# 3. 比较 If-None-Match 或 config_version 与 published.version
# 4. 相同 → 304；不同 → 200（仅返回 version + updated_at + cdn_url）
# 5. 响应头设置 ETag + Cache-Control
# 6. 注意：此接口不返回 config 完整 JSON，完整配置走 CDN
```
### A3. 点击上报 `POST /api/v1/click`

SDK 批量上报用户点击事件。

#### 请求

```json
{
  "app_id": "com.example.app",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "sdk_version": "1.2.0",
  "session_id": "sess_abc123",
  "events": [
    {
      "type": "click",
      "page": "home",
      "element": "buy_button",
      "position": { "x": 100, "y": 200 },
      "timestamp": 1719734400000,
      "extra": {}
    },
    {
      "type": "click",
      "page": "home",
      "element": "search_bar",
      "position": { "x": 50, "y": 80 },
      "timestamp": 1719734401000,
      "extra": { "keyword": "手机" }
    }
  ]
}
```

#### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | string | 是 | 应用标识；匿名采集阶段服务端仅校验长度，不校验是否真实存在或启用 |
| device_id | string | 是 | 设备唯一 ID |
| sdk_version | string | 否 | SDK 版本号 |
| session_id | string | 否 | 会话 ID |
| events | array | 是 | 事件数组，单次最多 100 条 |
| events[].type | string | 是 | 事件类型，如 `click`, `page_view` |
| events[].page | string | 否 | 页面名称 |
| events[].element | string | 否 | 点击元素 |
| events[].position | object | 否 | 点击坐标 {x, y} |
| events[].timestamp | integer | 否 | 客户端时间戳(毫秒) |
| events[].extra | object | 否 | 额外数据（灵活扩展） |

#### 响应

成功或部分成功：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "accepted": 2
  }
}
```

全部事件因业务规则被拒绝：

```json
HTTP/1.1 422 Unprocessable Entity
{
  "code": 4001,
  "message": "all_events_rejected",
  "data": {
    "accepted": 0,
    "rejected": 2
  }
}
```

限流：click 与 log 写入接口共享同一个 IP 配额，合计超过 10 次/秒/IP 时返回 HTTP 429。

#### Codex 实现要点

```python
# backend/app/api/sdk/click.py
# 逻辑：
# 1. Pydantic 校验请求体，校验失败 → 返回 400
# 2. 遍历 events[]，过滤出合法事件
# 3. 合法事件逐条构造 INSERT，event_type = each_event.type（或统一为 'click'）
# 4. payload = 整条 event 对象的 JSON（含 type/page/element 等均存入 payload JSONB）
# 5. server_ts = NOW(), client_ts = to_timestamp(timestamp/1000)
# 6. 全部事件被拒绝 → 返回 HTTP 422 + {"code":4001,"message":"all_events_rejected"}
# 7. 数据库写入异常 → 返回 500，不吞错误
# 8. 仅在全部成功时返回 {"code":0, "message":"ok", "data":{"accepted":N}}
# 9. 部分成功场景返回 {"code":0, "message":"partial_success", "data":{"accepted":N, "rejected":M}}
```

---

### A4. 日志上报 `POST /api/v1/log`

SDK 批量上报日志。

#### 请求

```json
{
  "app_id": "com.example.app",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "sdk_version": "1.2.0",
  "logs": [
    {
      "level": "error",
      "tag": "NetworkManager",
      "message": "Connection timeout to https://api.example.com",
      "timestamp": 1719734400000,
      "extra": {
        "stack": "Error: timeout\n  at NetworkManager.java:42\n  ..."
      }
    },
    {
      "level": "info",
      "tag": "Lifecycle",
      "message": "App entered foreground",
      "timestamp": 1719734405000,
      "extra": {}
    }
  ]
}
```

#### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | string | 是 | 应用标识；匿名采集阶段服务端仅校验长度，不校验是否真实存在或启用 |
| device_id | string | 是 | 设备唯一 ID |
| sdk_version | string | 否 | SDK 版本号 |
| logs | array | 是 | 日志数组，单次最多 100 条 |
| logs[].level | string | 是 | 日志级别: `debug`, `info`, `warn`, `error` |
| logs[].tag | string | 否 | 日志标签 |
| logs[].message | string | 是 | 日志内容 |
| logs[].timestamp | integer | 否 | 客户端时间戳(毫秒) |
| logs[].extra | object | 否 | 附加信息（堆栈等） |

#### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "accepted": 2
  }
}
```

限流：click 与 log 写入接口共享同一个 IP 配额，合计超过 10 次/秒/IP 时返回 HTTP 429。

#### Codex 实现要点

```python
# backend/app/api/sdk/log.py
# 逻辑：
# 1. Pydantic 校验，校验失败 → 返回 400
# 2. event_type = 'log'
# 3. payload = 整条 log 对象 JSONB（含 level/tag/message/extra）
# 4. 数据库写入异常 → 返回 500
# 5. 全部成功返回 {"code":0, "message":"ok", "data":{"accepted":N}}
```

---

## B. 管理后台接口（端口 8101）

**Base URL**: `http://127.0.0.1:8101/api/admin`

管理后台接口需简单鉴权（Phase 1 可用固定 Token，Phase 3 接用户系统）。
请求头统一使用：`Authorization: Bearer <ADMIN_TOKEN>`。

---

### B1. 数据大盘

#### B1.1 今日概览 `GET /api/admin/dashboard/summary`

```json
// 响应
{
  "code": 0,
  "data": {
    "today_pv": 12580,
    "yesterday_pv": 11840,
    "today_uv": 2987,
    "yesterday_uv": 2870,
    "today_events": 45230,
    "yesterday_events": 43012,
    "active_devices": 3012,
    "yesterday_active_devices": 2891,
    "error_count": 156
  }
}
```

#### B1.2 趋势图 `GET /api/admin/dashboard/trend`

```
GET /api/admin/dashboard/trend?range=24h&event_type=click
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| range | string | 否 | `24h`(默认), `7d`, `30d` |
| event_type | string | 否 | 筛选事件类型 |

```json
// 响应
{
  "code": 0,
  "data": {
    "points": [
      {"time": "2026-06-30T00:00:00Z", "count": 520, "uv": 120},
      {"time": "2026-06-30T01:00:00Z", "count": 310, "uv": 85}
    ]
  }
}
```

#### B1.3 事件分布 `GET /api/admin/dashboard/breakdown`

```
GET /api/admin/dashboard/breakdown?date=2026-06-30&dimension=event_type
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | string | 否 | 日期，默认今天 |
| dimension | string | 否 | 维度: `event_type`(默认), `page`, `element` |

```json
// 响应
{
  "code": 0,
  "data": [
    {"name": "click", "count": 35200, "percentage": 77.8},
    {"name": "page_view", "count": 8500, "percentage": 18.8},
    {"name": "log", "count": 1530, "percentage": 3.4}
  ]
}
```

#### B1.4 事件明细 `GET /api/admin/events`

```
GET /api/admin/events?page=1&page_size=20&event_type=click&date_from=2026-06-29&date_to=2026-06-30
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | integer | 否 | 页码，默认 1 |
| page_size | integer | 否 | 每页条数，默认 20，最大 100 |
| event_type | string | 否 | 事件类型筛选 |
| app_id | string | 否 | 应用筛选 |
| device_id | string | 否 | 设备筛选 |
| date_from | string | 否 | 开始日期 |
| date_to | string | 否 | 结束日期 |

```json
// 响应
{
  "code": 0,
  "data": {
    "total": 45230,
    "page": 1,
    "page_size": 20,
    "items": [
      {
        "id": 12345,
        "event_type": "click",
        "device_id": "uuid-xxx",
        "payload": {"page":"home","element":"buy"},
        "client_ts": "2026-06-30T10:30:00Z",
        "server_ts": "2026-06-30T10:30:01Z"
      }
    ]
  }
}
```

#### Codex 实现要点

```python
# backend/app/api/admin/dashboard.py
# summary: 直接 COUNT + COUNT(DISTINCT device_id) FROM sdk_events WHERE server_ts >= today
# trend: 按小时 GROUP BY，时间范围大则按天 GROUP BY
# breakdown: GROUP BY event_type + 计算百分比
# events: 分页查询 + 多条件 WHERE（用 Query 参数动态构建 SQL）
```

---

### B2. 配置表管理

#### B2.1 配置列表 `GET /api/admin/configs`

```json
// 响应
{
  "code": 0,
  "data": {
    "published": {
      "id": 5,
      "version": "20260630_v3",
      "publish_at": "2026-06-30T10:00:00Z",
      "change_log": "新增首页AB测试配置"
    },
    "drafts": [
      {"id": 6, "version": "draft_001", "created_at": "...", "change_log": "..."}
    ],
    "history": [
      {"id": 4, "version": "20260629_v2", "status": "archived", "publish_at": "..."},
      {"id": 3, "version": "20260628_v1", "status": "archived", "publish_at": "..."}
    ]
  }
}
```

#### B2.2 获取配置详情 `GET /api/admin/configs/{id}`

```json
// 响应
{
  "code": 0,
  "data": {
    "id": 5,
    "version": "20260630_v3",
    "config_data": { /* 完整 JSON */ },
    "status": "published",
    "publish_at": "...",
    "change_log": "..."
  }
}
```

#### B2.3 创建配置 `POST /api/admin/configs`

```json
// 请求
{
  "config_data": { /* 完整配置 JSON */ },
  "change_log": "新增首页AB测试配置"
}
```

```json
// 响应
{
  "code": 0,
  "data": {
    "id": 6,
    "version": "draft_20260630103000",
    "status": "draft",
    "created_at": "2026-06-30T10:30:00Z"
  }
}
```

#### B2.4 编辑配置 `PUT /api/admin/configs/{id}`

> 仅可编辑 status='draft' 的配置。

```json
// 请求
{
  "config_data": { /* 完整配置 JSON */ },
  "change_log": "修改了超时时间"
}
```

#### B2.5 发布配置 `POST /api/admin/configs/{id}/publish`

> 将指定草稿发布到 CDN。这是核心操作！

```json
// 响应
{
  "code": 0,
  "data": {
    "version": "20260630_v3",
    "publish_at": "2026-06-30T10:35:00Z",
    "cdn_url": "https://cdn.example.com/config/latest.json",
    "cos_key": "config/v20260630_v3.json"
  }
}
```

#### B2.6 回滚配置 `POST /api/admin/configs/{id}/rollback`

> 将指定历史版本重新发布（status: archived → published），并同步覆盖 CDN 的 `config/latest.json`。

```json
// 响应
{
  "code": 0,
  "data": {
    "version": "20260629_v2",
    "publish_at": "2026-06-30T10:40:00Z",
    "message": "已回滚到版本 20260629_v2"
  }
}
```

#### Codex 实现要点 — config_service.py

```python
# backend/app/services/config_service.py

async def create_config(db, config_data: dict, change_log: str) -> SdkConfig:
    """创建配置草稿"""
    version = f"draft_{datetime.now():%Y%m%d%H%M%S}"
    config = SdkConfig(
        version=version,
        config_data=config_data,
        status="draft",
        change_log=change_log
    )
    db.add(config)
    await db.flush()
    return config

async def publish_config(db, config_id: int, published_by: str) -> dict:
    """发布配置到 CDN"""
    config = await db.get(SdkConfig, config_id)
    if not config or config.status != "draft":
        raise ValueError("只能发布草稿状态的配置")

    # 1. 生成正式版本号
    version = datetime.now().strftime("%Y%m%d_v%H%M%S")

    # 2. 构建发布 JSON
    publish_data = {
        "version": version,
        "updated_at": datetime.now().isoformat(),
        "config": config.config_data
    }
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()

    # 3. 上传腾讯云 COS
    cos_key = f"config/v{version}.json"

    # TODO: 实际接入腾讯云 COS SDK
    # cos_client.put_object(Bucket=..., Key=cos_key, Body=json_bytes)
    # cos_client.put_object(Bucket=..., Key='config/latest.json', Body=json_bytes,
    #                       CacheControl='max-age=300')

    # 4. 更新状态
    # 旧 published → archived
    await db.execute(
        "UPDATE sdk_configs SET status='archived' WHERE status='published'"
    )
    # 当前 draft → published
    config.status = "published"
    config.version = version
    config.publish_at = datetime.now()
    config.published_by = published_by
    config.cos_key = cos_key
    await db.flush()

    return {
        "version": version,
        "publish_at": config.publish_at.isoformat(),
        "cdn_url": f"https://cdn.example.com/config/latest.json",
        "cos_key": cos_key
    }
```

---

### B3. SDK 版本管理

#### B3.1 版本列表 `GET /api/admin/versions`

```
GET /api/admin/versions?platform=ios
```

#### B3.2 添加版本 `POST /api/admin/versions`

```json
// 请求
{
  "platform": "ios",
  "version_code": 120,
  "version_name": "1.2.0",
  "update_policy": "suggest",
  "download_url": "https://cdn.example.com/sdk/ios/1.2.0.zip",
  "release_notes": "- 修复xxx\n- 新增xxx",
  "file_size": 5242880,
  "file_hash": "sha256:abc123"
}
```

#### B3.3 编辑版本 `PUT /api/admin/versions/{id}`

> 可修改 update_policy、download_url、release_notes、status 等。

---

## C. 通用规范

### C.1 统一响应格式

```json
{
  "code": 0,          // 0=成功, 非0=失败
  "message": "ok",    // 错误时描述原因
  "data": {}          // 业务数据
}
```

### C.2 HTTP 状态码

| 状态码 | 场景 |
|--------|------|
| 200 | 正常响应 |
| 304 | 配置未变化（ETag） |
| 400 | 参数校验失败 |
| 404 | 资源不存在 |
| 500 | 服务端异常 |

### C.3 Pydantic Schema 定义位置

所有请求/响应的 Pydantic 模型放在：
- `backend/app/schemas/sdk_schemas.py` — SDK 接口专用
- `backend/app/schemas/admin_schemas.py` — 管理后台接口专用

---

> 🍔 API 规格完。下一份 → `03-DATABASE.md`
