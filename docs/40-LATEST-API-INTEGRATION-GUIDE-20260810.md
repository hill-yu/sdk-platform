# SDK 平台最新接口对接文档

> 文档版本：1.1
>
> 更新时间：2026-08-11
>
> 对应功能分支：`codex/post-config-download-semver`
> 生产域名：`https://sdk.deeppopgame.xyz`

## 1. 文档说明

本文档描述本次部署后的接口基线，覆盖 SDK 侧接口和管理后台接口。配置下发协议为“包名隔离 + 三段版本判断 + POST 下载 + AES-256-GCM 加密信封”。

以下旧协议已经停用：

```text
GET  /api/v1/config/meta
POST /api/v1/config/latest
```

旧 `/api/v1/config/latest` 当前返回 `404`。新版 SDK 必须调用 `POST /api/v1/config/meta` 并在 JSON 请求体中提交 `package_name`。

## 2. 服务地址和鉴权

### 2.1 SDK API

```text
Base URL: https://sdk.deeppopgame.xyz
```

配置相关接口要求：

```http
Authorization: Bearer <SDK_CONFIG_TOKEN>
```

版本检查、点击上报和日志上报当前不要求该 Token。

### 2.2 Admin API

```text
Base URL: https://sdk.deeppopgame.xyz/api/admin
```

所有 Admin API 要求：

```http
Authorization: Bearer <ADMIN_TOKEN>
```

Token 不得放入 URL、查询参数、日志或前端源代码。

## 3. SDK 配置获取流程

```text
SDK 获取自身包名
  -> POST /api/v1/config/meta
  -> 比较响应 version 与本地成功启用版本
  -> 版本相同：继续使用本地配置
  -> 版本不同：根据三个开关分别下载加密信封
  -> 校验包名、版本、配置类型、算法和 key_id
  -> HKDF-SHA256 派生密钥
  -> AES-256-GCM 解密并验证认证标签
  -> JSON 和业务校验成功后原子替换本地配置
  -> 最后更新本地版本号
```

任何下载、解密或 JSON 校验失败时，必须保留上一份有效配置，并且不能更新本地版本号。

## 4. 获取配置元信息

### 4.1 请求

```http
POST /api/v1/config/meta
Authorization: Bearer <SDK_CONFIG_TOKEN>
Content-Type: application/json
```

```json
{
  "package_name": "test.package"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `package_name` | string | 是 | SDK 实际包名；长度 1～255，允许小写字母、数字、点、下划线和连字符 |

包名会去除首尾空格并转换为小写。生产环境当前已有配置的包名为 `test.package`。

### 4.2 成功响应

```json
{
  "code": 0,
  "data": {
    "package_name": "test.package",
    "version": "1.0.0",
    "updated_at": "2026-08-06T07:49:10.366388+00:00",
    "isOpen": true,
    "isNewsTouch": true,
    "isNewTextRule": true,
    "cdn_url": "https://sdk.deeppopgame.xyz/api/v1/config/packages/test.package/versions/1.0.0/main",
    "cdn_url2": "https://sdk.deeppopgame.xyz/api/v1/config/packages/test.package/versions/1.0.0/new-touch",
    "cdn_url3": "https://sdk.deeppopgame.xyz/api/v1/config/packages/test.package/versions/1.0.0/new-text-rule"
  }
}
```

| 响应字段 | 说明 |
|---|---|
| `package_name` | 本次配置所属包名，SDK 必须与自身包名核对 |
| `version` | 服务端当前已发布配置版本，由 SDK 与本地版本比较 |
| `updated_at` | 当前版本发布时间，ISO 8601 格式 |
| `isOpen` | 是否启用主配置 |
| `isNewsTouch` | 是否拉取 `cdn_url2` |
| `isNewTextRule` | 是否拉取 `cdn_url3` |
| `cdn_url` | 主配置加密信封地址，类型为 `main` |
| `cdn_url2` | 新触达配置加密信封地址，类型为 `new_touch` |
| `cdn_url3` | 新文本规则加密信封地址，类型为 `new_text_rule` |

`meta` 不接收 SDK 本地版本号，也不返回 `304`。版本是否相同完全由 SDK 本地判断。

### 4.3 curl 示例

```bash
curl -X POST 'https://sdk.deeppopgame.xyz/api/v1/config/meta' \
  -H "Authorization: Bearer $SDK_CONFIG_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"package_name":"test.package"}'
