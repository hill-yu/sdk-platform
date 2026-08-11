# 配置下载 POST 化与按包版本序列实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将三类加密配置下载接口改为 POST，并让配置按包名在发布成功时使用 `1.0.0` 起步的三段十进制序列，安全迁移现有生产版本。

**架构：** 新建一个无数据库依赖的版本工具模块，负责严格解析、比较、递增和历史映射；配置服务在取得包级事务锁后读取该包全部正式版本并分配下一个版本，回滚则重新激活原历史记录。迁移脚本先预检并生成稳定映射，再以旧 AAD 解密、用新 AAD 重加密，最后原子更新数据库。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy Async、PostgreSQL、cryptography AES-GCM、pytest、Vue 3/Vitest。

---

## 文件结构

- 创建 `backend/app/services/config_version.py`：三段十进制版本的解析、递增、最大值和历史映射。
- 创建 `backend/tests/test_config_version.py`：版本规则的纯单元测试。
- 修改 `backend/app/services/config_service.py`：按包分配版本、回滚复用历史记录、保持 Meta/下载信封一致。
- 修改 `backend/tests/test_config_service.py`：发布、跨包、回滚和历史最大版本测试。
- 修改 `backend/app/api/sdk/config.py`：配置下载路由由 GET 改为 POST。
- 修改 `backend/tests/test_sdk_api.py`：POST 成功、GET 405、鉴权和 Meta URL 一致性。
- 创建 `scripts/migrate_config_versions.py`：生产历史版本预检、重加密、事务迁移和显式确认入口。
- 创建 `backend/tests/test_config_version_migration.py`：迁移映射、AAD 重加密、幂等和失败测试。
- 修改 `scripts/init_db.sql`：记录正式版本约束和按包唯一性所需数据库定义。
- 修改 `docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md`：更新 SDK 下载方法和版本规则。
- 创建 `docs/43-POST-CONFIG-DOWNLOAD-SEMVER-IMPLEMENTATION-20260811.md`：实施、迁移、验证及回滚记录。

### 任务 1：实现三段十进制版本规则

**文件：**
- 创建：`backend/app/services/config_version.py`
- 创建：`backend/tests/test_config_version.py`

- [ ] **步骤 1：编写失败的版本单元测试**

```python
import pytest

from app.services.config_version import next_version, parse_version


@pytest.mark.parametrize(
    ("current", "expected"),
    [(None, "1.0.0"), ("1.0.8", "1.0.9"), ("1.0.9", "1.1.0"), ("1.9.9", "2.0.0")],
)
def test_next_version_uses_decimal_triplet_sequence(current, expected):
    assert next_version(current) == expected


@pytest.mark.parametrize("value", ["1.0", "v1.0.0", "1.0.10", "draft_1", "20260811_v120000"])
def test_parse_version_rejects_non_sequence_values(value):
    with pytest.raises(ValueError):
        parse_version(value)
```

- [ ] **步骤 2：运行测试并确认因模块不存在而失败**

运行：`python -m pytest backend/tests/test_config_version.py -q`

预期：FAIL，`ModuleNotFoundError: app.services.config_version`。

- [ ] **步骤 3：实现最小版本工具**

```python
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.([0-9])\.([0-9])$")


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"非法正式版本: {value}")
    return tuple(map(int, match.groups()))


def next_version(current: str | None) -> str:
    if current is None:
        return "1.0.0"
    major, minor, patch = parse_version(current)
    patch += 1
    if patch == 10:
        patch = 0
        minor += 1
    if minor == 10:
        minor = 0
        major += 1
    return f"{major}.{minor}.{patch}"
```

同时实现 `max_version(values)`，按解析后的整数元组比较；空集合返回 `None`。

- [ ] **步骤 4：运行版本测试确认通过**

运行：`python -m pytest backend/tests/test_config_version.py -q`

预期：全部通过。

- [ ] **步骤 5：提交版本工具**

```bash
git add backend/app/services/config_version.py backend/tests/test_config_version.py
git commit -m "feat(config): add package version sequence"
```

### 任务 2：发布递增与回滚复用历史版本

**文件：**
- 修改：`backend/app/services/config_service.py`
- 修改：`backend/tests/test_config_service.py`

- [ ] **步骤 1：编写发布与回滚失败测试**

增加真实服务行为测试，至少断言：

```python
assert await allocate_next_version(db, "com.a.app") == "1.1.0"  # 历史含 1.0.9
assert await allocate_next_version(db, "com.b.app") == "1.0.0"  # 另一包无历史

before_count = len(db.configs)
result = await rollback_config(db, archived.id, "admin")
assert len(db.configs) == before_count
assert result["version"] == archived.version
assert archived.status == "published"
assert previous_published.status == "archived"
```

另加回滚到 `1.0.3`、历史最大为 `1.1.1` 后，新发布得到 `1.1.2` 的测试。

