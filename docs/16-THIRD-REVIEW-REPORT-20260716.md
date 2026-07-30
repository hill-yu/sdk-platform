# SDK 数据中台第三次代码审阅报告

> 审阅日期：2026-07-16  
> 审阅对象：根据 `14-SECOND-REVIEW-REPORT-20260716.md` 和 `15-SECOND-REVIEW-FEEDBACK.md` 修改后的当前代码  
> 审阅范围：配置发布一致性、SDK 配置查询、数据库迁移、请求体限制、Nginx 配置、测试及前端构建  
> 审阅方法：修复声明与代码逐项对照、完整测试、前端构建、分块请求运行时探针

---

## 1. 审阅结论

本轮修改已经完成以下工作：

- SDK 配置查询增加 `cos_upload_status='success'` 条件。
- COS 上传失败时不再提前归档旧 published 配置。
- 新增 `cos_upload_status` 数据库迁移脚本和 CHECK 约束。
- Nginx 文档增加 SDK 1 MB、Admin 5 MB 请求限制。
- 非法和负数 `Content-Length` 已从 500 修正为 400。
- Admin API 和前端已显示 COS 同步状态。
- 测试桩不再吞掉所有异常。

但是，本轮复审仍发现 2 项必须修复问题和 4 项建议修改问题：

1. 分块超限请求触发 500，请求体限制修复尚未完成。
2. “先 COS、后数据库”仍无法保证数据库和 CDN 一致，并存在并发发布竞态。

当前后端测试 17/17 通过，前端构建成功，但现有测试没有覆盖上述两条关键路径。因此，项目仍不建议直接上线。

### 1.1 风险汇总

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 2 | 修复和验证前不建议上线 |
| 建议修改 | 4 | 建议上线前处理，其中迁移部署流程应视为发布前置条件 |
| 已确认修复 | 6 | 当前代码或文档已落实 |

---

## 2. 对 15 号反馈文档的复核

`15-SECOND-REVIEW-FEEDBACK.md` 仍然是一份分析和修复计划，不是包含完成状态与验证输出的正式修复报告。文档提出的多数代码修改已经实际落地，但其中“ASGI 层累计实际字节数，超限返回 413”和“加测试用例”没有达到预期：运行时分块超限请求返回 500，测试目录中也没有请求限制测试。

本报告不以提交信息或反馈文档中的“修复”字样作为完成依据，所有完成状态均以当前代码与实际命令输出为准。

---

## 3. 必须修复

### 3.1 [必须修复] 分块超限请求仍返回 500

**位置**：

- `backend/app/sdk_main.py:16-51`
- `backend/app/admin_main.py:25-60`

当前实现通过替换 `request._receive` 累计实际请求体大小，并在超限时抛出自定义 `RequestSizeExceeded`：

```python
async def limited_receive():
    ...
    if total > self.max_bytes:
        raise RequestSizeExceeded(self.max_bytes)
```

外层尝试用以下代码转换为 HTTP 413：

```python
try:
    return await call_next(request)
except RequestSizeExceeded:
    return JSONResponse(status_code=413, ...)
```

但 `BaseHTTPMiddleware.call_next()` 会在独立任务中运行下游应用。接收请求体时产生的异常经过任务组传播后，并不一定以裸 `RequestSizeExceeded` 到达当前 `except`，因此本轮运行时探针得到 500。

#### 实际探针

最大请求体设为 10 字节：

```text
declared 413 {"detail":"Request body too large"}
chunked 500 Internal Server Error
invalid 400 {"detail":"Invalid Content-Length header"}
negative 400 {"detail":"Invalid Content-Length"}
```

#### 影响

- 分块请求虽然不再被正常处理，但服务向客户端返回 500，而不是可预期的 413。
- 异常会进入服务错误日志和告警，容易被误判为应用故障。
- Admin 和 SDK 两套中间件都有同样的问题。
- 现有测试无法防止此问题回归。

#### 建议

不要基于 `BaseHTTPMiddleware` 和修改私有属性 `request._receive` 实现此限制。建议编写纯 ASGI 中间件，直接包装 `receive` 和 `send`，在调用下游应用前后完整控制消息流。

必须增加以下测试：

- 声明 Content-Length 且刚好等于限制。
- 声明 Content-Length 且超过限制。
- 无 Content-Length 的分块请求刚好等于限制。
- 无 Content-Length 的分块请求超过限制，验证返回 413。
- 非法、负数和冲突 Content-Length。
- SDK 1 MB 与 Admin 5 MB 两组配置。

### 3.2 [必须修复] 先上传 COS 仍不能保证 DB/CDN 一致，并存在并发竞态

**位置**：

- `backend/app/services/config_service.py:74-104`
- `backend/app/services/config_service.py:114-144`

当前流程变为：

