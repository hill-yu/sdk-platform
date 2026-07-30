# 第十次审阅意见修复过程记录

> 日期：2026-07-21  
> 输入依据：`docs/29-TENTH-REVIEW-REPORT-20260721.md`  
> 修复原则：仅处理第十次审阅报告中列出的修复意见，不扩展到其他历史问题或新问题。

## 1. 修复范围

本次修复覆盖第十次审阅报告中的以下项目：

| 审阅项 | 处理结果 | 涉及文件 |
|---|---|---|
| 2.1 定期清理没有删除其他 IP 的过期时间戳 | 已修复 | `backend/app/core/rate_limit.py` |
| 3.1 威胁模型不是正式风险接受记录 | 已补充 | `docs/THREAT-MODEL.md` |
| 3.2 “有效 app_id”描述与实现不符 | 已更正 | `docs/THREAT-MODEL.md`、`docs/02-API-SPEC.md` |
| 3.3 全部拒绝仍返回 HTTP 200，log 拒绝分支误导 | 已处理 | `backend/app/api/sdk/click.py`、`backend/app/api/sdk/log.py`、`docs/02-API-SPEC.md` |
| 3.4 click/log 使用两个独立限流桶 | 已确认并补测 | `backend/app/api/sdk/click.py`、`backend/app/api/sdk/log.py`、`backend/app/core/rate_limit.py` |
| 3.5 自动化测试覆盖不完整 | 已补充重点测试 | `backend/tests/test_rate_limit.py` |

说明：`click.py` 的 HTTP 422 行为在本轮开始前已经存在，本次只补齐文档和测试，不重复改动该文件。

## 2. 代码修复记录

### 2.1 限流状态清理与容量上限

`SimpleRateLimiter` 增加了：

- `clock` 参数，用于测试中注入可控时钟；
- `max_keys` 参数，用于限制内存字典最大 IP 键数量；
- `cleanup()` 方法，统一清理所有 IP 的过期时间戳，并删除清空后的键；
- 每 1000 次写入请求触发一次全局清理。

修复后的行为：

- 当前 IP 每次请求仍会先过滤过期时间戳；
- 全局清理会遍历所有 IP，而不是只检查列表是否为空；
- 超过 `max_keys` 时，删除时间戳最旧的键，保留最新键。

### 2.2 log 不可达拒绝分支

`LogReportRequest.logs` 已由 schema 保证 `min_length=1`，且当前 log 路由没有业务拒绝规则，因此 `if not values` 和 `partial_success` 分支没有真实入口。

本次删除了 log 路由中的误导性全部拒绝分支和部分成功分支，保留真实行为：

- schema 校验失败由 FastAPI 返回 422；
- 数据库写入失败返回 500，并执行 rollback；
- 全部日志写入成功返回 `code=0`、`message=ok`。

### 2.3 文档协议对齐

`docs/THREAT-MODEL.md` 补充：

- 风险编号；
- 风险所有者；
- 批准状态；
- 接受日期；
- 复审日期；
- 适用范围；
- 退出条件；
- 监控与处置阈值。

`docs/02-API-SPEC.md` 补充：

- click/log 写入接口的 `app_id` 仅做长度校验，不校验真实存在或启用；
- click 全部事件被拒绝时返回 HTTP 422 + `code=4001`；
- click/log 写入接口共享同一个 IP 配额，合计超过 10 次/秒/IP 时返回 HTTP 429；
- log 接口文档删除无实际拒绝规则支撑的 `partial_success` 描述。

## 3. 自动化测试补充

在 `backend/tests/test_rate_limit.py` 中新增覆盖：

1. 全局清理会删除其他 IP 的过期时间戳和空键；
2. 时间窗口过期后，同一 IP 可以重新请求；
3. 限流器达到容量上限时保留最新 IP 键；
4. log 路由也受写入限流保护；
5. config/version 读接口不消耗写入限流配额；
6. click 与 log 共享同一个写入限流桶；
7. click 数据库 `execute` 异常时执行 rollback，并返回 HTTP 500。

## 4. 验证记录

### 4.1 后端完整测试

```text
python -m pytest backend/tests -q
42 passed in 4.61s
```

### 4.2 前端生产构建

```text
npm run build
656 modules transformed
✓ built in 3.93s
```

仍保留既有提示：主 JS chunk 大于 500 kB。本次未处理该提示，因为它不属于第十次审阅意见的修复范围。

### 4.3 限流清理探针

```text
keys_after_cleanup= 1
remaining_keys= ['10.1.0.1']
```

结论：旧 IP 的过期时间戳和键已被全局清理回收，不再复现第十次审阅报告中的 `keys_after_two_cleanup_cycles = 2000`。

## 5. 修复结论

本次已按 `docs/29-TENTH-REVIEW-REPORT-20260721.md` 中列出的修复意见完成对应修复，并已用后端测试、前端构建和限流清理探针验证。

未处理事项：无。本轮没有引入第十次审阅意见以外的新需求修复。
