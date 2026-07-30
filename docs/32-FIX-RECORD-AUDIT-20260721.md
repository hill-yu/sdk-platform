# 对 31-TENTH-REVIEW-FIX-RECORD-20260721.md 的审阅报告

> 审阅日期：2026-07-21  
> 审阅对象：`docs/31-TENTH-REVIEW-FIX-RECORD-20260721.md`（第十次审阅修复记录）  
> 审阅依据：`docs/29-TENTH-REVIEW-REPORT-20260721.md`（第十次审阅报告）  
> 审阅方式：逐项对照源代码、文档和实测验证

---

## 1. 审阅结论

**修复记录扎实可靠，六项修复的声称均有代码/文档/测试的真实支撑。** 不存在"声称修了但没修"的情况。审阅报告 §6 列出的六项最低验收条件全部满足。

| 级别 | 数量 | 说明 |
|---:|---:|---|
| ✅ 通过 | 6 | 六项修复全部做实，验收条件全部满足 |
| ⚠️ 建议 | 3 | 文档措辞和说明性细节可优化，不影响实质内容 |
| ❌ 未通过 | 0 | — |

**最终判断：第十次审阅可以正式关闭。** 🎉

---

## 2. 逐项核实

### 2.1 [必须修复] 定期清理没有删除其他 IP 的过期时间戳 → ✅ 通过

| 修复文档声称 | 核实结果 |
|---|---|
| `clock` 参数用于测试 | `rate_limit.py:15` — `clock: Callable[[], float] \| None` ✅ |
| `max_keys` 容量上限 | `rate_limit.py:14,19` — 默认 10000 ✅ |
| `cleanup()` 遍历所有 IP 过滤过期时间戳 | `rate_limit.py:41-46` — 逐键过滤，全部过期则删键 ✅ |
| 每 1000 次写入触发全局清理 | `rate_limit.py:32-36` — `_cleanup_counter` 机制 ✅ |
| 超限淘汰最旧键 | `rate_limit.py:48-51` — 按时间戳排序，保留最新 N 个 ✅ |

**实测探针验证**（来自修复文档 §4.3）：
```
keys_after_cleanup= 1
remaining_keys= ['10.1.0.1']
```
旧 IP 的过期时间戳和键已被回收。与审阅报告中的 `keys_after_two_cleanup_cycles = 2000` 对比，问题已彻底解决。

---

### 2.2 [建议修改] log 不可达拒绝分支 → ✅ 通过

| 修复文档声称 | 核实结果 |
|---|---|
| 删除 `if not values` 分支 | `log.py` — 无此分支，直接从构造 values 到 try-except 写入 ✅ |
| 删除 `partial_success` 分支 | `log.py:71` — 只返回 `code=0, message=ok` ✅ |
| DB 异常 → rollback + 500 | `log.py:66-69` — `await db.rollback()` 后 `raise HTTPException(500)` ✅ |

**分析**：`LogReportRequest.logs` 由 schema 保证 `min_length=1`，log 路由无业务拒绝规则，因此旧代码中的 `if not values` 和 `partial_success` 确为不可达分支。删除后代码更简洁、语义更明确。

---

### 2.3 [建议修改] 威胁模型 → ✅ 通过

| 修复文档声称 | 核实结果 |
|---|---|
| 风险编号 | `THREAT-MODEL.md:4` — `SDK-ANON-WRITE-001` ✅ |
| 风险所有者 | `THREAT-MODEL.md:5` — "SDK 数据中台负责人" ✅ |
| 批准状态 | `THREAT-MODEL.md:6` — "临时接受" ✅ |
| 接受日期 / 复审日期 | `THREAT-MODEL.md:7-8` — 2026-07-21 / 2026-08-21 ✅ |
| 适用范围 | `THREAT-MODEL.md:9` — 列出具体接口路径 ✅ |
| 退出条件 | `THREAT-MODEL.md:10` — 上线签名鉴权后重新评估 ✅ |
| 监控与处置阈值 | `THREAT-MODEL.md:23-27` — 4 条量化阈值 ✅ |

此外，app_id 描述从"持有有效 app_id"更正为"任意字符串作为 app_id，服务端不校验其有效性"（`THREAT-MODEL.md:14`），与实现行为一致。

---

### 2.4 [建议修改] 文档协议对齐 → ✅ 通过

**`docs/02-API-SPEC.md` 逐项核实：**

| 修复文档声称 | 核实结果 |
|---|---|
| click 的 `app_id` 仅做长度校验 | `02-API-SPEC.md:214` — "匿名采集阶段服务端仅校验长度，不校验是否真实存在或启用" ✅ |
| log 的 `app_id` 同上 | `02-API-SPEC.md:310` — 同样描述 ✅ |
| click 全部拒绝 → HTTP 422 + code=4001 | `02-API-SPEC.md:266` — 明确记录 ✅ |
| click/log 共享 IP 配额，合计 10 次/秒/IP → 429 | `02-API-SPEC.md:254,332` — 两处均注明 ✅ |
| log 删除 `partial_success` 描述 | `02-API-SPEC.md:343` — 仅保留 `code=0, message=ok` ✅ |

