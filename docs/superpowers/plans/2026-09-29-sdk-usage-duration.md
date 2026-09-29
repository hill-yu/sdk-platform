# SDK 使用时长上报与后台查询实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增 SDK 使用时长秒数上报接口、独立持久化表，以及按 UTC+8 日期和基础字段筛选的 Admin 汇总与分页查询接口。

**架构：** SDK 写接口将单次 `duration_s` 和设备基础信息同步写入独立的 `sdk_usage_durations` 表，不进入 `sdk_events`。Admin 查询服务复用一套筛选条件完成数据库聚合和分页明细查询，日期统一转换为 UTC 半开区间，响应时间统一序列化为 UTC+8。

**技术栈：** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2 Async、PostgreSQL 15+、pytest、FastAPI TestClient。

---

## 文件结构与职责

**创建：**

- `backend/app/models/usage_duration.py`：独立使用时长 ORM 模型和数据库约束。
- `backend/app/api/sdk/usage_duration.py`：SDK 单条使用时长写接口。
- `backend/app/api/admin/usage_duration.py`：Admin 查询参数校验、鉴权和响应入口。
- `backend/app/services/usage_duration_service.py`：UTC+8 日期范围解析、统一筛选、汇总和分页。
- `scripts/migrate_usage_durations.sql`：现有生产数据库的可重复执行迁移。
- `backend/tests/test_usage_duration_migration.py`：模型、初始化 SQL 和增量迁移测试。
- `backend/tests/test_usage_duration_api.py`：SDK 写接口测试。
- `backend/tests/test_usage_duration_service.py`：查询服务、筛选和序列化测试。
- `backend/tests/test_usage_duration_admin_api.py`：Admin 路由、鉴权和参数转发测试。
- `docs/49-SDK-USAGE-DURATION-API-20260929.md`：独立对接文档。

**修改：**

- `backend/app/models/__init__.py`：导出新 ORM 模型。
- `backend/app/schemas/sdk_schemas.py`：新增严格请求模型。
- `backend/app/sdk_main.py`：注册 SDK 路由。
- `backend/app/admin_main.py`：注册 Admin 路由。
- `scripts/init_db.sql`：新环境初始化新表和索引。
- `docs/02-API-SPEC.md`：在总 API 规范中登记两个新接口。

**明确不修改：**

- `frontend/` 下所有文件；
- 现有日志、点击和配置接口；
- `sdk_events` 表及其分区；
- 现有日志解析、导出和物化视图。

---

### 任务 1：用测试锁定独立表、模型和可重复迁移

**文件：**

- 创建：`backend/tests/test_usage_duration_migration.py`
- 创建：`backend/app/models/usage_duration.py`
- 创建：`scripts/migrate_usage_durations.sql`
- 修改：`backend/app/models/__init__.py`
- 修改：`scripts/init_db.sql`

- [ ] **步骤 1：编写失败的迁移与模型测试**

创建 `backend/tests/test_usage_duration_migration.py`：

```python
import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from app.models.usage_duration import SdkUsageDuration


ROOT = Path(__file__).resolve().parents[2]


def test_usage_duration_model_has_expected_table_and_check_constraint():
    assert SdkUsageDuration.__tablename__ == "sdk_usage_durations"
    columns = SdkUsageDuration.__table__.columns
    assert columns["package_name"].nullable is False
    assert columns["device_id"].nullable is False
    assert columns["app_version"].nullable is False
    assert columns["duration_s"].nullable is False
    checks = {
        str(constraint.sqltext)
        for constraint in SdkUsageDuration.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "duration_s BETWEEN 1 AND 3600" in checks


def _assert_usage_duration_ddl(sql: str):
    assert "CREATE TABLE IF NOT EXISTS sdk_usage_durations" in sql
    assert re.search(r"duration_s\s+INTEGER", sql)
    assert "CHECK (duration_s BETWEEN 1 AND 3600)" in sql
    assert "idx_usage_durations_server_ts" in sql
    assert "idx_usage_durations_package_ts" in sql
    assert "idx_usage_durations_package_device_ts" in sql


def test_init_db_contains_usage_duration_table_and_indexes():
    _assert_usage_duration_ddl((ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8"))


def test_incremental_migration_is_idempotent_by_construction():
    sql = (ROOT / "scripts" / "migrate_usage_durations.sql").read_text(encoding="utf-8")
    _assert_usage_duration_ddl(sql)
    assert sql.count("CREATE TABLE IF NOT EXISTS sdk_usage_durations") == 1
    assert sql.count("CREATE INDEX IF NOT EXISTS") == 3
```

