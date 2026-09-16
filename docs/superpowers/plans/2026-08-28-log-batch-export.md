# SDK 原始日志批量导出实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在日志查看页按多个包名和当前筛选条件创建后台异步任务，并下载包含原始日志的 CSV。

**架构：** PostgreSQL 的 `sdk_log_export_jobs` 表充当持久任务队列，独立 Python Worker 使用 `FOR UPDATE SKIP LOCKED` 领取任务并分批生成 CSV。Admin API 负责候选包名、创建任务、查询状态和鉴权下载，Vue 日志页负责多选、轮询和 Blob 下载。

**技术栈：** FastAPI、SQLAlchemy AsyncSession、PostgreSQL JSONB、Python `csv`、Vue 3、TypeScript、Axios、Vitest、pytest。

---

## 文件结构

### 后端任务与导出

- 创建 `backend/app/models/log_export_job.py`：导出任务 ORM。
- 修改 `backend/app/models/__init__.py`：导出新模型。
- 创建 `backend/app/schemas/log_export_schemas.py`：创建任务请求校验。
- 创建 `backend/app/services/log_export_service.py`：包名检索、任务 CRUD、过滤条件和 CSV 生成。
- 创建 `backend/app/api/admin/log_exports.py`：四个 Admin API。
- 创建 `backend/app/workers/__init__.py`：Worker 包。
- 创建 `backend/app/workers/log_export_worker.py`：数据库轮询与任务执行入口。
- 修改 `backend/app/admin_main.py`：注册导出路由。
- 修改 `backend/app/core/config.py`：增加 `LOG_EXPORT_DIR`。

### 数据库与部署

- 创建 `scripts/migrate_log_export_jobs.sql`：生产库幂等迁移。
- 修改 `scripts/init_db.sql`：新环境创建任务表。
- 创建 `deploy/sdk-log-export-worker.service.example`：独立 Worker systemd 模板。
- 修改 `backend/.env.example`：记录导出目录。

### 前端

- 创建 `frontend/src/api/logExports.ts`：包名、任务、下载 API 和类型。
- 创建 `frontend/src/components/PackageMultiSelect.vue`：包名检索与多选。
- 创建 `frontend/src/components/LogExportPanel.vue`：创建任务、轮询、下载状态。
- 修改 `frontend/src/views/LogViewer.vue`：挂载导出组件并传入当前筛选条件。

### 测试与文档

- 创建 `backend/tests/test_log_export_service.py`：过滤、CSV、时区和 Worker 状态测试。
- 创建 `backend/tests/test_log_export_api.py`：接口鉴权与状态契约测试。
- 创建 `frontend/src/api/logExports.test.ts`：API 参数与 Blob 下载测试。
- 创建 `frontend/src/components/PackageMultiSelect.test.ts`：检索、多选与删除测试。
- 创建 `frontend/src/components/LogExportPanel.test.ts`：任务创建、轮询与下载测试。
- 修改 `frontend/src/views/LogViewer.test.ts`：验证当前筛选条件传给导出组件。
- 修改 `docs/44-COMPLETE-API-INTEGRATION-GUIDE-20260811.md`：补充 Admin 导出接口。
- 创建 `docs/46-LOG-BATCH-EXPORT-DEPLOYMENT-20260828.md`：迁移、目录、Worker 和验收流程。

---

### 任务 1：建立导出任务模型和数据库结构

**文件：**
- 创建：`backend/app/models/log_export_job.py`
- 修改：`backend/app/models/__init__.py`
- 创建：`scripts/migrate_log_export_jobs.sql`
- 修改：`scripts/init_db.sql`
- 测试：`backend/tests/test_log_export_service.py`

- [ ] **步骤 1：编写失败的模型与迁移测试**

在 `backend/tests/test_log_export_service.py` 写入：

