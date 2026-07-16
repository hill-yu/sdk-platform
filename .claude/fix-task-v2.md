# Claude Fix Task: SDK Platform — 第二轮修复（6项）

## 项目位置
D:\code\SDK\

## 修复原则
- ⚠️ 只修复指定问题，不要改动其他代码
- ⚠️ 保持现有函数签名不变
- ⚠️ 修改后执行 `python -c "import ast; ast.parse(open('文件路径').read()); print('OK: 文件路径')"` 验证语法

---

## Fix H1: click.py + log.py — 移除死代码，简化异常处理

**文件**: `D:\code\SDK\backend\app\api\sdk\click.py` 和 `log.py`

**问题**: `on_conflict_do_nothing()` 后的 try/except 回退代码永远不会执行，是死代码

**修复**:
去掉逐条 `db.begin_nested()` / `db.add()` / `except` 的旧模式残留代码。批量 INSERT 后直接用一个整体 try/except 兜底：
```python
try:
    stmt = pg_insert(SdkEvent).values(values)
    await db.execute(stmt)
    accepted = len(values)
except Exception:
    # 批量写入失败，整批 rejected
    rejected = len(values)
    accepted = 0
```

验证: 文件语法正确，import 完整，SdkEvent 和 pg_insert 正确导入

---

## Fix H2: click.py + log.py — 全失败时返回 code≠0

**文件**: `D:\code\SDK\backend\app\api\sdk\click.py` 和 `log.py`

**问题**: `rejected > 0 and accepted == 0` 时返回 `code:0`，SDK 以为数据落库了——假成功

**修复**:
```python
# 全部失败
if accepted == 0 and rejected > 0:
    return {
        "code": 5001,
        "message": "all_events_rejected",
        "data": {"accepted": 0, "rejected": rejected},
    }

# 部分成功
if rejected > 0:
    return {
        "code": 0,
        "message": "partial_success",
        "data": {"accepted": accepted, "rejected": rejected},
    }

# 全部成功
return {
    "code": 0,
    "message": "ok",
    "data": {"accepted": accepted, "rejected": 0},
}
```

验证: 检查返回字典中 code 值的逻辑正确

---

## Fix H3: config_service.py — COS 先写 DB 再写 COS，加事务保护

**文件**: `D:\code\SDK\backend\app\services\config_service.py`

**问题**: 先上传 COS 成功，再更新 DB 失败 → CDN 和数据库状态不一致

**修复顺序（防不一致）**:
```
① 查配置(draft) → ② 生成版本号 → ③ DB: 旧published→archived, 当前→published → 
④ COS: 上传 latest.json + 历史版本 → ⑤ 若COS失败: DB回滚(把状态改回来)
```

即: 先写 DB，COS 上传失败时可回滚。
```python
async def publish_config(db, config_id: int, published_by: str) -> dict:
    config = await db.get(SdkConfig, config_id)
    if not config or config.status != "draft":
        raise ValueError("只能发布草稿状态的配置")
    
    version = datetime.now().strftime("%Y%m%d_v%H%M%S")
    
    # ① 先更新数据库状态
    await db.execute(
        update(SdkConfig).where(SdkConfig.status == "published").values(status="archived")
    )
    config.status = "published"
    config.version = version
    config.publish_at = datetime.now()
    config.published_by = published_by
    config.cos_key = f"config/v{version}.json"
    await db.flush()
    
    # ② 再上传 COS
    publish_data = {
        "version": version,
        "updated_at": datetime.now().isoformat(),
        "config": config.config_data,
    }
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()
    
    cdn_url = f"https://cdn.example.com/config/latest.json"
    
    try:
        client = _get_cos_client()
        client.put_object(Bucket=settings.COS_BUCKET, Key=f"config/v{version}.json", Body=json_bytes)
        client.put_object(
            Bucket=settings.COS_BUCKET,
            Key="config/latest.json",
            Body=json_bytes,
            CacheControl="max-age=300",
        )
    except Exception:
        # COS 上传失败 → 回滚 DB 状态
        await db.rollback()
        raise RuntimeError("COS 上传失败，配置发布已回滚")
    
    return {
        "version": version,
        "publish_at": config.publish_at.isoformat(),
        "cdn_url": cdn_url,
        "cos_key": config.cos_key,
    }
```

验证: 导入完整 (datetime, json, update from sqlalchemy, _get_cos_client)，逻辑顺序正确

---

## Fix M1: admin_main.py — ETL 裸 text() SQL → 改用 SQLAlchemy session

**文件**: `D:\code\SDK\backend\app\admin_main.py`

**问题**: `await conn.execute(text("SELECT refresh_materialized_views()"))` 用裸 text()

**修复**:
```python
from app.core.database import async_session_factory
from sqlalchemy import text

async def etl_refresh_loop():
    """ETL 定时刷新物化视图。启动时立即刷新一次，之后每5分钟刷新。"""
    # 启动时立即刷新
    async with async_session_factory() as session:
        try:
            await session.execute(text("SELECT refresh_materialized_views()"))
            await session.commit()
            logger.info("ETL 初始刷新完成")
        except Exception:
            await session.rollback()
    
    # 定时循环
    while True:
        await asyncio.sleep(300)
        async with async_session_factory() as session:
            try:
                await session.execute(text("SELECT refresh_materialized_views()"))
                await session.commit()
            except Exception:
                await session.rollback()
                logger.warning("ETL 刷新失败")
```

同时把 `print()` 改为 `logger.warning()`：
```python
import logging
logger = logging.getLogger(__name__)
```

验证: logger 正确使用，session 正确创建和关闭

---

## Fix M2: deps.py — hmac import 移到文件顶部

**文件**: `D:\code\SDK\backend\app\api\admin\deps.py`

**问题**: `import hmac` 写在函数体内部，每次鉴权都重新 import

**修复**: 把 `import hmac` 移到文件顶部 import 区域

```python
from __future__ import annotations

import hmac  # ← 移到顶部

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
```

然后删除函数内部的 `import hmac`

验证: 所有 import 在文件顶部，函数体干净

---

## 验证步骤

修改完成后，对每个修改的 .py 文件执行:
```bash
cd D:\code\SDK\backend
python -c "import ast; ast.parse(open('app/文件路径').read()); print('OK: 文件路径')"
```

全部通过后输出总结。
