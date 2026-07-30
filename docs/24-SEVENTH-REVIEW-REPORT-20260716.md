# SDK 数据中台第七次代码审阅报告

> 审阅日期：2026-07-16  
> 审阅对象：`23-SIXTH-REVIEW-FEEDBACK.md` 及其对应提交后的当前代码  
> 重点范围：请求体限制中间件、commit 失败补偿事务、测试有效性、既有技术债  
> 审阅方法：逐项核对修复声明、代码路径分析、后端完整测试、前端生产构建、ASGI 生命周期复核、SQLAlchemy rollback 状态探针

---

## 1. 审阅结论

23 号反馈文档所列的三项代码修改均已真实落地：

- 请求体中间件收到 `http.disconnect` 会立即退出；累计超限后会立即返回 413，不再等待剩余 body。
- commit 异常后已经先调用 `await db.rollback()`，再创建独立 recovery session。
- SDK/Admin 的重复中间件已经提取到 `backend/app/core/middleware.py`。

后端完整测试为 **33/33 通过**，前端生产构建成功。

但是，commit 失败补偿仍有 1 项必须修复问题：代码在 `rollback()` 后继续读取原 ORM 实例的 `config.id`。SQLAlchemy rollback 会无条件 expire 当前 session 中的对象属性；在 AsyncSession 中，读取过期属性可能触发隐式数据库 IO 并抛出 `MissingGreenlet`。这会使 recovery session 尚未建立就进入二次异常，导致反馈文档声称的 failed 状态持久化在真实 SQLAlchemy 环境中不可靠。

因此，“42 项、0 剩余”和“第六次审阅全部关闭”的结论仍不成立。当前建议为：**修复该恢复路径并补真实 AsyncSession/PostgreSQL 集成测试后再做上线判断。**

### 1.1 风险汇总

| 级别 | 数量 | 上线影响 |
|---|---:|---|
| 必须修复 | 1 | commit 失败补偿可能在创建恢复事务前再次失败 |
| 建议修改 | 5 | 提升异常可诊断性与测试可信度 |
| 已确认修复 | 3 | 23 号文档列出的直接代码修复已落地 |

---

## 2. 对 23 号修复报告的逐项复核

| 修复声明 | 复核结论 | 依据 |
|---|---|---|
| disconnect 立即退出 | 已修复 | `core/middleware.py:45-47` |
| 超限不等待剩余 body | 已修复 | `core/middleware.py:56-59` |
| commit 失败先 rollback | 已实现，但恢复路径仍有缺陷 | `config_service.py:109-124`、`:181-196` |
| 中间件提取 | 已修复 | SDK/Admin 均导入同一个 `RequestSizeLimitMiddleware` |
| 技术债更新 | 已记录 | `TECH-DEBT.md` 新增真实 PostgreSQL 集成测试项 |
| 33 passed | 与实际一致 | 本轮实测 `33 passed in 8.52s` |
| 0 剩余 | 不成立 | 仍有 1 项必须修复，且 D2-D4 为 Medium 技术债 |

---

## 3. 必须修复

### 3.1 [必须修复] rollback 后读取原 ORM 对象，补偿流程可能触发 MissingGreenlet

**位置：**

- `backend/app/services/config_service.py:109-124`
- `backend/app/services/config_service.py:181-196`
- `backend/tests/test_reconcile.py:161-235`

当前两个发布路径都采用如下顺序：

```python
except Exception:
    await db.rollback()
    async with async_session_factory() as recovery_session:
        async with recovery_session.begin():
            cfg = await recovery_session.get(SdkConfig, config.id)
```

先 rollback 再开启独立 session 的方向是正确的，它解决了上一轮指出的原事务锁未释放问题。但 `config.id` 仍来自已经 rollback 的原 session 对象。

SQLAlchemy 的 `Session.rollback()` 会完全 expire session 中的对象状态，不受 `expire_on_commit=False` 影响。本轮用普通 SQLAlchemy Session 验证，rollback 前后对象状态为：

```text
before: expired_attributes = set()
after rollback: expired_attributes = {'id', 'name'}
identity = (1,)
```

同步 Session 访问 `obj.id` 会隐式发起 SELECT；AsyncSession 不允许普通属性访问隐式执行异步 IO，常见结果是 `sqlalchemy.exc.MissingGreenlet`。当前代码第一次在 recovery `get()` 参数中读取 `config.id`，且此读取发生在内部 `try` 中；异常虽可能被记录，但后续 critical 日志又再次读取 `config.id`，可能覆盖原异常并直接逃逸。回滚发布路径存在同样问题。

#### 影响

- COS `latest.json` 已指向新版本，但 failed 标记可能没有写入。
- recovery session 可能根本没有被创建。
- API 不一定返回预期的 500 `HTTPException`，而可能返回未处理异常。
- 日志中的“系统已记录”与真实状态不一致。
- 当前 fake 测试不会 expire Python 假对象，因此无法发现问题。

#### 修复建议

在任何可能 rollback 的操作之前，把恢复所需的纯值保存到局部变量：

```python
config_id = config.id
target_version = version

try:
    await db.commit()
except Exception:
    await db.rollback()
    async with async_session_factory() as recovery_session:
        async with recovery_session.begin():
            cfg = await recovery_session.get(SdkConfig, config_id)
```

更稳妥的做法是提取统一的 `_record_publish_failure(config_id, version)`，两个发布路径只传不可变标量，避免再次复制异常处理代码。

#### 必需测试

至少补充以下验证：