```

### 4.4 错误响应

| 场景 | HTTP 状态 | 说明 |
|---|---:|---|
| Token 缺失或错误 | 401 | `Invalid SDK config token` |
| `package_name` 缺失或格式非法 | 422 | 请求字段校验失败 |
| 包名不存在或没有已发布配置 | 404 | `code=1`、`data=null` |
| 服务器没有配置 Token | 500 | 服务端配置错误 |

## 5. 下载加密配置

三个地址均由 `meta` 动态返回，SDK 不应自行拼接。当前本地下发模式使用以下接口：

```http
POST /api/v1/config/packages/{package_name}/versions/{version}/{config_type}
Authorization: Bearer <SDK_CONFIG_TOKEN>
```

下载请求没有请求体。旧 GET 方法不兼容，返回 `405 Method Not Allowed`。

`config_type` 只允许：

| URL 类型 | 信封中的 `config_type` |
|---|---|
| `main` | `main` |
| `new-touch` | `new_touch` |
| `new-text-rule` | `new_text_rule` |

请求示例：

```bash
curl -X POST 'https://sdk.deeppopgame.xyz/api/v1/config/packages/test.package/versions/1.0.0/main' \
  -H "Authorization: Bearer $SDK_CONFIG_TOKEN"
```

成功响应为加密信封：

```json
{
  "version": "1.0.0",
  "package_name": "test.package",
  "config_type": "main",
  "algorithm": "AES-256-GCM",
  "key_id": "v1",
  "nonce": "Base64编码的12字节随机数",
  "ciphertext": "Base64编码的密文及16字节GCM认证标签"
}
```

该响应没有 `code/data` 外层包装。SDK 应先校验信封元数据，再进行 Base64 解码和解密。

错误状态：

| 场景 | HTTP 状态 |
|---|---:|
| Token 缺失或错误 | 401 |
| 包名、版本或类型不存在 | 404/422 |
| 使用 GET 下载 | 405 |

### 5.1 配置版本规则

每个包名分别从 `1.0.0` 开始递增：

```text
1.0.0 → 1.0.1 → ... → 1.0.9 → 1.1.0 → ... → 1.9.9 → 2.0.0
```

- 草稿不占用正式版本；
- 发布成功时才分配新版本；
- Meta 的 `version`、三个 URL 中的版本和下载信封的 `version` 必须一致；
- 回滚直接恢复历史配置原版本，不创建新版本；
- 回滚后的下一次发布仍从该包所有历史记录中的最大版本继续递增。

## 6. 配置解密协议

### 6.1 密钥派生

```text
输入密钥材料 IKM = UTF-8(SDK_CONFIG_TOKEN)
算法              = HKDF-SHA256
salt              = UTF-8("sdk-config-encryption-v1")
info              = UTF-8("sdk-config/aes-256-gcm")
输出长度          = 32 字节
```

### 6.2 AAD

严格按照以下格式和顺序构造 UTF-8 字节：

```text
package_name=<package_name>&version=<version>&config_type=<config_type>
```

示例：

```text
package_name=test.package&version=1.0.0&config_type=main
```

### 6.3 AES-GCM 参数

```text
算法       AES-256-GCM
密钥       HKDF 派生的 32 字节密钥
nonce      Base64 解码后的 12 字节
ciphertext Base64 解码后的密文，末尾包含 16 字节认证标签
AAD        上述固定格式的 UTF-8 字节
```

认证标签校验失败时，配置必须视为无效，不得尝试忽略错误继续解析。

跨语言固定测试向量见：`docs/SDK-CONFIG-CRYPTO-TEST-VECTOR.json`。

## 7. SDK 版本检查

### 7.1 请求

```http
GET /api/v1/version?platform=ios&current_version=120
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `platform` | 是 | `ios` 或 `android` |
| `current_version` | 否 | 当前 SDK 数字版本号，默认 `0` |

有更新时返回：

```json
{
  "code": 0,
  "data": {
    "has_update": true,
    "update_policy": "suggest",
    "latest_version": {
      "platform": "ios",
      "version_code": 121,
      "version_name": "1.2.1",
      "download_url": "https://cdn.example.com/sdk/ios/1.2.1.zip",
      "release_notes": "更新说明",
      "file_size": 102400,
      "file_hash": "sha256值"
    },
    "min_required_version": 100
  }
}
```

`update_policy` 可为 `force`、`suggest`、`silent`。

## 8. 点击事件上报

### 8.1 请求

```http
POST /api/v1/click
Content-Type: application/json
```

```json
{
  "package_name": "test.package",
  "device_id": "device-001",
  "sdk_version": "1.0.0",
  "session_id": "session-001",
  "events": [
    {
      "type": "click",
      "page": "home",
      "element": "confirm_button",
      "position": {"x": 120, "y": 260},
      "timestamp": 1786330000000,
      "extra": {}
    }
  ]
}
```

限制：

- `events` 每次 1～100 条。
- `package_name` 必传，最大 255 字符；`device_id` 最大 64 字符。
- 单条事件的 `page` 和 `element` 不能同时为空。
- `timestamp` 为毫秒时间戳；非法时间戳会被忽略并使用服务端时间。

