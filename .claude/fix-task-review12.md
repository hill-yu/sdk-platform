# Claude Fix Task: 12号审阅报告 — 全部修复（11项）

## 项目位置
D:\code\SDK\

## ⚠️ 铁律：每修完一项，立即 git add + git commit。按编号顺序执行。

---

## Fix 3.1: 配置回滚漏 await + COS 改同步 (MUST FIX)

文件: `D:\code\SDK\backend\app\services\config_service.py`

问题: `_upload_config_payload()` 是 async，调用处缺 `await`，coroutine 从未执行

修复:
1. 将 `_upload_config_payload` 改为普通同步函数（去掉 `async`）
2. 所有调用处改为 `await asyncio.to_thread(_upload_config_payload, ...)`
3. 确保 `import asyncio` 在文件顶部

```python
import asyncio

def _upload_config_payload(cos_key: str, json_bytes: bytes) -> str:  # 去掉 async
    """上传配置到 COS（同步函数，由调用方通过 to_thread 执行）"""
    settings = get_settings()
    if not settings.COS_SECRET_ID or not settings.COS_SECRET_KEY or not settings.COS_BUCKET:
        raise RuntimeError("COS 凭证未配置")
    # ... 后续不变

# publish_config 中:
await asyncio.to_thread(_upload_config_payload, f"config/v{version}.json", json_bytes)
await asyncio.to_thread(_upload_config_payload, "config/latest.json", json_bytes)

# _publish_from_record 中同上
```

提交: `git commit -m "fix: 3.1 回滚漏await修复+COS改同步+to_thread防阻塞事件循环"`

---

## Fix 3.2: 实现真实请求体大小限制 (MUST FIX)

文件: `D:\code\SDK\backend\app\sdk_main.py` 和 `admin_main.py`

问题: `request_max_size` 不是 FastAPI 有效参数

修复:
1. 删除无效的 `request_max_size=...`
2. 在两个入口文件中添加 ASGI 中间件:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes
    
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Max: {self.max_bytes} bytes"}
            )
        return await call_next(request)

# SDK: app.add_middleware(RequestSizeLimitMiddleware, max_bytes=1_000_000)
# Admin: app.add_middleware(RequestSizeLimitMiddleware, max_bytes=5_000_000)
```

提交: `git commit -m "fix: 3.2 实现真实请求体大小限制，SDK 1MB / Admin 5MB，超限返回413"`

---

## Fix 3.3: advisory lock 改用事务级 xact (MUST FIX)

文件: `D:\code\SDK\scripts\init_db.sql`

问题: session 级锁在异常路径不释放

修复: 将 `pg_try_advisory_lock` + `pg_advisory_unlock` 改为 `pg_try_advisory_xact_lock`:

```sql
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    IF pg_try_advisory_xact_lock(12345) THEN
        REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_event_stats;
        REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_trend;
    END IF;
END;
$$ LANGUAGE plpgsql;
```

关键变化: 删除 `PERFORM pg_advisory_unlock(12345)` — 事务级锁在函数返回时自动释放。

提交: `git commit -m "fix: 3.3 advisory lock改事务级xact，异常时自动释放不泄漏"`

---

## Fix 3.4: COS/DB 一致性 — commit 后 COS (MUST FIX)

文件: `D:\code\SDK\backend\app\services\config_service.py`

问题: flush 后 COS 上传，但 commit 可能失败

修复: COS 上传移到 commit 之后执行。在 `publish_config` 中:

```python
# ① DB 操作: 归档旧 + 设置当前
await db.execute(update(SdkConfig).where(...).values(status="archived"))
config.status = "published"
config.version = version
config.publish_at = datetime.now()
config.cos_key = f"config/v{version}.json"
await db.flush()
# 此时 get_db 会自动 commit（因为函数正常返回）

# ② 函数返回前，先 commit 确保 DB 落库
# (get_db 依赖会在 yield 后 commit，这里显式确保)
# ③ COS 上传放在 DB 确认后
try:
    await asyncio.to_thread(_upload_config_payload, f"config/v{version}.json", json_bytes)
    await asyncio.to_thread(_upload_config_payload, "config/latest.json", json_bytes)
except Exception:
    # COS 失败时标记状态（DB 已提交，需异步修复）
    config.cos_upload_status = "failed"
    logger.exception("COS 上传失败，DB 已提交，需人工修复: version=%s", version)
    raise RuntimeError(f"COS 上传失败: {version}，配置已入库但 CDN 未更新，请联系管理员")
```

同时给 sdk_configs 表加 `cos_upload_status` 列（可选，VARCHAR(20), default 'pending'）

提交: `git commit -m "fix: 3.4 COS上传移到DB提交后，失败时标记status支持人工修复"`

---

## Fix 4.1: COS 同步调用改 to_thread (SUGGESTED)

已随 3.1 一并修复。如果 3.1 已正确改为 `await asyncio.to_thread(_upload_config_payload, ...)`，则本项自动完成。

无需额外操作，在 3.1 的 commit message 中已包含。

---

## Fix 4.2: config_data 字节大小校验 (SUGGESTED)

文件: `D:\code\SDK\backend\app\schemas\admin_schemas.py`

问题: `Field(max_length=500000)` 对 dict 限制的是键数量

修复:
```python
from pydantic import field_validator
import json