- [ ] **步骤 2：运行定点测试确认失败原因正确**

运行：`python -m pytest backend/tests/test_config_service.py -q`

预期：FAIL；现实现生成时间戳版本且回滚新增记录。

- [ ] **步骤 3：在包级锁内分配下一版本**

在 `config_service.py` 增加查询：

```python
async def _next_package_version(db: AsyncSession, package_name: str) -> str:
    versions = (
        await db.execute(
            select(SdkConfig.version).where(
                SdkConfig.package_name == package_name,
                SdkConfig.status.in_(("published", "archived")),
            )
        )
    ).scalars().all()
    return next_version(max_version(versions))
```

`_publish_from_record` 必须先获取现有包级 advisory transaction lock，再调用 `_next_package_version`；只有数据库事务成功才实际占用该版本。

- [ ] **步骤 4：改为原记录回滚**

`rollback_config` 获取相同包级锁后：归档当前 published、把 source 改为 published，保留 `source.version` 和 `source.encrypted_config`，更新发布人、发布时间及下发字段。不要创建 `SdkConfig`，不要调用正式版本分配函数。

COS 模式回滚使用 source 版本重新生成三类信封并上传到该版本对象路径；local 模式直接恢复动态下发。

- [ ] **步骤 5：运行服务定点测试**

运行：`python -m pytest backend/tests/test_config_service.py backend/tests/test_encrypted_config_service.py -q`

预期：全部通过。

- [ ] **步骤 6：提交发布与回滚变更**

```bash
git add backend/app/services/config_service.py backend/tests/test_config_service.py backend/tests/test_encrypted_config_service.py
git commit -m "feat(config): version publishes per package"
```

### 任务 3：配置下载接口改为 POST

**文件：**
- 修改：`backend/app/api/sdk/config.py`
- 修改：`backend/tests/test_sdk_api.py`

- [ ] **步骤 1：先修改测试表达新接口契约**

```python
response = client.post(
    "/api/v1/config/packages/com.example.app/versions/1.0.0/new-touch",
    headers=_headers(),
)
assert response.status_code == 200
assert client.get(
    "/api/v1/config/packages/com.example.app/versions/1.0.0/new-touch",
    headers=_headers(),
).status_code == 405
```

同时验证 POST 缺 Token 返回 401，Meta 三个 URL 都包含 published 的同一版本。

- [ ] **步骤 2：运行 SDK API 测试确认失败**

运行：`python -m pytest backend/tests/test_sdk_api.py -q`

预期：POST 下载返回 405，GET 仍返回 200。

- [ ] **步骤 3：替换 FastAPI 路由方法**

将 `@router.get(...)` 改为 `@router.post(...)`，保留路径参数、Token 依赖和响应逻辑，不增加请求体。

- [ ] **步骤 4：运行 SDK API 测试确认通过**

运行：`python -m pytest backend/tests/test_sdk_api.py backend/tests/test_rate_limit.py -q`

预期：全部通过。

- [ ] **步骤 5：提交接口变更**

```bash
git add backend/app/api/sdk/config.py backend/tests/test_sdk_api.py
git commit -m "feat(api): require POST for config downloads"
```

### 任务 4：实现历史版本原子迁移

**文件：**
- 创建：`scripts/migrate_config_versions.py`
- 创建：`backend/tests/test_config_version_migration.py`
- 修改：`scripts/init_db.sql`

- [ ] **步骤 1：编写迁移映射和重加密失败测试**

```python
def test_build_mapping_is_stable_per_package():
    rows = [
        row(2, "com.a", published_at=SECOND),
        row(1, "com.a", published_at=FIRST),
        row(3, "com.b", published_at=FIRST),
    ]
    assert build_version_mapping(rows) == {1: "1.0.0", 2: "1.0.1", 3: "1.0.0"}


def test_reencrypt_record_binds_ciphertext_to_new_version():
    migrated = reencrypt_record(record, "1.0.0", TOKEN)
    assert decrypt_payload(migrated, TOKEN)["mainConfig"] == {"ok": True}
    assert migrated["version"] == "1.0.0"
```

增加已迁移标准序列再次预检时不重排的幂等测试，以及任一旧密文不可解密时不执行 UPDATE 的测试。

- [ ] **步骤 2：运行迁移测试确认失败**

运行：`python -m pytest backend/tests/test_config_version_migration.py -q`

预期：FAIL，迁移模块不存在。

- [ ] **步骤 3：实现纯映射和重加密函数**

`build_version_mapping(rows)` 按 `package_name` 分组，以 `(publish_at or created_at, created_at, id)` 稳定排序，从 `1.0.0` 依次编号。若一组全部已经是从 `1.0.0` 开始的连续标准序列，则返回原映射，保证重复执行不改变版本。

`reencrypt_record` 使用记录原信封中的 package/version/type 解密，校验三根字段，再用目标版本和 `config_type=full` 生成新信封并回读验证。