1. 上传版本文件。
2. 覆盖 `config/latest.json`。
3. 归档数据库旧配置。
4. 将当前配置设为 published。
5. 依赖外层 `get_db()` 提交数据库事务。

该顺序解决了“COS 上传失败就提前归档旧配置”的问题，但没有解决跨系统原子性。

#### 场景一：COS 成功、数据库提交失败

`latest.json` 已指向新版本，但数据库事务可能因唯一约束、连接中断、数据库重启、磁盘故障等原因提交失败。此时 SDK 元信息仍返回旧数据库版本，而 CDN latest 已是新内容。

#### 场景二：两个发布请求并发

请求 A、B 可能发生以下交错：

1. A 上传 latest=A。
2. B 上传 latest=B。
3. B 数据库提交 published=B。
4. A 数据库后提交 published=A。

最终数据库 published=A，但 CDN latest=B。数据库的部分唯一索引只能保证最多一条 published，无法保证外部 COS 的写入顺序与数据库提交顺序一致。

#### 场景三：版本文件成功、latest 成功、数据库更新失败

当前没有补偿、重试或对账机制。管理后台也无法从数据库判断 latest 实际指向哪个版本。

#### 建议

仅调整“DB 和 COS 谁先”不能实现跨系统原子提交。建议至少引入轻量级发布编排：

1. 使用数据库 advisory lock 或行锁串行化发布。
2. 创建独立发布记录，状态为 `publishing`。
3. 上传不可变版本文件。
4. 数据库提交目标版本和发布意图。
5. 更新 `latest.json`。
6. 更新数据库为 `published/success`。
7. 任一步骤失败时保留可重试状态，并提供对账任务。

如果坚持最小方案，也必须实现：发布互斥、幂等键、latest 更新失败重试、数据库提交失败补偿，以及定期核对数据库 published 版本与 COS latest 内容。

---

## 4. 建议修改

### 4.1 [建议修改] 迁移脚本不可重复执行

**位置**：`scripts/migrate_cos_upload_status.sql:18-20`

字段添加使用了 `IF NOT EXISTS`，但约束使用：

```sql
ALTER TABLE sdk_configs
ADD CONSTRAINT chk_configs_cos_upload_status ...;
```

迁移脚本第二次执行时会因为约束已存在而失败。部署过程中发生重试或运维人员重复执行时，无法安全恢复。

建议使用 `DO $$ ... IF NOT EXISTS (...) THEN ... END IF; END $$;` 检查 `pg_constraint`，或正式采用 Alembic revision 管理一次性迁移。

### 4.2 [建议修改] 部署流程没有执行新增迁移

**位置**：`docs/07-DEPLOYMENT.md:292-318`

新增了 `scripts/migrate_cos_upload_status.sql`，但代码更新流程仍只有解压、安装依赖、重启服务，没有执行数据库迁移。仓库其他部署说明也只引用 `init_db.sql`。

对现有环境直接更新代码后，ORM 会访问不存在的 `cos_upload_status` 列，导致配置相关接口失败。

建议：

- 在日常代码更新流程中增加数据库备份和迁移命令。
- 迁移失败时禁止重启新版本服务。
- 增加迁移完成检查，例如查询 `information_schema.columns` 和 `pg_constraint`。
- 长期使用 Alembic `upgrade head` 代替人工挑选 SQL 文件。

### 4.3 [建议修改] 初始 published 配置默认处于 pending，SDK 不会返回

**位置**：

- `scripts/init_db.sql:205-219`
- `backend/app/api/sdk/config.py:31-35`

初始数据插入 `status='published'`，但没有指定 `cos_upload_status`，因此使用默认值 `pending`。SDK 现在只查询 `published + success`，全新数据库初始化后会返回“暂无已发布的配置”。

这可能是合理的安全行为，因为初始配置中的 CDN 地址仍是占位符且没有真实上传；但它与 09 号上线清单中“初始 published 记录可用”的预期不一致。

建议二选一并统一文档：

- 不再将模板记录标为 published，改为 draft，要求部署后通过管理后台正式发布；或
- 部署脚本完成真实 COS 上传后再将其设为 published/success。

不建议简单把占位模板直接标记为 success。

### 4.4 [建议修改] 新增关键行为没有测试覆盖

**位置**：`backend/tests`

本轮后端测试数量仍为 17，检索没有发现以下用例：

- 请求体普通和分块超限测试。
- 非法 Content-Length 测试。
- COS 第一次上传失败、latest 上传失败测试。
- COS 成功但数据库更新或提交失败测试。
- 并发发布一致性测试。
- SDK 排除 pending/failed 配置的查询条件测试。
- 数据库迁移回填和重复执行测试。

现有 `test_config_service.py` 主要验证回滚后版本格式和 success 字段，无法证明失败与并发路径正确。

