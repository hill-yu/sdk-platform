# SDK 数据中台 — API 对接文档

> 版本 v1.0 | 2026-06-30 | 给 SDK 开发同事

---

## 1. 概述

本文档描述移动 App SDK（iOS/Android）与后端的所有交互接口。

- **通信协议**：HTTPS
- **数据格式**：JSON
- **字符编码**：UTF-8
- **Base URL（开发环境）**：`http://localhost:8100`
- **Base URL（生产环境）**：`https://api.example.com`（待定）

---

## 2. 接口列表

| 序号 | 接口 | 方法 | 说明 | 调用时机 |
|------|------|------|------|---------|
| ① | `/api/v1/version` | GET | SDK 版本检查 | App 启动时 |
| ② | `/api/v1/config/meta` | GET | 配置元信息（版本探测） | 定时/启动时 |
| ③ | `/api/v1/click` | POST | 点击事件上报 | 用户交互时，可批量 |
| ④ | `/api/v1/log` | POST | 日志上报 | 按需，可批量 |

> **配置获取说明**：SDK 的完整配置应从 CDN 拉取（`https://cdn.example.com/config/latest.json`），接口 ② 仅用于获取最新版本号，判断是否需要重新拉取 CDN。

---

## 3. 接口详情

### 3.1 版本检查 `GET /api/v1/version`

#### 请求

```
GET /api/v1/version?platform=ios&current_version=110
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| platform | string | **是** | `ios` 或 `android` |
| current_version | integer | 否 | 当前 SDK 的 version_code，首次传 0 |

#### 响应 — 有更新 (200)

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

#### 响应 — 无更新 (200)

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

#### update_policy 说明

| 值 | SDK 行为 |
|----|---------|
| `force` | **强制更新**—弹窗不可关闭，用户必须升级后才能使用 App |
| `suggest` | **建议更新**—弹窗提示新版本，用户可选择"稍后提醒" |
| `silent` | **静默更新**—后台下载新版本包，下次启动时安装 |

#### version_code 计算规则

`version_code` 是整数，每次发版递增（如 `110` → `120` → `130`）。SDK 本地存储当前 version_code，启动时传给后端比较。

---

### 3.2 配置元信息 `GET /api/v1/config/meta`

> **重要**：此接口**不返回完整配置**，仅返回版本号 + CDN 地址。
> SDK 拿到 cdn_url 后直接从 CDN 拉取完整配置文件。

#### 请求

```
GET /api/v1/config/meta?app_id=com.example.app&config_version=20260630_v2
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | string | **是** | 应用标识（包名） |
| config_version | string | 否 | SDK 当前缓存的配置版本号，用于增量判断 |

#### 请求头（缓存协商）

```
If-None-Match: "20260630_v2"
```

#### 响应 — 已是最新 (304 Not Modified)

```
HTTP/1.1 304 Not Modified
ETag: "20260630_v2"
Cache-Control: max-age=300
```

> Body 为空。SDK 继续使用本地缓存的 CDN 配置文件，无需重新下载。

#### 响应 — 有新版本 (200)

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

> SDK 收到新版本号后，从 `cdn_url` 重新拉取完整配置 JSON。

#### 响应 — 无已发布配置 (200)

```json
{
  "code": 1,
  "message": "暂无已发布的配置",
  "data": null
}
```

#### CDN 配置文件格式

SDK 从 CDN 获取的完整配置 JSON 格式：

```json
{
  "version": "20260630_v3",
  "updated_at": "2026-06-30T10:00:00+08:00",
  "config": {
    "features": {
      "new_ui": { "enabled": true, "min_version": "1.2.0" }
    },
    "rules": [],
    "urls": {
      "api_base": "https://api.example.com",
      "cdn_base": "https://cdn.example.com"
    }
  }
}
```

> `config` 内部的字段结构由 SDK 团队定义，后端透传不做解析。

#### SDK 推荐实现伪代码

```swift
// iOS 示例
func checkConfigUpdate() {
    let currentVersion = UserDefaults.standard.string(forKey: "config_version") ?? ""
    var request = URLRequest(url: URL(string: "\(baseURL)/api/v1/config/meta?app_id=\(appId)&config_version=\(currentVersion)")!)
    request.setValue("\"\(currentVersion)\"", forHTTPHeaderField: "If-None-Match")
    
    let task = URLSession.shared.dataTask(with: request) { data, response, error in
        if let httpResponse = response as? HTTPURLResponse {
            if httpResponse.statusCode == 304 {
                return // 无更新，使用缓存
            }
        }
        // 解析 cdn_url，从 CDN 下载完整配置
        // ...
    }
    task.resume()
}
```

---