- [ ] **步骤 4：实现数据库预检与确认写入**

CLI：

```text
python scripts/migrate_config_versions.py
python scripts/migrate_config_versions.py --apply --confirm MIGRATE_CONFIG_VERSIONS
```

默认只打印脱敏映射摘要和校验结果。`--apply` 必须同时提供确认串。应用模式对目标记录 `FOR UPDATE`，在一次事务中完成全部重加密、临时版本避让、最终版本写入和唯一性验证；任何异常由事务整体回滚。

- [ ] **步骤 5：更新初始化 SQL 注释和约束**

保留 `(package_name, version)` 唯一约束及每包单 published 部分唯一索引，补充正式版本格式约束，仅约束 `published/archived`：

```sql
CHECK (status = 'draft' OR version ~ '^[0-9]+\.[0-9]\.[0-9]$')
```

- [ ] **步骤 6：运行迁移及模型测试**

运行：`python -m pytest backend/tests/test_config_version_migration.py backend/tests/test_config_migration.py -q`

预期：全部通过。

- [ ] **步骤 7：提交迁移工具**

```bash
git add scripts/migrate_config_versions.py scripts/init_db.sql backend/tests/test_config_version_migration.py
git commit -m "feat(config): migrate package versions safely"
```

### 任务 5：更新接口文档并完成全量验证

**文件：**
- 修改：`docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md`
- 创建：`docs/43-POST-CONFIG-DOWNLOAD-SEMVER-IMPLEMENTATION-20260811.md`

- [ ] **步骤 1：更新最新对接文档**

将三类配置下载示例全部改为 POST，明确无请求体、必须带 SDK Bearer Token；加入按包版本序列、发布分配、回滚复用和 Meta 一致性说明。只更新最新对接文档，不批量修改历史审阅文档。

- [ ] **步骤 2：运行旧契约残留扫描**

运行：

```powershell
rg -n "GET /api/v1/config/packages|client\.get\(.*config/packages" backend docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md
```

预期：生产路由、现行测试和最新对接文档中不存在把下载接口描述为 GET 的残留；允许 GET 405 断言。

- [ ] **步骤 3：运行后端全量测试**

运行：`python -m pytest backend/tests -q`

预期：0 failed。

- [ ] **步骤 4：运行前端测试和构建**

运行：`npm test -- --run`，工作目录 `frontend`；预期全部通过。

运行：`npm run build`，工作目录 `frontend`；预期退出码 0。

- [ ] **步骤 5：编写实施记录**

记录变更提交、红绿测试证据、迁移命令、生产备份命令、服务重启命令、接口冒烟请求及回滚步骤。不得写入 Token、数据库密码或 VPS 密码。

- [ ] **步骤 6：提交文档**

```bash
git add docs/40-LATEST-API-INTEGRATION-GUIDE-20260810.md docs/43-POST-CONFIG-DOWNLOAD-SEMVER-IMPLEMENTATION-20260811.md
git commit -m "docs: update config delivery integration"
```

### 任务 6：生产部署与验证

**文件：**
- 不新增源码文件；只执行受控部署并把结果补充到 `docs/43-POST-CONFIG-DOWNLOAD-SEMVER-IMPLEMENTATION-20260811.md`。

- [ ] **步骤 1：核对并备份生产漂移**

在服务器记录 `git status --short`、`git diff --stat`、当前 HEAD；将工作区补丁和数据库备份保存到服务器备份目录，输出中不得显示环境变量值。

- [ ] **步骤 2：部署前迁移预检**

使用生产 `.env` 运行 `migrate_config_versions.py` 默认预检，核对两个包名的记录数量、目标序列和解密验证全部成功。

- [ ] **步骤 3：数据库备份并进入维护窗口**

使用 PostgreSQL 自定义格式备份 `sdk_platform`。备份文件存在且大小大于零后，停止 SDK API 与 Admin API，避免迁移期间写入。

- [ ] **步骤 4：执行正式迁移和代码部署**

运行带确认串的迁移命令，部署已验证提交，重启 `sdk-api`、`sdk-admin`，检查 systemd 状态和最近日志无 traceback。

- [ ] **步骤 5：生产冒烟验证**

用生产 Token 但不输出 Token：

1. POST Meta 获取测试包当前版本；
2. 断言版本匹配 `^[0-9]+\.[0-9]\.[0-9]$`；
3. 对三个返回 URL 使用 POST，断言 200 且信封包名、版本和类型正确；
4. 对三个 URL 使用 GET，断言 405；
5. 用服务端测试程序解密三个信封，确认 AAD 校验成功；
6. 后台列表与当前 published 版本一致。

- [ ] **步骤 6：记录部署结果并提交**

将脱敏后的迁移数量、服务状态和 HTTP 状态写入实施文档，执行最终 `git diff --check`，提交部署记录。