- [ ] **步骤 2：运行测试并确认因模型或 SQL 缺失而失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_migration.py -q
```

预期：FAIL，首先出现 `ModuleNotFoundError: app.models.usage_duration`。

- [ ] **步骤 3：创建最小 ORM 模型并导出**

创建 `backend/app/models/usage_duration.py`：

```python
"""SDK 使用时长 ORM 模型。"""

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func

from app.core.database import Base


class SdkUsageDuration(Base):
    __tablename__ = "sdk_usage_durations"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    package_name = Column(String(255), nullable=False)
    device_id = Column(String(64), nullable=False)
    device_model = Column(String(100), nullable=False)
    os = Column(String(50), nullable=False)
    app_version = Column(String(50), nullable=False)
    sdk_version = Column(String(20), nullable=False)
    duration_s = Column(Integer, nullable=False)
    server_ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ip = Column(INET)
    user_agent = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "duration_s BETWEEN 1 AND 3600",
            name="chk_usage_durations_duration_s",
        ),
        Index("idx_usage_durations_server_ts", server_ts.desc()),
        Index("idx_usage_durations_package_ts", package_name, server_ts.desc()),
        Index(
            "idx_usage_durations_package_device_ts",
            package_name,
            device_id,
            server_ts.desc(),
        ),
    )
```

在 `backend/app/models/__init__.py` 增加：

```python
from app.models.usage_duration import SdkUsageDuration
```

并把 `"SdkUsageDuration"` 加入 `__all__`。

- [ ] **步骤 4：在初始化 SQL 和增量迁移中加入同一份 DDL**

向 `scripts/init_db.sql` 的基础业务表区域加入：

```sql
CREATE TABLE IF NOT EXISTS sdk_usage_durations (
    id              BIGSERIAL PRIMARY KEY,
    package_name    VARCHAR(255) NOT NULL,
    device_id       VARCHAR(64)  NOT NULL,
    device_model    VARCHAR(100) NOT NULL,
    os              VARCHAR(50)  NOT NULL,
    app_version     VARCHAR(50)  NOT NULL,
    sdk_version     VARCHAR(20)  NOT NULL,
    duration_s      INTEGER      NOT NULL,
    server_ts       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip              INET,
    user_agent      TEXT,
    CONSTRAINT chk_usage_durations_duration_s
        CHECK (duration_s BETWEEN 1 AND 3600)
);