```python
from pathlib import Path

from app.models.log_export_job import LogExportJob


def test_log_export_job_model_has_required_columns():
    columns = LogExportJob.__table__.columns
    assert set(columns.keys()) == {
        "id", "status", "package_names", "device_id", "log_level",
        "date_from", "date_to", "file_path", "row_count", "error_message",
        "created_at", "started_at", "finished_at",
    }
    assert columns["package_names"].nullable is False
    assert columns["file_path"].nullable is True


def test_log_export_migration_is_idempotent_and_indexed():
    sql = Path("scripts/migrate_log_export_jobs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS sdk_log_export_jobs" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_log_export_jobs_status_created" in sql
    assert "CHECK (status IN ('pending', 'running', 'success', 'failed'))" in sql
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```powershell
python -m pytest backend/tests/test_log_export_service.py -q
```

预期：FAIL，提示 `app.models.log_export_job` 不存在。

- [ ] **步骤 3：实现任务模型**

创建 `backend/app/models/log_export_job.py`：

```python
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class LogExportJob(Base):
    __tablename__ = "sdk_log_export_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed')",
            name="chk_log_export_jobs_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    status = Column(String(20), nullable=False, default="pending", index=True)
    package_names = Column(JSONB, nullable=False)
    device_id = Column(String(64))
    log_level = Column(String(10))
    date_from = Column(Date)
    date_to = Column(Date)
    file_path = Column(Text)
    row_count = Column(BigInteger, nullable=False, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
```

在 `backend/app/models/__init__.py` 导出 `LogExportJob`。

- [ ] **步骤 4：实现生产迁移与初始化 SQL**

创建 `scripts/migrate_log_export_jobs.sql`，并将同一表定义追加到 `scripts/init_db.sql`：

```sql
CREATE TABLE IF NOT EXISTS sdk_log_export_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    package_names JSONB NOT NULL,
    device_id VARCHAR(64),
    log_level VARCHAR(10),
    date_from DATE,
    date_to DATE,
    file_path TEXT,
    row_count BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT chk_log_export_jobs_status
        CHECK (status IN ('pending', 'running', 'success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_log_export_jobs_status_created
    ON sdk_log_export_jobs (status, created_at);
```

- [ ] **步骤 5：运行测试并提交**

运行：

```powershell
python -m pytest backend/tests/test_log_export_service.py -q
```

预期：PASS。

提交：

```powershell
git add backend/app/models backend/tests/test_log_export_service.py scripts/init_db.sql scripts/migrate_log_export_jobs.sql
git commit -m "feat(export): add persistent log export jobs"
```

---

### 任务 2：实现请求校验、查询条件与 CSV 写入

**文件：**
- 创建：`backend/app/schemas/log_export_schemas.py`
- 创建：`backend/app/services/log_export_service.py`
- 修改：`backend/app/core/config.py`
- 修改：`backend/.env.example`
- 测试：`backend/tests/test_log_export_service.py`

- [ ] **步骤 1：编写失败的请求校验测试**

追加：

```python
import pytest
from pydantic import ValidationError

from app.schemas.log_export_schemas import LogExportCreateRequest


def test_create_request_trims_and_deduplicates_packages():
    body = LogExportCreateRequest(
        package_names=[" com.a ", "com.b", "com.a"],
        device_id=" ",
        date_from="2026-08-28",
        date_to="2026-08-28",
    )
    assert body.package_names == ["com.a", "com.b"]
    assert body.device_id is None


def test_create_request_rejects_empty_packages_and_reversed_dates():
    with pytest.raises(ValidationError):
        LogExportCreateRequest(package_names=[])
    with pytest.raises(ValidationError):
        LogExportCreateRequest(
            package_names=["com.a"], date_from="2026-08-29", date_to="2026-08-28"
        )
```

- [ ] **步骤 2：编写失败的 CSV 单元测试**

追加测试，使用简单对象传入纯函数，不依赖数据库：

```python
import csv
from datetime import datetime, timezone
from io import StringIO

from app.services.log_export_service import csv_row_for_event


def test_csv_row_preserves_extra_and_converts_time_to_utc8():
    event = type("Event", (), {
        "id": 7,
        "package_name": "com.a",
        "device_id": "d1",
        "sdk_version": "1.0.3",
        "payload": {"level": "info", "tag": "t", "message": "m", "extra": "{H1|a=1}"},
        "client_ts": None,
        "server_ts": datetime(2026, 8, 28, 1, 2, 3, tzinfo=timezone.utc),
    })()
    assert csv_row_for_event(event) == [
        "7", "com.a", "d1", "1.0.3", "info", "t", "m", "{H1|a=1}", "", "2026-08-28 09:02:03"
    ]


def test_csv_row_escapes_formula_prefix_without_changing_normal_extra():
    event = type("Event", (), {
        "id": 8, "package_name": "com.a", "device_id": None, "sdk_version": None,
        "payload": {"level": "info", "message": "=cmd()", "extra": "+raw"},
        "client_ts": None, "server_ts": datetime(2026, 8, 28, tzinfo=timezone.utc),
    })()
    row = csv_row_for_event(event)
    assert row[6] == "'=cmd()"
    assert row[7] == "'+raw"
```

- [ ] **步骤 3：运行测试验证失败**

运行：

```powershell
python -m pytest backend/tests/test_log_export_service.py -q
```

预期：FAIL，缺少 schema 和 service。

- [ ] **步骤 4：实现请求模型**

创建 `backend/app/schemas/log_export_schemas.py`：

```python
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LogExportCreateRequest(BaseModel):
    package_names: list[str] = Field(min_length=1, max_length=50)
    device_id: str | None = Field(default=None, max_length=64)
    log_level: Literal["debug", "info", "warn", "error"] | None = None
    date_from: date | None = None
    date_to: date | None = None

    @field_validator("package_names")
    @classmethod
    def normalize_packages(cls, values: list[str]) -> list[str]:
        result = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not result:
            raise ValueError("至少选择一个包名")
        if any(len(value) > 255 for value in result):
            raise ValueError("包名长度不能超过 255")
        return result

    @field_validator("device_id")
    @classmethod
    def normalize_device(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期")
        return self
```

- [ ] **步骤 5：实现过滤器和 CSV 纯函数**

在 `backend/app/services/log_export_service.py` 定义：

```python
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select

from app.models.event import SdkEvent

SHANGHAI = ZoneInfo("Asia/Shanghai")
CSV_HEADER = [
    "id", "package_name", "device_id", "sdk_version", "level", "tag",
    "message", "extra", "client_ts", "server_ts",
]


def _csv_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _local_time(value: datetime | None) -> str:
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def csv_row_for_event(event: SdkEvent) -> list[str]:
    payload = event.payload or {}
    return [
        str(event.id), _csv_text(event.package_name), _csv_text(event.device_id),
        _csv_text(event.sdk_version), _csv_text(payload.get("level")),
        _csv_text(payload.get("tag")), _csv_text(payload.get("message")),
        _csv_text(payload.get("extra")), _local_time(event.client_ts),
        _local_time(event.server_ts),
    ]


def apply_job_filters(stmt: Select, job) -> Select:
    stmt = stmt.where(
        SdkEvent.event_type == "log",
        SdkEvent.package_name.in_(job.package_names),
    )
    if job.device_id:
        stmt = stmt.where(SdkEvent.device_id == job.device_id)
    if job.log_level:
        stmt = stmt.where(SdkEvent.payload["level"].astext == job.log_level)
    if job.date_from:
        start = datetime.combine(job.date_from, time.min, SHANGHAI)
        stmt = stmt.where(SdkEvent.server_ts >= start)
    if job.date_to:
        end = datetime.combine(job.date_to + timedelta(days=1), time.min, SHANGHAI)
        stmt = stmt.where(SdkEvent.server_ts < end)
    return stmt
```

- [ ] **步骤 6：增加导出目录设置**

在 `Settings` 增加：

```python
LOG_EXPORT_DIR: str = "exports"
```

在 `backend/.env.example` 增加 `LOG_EXPORT_DIR=/www/wwwroot/sdk-api/exports`。

- [ ] **步骤 7：运行测试并提交**

运行：

```powershell
python -m pytest backend/tests/test_log_export_service.py backend/tests/test_settings.py -q
```

预期：PASS。

提交：

```powershell
git add backend/app/schemas backend/app/services/log_export_service.py backend/app/core/config.py backend/.env.example backend/tests/test_log_export_service.py
git commit -m "feat(export): validate filters and format raw log csv"
```

---

### 任务 3：实现导出任务 API

**文件：**
- 创建：`backend/app/api/admin/log_exports.py`
- 修改：`backend/app/admin_main.py`
- 修改：`backend/app/services/log_export_service.py`
- 创建：`backend/tests/test_log_export_api.py`

- [ ] **步骤 1：编写失败的 API 测试**

测试通过依赖覆盖注入假 session，并覆盖 service 函数，断言：

```python
def test_log_export_routes_require_admin_token(admin_client):
    assert admin_client.get("/api/admin/log-packages").status_code == 401
    assert admin_client.post("/api/admin/log-exports", json={"package_names": ["com.a"]}).status_code == 401


def test_create_export_returns_pending(auth_admin_client, monkeypatch):
    async def fake_create(_db, body):
        return {"id": "3f21f57d-9a85-4a69-a684-a7ff3ee26bc1", "status": "pending"}
    monkeypatch.setattr("app.api.admin.log_exports.log_export_service.create_job", fake_create)
    response = auth_admin_client.post(
        "/api/admin/log-exports",
        json={"package_names": ["com.a", "com.b"], "log_level": "info"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"
```

同文件继续覆盖：包名检索传递 `keyword/limit`；反向日期返回 422；未知任务返回 404；非成功任务下载返回 409；成功任务用 `FileResponse` 返回 `text/csv` 且不暴露真实路径。

- [ ] **步骤 2：运行 API 测试验证失败**

运行：

```powershell
python -m pytest backend/tests/test_log_export_api.py -q
```

预期：FAIL，路由不存在。

- [ ] **步骤 3：实现 service 的 API 方法**

在 `log_export_service.py` 增加以下签名和行为：

```python
async def search_packages(db: AsyncSession, keyword: str | None, limit: int) -> list[str]:
    stmt = select(SdkEvent.package_name).where(SdkEvent.event_type == "log").distinct()
    if keyword and keyword.strip():
        stmt = stmt.where(SdkEvent.package_name.ilike(f"%{keyword.strip()}%"))
    rows = await db.execute(stmt.order_by(SdkEvent.package_name).limit(limit))
    return list(rows.scalars().all())


async def create_job(db: AsyncSession, body: LogExportCreateRequest) -> dict[str, str]:
    job = LogExportJob(**body.model_dump(), status="pending")
    db.add(job)
    await db.flush()
    return {"id": str(job.id), "status": job.status}


async def get_job(db: AsyncSession, job_id: UUID) -> LogExportJob | None:
    return await db.get(LogExportJob, job_id)


def serialize_job(job: LogExportJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "status": job.status,
        "row_count": int(job.row_count or 0),
        "error_message": job.error_message,
        "created_at": job.created_at.astimezone(SHANGHAI).isoformat(),
        "finished_at": job.finished_at.astimezone(SHANGHAI).isoformat() if job.finished_at else None,
    }
```

`search_packages` 使用：

```python
stmt = (
    select(SdkEvent.package_name)
    .where(SdkEvent.event_type == "log")
    .distinct()
    .order_by(SdkEvent.package_name)
    .limit(limit)
)
if keyword:
    stmt = stmt.where(SdkEvent.package_name.ilike(f"%{keyword.strip()}%"))
```

`create_job` 新建 `LogExportJob`、`flush()` 并返回字符串 UUID；状态查询序列化 UTC+8 ISO 时间且不包含 `file_path`。

- [ ] **步骤 4：实现四个路由并注册**

创建路由：

```python
router = APIRouter(
    tags=["Admin - Log Exports"],
    dependencies=[Depends(require_admin_token)],
)

@router.get("/log-packages")
async def get_log_packages(keyword: str | None = Query(None, max_length=255), limit: int = Query(20, ge=1, le=50), db=Depends(get_db_no_commit)):
    return {"code": 0, "data": {"items": await log_export_service.search_packages(db, keyword, limit)}}

@router.post("/log-exports")
async def create_log_export(body: LogExportCreateRequest, db=Depends(get_db)):
    return {"code": 0, "data": await log_export_service.create_job(db, body)}

@router.get("/log-exports/{job_id}")
async def get_log_export(job_id: UUID, db=Depends(get_db_no_commit)):
    job = await log_export_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return {"code": 0, "data": log_export_service.serialize_job(job)}

@router.get("/log-exports/{job_id}/download")
async def download_log_export(job_id: UUID, db=Depends(get_db_no_commit)):
    job = await log_export_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if job.status != "success":
        raise HTTPException(status_code=409, detail="导出任务尚未完成")
    export_dir = Path(get_settings().LOG_EXPORT_DIR).resolve()
    file_path = Path(job.file_path or "").resolve()
    if file_path.parent != export_dir or not file_path.is_file():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    return FileResponse(file_path, media_type="text/csv; charset=utf-8", filename=f"sdk-logs-{job.id}.csv")
```

下载接口使用 `Path.resolve()` 后验证其父目录为 `Path(settings.LOG_EXPORT_DIR).resolve()`，再返回 `FileResponse`。在 `admin_main.py` 导入并 `include_router`。

- [ ] **步骤 5：运行测试并提交**

运行：

```powershell
python -m pytest backend/tests/test_log_export_api.py backend/tests/test_admin_api.py -q
```

预期：PASS。

提交：

```powershell
git add backend/app/api/admin/log_exports.py backend/app/admin_main.py backend/app/services/log_export_service.py backend/tests/test_log_export_api.py
git commit -m "feat(api): add authenticated log export endpoints"
```

---

### 任务 4：实现独立 Worker

**文件：**
- 创建：`backend/app/workers/__init__.py`
- 创建：`backend/app/workers/log_export_worker.py`
- 修改：`backend/app/services/log_export_service.py`
- 修改：`backend/tests/test_log_export_service.py`

- [ ] **步骤 1：编写失败的任务领取与完成测试**

使用可记录 `execute/commit` 的 fake session，覆盖文件生成函数，验证：

```python
@pytest.mark.asyncio
async def test_claim_pending_job_uses_skip_locked_and_marks_running(fake_job_session):
    job = await claim_next_job(fake_job_session)
    assert job.status == "running"
    assert job.started_at is not None
    assert fake_job_session.committed is True
    assert "SKIP LOCKED" in str(fake_job_session.executed[0]).upper()


@pytest.mark.asyncio
async def test_run_job_marks_success_with_file_and_count(tmp_path, fake_job_session, monkeypatch):
    async def fake_write(*_args, **_kwargs):
        path = tmp_path / "job.csv"
        path.write_text("id,extra\n1,raw\n", encoding="utf-8")
        return path, 1
    monkeypatch.setattr("app.services.log_export_service.write_job_csv", fake_write)
    await run_job(fake_job_session.job, session_factory=fake_job_session.factory)
    assert fake_job_session.job.status == "success"
    assert fake_job_session.job.row_count == 1
```

另测 `write_job_csv` 在写入异常时删除 `.tmp`；`run_job` 将状态设为 `failed` 且错误摘要最长 1000 字符。

- [ ] **步骤 2：运行测试验证失败**

运行：

```powershell
python -m pytest backend/tests/test_log_export_service.py -q
```

预期：FAIL，Worker 函数不存在。

- [ ] **步骤 3：实现任务领取**

在 service 中实现：

```python
async def claim_next_job(db: AsyncSession) -> LogExportJob | None:
    stmt = (
        select(LogExportJob)
        .where(LogExportJob.status == "pending")
        .order_by(LogExportJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()
    return job
```

- [ ] **步骤 4：实现批量 CSV 写入与状态落库**

`write_job_csv` 创建导出目录，以 `job.id.tmp` 写临时文件，写入 UTF-8 BOM 和 `CSV_HEADER`。查询使用 `apply_job_filters(select(SdkEvent), job)`，按 `(server_ts, id)` 升序，每批 `limit(1000)`；下一批增加：

```python
or_(
    SdkEvent.server_ts > last_server_ts,
    and_(SdkEvent.server_ts == last_server_ts, SdkEvent.id > last_id),
)
```

每批 session 生命周期结束后继续下一批，直到不足 1000 条。成功后 `Path.replace(final_path)`，返回路径和行数。

`run_job` 使用新 session 按 ID 重取任务并更新：

```python
job.status = "success"
job.file_path = str(final_path.resolve())
job.row_count = row_count
job.finished_at = datetime.now(timezone.utc)
```

异常分支记录 `logger.exception`，但数据库 `error_message` 只保存 `str(exc)[:1000]`，并设 `failed/finished_at`。

- [ ] **步骤 5：实现 Worker 循环入口**

`backend/app/workers/log_export_worker.py`：

```python
import asyncio
import logging

from app.core.database import async_session_factory
from app.services.log_export_service import claim_next_job, run_job

logger = logging.getLogger(__name__)


async def worker_loop() -> None:
    while True:
        async with async_session_factory() as session:
            job = await claim_next_job(session)
        if job is None:
            await asyncio.sleep(2)
            continue
        await run_job(job.id, async_session_factory)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_loop())
```

- [ ] **步骤 6：运行测试并提交**

运行：

```powershell
python -m pytest backend/tests/test_log_export_service.py -q
```

预期：PASS。

提交：

```powershell
git add backend/app/workers backend/app/services/log_export_service.py backend/tests/test_log_export_service.py
git commit -m "feat(export): generate raw log csv in worker"
```

---

### 任务 5：实现前端包名多选和异步下载

**文件：**
- 创建：`frontend/src/api/logExports.ts`
- 创建：`frontend/src/api/logExports.test.ts`
- 创建：`frontend/src/components/PackageMultiSelect.vue`
- 创建：`frontend/src/components/PackageMultiSelect.test.ts`
- 创建：`frontend/src/components/LogExportPanel.vue`
- 创建：`frontend/src/components/LogExportPanel.test.ts`
- 修改：`frontend/src/views/LogViewer.vue`
- 修改：`frontend/src/views/LogViewer.test.ts`

- [ ] **步骤 1：编写失败的 API 测试**

Mock `@/api/request`，验证：

```typescript
it("sends package search and export filters", async () => {
  await searchLogPackages("tech");
  expect(request.get).toHaveBeenCalledWith("/log-packages", { params: { keyword: "tech", limit: 20 } });
  await createLogExport({ package_names: ["com.a"], log_level: "info" });
  expect(request.post).toHaveBeenCalledWith("/log-exports", {
    package_names: ["com.a"], log_level: "info",
  });
});

it("downloads csv as a blob", async () => {
  await downloadLogExport("job-id");
  expect(request.get).toHaveBeenCalledWith("/log-exports/job-id/download", { responseType: "blob" });
});
```

- [ ] **步骤 2：实现前端 API**

定义：

```typescript
export interface LogExportFilters {
  package_names: string[];
  device_id?: string;
  log_level?: LogLevel;
  date_from?: string;
  date_to?: string;
}

export type LogExportStatus = "pending" | "running" | "success" | "failed";
export interface LogExportJob {
  id: string;
  status: LogExportStatus;
  row_count: number;
  error_message?: string | null;
  created_at: string;
  finished_at?: string | null;
}

export const searchLogPackages = (keyword: string) =>
  request.get("/log-packages", { params: { keyword: keyword || undefined, limit: 20 } });
export const createLogExport = (body: LogExportFilters) => request.post("/log-exports", body);
export const getLogExport = (id: string) => request.get(`/log-exports/${id}`);
export const downloadLogExport = (id: string) =>
  request.get(`/log-exports/${id}/download`, { responseType: "blob" });
```

- [ ] **步骤 3：编写包名多选失败测试**

验证输入触发检索、点击候选发出 `update:modelValue`、同一包名不重复、已选标签可删除。检索防抖使用 300 ms 和 Vitest fake timers。

- [ ] **步骤 4：实现 `PackageMultiSelect.vue`**

组件契约：

```typescript
const props = defineProps<{ modelValue: string[] }>();
const emit = defineEmits<{ (event: "update:modelValue", value: string[]): void }>();
```

内部维护 `keyword/options/loading/open`。`watch(keyword)` 300 ms 后调用 `searchLogPackages`；添加候选时用集合去重；标签删除后发出新数组。所有候选和标签只用 Vue 文本插值显示，不使用 `v-html`。

- [ ] **步骤 5：编写导出面板失败测试**

Mock API 并使用 fake timers，验证：

- 未选包名时按钮禁用；
- 点击后请求包含多个包名和父组件传入的四项筛选；
- `pending` 后每 2 秒查询；
- `success` 停止轮询并显示行数和下载按钮；
- `failed` 停止轮询并显示 `error_message`；
- 卸载组件清理 timer；
- 下载 Blob 后创建临时 `<a>`，其 `download` 属性设为 ``sdk-logs-${currentJob.id}.csv``，随后回收 object URL。

- [ ] **步骤 6：实现 `LogExportPanel.vue`**

Props 固定为：

```typescript
const props = defineProps<{
  deviceId: string;
  logLevel: "" | LogLevel;
  dateFrom: string;
  dateTo: string;
}>();
```

内部维护 `packageNames/currentJob/submitting/error/timer`，创建 body 时将空字符串转成 `undefined`。轮询函数每次请求完成后才调用 `setTimeout(pollJob, 2000)`，避免请求重叠；成功和失败不再安排 timer。

- [ ] **步骤 7：接入日志页并测试筛选透传**

在 `LogViewer.vue` 过滤面板下方加入：

```vue
<LogExportPanel
  :device-id="filters.device_id"
  :log-level="filters.log_level as '' | LogLevel"
  :date-from="filters.date_from"
  :date-to="filters.date_to"
/>
```

`LogViewer.test.ts` stub `LogExportPanel`，设置四个筛选值后断言组件 props 更新。现有单包名列表筛选保持不变。

- [ ] **步骤 8：运行前端测试和构建并提交**

运行：

```powershell
Set-Location frontend
npm test -- --run src/api/logExports.test.ts src/components/PackageMultiSelect.test.ts src/components/LogExportPanel.test.ts src/views/LogViewer.test.ts
npm run build
```

预期：所有测试 PASS，构建成功。

提交：

```powershell
git add frontend/src/api/logExports.ts frontend/src/api/logExports.test.ts frontend/src/components/PackageMultiSelect.vue frontend/src/components/PackageMultiSelect.test.ts frontend/src/components/LogExportPanel.vue frontend/src/components/LogExportPanel.test.ts frontend/src/views/LogViewer.vue frontend/src/views/LogViewer.test.ts
git commit -m "feat(admin): export filtered logs by packages"
```

---

### 任务 6：补全部署配置和接口文档

**文件：**
- 创建：`deploy/sdk-log-export-worker.service.example`
- 修改：`docs/44-COMPLETE-API-INTEGRATION-GUIDE-20260811.md`
- 创建：`docs/46-LOG-BATCH-EXPORT-DEPLOYMENT-20260828.md`

- [ ] **步骤 1：创建 systemd 服务模板**

```ini
[Unit]
Description=SDK Log Export Worker
After=network.target postgresql.service

[Service]
Type=simple
User=www
WorkingDirectory=/www/wwwroot/sdk-api/backend
EnvironmentFile=/www/wwwroot/sdk-api/backend/.env
ExecStart=/www/wwwroot/sdk-api/backend/venv/bin/python -m app.workers.log_export_worker
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

部署时按生产实际用户和路径替换 `User/WorkingDirectory/EnvironmentFile/ExecStart`，模板本身不写真实 Token。

- [ ] **步骤 2：更新接口文档**

记录四个接口的鉴权、请求/响应、状态码和 CSV 表头。明确多包名仅用于导出，现有日志列表查询仍为单包名完全匹配。

- [ ] **步骤 3：编写部署文档**

文档包含可复制执行的顺序：

```powershell
psql "$env:DATABASE_URL" -f scripts/migrate_log_export_jobs.sql
```

Linux 生产步骤包含：创建 `$LOG_EXPORT_DIR`、设置所属用户、安装并启动 Worker、重启 Admin API、查询服务状态、创建一条测试导出任务并下载验收。不得在文档中写入真实 Admin Token 或数据库密码。

- [ ] **步骤 4：提交文档**

```powershell
git add deploy/sdk-log-export-worker.service.example docs/44-COMPLETE-API-INTEGRATION-GUIDE-20260811.md docs/46-LOG-BATCH-EXPORT-DEPLOYMENT-20260828.md
git commit -m "docs: add log export deployment guide"
```

---

### 任务 7：全量验证与范围审查

**文件：**
- 检查：本计划列出的所有文件
- 检查：`docs/superpowers/specs/2026-08-28-log-batch-export-design.md`

- [ ] **步骤 1：运行后端全量测试**

```powershell
python -m pytest backend/tests -q
```

预期：全部 PASS，0 failed。

- [ ] **步骤 2：运行前端全量测试与构建**

```powershell
Set-Location frontend
npm test -- --run
npm run build
```

预期：全部 PASS，生产构建成功。允许保留基线已有的 chunk-size warning，不为本功能重构打包。

- [ ] **步骤 3：运行静态范围检查**

```powershell
Set-Location ..
rg -n "Celery|Redis|RabbitMQ|xlsx|解析后日志" backend frontend
git diff 78109ae --stat
git status --short
```

预期：未引入额外队列或 Excel 依赖；变更仅涉及计划文件。

- [ ] **步骤 4：执行本地集成冒烟**

对本地 PostgreSQL 执行迁移，启动 Admin API 和 Worker；用 Admin Token：

1. 搜索包名并选中两个包名；
2. 创建带日期和等级条件的任务；
3. 验证状态从 `pending/running` 到 `success`；
4. 下载 CSV；
5. 用 PowerShell `Import-Csv` 验证列名、包名集合、等级和 UTC+8 时间；
6. 对非成功任务下载验证 HTTP 409；
7. 对无 Token 请求验证 HTTP 401。

- [ ] **步骤 5：使用 requesting-code-review 审阅实现**

重点检查：任务锁是否避免重复领取、Worker 是否逐批读取、临时文件是否清理、下载路径是否限制在导出目录、Admin Token 是否覆盖全部接口、筛选语义是否与页面一致、`extra` 是否未解析。

- [ ] **步骤 6：提交验证中必要的修复**

仅修复审阅发现且属于本规格的问题，重新执行步骤 1～4，然后提交：

```powershell
git add backend frontend scripts deploy docs
git commit -m "fix(export): address batch export review"
```

若没有修复，不创建空提交。

---

## 自检结果

- 规格覆盖：多包名检索、当前筛选条件、异步任务、原始 CSV、UTC+8、鉴权下载、独立 Worker 和生产迁移均有对应任务。
- 范围控制：未包含任务历史、删除、重试、自动清理、对象存储、Excel、解析日志或新队列基础设施。
- 类型一致：前后端状态统一为 `pending/running/success/failed`；筛选字段统一为 `package_names/device_id/log_level/date_from/date_to`。
- 验证闭环：后端、前端、构建、数据库迁移和真实 CSV 下载均有明确验证步骤。
