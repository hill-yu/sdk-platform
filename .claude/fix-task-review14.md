# Claude Fix Task: 14号二次审阅报告 — 3项必须修复 + 4项建议修改

## 项目位置
D:\code\SDK\

## ⚠️ 每修完一个 Fix，立即 git add + git commit。按编号顺序执行。

---

## Fix 3.1: COS失败配置不对SDK可见 (MUST FIX — 方案B)

### 步骤1: 修改 SDK 查询条件

文件: `D:\code\SDK\backend\app\api\sdk\config.py`

将第 31-33 行左右的查询改为:
```python
result = await db.execute(
    select(SdkConfig).where(
        SdkConfig.status == "published",
        SdkConfig.cos_upload_status == "success"
    ).limit(1)
)
```

### 步骤2: 修改发布流程 — 先COS后归档

文件: `D:\code\SDK\backend\app\services\config_service.py` 的 `publish_config()`

改为: 先上传 COS → 成功后才归档旧配置并设新配置为 published:
```python
async def publish_config(db, config_id: int, published_by: str) -> dict:
    config = await db.get(SdkConfig, config_id)
    if not config or config.status != "draft":
        raise ValueError("只能发布草稿状态的配置")
    
    version = datetime.now().strftime("%Y%m%d_v%H%M%S_%f")
    publish_data = {"version": version, "updated_at": datetime.now().isoformat(), "config": config.config_data}
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()
    
    # ① 先上传 COS（版本文件 + latest.json）
    await asyncio.to_thread(_upload_config_payload, f"config/v{version}.json", json_bytes)
    await asyncio.to_thread(_upload_config_payload, "config/latest.json", json_bytes)
    
    # ② COS 成功 → 归档旧 + 当前变 published
    await db.execute(
        update(SdkConfig).where(SdkConfig.status == "published").values(status="archived")
    )
    config.status = "published"
    config.version = version
    config.publish_at = datetime.now()
    config.published_by = published_by
    config.cos_key = f"config/v{version}.json"
    config.cos_upload_status = "success"
    config.cdn_url = _cdn_url(config.cos_key)
    
    return {"version": version, "publish_at": config.publish_at.isoformat(), "cdn_url": config.cdn_url, "cos_key": config.cos_key}
```

关键变化: COS 失败时抛异常 → 旧 published 完好 → DB 无任何变更

### 步骤3: 同样修改 _publish_from_record()

文件: `D:\code\SDK\backend\app\services\config_service.py`

改为同样逻辑: 先 COS → 后 DB

提交: `git commit -m "fix: 3.1 COS失败配置不对SDK可见，改为先COS后DB+查询加cos_upload_status条件"`

---

## Fix 3.2: 数据库迁移脚本 (MUST FIX)

### 步骤1: 创建迁移脚本

创建文件: `D:\code\SDK\scripts\migrate_cos_upload_status.sql`

```sql
-- 迁移: 添加 cos_upload_status 列
-- 适用于已有 sdk_configs 表的数据库升级

ALTER TABLE sdk_configs
ADD COLUMN IF NOT EXISTS cos_upload_status VARCHAR(20);

UPDATE sdk_configs
SET cos_upload_status = CASE
    WHEN status = 'published' THEN 'success'
    ELSE 'pending'
END
WHERE cos_upload_status IS NULL;

ALTER TABLE sdk_configs
ALTER COLUMN cos_upload_status SET DEFAULT 'pending',
ALTER COLUMN cos_upload_status SET NOT NULL;

ALTER TABLE sdk_configs
ADD CONSTRAINT chk_configs_cos_upload_status
CHECK (cos_upload_status IN ('pending', 'success', 'failed'));
```

### 步骤2: 同步更新 init_db.sql

文件: `D:\code\SDK\scripts\init_db.sql`

在 sdk_configs 建表语句中添加 `cos_upload_status` 列和 CHECK 约束（如果还没有的话）。

提交: `git commit -m "fix: 3.2 添加cos_upload_status数据库迁移脚本+CHECK约束"`

---

## Fix 3.3: 请求体限制防绕过 + 非法头部400 (MUST FIX)

### 步骤1: 重写中间件 — 按实际接收字节计数

文件: `D:\code\SDK\backend\app\sdk_main.py` 和 `admin_main.py` 中的 `RequestSizeLimitMiddleware`

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes
    
    async def dispatch(self, request: Request, call_next):
        # 1. 检查 Content-Length（快速拦截）
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(status_code=413, content={"detail": f"Request body too large"})
                if int(content_length) < 0:
                    return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
        
        # 2. 包装 receive 累计实际字节数
        total = 0
        original_receive = request.receive
        
        async def limited_receive():
            nonlocal total
            message = await original_receive()
            if message.get("type") == "http.request" and message.get("body"):
                total += len(message["body"])
                if total > self.max_bytes:
                    raise RequestSizeExceeded(self.max_bytes)
            return message
        
        request._receive = limited_receive
        
        try:
            return await call_next(request)
        except RequestSizeExceeded:
            return JSONResponse(status_code=413, content={"detail": f"Request body too large"})

class RequestSizeExceeded(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
```

### 步骤2: Nginx 配置

文件: `D:\code\SDK\docs\07-DEPLOYMENT.md` 的 Nginx 配置段

在 SDK API location 块加: `client_max_body_size 1m;`
在 Admin API location 块加: `client_max_body_size 5m;`

提交: `git commit -m "fix: 3.3 请求体限制防分块绕过+非法Content-Length返回400+Nginx配置"`

---

## Fix 4.1: Service事务边界 — 本次不改，记录为技术债

创建文件: `D:\code\SDK\docs\TECH-DEBT.md`

内容:
```md
# 技术债记录

## D1: config_service 事务边界分散
- 位置: config_service.py
- 问题: Service 自行 commit + 依赖外层 get_db commit，两层事务边界
- 建议: 后续独立发布用例统一编排事务阶段
- 优先级: Low
- 创建日期: 2026-07-16
```

提交: `git commit -m "docs: 记录config_service事务边界技术债"`

---

## Fix 4.2: Admin API 暴露 COS 上传状态 (SUGGESTED)

### 步骤1: _serialize_config 加 cos_upload_status

文件: `D:\code\SDK\backend\app\services\config_service.py`

在 `_serialize_config()` 返回 dict 中加:
```python
"cos_upload_status": config.cos_upload_status,
```

### 步骤2: 前端显示状态

文件: `D:\code\SDK\frontend\src\views\ConfigManager.vue`

在配置列表中显示 `cos_upload_status`:
- `success` → 绿色 "已同步" 标签
- `pending` → 黄色 "同步中"
- `failed` → 红色 "同步失败"

提交: `git commit -m "fix: 4.2 Admin API暴露cos_upload_status，前端显示同步状态"`

---

## Fix 4.3: 测试桩吞异常修复 (SUGGESTED)

文件: `D:\code\SDK\backend\tests\conftest.py`

找到 `StubWriteSession.execute()` 中的 `except Exception: pass`，改为:
```python
except (AttributeError, KeyError, TypeError):
    pass  # 参数提取相关异常才忽略
```

提交: `git commit -m "fix: 4.3 测试桩只捕获预期异常，数据库失败异常正常传播"`

---

## Fix 4.4: CHECK 约束 — 随 3.2 一并修复 ✅

已在 3.2 的迁移脚本中包含，无需额外操作。

---

## 验证

全部完成后:
```bash
cd D:\code\SDK
git log --oneline -10
python -m pytest backend/tests -q  # 目标: 17 passed, 0 failed
```