### 3.3 点击上报 `POST /api/v1/click`

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
| app_id | string | **是** | 应用标识（包名） |
| device_id | string | **是** | 设备唯一 ID（UUID/IDFA） |
| sdk_version | string | 否 | SDK 版本号 |
| session_id | string | 否 | 会话 ID，同一个 App 启动周期内不变 |
| events | array | **是** | 事件数组，**单次最多 100 条**，建议积累到 20 条以上再上报 |
| events[].type | string | **是** | 事件类型：`click`、`page_view`、`exposure` 等 |
| events[].page | string | 否 | 页面名称，如 `"home"`、`"product_detail"` |
| events[].element | string | 否 | 点击元素标识，如 `"buy_button"` |
| events[].position | object | 否 | 点击坐标 `{"x": 100, "y": 200}` |
| events[].timestamp | integer | 否 | 客户端时间戳（**毫秒**） |
| events[].extra | object | 否 | 扩展数据，任意 JSON 对象 |

#### 响应

**全部成功：**
```json
{
  "code": 0,
  "message": "ok",
  "data": { "accepted": 2, "rejected": 0 }
}
```

**部分成功（个别事件字段无效被跳过）：**
```json
{
  "code": 0,
  "message": "partial_success",
  "data": { "accepted": 87, "rejected": 13 }
}
```

#### SDK 实现建议

```swift
// 批量上报策略
class EventReporter {
    private var buffer: [ClickEvent] = []
    private let maxBuffer = 20       // 积累 20 条上报
    private let maxInterval: TimeInterval = 30  // 或每 30 秒上报
    
    func track(event: ClickEvent) {
        buffer.append(event)
        if buffer.count >= maxBuffer {
            flush()
        }
    }
    
    func flush() {
        guard !buffer.isEmpty else { return }
        let batch = buffer
        buffer.removeAll()
        // POST /api/v1/click
        // 失败时重试 1 次，仍失败则丢弃
    }
}
```

---

### 3.4 日志上报 `POST /api/v1/log`

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
| app_id | string | **是** | 应用标识（包名） |
| device_id | string | **是** | 设备唯一 ID |
| sdk_version | string | 否 | SDK 版本号 |
| logs | array | **是** | 日志数组，**单次最多 100 条** |
| logs[].level | string | **是** | 日志级别：`debug`、`info`、`warn`、`error` |
| logs[].tag | string | 否 | 日志标签，用于分类（如 `"NetworkManager"`） |
| logs[].message | string | **是** | 日志内容 |
| logs[].timestamp | integer | 否 | 客户端时间戳（**毫秒**） |
| logs[].extra | object | 否 | 附加信息（堆栈、上下文等） |

#### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": { "accepted": 2, "rejected": 0 }
}
```

---

## 4. 通用规范

### 4.1 统一响应格式

所有接口遵循统一格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

| 字段 | 说明 |
|------|------|
| code | `0` = 成功，非 `0` = 业务异常 |
| message | 人类可读的描述信息 |
| data | 业务数据，可能为 `null` |

### 4.2 HTTP 状态码

| 状态码 | 场景 |
|--------|------|
| 200 | 正常响应 |
| 304 | 配置未变化（config/meta 接口缓存命中） |
| 400 | 请求参数错误（缺少必填字段、格式不合法） |
| 500 | 服务端内部错误 |

### 4.3 上报策略建议

| 建议 | 说明 |
|------|------|
| **批量上报** | 积累 20 条以上或间隔 30 秒再上报，减少请求次数 |
| **失败重试** | 网络失败时重试 1 次，仍失败则丢弃当前批次 |
| **离线缓存** | 无网络时缓存到本地，恢复网络后批量上报（最多缓存 500 条） |
| **流量控制** | 日志类数据仅在 Wi-Fi 下上报；点击事件不限 |
| **不阻塞主线程** | 所有上报操作在后台线程执行 |

### 4.4 数据格式注意事项

- `timestamp` 使用**毫秒级 Unix 时间戳**（如 `1719734400000`）
- `device_id` 在 App 卸载重装前应保持不变（建议用 UUID + Keychain 持久化）
- `app_id` 使用应用的包名（Bundle ID / Application ID）
- JSON 中的字符串统一使用 UTF-8 编码

---

## 5. 测试环境信息

| 项 | 值 |
|----|-----|
| SDK API 地址 | `http://localhost:8100` |
| CDN 配置地址 | `https://cdn.example.com/config/latest.json`（生产环境配置） |

### 快速自测

```bash
# 版本检查
curl "http://localhost:8100/api/v1/version?platform=ios&current_version=0"

# 配置元信息
curl "http://localhost:8100/api/v1/config/meta?app_id=test"

# 点击上报
curl -X POST http://localhost:8100/api/v1/click \
  -H "Content-Type: application/json" \
  -d '{"app_id":"com.test","device_id":"dev-001","events":[{"type":"click","page":"home","element":"btn","timestamp":1719734400000}]}'

# 日志上报
curl -X POST http://localhost:8100/api/v1/log \
  -H "Content-Type: application/json" \
  -d '{"app_id":"com.test","device_id":"dev-001","logs":[{"level":"info","tag":"Test","message":"hello","timestamp":1719734400000}]}'
```

---

## 6. 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-06-30 | 初始版本，4 个 SDK 接口 |

---

> 有问题随时找后端同学（喻远飞）沟通 🍔