成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {"accepted": 1, "rejected": 0}
}
```

部分事件无效会返回 `partial_success`；全部事件被拒绝时 HTTP 状态为 `422`、业务码为 `4001`。

## 9. 日志上报

### 9.1 请求

```http
POST /api/v1/log
Content-Type: application/json
```

```json
{
  "package_name": "test.package",
  "device_id": "device-001",
  "sdk_version": "1.0.0",
  "logs": [
    {
      "level": "info",
      "tag": "Config",
      "message": "config loaded",
      "timestamp": 1786330000000,
      "extra": "{ouoghaougoagahdgjalglauoi|dlaugouojlJ}"
    }
  ]
}
```

限制：

- `logs` 每次 1～100 条。
- `level` 只允许 `debug`、`info`、`warn`、`error`。
- `package_name` 必传，最大 255 字符。
- `level` 必传，只允许 `debug`、`info`、`warn`、`error`。
- `extra` 必传且必须是字符串；服务端不解析、不校验其内部格式，会原样保存。
- `message` 可不传、传 `null` 或空字符串；服务端统一保存为空字符串。非空时最大 10000 字符。
- `tag` 可选，最大 100 字符。

## 10. Admin 配置管理接口

以下路径均以 `/api/admin` 为前缀，并要求 Admin Bearer Token。

### 10.1 配置接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/configs?package_name=test.package` | 获取配置摘要列表；包名可选 |
| GET | `/configs/{config_id}` | 获取配置详情；服务端解密后返回 `config_data` |
| POST | `/configs` | 创建加密草稿 |
| PUT | `/configs/{config_id}` | 修改草稿并重新加密 |
| POST | `/configs/{config_id}/publish` | 发布草稿 |
| POST | `/configs/{config_id}/rollback` | 恢复历史记录及其原版本，不创建新版本 |
| GET | `/configs/reconcile?package_name=test.package` | 对账数据库版本与下发信封版本 |

### 10.2 创建草稿

```http
POST /api/admin/configs
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json
```

```json
{
  "package_name": "test.package",
  "config_data": {
    "mainConfig": {},
    "newTouchConfig": {},
    "newTextRuleConfig": {}
  },
  "change_log": "初始化配置"
}
```

三个根字段必须同时存在。配置 JSON 的 UTF-8 序列化大小不得超过 500000 字节。

### 10.3 修改草稿

```http
PUT /api/admin/configs/{config_id}
```

```json
{
  "config_data": {
    "mainConfig": {},
    "newTouchConfig": {},
    "newTextRuleConfig": {}
  },
  "change_log": "调整配置"
}
```

修改接口不接受包名。仅 `draft` 状态可以修改；`published` 和 `archived` 为只读。

### 10.4 列表响应

```json
{
  "code": 0,
  "data": {
    "published": [],
    "drafts": [],
    "history": []
  }
}
```

列表只返回摘要，不返回 `config_data` 或 `encrypted_config`。完整配置只能通过管理员鉴权的详情接口读取。

## 11. Admin 版本和数据接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/versions?platform=ios` | SDK 版本列表 |
| POST | `/api/admin/versions` | 创建 SDK 版本 |
| PUT | `/api/admin/versions/{version_id}` | 修改 SDK 版本 |
| GET | `/api/admin/dashboard/summary` | Dashboard 汇总 |
| GET | `/api/admin/dashboard/trend?range=24h&event_type=click` | 趋势数据 |
| GET | `/api/admin/dashboard/breakdown?date=2026-08-10&dimension=event_type` | 维度分布 |
| GET | `/api/admin/events` | 事件明细分页查询 |

事件查询支持：`page`、`page_size`、`event_type`、`package_name`、`device_id`、`date_from`、`date_to`。`page_size` 范围为 1～100。

## 12. 对接验收清单

- [ ] SDK 使用真实包名调用 `POST /api/v1/config/meta`。
- [ ] SDK 能识别 `401`、`404` 和 `422`，不会把错误响应当作配置。
- [ ] SDK 只在服务端版本与本地有效版本不同时下载配置。
- [ ] SDK 按三个开关分别请求三个地址。
- [ ] SDK 验证信封包名、版本、类型、算法和 `key_id`。
- [ ] SDK 使用固定测试向量验证 HKDF/AES-GCM 实现。
- [ ] SDK 解密失败时保留上一份有效配置。
- [ ] 三份配置全部通过业务校验后再更新本地版本。
- [ ] Admin 新建配置时填写包名并包含三个标准根字段。
- [ ] Admin 列表不展示配置明文，详情接口只在鉴权后读取。

---

本接口文档替代旧配置获取协议说明；历史文档中关于 `GET /config/meta`、`config_version`、`app_id` 查询参数和全局 `latest.json` 的描述均不再适用。