1. 使用真实 AsyncSession，构造 commit 失败并执行 rollback，确认恢复代码不读取 expired ORM 属性。
2. 断言调用顺序为 `commit failed -> rollback completed -> recovery session begin`。
3. 从第二个独立 session 重新查询，确认 failed 状态已真实提交，而不是只检查同一个 Python 对象。
4. 同时覆盖 `publish_config()` 和 `_publish_from_record()`。

---

## 4. 建议修改

### 4.1 recovery 记录不存在时仍打印“已持久化”

`recovery_session.get()` 返回 `None` 时，代码不会更新任何记录，但退出事务后仍执行：

```python
logger.info("失败状态已持久化 ...")
```

建议在 `cfg is None` 时记录 critical/error，并让 API detail 明确表示补偿失败。只有实际找到记录并成功提交后才能打印“已持久化”。

### 4.2 recovery 失败时 API 仍声称“系统已记录”

内部 catch 已识别双重故障，但最终 HTTP detail 始终是：

```text
系统已记录，请联系管理员检查
```

当 recovery session 自身失败时，这个描述不准确。建议维护 `recovery_succeeded` 状态，返回不同 detail，并为告警系统输出结构化事件。

### 4.3 rollback 自身失败没有独立处理

`await db.rollback()` 位于 recovery 的 `try` 之外。如果连接失效等原因导致 rollback 也抛异常，独立恢复和统一告警均不会执行。建议至少保留原 commit 异常、单独捕获并记录 rollback 异常，再根据连接/锁状态决定是否尝试补偿或转入 Outbox/人工对账。

### 4.4 commit 失败测试仍未证明持久化和锁释放

`FakeDbCommitFail.rollback()` 为空实现，`_FakeAsyncContextManager.__aexit__()` 也不 commit。测试最终只断言：

```python
assert recovery_config.cos_upload_status == "failed"
```

这证明的是 Python 对象被赋值，并不证明：

- rollback 确实先于 recovery session；
- 原事务锁已释放；
- recovery transaction 已 commit；
- 新 session 能重新读到 failed；
- rollback 后原 ORM 对象是否过期。

`TECH-DEBT.md` 已把真实 PostgreSQL 集成测试列为 Medium，但在该测试落地前不应宣称 commit 补偿路径已被测试证明。

### 4.5 “0 剩余”与技术债清单矛盾

当前仍明确存在三项 Medium 技术债：

- D2：没有自动定时对账和告警；
- D3：未采用 Outbox，COS/DB 仍有窗口期；
- D4：缺少真实 PostgreSQL 集成测试。

建议后续反馈文档区分“本轮直接审阅项已处理”和“系统上线风险全部关闭”，不要用累计数字覆盖仍未完成的架构风险。

---

## 5. 已确认修复

### 5.1 disconnect 和超限流处理已修复

中间件现在：

- 收到 `http.disconnect` 直接 return；
- 非 `http.request` 消息不再加入重放列表；
- 累计字节超限后立即发送 413；
- 不再为了排空请求体继续等待客户端。

上一轮的无限 disconnect 自旋和超限等待问题已关闭。

### 5.2 原事务在 recovery 前执行 rollback

两个 commit 异常分支均已把 `await db.rollback()` 放到 recovery session 之前。该顺序修复了上一轮指出的明显自锁路径；本轮问题是 rollback 后对象访问，而不是 rollback 顺序本身。

### 5.3 中间件重复实现已消除

`sdk_main.py` 和 `admin_main.py` 均使用 `app.core.middleware.RequestSizeLimitMiddleware`，后续修复只需维护一处。

---

## 6. 验证记录

### 6.1 后端完整测试

```text
命令：python -m pytest backend/tests -q
结果：33 passed in 8.52s
退出码：0
```

现有测试全部通过，但不覆盖真实 rollback expire、数据库锁和 recovery commit。

### 6.2 前端生产构建

```text
命令：npm run build
结果：构建成功，656 modules transformed
退出码：0
主 JS：683.71 kB，gzip 237.20 kB
```

仍有单 chunk 超过 500 kB 的构建警告，不阻断本轮修复验收。

### 6.3 SQLAlchemy rollback 状态探针

```text
before set() 1
after_expired {'id', 'name'}
identity (1,)
access_id_sync_triggers_refresh 1
```

该探针确认 rollback 会使主键属性也进入 expired 状态。当前环境没有可用的本地 PostgreSQL（`localhost:5432 - no response`），因此未完成真实 AsyncSession/PostgreSQL 的最终复现；这也正是 D4 集成测试需要覆盖的内容。

---

## 7. 上线判断

| 检查项 | 状态 | 说明 |
|---|---|---|
| disconnect 正确退出 | 通过 | 已有明确分支 |
| 超限立即 413 | 通过 | 不再等待剩余 body |
| 中间件单一实现 | 通过 | SDK/Admin 共用 core 实现 |
| commit 前后锁顺序 | 部分通过 | 已先 rollback，但随后读取 expired ORM 对象 |
| failed 状态真实持久化 | 未证明 | fake 测试不 commit、不重新查询 |
| 自动对账与告警 | 未完成 | 仍为 Medium 技术债 |
| 后端测试 | 通过 | 33/33 |
| 前端构建 | 通过 | 有 chunk 体积警告 |

**最终判断：暂不建议以“全部关闭”状态直接上线。**

下一轮最低验收条件：

1. rollback 前缓存 `config_id` 等恢复所需标量，rollback 后不再访问原 ORM 实例。
2. 合并两处恢复逻辑，正确区分恢复成功、记录不存在和恢复失败。
3. 增加真实 AsyncSession/PostgreSQL 集成测试，证明 rollback 顺序、锁释放和独立事务持久化。
4. 后端完整测试保持 0 failed，前端构建保持成功。

