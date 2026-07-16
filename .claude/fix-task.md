# Claude Fix Task: SDK Platform — 代码审查修复

## 项目位置
D:\code\SDK\

## 需要修复的文件和具体改动

### Fix 1: database.py — 加连接池超时和回收 (CRITICAL)
文件: D:\code\SDK\backend\app\core\database.py
在 create_async_engine() 调用中添加两个参数:
- pool_timeout=5  (池满时等5秒拿不到连接就抛错,不挂死)
- pool_recycle=1800 (30分钟回收连接,防止pg端断开)

### Fix 2: admin_main.py — 限制 CORS (CRITICAL)
文件: D:\code\SDK\backend\app\admin_main.py
将 allow_origins=["*"] 改为 allow_origins=["http://localhost:5173", "http://localhost:3000"]
生产环境从环境变量读取: os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

### Fix 3: analysis_service.py — SQL 注入反模式 → SQLAlchemy ORM (CRITICAL)
文件: D:\code\SDK\backend\app\services\analysis_service.py
问题: 用 f-string 拼接 SQL 的 WHERE 子句和 dimension 表达式
修复: 改用 SQLAlchemy ORM 方式构建查询:
```python
from sqlalchemy import select, func, text
from app.models.event import SdkEvent

# 替换所有 f-string SQL 拼接为:
stmt = select(
    func.date_trunc('day', SdkEvent.server_ts).label('stat_date'),
    SdkEvent.event_type,
    func.count().label('event_count'),
    func.count(func.distinct(SdkEvent.device_id)).label('unique_devices')
).where(SdkEvent.server_ts >= start_date)
# 动态加条件用 if:
if event_type:
    stmt = stmt.where(SdkEvent.event_type == event_type)
if app_id:
    stmt = stmt.where(SdkEvent.app_id == app_id)
```

### Fix 4: init_db.sql — 物化视图刷新加并发锁 (HIGH)
文件: D:\code\SDK\scripts\init_db.sql
修改 refresh_materialized_views() 函数,用 pg_try_advisory_lock 防止并发刷新:
```sql
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    IF pg_try_advisory_lock(12345) THEN
        REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_event_stats;
        REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_trend;
        PERFORM pg_advisory_unlock(12345);
    END IF;
END;
$$ LANGUAGE plpgsql;
```
同时更新 admin_main.py 中 ETL 启动逻辑: 先立即刷新一次,然后再进入5分钟循环。

### Fix 5: click.py + log.py — savepoint 循环 → 批量 INSERT (HIGH)
文件: D:\code\SDK\backend\app\api\sdk\click.py 和 D:\code\SDK\backend\app\api\sdk\log.py
问题: 每条事件一个 savepoint,100条=100次DB往返
修复: 收集所有合法事件,用一次批量 INSERT:
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

values = []
for event in body.events:
    if not event.element and not event.page:
        rejected += 1
        continue
    values.append({...})
if values:
    stmt = pg_insert(SdkEvent).values(values).on_conflict_do_nothing()
    await db.execute(stmt)
    accepted = len(values)
```

### Fix 6: deps.py — Token 常量时间比较 (MEDIUM)
文件: D:\code\SDK\backend\app\api\admin\deps.py
将 `credentials.credentials != settings.ADMIN_TOKEN` 改为:
```python
import hmac
if not hmac.compare_digest(credentials.credentials, settings.ADMIN_TOKEN):
```
防止时序攻击。

### Fix 7: sdk_main.py — 加请求体大小限制 (MEDIUM)
文件: D:\code\SDK\backend\app\sdk_main.py
在 FastAPI app 创建时加:
```python
from fastapi import FastAPI, Request
app = FastAPI(title="SDK API", version="1.0.0", request_max_size=1_000_000)  # 1MB
```

### Fix 8: admin_main.py — 加请求体大小限制 (MEDIUM)
同上,在 admin_main.py 的 FastAPI() 加 request_max_size=5_000_000 (5MB,因为配置JSON可能较大)

## 验证
修改完成后,确保:
- 所有 .py 文件无语法错误
- click.py 和 log.py 的 import 正确
- analysis_service.py 不使用任何 f-string 拼接 SQL

## 关键约束
- 不要改业务逻辑,只做安全/性能修复
- 保持现有的函数签名不变
- 不要引入新的依赖
- 修改后文件能正常 import
