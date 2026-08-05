# `/api/v1/config/meta` 环境变量配置修复记录

日期：2026-08-05

## 1. 本次修复目标

根据接口对接要求，调整 SDK 配置元信息接口：

```http
GET /api/v1/config/meta
```

接口不再强制要求传入 `app_id`。SDK 可以直接无参数请求该接口，并根据返回的三个开关分别决定是否拉取三个 CDN JSON。

## 2. 修复前问题

原接口定义中：

```python
app_id: str = Query(...)
```

这会导致 SDK 不传 `app_id` 时返回 HTTP `422 Unprocessable Entity`。

同时，原接口只返回：

```json
{
  "version": "...",
  "updated_at": "...",
  "cdn_url": "..."
}
```

不满足当前 SDK 需要的三个开关和三个 CDN 地址。

## 3. 本次修复内容

### 3.1 `app_id` 改为可选

接口现在支持：

```http
GET /api/v1/config/meta
```

也兼容旧调用方式：

```http
GET /api/v1/config/meta?app_id=test
```

### 3.2 新增环境变量配置项

在后端配置类中新增以下环境变量：

```env
CONFIG_META_IS_OPEN=true
CONFIG_META_IS_NEWS_TOUCH=true
CONFIG_META_IS_NEW_TEXT_RULE=true
CONFIG_META_CDN_URL=https://cdnversion.deeppopgame.xyz/config/latest.json
CONFIG_META_CDN_URL2=https://cdnNewtouch.deeppopgame.xyz/config/latest.json
CONFIG_META_CDN_URL3=https://cdnNewTextRule.deeppopgame.xyz/config/latest.json
```

### 3.3 接口返回结构调整

接口成功返回示例：

```json
{
  "code": 0,
  "data": {
    "version": "1.0.11",
    "updated_at": "2026-06-30T10:00:00+00:00",
    "isOpen": true,
    "isNewsTouch": true,
    "isNewTextRule": true,
    "cdn_url": "https://cdnversion.deeppopgame.xyz/config/latest.json",
    "cdn_url2": "https://cdnNewtouch.deeppopgame.xyz/config/latest.json",
    "cdn_url3": "https://cdnNewTextRule.deeppopgame.xyz/config/latest.json"
  }
}
```

字段说明：

| 字段 | 来源 | 说明 |
|---|---|---|
| `version` | 当前已发布配置记录 | SDK 用于判断本地缓存是否过期 |
| `updated_at` | 当前已发布配置记录 | 配置发布时间 |
| `isOpen` | `CONFIG_META_IS_OPEN` | 是否拉取 `cdn_url` |
| `isNewsTouch` | `CONFIG_META_IS_NEWS_TOUCH` | 是否拉取 `cdn_url2` |
| `isNewTextRule` | `CONFIG_META_IS_NEW_TEXT_RULE` | 是否拉取 `cdn_url3` |
| `cdn_url` | `CONFIG_META_CDN_URL` | 主配置 JSON 地址 |
| `cdn_url2` | `CONFIG_META_CDN_URL2` | 新触达配置 JSON 地址 |
| `cdn_url3` | `CONFIG_META_CDN_URL3` | 新文本规则配置 JSON 地址 |

## 4. 修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/app/core/config.py` | 新增 3 个开关和 3 个 CDN 地址环境变量配置 |
| `backend/app/api/sdk/config.py` | `app_id` 改为可选；返回环境变量配置的开关和 CDN 地址 |
| `backend/tests/test_sdk_api.py` | 新增无参数请求和环境变量返回结构测试 |

## 5. 验证结果

已执行后端测试：

```bash
python -m pytest backend\tests\test_sdk_api.py -q
```

结果：

```text
7 passed in 0.05s
```

已执行全量后端测试：

```bash
python -m pytest backend\tests -q
```

结果：

```text
42 passed in 4.60s
```

## 6. 部署配置说明

服务器 `.env` 文件需要增加：

```env
CONFIG_META_IS_OPEN=true
CONFIG_META_IS_NEWS_TOUCH=true
CONFIG_META_IS_NEW_TEXT_RULE=true
CONFIG_META_CDN_URL=https://cdnversion.deeppopgame.xyz/config/latest.json
CONFIG_META_CDN_URL2=https://cdnNewtouch.deeppopgame.xyz/config/latest.json
CONFIG_META_CDN_URL3=https://cdnNewTextRule.deeppopgame.xyz/config/latest.json
```

修改 `.env` 后需要重启 SDK API 服务，使环境变量生效。

示例：

```bash
sudo systemctl restart sdk-api
```

如果实际服务名不同，请以服务器上的 systemd 服务名为准。
