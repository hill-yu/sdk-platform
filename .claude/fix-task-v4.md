# Claude Fix Task: SDK Platform — 第四轮收尾修复（6项）

## 项目位置
D:\code\SDK\

## ⚠️ 铁律：每修完一个 Fix，立即 git add + git commit

---

## Fix 1: admin_main.py — lifespan/on_event 混用 → 统一用 lifespan

文件: D:\code\SDK\backend\app\admin_main.py

问题: FastAPI 禁止混用 `lifespan` 和 `@app.on_event("startup")`，startup 可能不执行

修复: 删除 `@app.on_event("startup")`，把 ADMIN_TOKEN 校验 + ETL 启动逻辑全部合并到 `lifespan` 中:

```python
from contextlib import asynccontextmanager
from app.core.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：校验 ADMIN_TOKEN
    settings = get_settings()
    if not settings.ADMIN_TOKEN or "change-me" in settings.ADMIN_TOKEN:
        raise RuntimeError("ADMIN_TOKEN 未设置或使用弱默认值！请在 .env 中设置强随机 ADMIN_TOKEN")
    logger.info("ADMIN_TOKEN 校验通过")

    # 启动 ETL 定时刷新
    etl_task = asyncio.create_task(etl_refresh_loop())
    logger.info("ETL 定时刷新已启动")
    
    yield  # 应用运行中
    
    # 关闭：取消 ETL 任务
    etl_task.cancel()
    try:
        await etl_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Admin API", version="1.0.0", lifespan=lifespan, request_max_size=5_000_000)
```

删除文件末尾的 `startup_admin()` 函数和 `@app.on_event("startup")` 装饰器。

提交: `git commit -m "fix: 统一使用lifespan替代on_event混用，确保启动逻辑可靠执行"`

---

## Fix 2: ETL 周期刷新 logger.warning → logger.exception

文件: D:\code\SDK\backend\app\admin_main.py

在 `etl_refresh_loop()` 的定时循环 except 块中，将 `logger.warning` 改为 `logger.exception`:

```python
except Exception:
    await session.rollback()
    logger.exception("ETL 刷新失败")  # ← 改这行
```

提交: `git commit -m "fix: ETL周期刷新logger.warning改为logger.exception，保留完整堆栈"`

---

## Fix 3: click.py + log.py — 负时间戳导致 500 → 改为单条跳过

文件: D:\code\SDK\backend\app\api\sdk\click.py 和 log.py

问题: `datetime.fromtimestamp(负数/1000)` 抛出 OSError/ValueError，导致整个请求 500

修复: 在构建 values 列表时，时间戳转换失败 → 跳过该条事件（rejected += 1），不影响同批次其他事件:

```python
for event in body.events:
    if not event.element and not event.page:
        rejected += 1
        continue
    
    client_ts = None
    if event.timestamp is not None and event.timestamp > 0:
        try:
            client_ts = datetime.fromtimestamp(event.timestamp / 1000, tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            client_ts = None  # 非法时间戳 → 跳过，不用该字段
    
    values.append({...})
```

提交: `git commit -m "fix: 负时间戳改为单条跳过而非整个请求500"`

---

## Fix 4: sdk_schemas.py — 关键字段加 max_length

文件: D:\code\SDK\backend\app\schemas\sdk_schemas.py

给以下字段加 `max_length`:
- `app_id: str = Field(..., max_length=32)`
- `device_id: str = Field(..., max_length=64)`
- `sdk_version: Optional[str] = Field(None, max_length=20)`
- `session_id: Optional[str] = Field(None, max_length=64)`
- `ClickEvent.page: Optional[str] = Field(None, max_length=200)`
- `ClickEvent.element: Optional[str] = Field(None, max_length=200)`
- `LogEntry.message: str = Field(..., max_length=10000)`
- `LogEntry.tag: Optional[str] = Field(None, max_length=100)`

提交: `git commit -m "fix: SDK schemas关键字段加max_length，防止超长输入穿透到DB"`

---

## Fix 5: event_service.py — 删除死代码 build_sdk_event()

文件: D:\code\SDK\backend\app\services\event_service.py

整文件删除或清空为只有注释的空文件（保持目录结构）。click.py 和 log.py 均未使用此函数，纯死代码。

如有其他文件 import 了 event_service，先移除 import 再删文件。

提交: `git commit -m "chore: 删除未使用的event_service.py死代码"`

---

## Fix 6: admin_schemas.py — config_data 加大小限制

文件: D:\code\SDK\backend\app\schemas\admin_schemas.py

如果存在 `ConfigUpsertRequest`:
```python
from pydantic import Field
config_data: dict[str, Any] = Field(..., max_length=500000)  # 500KB 上限
```

提交: `git commit -m "fix: config_data加500KB大小限制，防超大JSON攻击"`

---

## 完成后验证

```bash
cd D:\code\SDK
git log --oneline -10
```