建议至少为每个必须修复问题增加可复现的回归测试，再以测试通过作为关闭依据。

---

## 5. 已确认修复

### 5.1 SDK 过滤未上传成功的配置

SDK 元信息查询已增加：

```python
SdkConfig.cos_upload_status == "success"
```

pending/failed 配置不会直接被 SDK 查询返回。

### 5.2 COS 上传失败不再提前归档旧配置

发布和回滚路径均在两个 COS 上传成功后才执行数据库旧版本归档。在 COS 上传本身失败的场景中，旧 published 配置不会被提前修改。

### 5.3 新增数据库迁移和 CHECK 约束

已新增 `scripts/migrate_cos_upload_status.sql`，包括字段添加、历史数据回填、默认值、非空约束和合法值约束；全新初始化脚本也包含对应字段和 CHECK 约束。

迁移内容方向正确，但仍需解决重复执行与部署流程接入问题。

### 5.4 非法 Content-Length 返回 400

非法字符串和负数 Content-Length 已不再触发 500，本轮探针均返回 400。

### 5.5 Nginx 请求大小配置已写入部署文档

`docs/07-DEPLOYMENT.md` 已分别为 `/api/v1/` 和 `/api/admin/` 增加 1 MB、5 MB 限制。

### 5.6 Admin API 和前端显示上传状态

`_serialize_config()` 已返回 `cos_upload_status`，配置管理页面增加同步状态标签。

### 5.7 测试桩异常处理范围已缩小

`StubWriteSession.execute()` 不再使用 `except Exception: pass`，只忽略参数提取相关异常，模拟数据库失败可以继续向上传播。

---

## 6. 验证记录

### 6.1 后端完整测试

```text
命令：python -m pytest backend/tests -q
结果：17 passed in 0.34s
结论：现有测试通过，但未覆盖本轮关键风险路径
```

### 6.2 前端生产构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
主 JS：约 683.71 kB，gzip 后约 237.20 kB
警告：chunk 超过 500 kB
结论：构建通过，包体警告不阻断本轮功能
```

### 6.3 请求体限制运行时探针

```text
限制：10 字节
带正确 Content-Length 的 11 字节请求：413
无 Content-Length 的 12 字节分块请求：500
Content-Length=invalid：400
Content-Length=-1：400
```

结论：非法头部处理已修复，但分块超限路径仍失败。

### 6.4 迁移检查

```text
迁移文件：存在
字段回填：存在
CHECK 约束：存在
重复执行保护：字段有，约束没有
部署流程引用：未发现
```

### 6.5 未执行的外部验证

本轮未连接真实 PostgreSQL 和腾讯云 COS，因此没有验证：

- 迁移在真实已有库上的执行与重复执行。
- 真实 COS 上传和 latest 切换。
- 数据库提交失败补偿。
- 多请求并发发布。
- Nginx 实际 1 MB/5 MB 限制。

---

## 7. 与 14 号报告问题的状态对照

| 14 号报告问题 | 当前状态 | 说明 |
|---|---|---|
| 失败配置对 SDK 可见 | 部分修复 | SDK 已过滤 success，但跨系统提交失败和并发仍可能不一致 |
| 新字段缺少迁移 | 部分修复 | 迁移已创建，但不完全幂等且未接入部署流程 |
| 请求限制可绕过 | 未完成 | 非法头修复；分块超限从绕过变为 500，仍未返回 413 |
| 事务边界混合 | 已简化 | Service 不再自行 commit，但跨系统发布仍需编排 |
| Admin 未暴露上传状态 | 已修复 | API 和前端均已展示 |
| 测试桩吞异常 | 已修复 | 捕获范围已缩小 |
| 上传状态缺少约束 | 已修复 | 初始化和迁移均增加 CHECK |

---

## 8. 建议修复顺序

1. 用纯 ASGI 中间件修复分块超限 500，并添加完整请求体测试。
2. 串行化配置发布，补齐 COS/DB 失败补偿、幂等和对账机制。
3. 为发布失败、数据库失败和并发发布增加测试。
4. 将数据库迁移接入部署流程并实现可重复执行保护。
5. 明确初始模板配置是 draft 还是可用 published，并同步 09 号清单。
6. 在测试 PostgreSQL、COS 和 Nginx 环境执行端到端验证。

---

## 9. 上线判定

**当前判定：不建议上线。**

重新评估上线至少需要满足：

- 分块超限请求稳定返回 413，不产生 500。
- 配置发布在数据库提交失败和并发请求下不会造成 DB published 与 CDN latest 不一致。
- 迁移脚本已接入部署流程，并在测试数据库验证可安全执行。
- 新增请求限制、发布失败、并发和迁移回归测试。
- 后端完整测试继续保持 0 failed。
- 完成真实 PostgreSQL、COS/CDN、Nginx 的端到端验证。