CREATE INDEX IF NOT EXISTS idx_usage_durations_server_ts
    ON sdk_usage_durations (server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_durations_package_ts
    ON sdk_usage_durations (package_name, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_durations_package_device_ts
    ON sdk_usage_durations (package_name, device_id, server_ts DESC);
```

使用完全相同的 DDL 创建 `scripts/migrate_usage_durations.sql`，文件开头加事务：

```sql
BEGIN;
CREATE TABLE IF NOT EXISTS sdk_usage_durations (
    id              BIGSERIAL PRIMARY KEY,
    package_name    VARCHAR(255) NOT NULL,
    device_id       VARCHAR(64)  NOT NULL,
    device_model    VARCHAR(100) NOT NULL,
    os              VARCHAR(50)  NOT NULL,
    app_version     VARCHAR(50)  NOT NULL,
    sdk_version     VARCHAR(20)  NOT NULL,
    duration_s      INTEGER      NOT NULL,
    server_ts       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip              INET,
    user_agent      TEXT,
    CONSTRAINT chk_usage_durations_duration_s
        CHECK (duration_s BETWEEN 1 AND 3600)
);

CREATE INDEX IF NOT EXISTS idx_usage_durations_server_ts
    ON sdk_usage_durations (server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_durations_package_ts
    ON sdk_usage_durations (package_name, server_ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_durations_package_device_ts
    ON sdk_usage_durations (package_name, device_id, server_ts DESC);
COMMIT;
```

- [ ] **步骤 5：运行迁移测试并确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_migration.py -q
```

预期：`3 passed`。

- [ ] **步骤 6：提交独立存储层**

```powershell
git add backend/app/models/usage_duration.py backend/app/models/__init__.py scripts/init_db.sql scripts/migrate_usage_durations.sql backend/tests/test_usage_duration_migration.py
git commit -m "feat: add SDK usage duration storage"
```

---

### 任务 2：用 TDD 实现 SDK 使用时长上报接口

**文件：**

- 创建：`backend/tests/test_usage_duration_api.py`
- 创建：`backend/app/api/sdk/usage_duration.py`
- 修改：`backend/app/schemas/sdk_schemas.py`
- 修改：`backend/app/sdk_main.py`

- [ ] **步骤 1：编写请求验证和成功写入测试**

创建 `backend/tests/test_usage_duration_api.py`：

```python
import pytest

from app.core.database import get_db
from app.core.rate_limit import write_limiter
from tests.conftest import StubWriteSession, override_write_db


VALID_BODY = {
    "package_name": " COM.Example.App ",
    "device_id": "device-001",
    "device_model": "iPhone13,2",
    "os": "17.5.1",
    "ver": "1.0",
    "sdk_version": "1.0.3",
    "duration_s": 60,
}


@pytest.fixture(autouse=True)
def reset_limiter():
    write_limiter._store.clear()
    yield
    write_limiter._store.clear()


def test_usage_duration_writes_normalized_record_and_returns_acceptance(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post(
        "/api/v1/usage-duration",
        json=VALID_BODY,
        headers={"User-Agent": "ExampleSDK/1.0.3"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "ok",
        "data": {"accepted": 1, "rejected": 0},
    }
    assert len(session.records) == 1
    record = session.records[0]
    assert record.package_name == "com.example.app"
    assert record.device_id == "device-001"
    assert record.device_model == "iPhone13,2"
    assert record.os == "17.5.1"
    assert record.app_version == "1.0"
    assert record.sdk_version == "1.0.3"
    assert record.duration_s == 60
    assert str(record.ip) == "testclient"
    assert record.user_agent == "ExampleSDK/1.0.3"
    assert record.server_ts.tzinfo is not None


@pytest.mark.parametrize("duration_s", [1, 3600])
def test_usage_duration_accepts_inclusive_boundaries(client, duration_s):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post(
        "/api/v1/usage-duration",
        json={**VALID_BODY, "duration_s": duration_s},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("duration_s", [0, -1, 3601, 1.5, "60"])
def test_usage_duration_rejects_invalid_or_non_integer_duration(client, duration_s):
    response = client.post(
        "/api/v1/usage-duration",
        json={**VALID_BODY, "duration_s": duration_s},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["package_name", "device_id", "device_model", "os", "ver", "sdk_version", "duration_s"],
)
def test_usage_duration_requires_all_contract_fields(client, field):
    body = dict(VALID_BODY)
    del body[field]
    assert client.post("/api/v1/usage-duration", json=body).status_code == 422


def test_usage_duration_uses_write_limiter(client):
    session = StubWriteSession()
    client.app.dependency_overrides[get_db] = override_write_db(session)
    responses = [
        client.post("/api/v1/usage-duration", json=VALID_BODY)
        for _ in range(write_limiter.max + 1)
    ]
    assert responses[-1].status_code == 429


def test_usage_duration_returns_safe_500_on_database_error(client):
    session = StubWriteSession(fail_predicate=lambda _record: True)
    client.app.dependency_overrides[get_db] = override_write_db(session)
    response = client.post("/api/v1/usage-duration", json=VALID_BODY)
    assert response.status_code == 500
    assert response.json()["detail"] == "数据库写入失败"
```

- [ ] **步骤 2：运行接口测试并确认路由不存在**

运行：

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_api.py -q
```

预期：FAIL，成功场景返回 HTTP 404。

- [ ] **步骤 3：增加严格请求模型**

在 `backend/app/schemas/sdk_schemas.py` 增加：

```python
class UsageDurationReportRequest(BaseModel):
    package_name: str = Field(..., min_length=1, max_length=255)
    device_id: str = Field(..., min_length=1, max_length=64)
    device_model: str = Field(..., min_length=1, max_length=100)
    os: str = Field(..., min_length=1, max_length=50)
    ver: str = Field(..., min_length=1, max_length=50)
    sdk_version: str = Field(..., min_length=1, max_length=20)
    duration_s: int = Field(..., ge=1, le=3600, strict=True)

    @field_validator("package_name")
    @classmethod
    def validate_package_name(cls, value: str) -> str:
        return normalize_package_name(value)
```

- [ ] **步骤 4：实现同步单条写入路由**

创建 `backend/app/api/sdk/usage_duration.py`：

```python
"""SDK 使用时长上报接口。"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import write_limiter
from app.models.usage_duration import SdkUsageDuration
from app.schemas.sdk_schemas import UsageDurationReportRequest


logger = logging.getLogger(__name__)
router = APIRouter(tags=["SDK - Usage Duration"])


@router.post("/api/v1/usage-duration")
async def report_usage_duration(
    request: Request,
    body: UsageDurationReportRequest,
    db: AsyncSession = Depends(get_db),
    _rate=Depends(write_limiter),
):
    record = SdkUsageDuration(
        package_name=body.package_name,
        device_id=body.device_id,
        device_model=body.device_model,
        os=body.os,
        app_version=body.ver,
        sdk_version=body.sdk_version,
        duration_s=body.duration_s,
        server_ts=datetime.now(timezone.utc),
        ip=str(request.client.host) if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    try:
        db.add(record)
        await db.flush()
    except Exception:
        logger.exception("使用时长写入失败，package_name=%s", body.package_name)
        await db.rollback()
        raise HTTPException(status_code=500, detail="数据库写入失败")
    return {
        "code": 0,
        "message": "ok",
        "data": {"accepted": 1, "rejected": 0},
    }
```

在 `backend/app/sdk_main.py` 导入并注册：

```python
from app.api.sdk import version, config, click, log, usage_duration

app.include_router(usage_duration.router)
```

- [ ] **步骤 5：运行 SDK 接口测试并修正测试桩的 flush 行为**

运行：

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_api.py -q
```

预期：全部通过。失败数据库测试必须验证响应不泄露模拟异常文本。

- [ ] **步骤 6：提交 SDK 写接口**

```powershell
git add backend/app/schemas/sdk_schemas.py backend/app/api/sdk/usage_duration.py backend/app/sdk_main.py backend/tests/test_usage_duration_api.py
git commit -m "feat: add SDK usage duration reporting"
```

---

### 任务 3：用 TDD 实现 UTC+8 筛选、汇总与分页服务

**文件：**

- 创建：`backend/tests/test_usage_duration_service.py`
- 创建：`backend/app/services/usage_duration_service.py`

- [ ] **步骤 1：编写日期范围和筛选构造测试**

创建 `backend/tests/test_usage_duration_service.py`，先覆盖纯函数：

```python
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import usage_duration_service


def test_resolve_range_defaults_to_utc_plus_8_today(monkeypatch):
    monkeypatch.setattr(usage_duration_service, "business_today", lambda: date(2026, 9, 29))
    start, end = usage_duration_service.resolve_usage_date_range(None, None)
    assert start == datetime(2026, 9, 28, 16, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 29, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("date_from", "date_to", "message"),
    [
        (date(2026, 9, 1), None, "必须成对提供"),
        (None, date(2026, 9, 1), "必须成对提供"),
        (date(2026, 9, 2), date(2026, 9, 1), "结束日期不能早于开始日期"),
        (date(2026, 8, 1), date(2026, 9, 1), "最多查询 31 天"),
    ],
)
def test_resolve_range_rejects_invalid_ranges(date_from, date_to, message):
    with pytest.raises(ValueError, match=message):
        usage_duration_service.resolve_usage_date_range(date_from, date_to)


def test_build_filters_uses_all_exact_match_fields():
    filters = usage_duration_service.build_usage_filters(
        package_name="com.example.app",
        device_id="device-1",
        sdk_version="1.0.3",
        ver="1.0",
        range_start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        range_end=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    sql = " AND ".join(
        str(item.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for item in filters
    )
    assert "package_name = 'com.example.app'" in sql
    assert "device_id = 'device-1'" in sql
    assert "sdk_version = '1.0.3'" in sql
    assert "app_version = '1.0'" in sql
    assert "server_ts >=" in sql
    assert "server_ts <" in sql
```

- [ ] **步骤 2：运行纯函数测试并确认服务模块缺失**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_service.py -q
```

预期：FAIL，出现 `ImportError`。

- [ ] **步骤 3：实现日期范围和统一筛选纯函数**

创建 `backend/app/services/usage_duration_service.py` 的基础部分：

```python
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import business_day_utc_range, business_today, serialize_business_time
from app.models.usage_duration import SdkUsageDuration


MAX_QUERY_DAYS = 31


def resolve_usage_date_range(date_from: date | None, date_to: date | None):
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from 和 date_to 必须成对提供")
    if date_from is None:
        date_from = date_to = business_today()
    assert date_to is not None
    if date_to < date_from:
        raise ValueError("结束日期不能早于开始日期")
    if (date_to - date_from).days + 1 > MAX_QUERY_DAYS:
        raise ValueError("单次最多查询 31 天")
    start, _ = business_day_utc_range(date_from)
    _, end = business_day_utc_range(date_to)
    return start, end


def build_usage_filters(
    *,
    package_name: str | None,
    device_id: str | None,
    sdk_version: str | None,
    ver: str | None,
    range_start,
    range_end,
):
    filters = [
        SdkUsageDuration.server_ts >= range_start,
        SdkUsageDuration.server_ts < range_end,
    ]
    if package_name:
        filters.append(SdkUsageDuration.package_name == package_name)
    if device_id:
        filters.append(SdkUsageDuration.device_id == device_id)
    if sdk_version:
        filters.append(SdkUsageDuration.sdk_version == sdk_version)
    if ver:
        filters.append(SdkUsageDuration.app_version == ver)
    return filters
```

- [ ] **步骤 4：增加汇总、分页和 UTC+8 序列化测试**

在同一测试文件增加固定两次查询结果桩。查询顺序固定为汇总、明细；`total` 直接复用同一汇总查询的 `report_count`，避免重复计数查询：

```python
class Result:
    def __init__(self, *, mapping=None, rows=None):
        self.mapping = mapping
        self.rows = rows or []

    def mappings(self):
        return self

    def one(self):
        return self.mapping

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, event):
        self.results = [
            Result(mapping={"total_duration_s": 120, "report_count": 2, "device_count": 1}),
            Result(rows=[event]),
        ]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_query_returns_summary_pagination_and_utc_plus_8_items():
    event = SimpleNamespace(
        id=7,
        package_name="com.example.app",
        device_id="device-1",
        device_model="iPhone13,2",
        os="17.5.1",
        app_version="1.0",
        sdk_version="1.0.3",
        duration_s=60,
        server_ts=datetime(2026, 9, 29, 8, 30, tzinfo=timezone.utc),
        ip="203.0.113.10",
        user_agent="ExampleSDK/1.0.3",
    )
    db = Session(event)
    data = await usage_duration_service.get_usage_durations(
        db,
        package_name="com.example.app",
        device_id=None,
        sdk_version=None,
        ver=None,
        date_from=date(2026, 9, 29),
        date_to=date(2026, 9, 29),
        page=1,
        page_size=20,
    )
    assert data["summary"] == {
        "total_duration_s": 120,
        "report_count": 2,
        "device_count": 1,
    }
    assert data["total"] == 2
    assert data["items"][0]["ver"] == "1.0"
    assert data["items"][0]["server_time"] == "2026-09-29T16:30:00+08:00"
    assert len(db.statements) == 2
```

- [ ] **步骤 5：实现聚合、总数和稳定分页**

在 `usage_duration_service.py` 增加：

```python
async def get_usage_durations(
    db: AsyncSession,
    *,
    package_name: str | None,
    device_id: str | None,
    sdk_version: str | None,
    ver: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    range_start, range_end = resolve_usage_date_range(date_from, date_to)
    filters = build_usage_filters(
        package_name=package_name,
        device_id=device_id,
        sdk_version=sdk_version,
        ver=ver,
        range_start=range_start,
        range_end=range_end,
    )
    summary_stmt = select(
        func.coalesce(func.sum(SdkUsageDuration.duration_s), 0).label("total_duration_s"),
        func.count(SdkUsageDuration.id).label("report_count"),
        func.count(distinct(SdkUsageDuration.device_id)).label("device_count"),
    ).where(*filters)
    summary_row = (await db.execute(summary_stmt)).mappings().one()

    list_stmt = (
        select(SdkUsageDuration)
        .where(*filters)
        .order_by(SdkUsageDuration.server_ts.desc(), SdkUsageDuration.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await db.execute(list_stmt)).scalars().all()
    items = [
        {
            "id": row.id,
            "package_name": row.package_name,
            "device_id": row.device_id,
            "device_model": row.device_model,
            "os": row.os,
            "ver": row.app_version,
            "sdk_version": row.sdk_version,
            "duration_s": row.duration_s,
            "server_time": serialize_business_time(row.server_ts),
            "ip": str(row.ip) if row.ip is not None else None,
            "user_agent": row.user_agent,
        }
        for row in rows
    ]
    return {
        "summary": {
            "total_duration_s": int(summary_row["total_duration_s"] or 0),
            "report_count": int(summary_row["report_count"] or 0),
            "device_count": int(summary_row["device_count"] or 0),
        },
        "total": int(summary_row["report_count"] or 0),
        "page": page,
        "page_size": page_size,
        "items": items,
    }
```

- [ ] **步骤 6：运行服务测试并确认通过**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_service.py -q
```

预期：全部通过。

- [ ] **步骤 7：提交查询服务**

```powershell
git add backend/app/services/usage_duration_service.py backend/tests/test_usage_duration_service.py
git commit -m "feat: add usage duration query service"
```

---

### 任务 4：用 TDD 暴露带鉴权的 Admin 查询接口

**文件：**

- 创建：`backend/tests/test_usage_duration_admin_api.py`
- 创建：`backend/app/api/admin/usage_duration.py`
- 修改：`backend/app/admin_main.py`

- [ ] **步骤 1：编写路由鉴权、参数转发和日期错误测试**

创建 `backend/tests/test_usage_duration_admin_api.py`：

```python
from fastapi.testclient import TestClient

from app.core.database import get_db_no_commit


TOKEN = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"


class Db:
    pass


async def override_db():
    yield Db()


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_usage_duration_admin_route_requires_token():
    from app.admin_main import app

    with TestClient(app) as client:
        response = client.get("/api/admin/usage-durations")
    assert response.status_code == 401


def test_usage_duration_admin_route_normalizes_package_and_forwards_filters(monkeypatch):
    from app.admin_main import app
    from app.api.admin import usage_duration

    calls = []

    async def fake_query(_db, **kwargs):
        calls.append(kwargs)
        return {
            "summary": {"total_duration_s": 0, "report_count": 0, "device_count": 0},
            "total": 0,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "items": [],
        }

    monkeypatch.setattr(usage_duration.usage_duration_service, "get_usage_durations", fake_query)
    app.dependency_overrides[get_db_no_commit] = override_db
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/usage-durations",
                params={
                    "package_name": " COM.Example.App ",
                    "device_id": "device-1",
                    "sdk_version": "1.0.3",
                    "ver": "1.0",
                    "date_from": "2026-09-01",
                    "date_to": "2026-09-29",
                    "page": 2,
                    "page_size": 50,
                },
                headers=headers(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls[0]["package_name"] == "com.example.app"
    assert calls[0]["device_id"] == "device-1"
    assert calls[0]["sdk_version"] == "1.0.3"
    assert calls[0]["ver"] == "1.0"
    assert calls[0]["page"] == 2
    assert calls[0]["page_size"] == 50


def test_usage_duration_admin_rejects_unpaired_and_overlong_dates():
    from app.admin_main import app

    with TestClient(app) as client:
        unpaired = client.get(
            "/api/admin/usage-durations?date_from=2026-09-01",
            headers=headers(),
        )
        overlong = client.get(
            "/api/admin/usage-durations?date_from=2026-08-01&date_to=2026-09-01",
            headers=headers(),
        )
    assert unpaired.status_code == 422
    assert overlong.status_code == 422
```

- [ ] **步骤 2：运行 Admin 测试并确认路由不存在**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_admin_api.py -q
```

预期：FAIL，路由返回 HTTP 404。

- [ ] **步骤 3：实现 Admin 路由并注册**

创建 `backend/app/api/admin/usage_duration.py`：

```python
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin_token
from app.core.database import get_db_no_commit
from app.services import usage_duration_service
from app.services.config_crypto import normalize_package_name


router = APIRouter(
    tags=["Admin - Usage Duration"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/usage-durations")
async def get_usage_durations(
    package_name: str | None = Query(None, max_length=255),
    device_id: str | None = Query(None, max_length=64),
    sdk_version: str | None = Query(None, max_length=20),
    ver: str | None = Query(None, max_length=50),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_no_commit),
):
    normalized_package = normalize_package_name(package_name) if package_name else None
    try:
        data = await usage_duration_service.get_usage_durations(
            db,
            package_name=normalized_package,
            device_id=device_id,
            sdk_version=sdk_version,
            ver=ver,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}
```

在 `backend/app/admin_main.py` 导入并注册：

```python
from app.api.admin import config_mgr, dashboard, log_analysis, log_exports, usage_duration, version_mgr

app.include_router(usage_duration.router, prefix="/api/admin")
```

- [ ] **步骤 4：运行 Admin 和服务测试并确认通过**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_admin_api.py backend/tests/test_usage_duration_service.py -q
```

预期：全部通过。

- [ ] **步骤 5：提交 Admin 查询接口**

```powershell
git add backend/app/api/admin/usage_duration.py backend/app/admin_main.py backend/tests/test_usage_duration_admin_api.py
git commit -m "feat: expose usage duration admin query"
```

---

### 任务 5：补齐接口文档并执行全量回归

**文件：**

- 创建：`docs/49-SDK-USAGE-DURATION-API-20260929.md`
- 修改：`docs/02-API-SPEC.md`

- [ ] **步骤 1：编写独立对接文档**

创建 `docs/49-SDK-USAGE-DURATION-API-20260929.md`，必须完整包含：

````markdown
# SDK 使用时长接口对接文档

## SDK 上报

`POST /api/v1/usage-duration`

请求字段：`package_name`、`device_id`、`device_model`、`os`、`ver`、`sdk_version`、`duration_s`。所有字段必填，`duration_s` 为 1～3600 的整数秒数。不传 `timestamp` 和 `report_id`。

成功响应：

```json
{"code":0,"message":"ok","data":{"accepted":1,"rejected":0}}
```

## Admin 查询

`GET /api/admin/usage-durations`

要求 `Authorization: Bearer <ADMIN_TOKEN>`。支持 `package_name`、`device_id`、`sdk_version`、`ver`、`date_from`、`date_to`、`page`、`page_size`。未传日期默认 UTC+8 当天，日期必须成对提供且最多 31 天。
````

文档还需加入完整请求、PowerShell/curl 示例、汇总与明细响应示例、HTTP 422/429/500 说明，以及“不提供幂等去重”的明确提示。

- [ ] **步骤 2：在总 API 规范中登记接口**

修改 `docs/02-API-SPEC.md`，增加两个接口的用途、鉴权、请求字段、筛选条件和对独立文档的链接。不得顺手修订其他历史接口。

- [ ] **步骤 3：运行所有新增测试**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests/test_usage_duration_migration.py backend/tests/test_usage_duration_api.py backend/tests/test_usage_duration_service.py backend/tests/test_usage_duration_admin_api.py -q
```

预期：全部通过。

- [ ] **步骤 4：运行后端全量回归**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -m pytest backend/tests -q
```

预期：原有 289 项加本次新增测试全部通过，0 failed。

- [ ] **步骤 5：运行前端全量回归**

```powershell
npm test -- --run
```

工作目录：`frontend`。

预期：23 个测试文件、135 项测试全部通过，0 failed。

- [ ] **步骤 6：执行静态差异检查**

```powershell
git diff --check
git status --short
git diff master...HEAD --stat
```

预期：`git diff --check` 无输出；变更仅覆盖本计划列出的后端、SQL、测试和文档文件；`frontend/` 无变更。

- [ ] **步骤 7：提交文档**

```powershell
git add docs/49-SDK-USAGE-DURATION-API-20260929.md docs/02-API-SPEC.md
git commit -m "docs: document SDK usage duration APIs"
```

---

## 最终验收检查

- [ ] `POST /api/v1/usage-duration` 无 SDK Token 也可调用，但写限流生效。
- [ ] 所有基础字段必填且长度符合设计，`duration_s` 只接受 `1～3600` 的整数。
- [ ] 数据只写入 `sdk_usage_durations`，不写入 `sdk_events`。
- [ ] 服务器接收时间、IP 和 User-Agent 被保存。
- [ ] `GET /api/admin/usage-durations` 要求 Admin Token。
- [ ] 默认日期为 UTC+8 当天，成对日期最多 31 天。
- [ ] 汇总、总数与明细使用完全相同的筛选条件。
- [ ] 明细按 `server_ts DESC, id DESC` 稳定排序并输出 UTC+8 时间。
- [ ] 初始化 SQL 和生产迁移脚本都包含独立表、检查约束和三个索引。
- [ ] 增量迁移脚本具备重复执行能力。
- [ ] 前后端全量测试通过。
- [ ] 没有前端、日志、点击、配置或导出功能的额外改动。
- [ ] 未执行推送、合并或生产部署；这些操作等待用户另行授权。