class ConfigUpsertRequest(BaseModel):
    config_data: dict[str, Any]
    
    @field_validator("config_data")
    @classmethod
    def validate_size(cls, v: dict) -> dict:
        json_bytes = json.dumps(v, ensure_ascii=False).encode("utf-8")
        if len(json_bytes) > 500_000:
            raise ValueError(f"config_data JSON 大小超过 500KB 限制（当前 {len(json_bytes)} 字节）")
        return v
```

提交: `git commit -m "fix: 4.2 config_data改为字节大小校验，非字典键数量"`

---

## Fix 4.3: 版本号加微秒防冲突 (SUGGESTED)

文件: `D:\code\SDK\backend\app\services\config_service.py`

问题: 秒级版本号同一秒内会冲突

修复: 所有版本号生成处改为含微秒:
```python
# 改前
version = datetime.now().strftime("%Y%m%d_v%H%M%S")
version_draft = f"draft_{datetime.now():%Y%m%d%H%M%S}"

# 改后
version = datetime.now().strftime("%Y%m%d_v%H%M%S_%f")  # %f = 微秒
version_draft = f"draft_{datetime.now():%Y%m%d%H%M%S_%f}"
```

提交: `git commit -m "fix: 4.3 版本号加微秒后缀防同一秒内唯一键冲突"`

---

## Fix 4.4: 占位 CDN 启动校验 (SUGGESTED)

文件: `D:\code\SDK\backend\app\admin_main.py` 和 `sdk_main.py`

问题: 代码和初始 SQL 中有 `cdn.example.com` 占位符

修复:
1. 在 admin_main.py 的 lifespan 中加校验:
```python
if "example.com" in settings.CDN_BASE_URL or "example.com" in settings.COS_BUCKET:
    raise RuntimeError(
        "CDN/COS 配置为占位符！请在 .env 中设置真实的 CDN_BASE_URL 和 COS_BUCKET"
    )
```

2. 修改 `api/sdk/config.py:54` 的 fallback:
```python
# 改前
cdn_url = published.cdn_url or "https://cdn.example.com/config/latest.json"

# 改后 — 不 fallback 到占位符，返回错误
if not published.cdn_url:
    return JSONResponse(status_code=500, content={
        "code": 2, "message": "配置已发布但 CDN 地址缺失，请联系管理员", "data": None
    })
cdn_url = published.cdn_url
```

提交: `git commit -m "fix: 4.4 启动时校验CDN/COS非占位符，运行时不fallback到example.com"`

---

## Fix 4.5: 前端 Token 处理 (SUGGESTED)

文件: `D:\code\SDK\frontend\src\api\request.ts`

问题: VITE_ADMIN_TOKEN 编译进静态 JS，localStorage 可被 XSS 读取

修复:
1. 删除从 VITE_ADMIN_TOKEN 读取的代码
2. 初次访问时弹出登录框让用户手动输入 Token
3. Token 存 sessionStorage（非 localStorage，关闭浏览器即清除）
4. 生产构建脚本中不注入 VITE_ADMIN_TOKEN

```typescript
// 改后
const getToken = (): string => {
    // 优先从 sessionStorage 读取
    const stored = sessionStorage.getItem("admin_token");
    if (stored) return stored;
    // 弹出输入框
    const input = prompt("请输入 Admin Token:");
    if (input) {
        sessionStorage.setItem("admin_token", input);
        return input;
    }
    return "";
};
```

提交: `git commit -m "fix: 4.5 前端Token改为sessionStorage+手动输入，禁止构建时注入"`

---

## Fix 5.2: token_tmp.txt gitignore (REFERENCE)

文件: `D:\code\SDK\.gitignore`

添加行: `backend/token*.txt`

如果 token_tmp.txt 存在，删除它:
```bash
rm -f backend/token_tmp.txt
```

提交: `git commit -m "chore: 5.2 token_tmp.txt加入gitignore并删除临时凭据文件"`

---

## Fix 3.5: 恢复测试基线 (MUST FIX — 最后执行)

依赖 3.1~3.4 全部修复完成后执行。

修复步骤:
1. 为测试环境注入满足强度要求的固定 Token（长度≥32，不含 admin/change-me）
2. 更新 SDK 写入测试桩：从模拟 `db.add()` 改为覆盖批量 `execute()`
3. 统一回滚版本号逻辑 + 更新测试预期
4. 修复 COS mock 中的 async/await

验证: `python -m pytest backend/tests -q` 要求 0 failed

提交: `git commit -m "fix: 3.5 恢复测试基线，修复Token校验/批量INSERT/回滚版本号/async-await"`

---

## 验证清单

全部修复完成后:
```bash
cd D:\code\SDK
git log --oneline -15
python -m pytest backend/tests -q  # 目标: 0 failed
```
