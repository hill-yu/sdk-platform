# Claude Fix Task: SDK Platform — 第三轮修复（8项，逐个提交）

## 项目位置
D:\code\SDK\

## ⚠️ 铁律：每修完一个 Fix，立即 git commit
修复顺序严格按 C1 → C2+C3 → H1 → H2 → H3 → H4+H5

每个 Fix 完成后执行:
```bash
cd D:\code\SDK
git add 修改的文件
git commit -m "fix: 简短描述 (对应编号)"
```

---

## Fix C1: 去除弱默认 ADMIN_TOKEN，启动时强制校验 (CRITICAL)

文件: `D:\code\SDK\backend\app\core\config.py`

问题: 默认值 `admin-secret-token-change-me` 是弱占位符，部署时忘改就直接暴露

修复:
```python
# 改前
ADMIN_TOKEN: str = Field(default="admin-secret-token-change-me", repr=False)

# 改后 — 去掉默认值，不设则启动失败
ADMIN_TOKEN: str = Field(default="", repr=False)
```

然后在 `admin_main.py` 启动事件中加校验:
```python
@app.on_event("startup")
async def startup_admin():
    settings = get_settings()
    if not settings.ADMIN_TOKEN or settings.ADMIN_TOKEN == "admin-secret-token-change-me":
        raise RuntimeError(
            "ADMIN_TOKEN 未设置或使用弱默认值！请在 .env 中设置: ADMIN_TOKEN=<随机字符串>"
        )
```

验证: 语法正确，admin_main.py 导入 get_settings

提交: `git commit -m "fix: C1 去除弱默认ADMIN_TOKEN，启动时强制校验"`

---

## Fix C2+C3: 统一 COS 上传行为——未配置时抛异常而非静默跳过 (CRITICAL)

文件: `D:\code\SDK\backend\app\services\config_service.py`

问题: `_upload_config_payload()` COS未配置时静默 `return`，导致DB已标记published但CDN无文件

修复: 将静默 `return` 改为 `raise RuntimeError`:
```python
def _upload_config_payload(cos_key: str, json_bytes: bytes) -> str:
    settings = get_settings()
    if not settings.COS_SECRET_ID or not settings.COS_SECRET_KEY or not settings.COS_BUCKET:
        raise RuntimeError(
            "COS 凭证未配置，无法上传配置。请在 .env 中设置 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET"
        )
    # ... 后续上传代码不变
```

同时同步 `_cdn_url()` 函数使用 `settings.CDN_BASE_URL`:
```python
def _cdn_url(cos_key: str) -> str:
    settings = get_settings()
    return f"{settings.CDN_BASE_URL.rstrip('/')}/{cos_key}"
```

验证: 语法正确

提交: `git commit -m "fix: C2+C3 统一COS未配置行为，改为抛异常防假成功"`

---

## Fix H1: published_by 使用 token 标识而非硬编码 admin (HIGH)

文件: `D:\code\SDK\backend\app\api\admin\deps.py`

问题: `require_admin_token()` 始终返回 `"admin"`，审计追踪失效

修复: 返回 token 的 SHA256 前8位作为操作者标识:
```python
import hashlib
import hmac

async def require_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    settings = get_settings()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    if not hmac.compare_digest(credentials.credentials, settings.ADMIN_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    return hashlib.sha256(credentials.credentials.encode()).hexdigest()[:8]
```

验证: 语法正确，import hashlib

提交: `git commit -m "fix: H1 published_by改为token哈希标识，支持审计追踪"`

---

## Fix H2: click.py + log.py 写入失败加日志 (HIGH)

文件: `D:\code\SDK\backend\app\api\sdk\click.py` 和 `log.py`

问题: `except Exception` 块完全静默，DB故障运维完全不知道

修复: 在 except 块中加 `logger.exception()`:
```python
import logging
logger = logging.getLogger(__name__)

# 在批量写入的 except 块中:
except Exception:
    logger.exception("批量写入事件失败，app_id=%s, count=%d", body.app_id, len(values))
    rejected += len(values)
    accepted = 0
```

验证: 两个文件语法正确，logger 正确定义

提交: `git commit -m "fix: H2 写入失败加logger.exception，消灭生产盲区"`

---

## Fix H3: ETL 初始刷新失败加日志 (HIGH)

文件: `D:\code\SDK\backend\app\admin_main.py`

问题: `etl_refresh_loop()` 启动时的初始刷新失败完全静默

修复: 在初始刷新的 except 块中加日志:
```python
# 启动时立即刷新
async with async_session_factory() as session:
    try:
        await session.execute(text("SELECT refresh_materialized_views()"))
        await session.commit()
        logger.info("ETL 初始刷新完成")
    except Exception:
        await session.rollback()
        logger.exception("ETL 初始刷新失败，大盘数据可能为空")  # ← 加这行
```

验证: 语法正确

提交: `git commit -m "fix: H3 ETL初始刷新失败加logger.exception"`

---

## Fix H4+H5: _publish_from_record 改为 DB 先 + COS 后 + 失败回滚 (HIGH)

文件: `D:\code\SDK\backend\app\services\config_service.py`

问题: `_publish_from_record()` 是"先COS后DB"，与 `publish_config()` 的"先DB后COS"相反，且COS成功DB失败时无清理

修复: 重写 `_publish_from_record()` 为 DB 先 + COS 后 + 失败回滚:
```python
async def _publish_from_record(db, record: SdkConfig) -> dict:
    """从已有记录发布（用于回滚和首次发布），DB先 + COS后 + 失败回滚"""
    settings = get_settings()
    version = datetime.now().strftime("%Y%m%d_v%H%M%S")
    
    # ① 先更新 DB
    await db.execute(
        update(SdkConfig)
        .where(SdkConfig.status == "published")
        .values(status="archived")
    )
    record.status = "published"
    record.version = version
    record.publish_at = datetime.now()
    record.cos_key = f"config/v{version}.json"
    record.cdn_url = _cdn_url(record.cos_key)
    await db.flush()
    
    # ② 再上传 COS
    publish_data = {
        "version": version,
        "updated_at": datetime.now().isoformat(),
        "config": record.config_data,
    }
    json_bytes = json.dumps(publish_data, ensure_ascii=False).encode()
    
    try:
        _upload_config_payload(f"config/v{version}.json", json_bytes)
        _upload_config_payload("config/latest.json", json_bytes)
    except Exception:
        await db.rollback()
        raise RuntimeError(f"COS 上传失败，配置回滚/发布已撤销: {version}")
    
    return {
        "version": version,
        "publish_at": record.publish_at.isoformat(),
        "cdn_url": record.cdn_url,
        "cos_key": record.cos_key,
    }
```

注意检查现有代码结构:
- `_publish_from_record()` 和 `publish_config()` 可能共享了重复逻辑
- 如果有重复，抽取公共函数 `_do_publish(db, record)` 给两边调用
- 但本次只改顺序 + 加回滚，不改架构

验证: 语法正确，导入 update from sqlalchemy

提交: `git commit -m "fix: H4+H5 统一发布/回滚为DB先+COS后+失败回滚"`

---

## 完成后验证

全部修复完成后执行:
```bash
cd D:\code\SDK
git log --oneline -10
```

确认每个 Fix 都有独立 commit。