---

### 2.5 [建议修改] click/log 限流桶共享 → ✅ 通过

| 修复文档声称 | 核实结果 |
|---|---|
| 共享同一实例 | `rate_limit.py:54` — 全局唯一 `write_limiter` 实例 ✅ |
| click 导入 | `click.py:14` — `from app.core.rate_limit import write_limiter` ✅ |
| log 导入 | `log.py:13` — 同上 ✅ |

> ⚠️ **措辞建议**：修复记录 §1 表中 3.4 行的处理结果写"已确认并补测"，但实际也修改了代码（30 号反馈文档 commit `27392b8` 记录了从各自 `SimpleRateLimiter()` 到共享实例的改动）。建议改为"已修复并补测"以更准确反映实际工作量。

---

### 2.6 [建议修改] 自动化测试补充 → ✅ 通过

**审阅报告 §3.5 建议的 7 项测试覆盖逐项对照：**

| # | 审阅建议 | 对应测试函数 | 状态 |
|:--:|---------|-------------|:--:|
| 1 | IP 状态清理与容量上限 | `test_rate_limit_cleanup_removes_stale_ip_keys` | ✅ |
| 2 | 时间窗口恢复 | `test_rate_limit_window_recovers_after_expiration` | ✅ |
| 3 | 限流器容量上限保留最新键 | `test_rate_limit_cleanup_caps_ip_key_count` | ✅ |
| 4 | log 路由限流 | `test_log_route_uses_shared_rate_limit_bucket` | ✅ |
| 5 | 配置/版本读接口豁免 | `test_read_routes_exempt_from_write_rate_limit` | ✅ |
| 6 | click/log 共享配额 | `test_log_route_uses_shared_rate_limit_bucket` | ✅ |
| 7 | DB execute 异常时 rollback + 500 | `test_click_db_execute_failure_rolls_back_and_returns_500` | ✅ |
| — | 多 worker/多实例行为 | 未覆盖 | ⚠️ |

> ⚠️ **说明**：审阅报告 §3.5 列出的"多 worker/多实例行为"本轮未覆盖。修复文档未解释跳过原因。建议补充说明："多 worker 行为受限于进程级内存隔离，应用层无法在单测中模拟；建议由 Nginx `limit_req` 或 Redis 原子计数覆盖，不在本轮应用层修复范围内。"

**实测**：
```
python -m pytest backend/tests -q
42 passed in 4.68s
```
与修复文档声称的 42 passed 完全一致（时间微小波动 4.68s vs 4.61s 属正常系统差异）。

---

## 3. 验证记录

### 3.1 后端完整测试

```
42 passed in 4.68s ✅
```

### 3.2 前端生产构建

```
656 modules transformed
✓ built in 4.00s
主 JS 683.71 kB，gzip 237.20 kB ✅
```

与修复文档声称一致。

### 3.3 限流实例唯一性

全局仅一个 `write_limiter` 实例（`rate_limit.py:54`），click 和 log 均导入同一对象，确认共享桶。

---

## 4. 对照下一轮验收条件

审阅报告 §6 列出的六项条件逐一对照：

| # | 验收条件 | 状态 |
|:--:|---------|:--:|
| 1 | 全局清理真正过滤所有 IP 的过期时间戳并删除空键 | ✅ |
| 2 | 增加最大容量或有界实现 | ✅（max_keys=10000 + LRU） |
| 3 | 补可控时钟的清理自动化测试 | ✅ |
| 4 | 威胁模型：责任人/审批状态/复审期限 + app_id 描述纠正 | ✅ |
| 5 | click/log 配额共享/独立明确，代码、Nginx、文档一致 | ✅ |
| 6 | 后端 0 failed + 前端构建成功 | ✅ |

**六项全部满足。**

---

## 5. 文档质量评价

### 做得好的地方

- **范围克制**：开头明确"仅处理第十次审阅报告"，不扩散到历史问题，务实
- **可追溯**：每项修复列出涉及文件，有据可查
- **验证驱动**：§4 包含实际跑过的命令输出，不是编造的数据
- **透明**：对 click.py 的 422 行为坦诚说明"本轮到开始前已经存在"

### 建议改进

1. **修复范围表 3.4 措辞**："已确认并补测" → "已修复并补测"（实际改了代码）
2. **多 worker 测试跳过说明**：补充一句为什么审阅报告 §3.5 中的"多 worker/多实例行为"未覆盖
3. **构建命令路径**：`npm run build` 实际应在 `frontend/` 目录执行，文档可注明工作目录以避免混淆

---

## 6. 最终结论

> 🍔 **这份修复记录烤得恰到好处。** 六项修复逐项做实——清理算法从"只删空壳"升级为"真正遍历内容过滤"，威胁模型从空文档升级为正式风险接受记录，限流从各自为战统一为共享配额。42 个测试全绿，前端构建无异常。第十次审阅可以正式关闭。

**评分：8.5/10**（扣分仅在极少量措辞准确性和上下文说明上，不影响实质内容）

即使不做任何修改，这份修复记录也足以通过第三方审计。
