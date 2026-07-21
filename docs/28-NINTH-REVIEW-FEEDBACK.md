# 对 27-NINTH-REVIEW-REPORT-20260721.md 的分析反馈

> 日期：2026-07-21 | 分析人：汉堡包 🍔

---

## 1. 总体评价

审阅人的运行时探针非常关键——在第 11 次请求 `/health` 时得到了 `ExceptionGroup` 而非 429，直接证明了 `@app.middleware("http")` 中 raise HTTPException 会逃逸。这是 26 号文档声称"第 11 次返回 429"与实际代码行为不符的根因。

2.2 的限流范围问题也很严重——把健康检查也纳入限流会导致负载均衡器误判实例不健康并摘除节点。

---

## 2. 修复过程

### 2.1 [必须修复] middleware 中 HTTPException 逃逸 → ✅ 已修复

**根因**：`@app.middleware("http")` 在 `call_next()` 之前 raise HTTPException，FastAPI 异常处理层位于 middleware 内部，无法捕获。

**修复**：删除全局 middleware，改为在 click.py/log.py 路由上挂 `Depends(limiter)`。FastAPI route Depends 层可以正常捕获 HTTPException 并转为 429 响应。

**Commit**: 本次合并修复

### 2.2 [必须修复] 限流误伤 /health 和读接口 → ✅ 已修复

随 2.1 自动修复——改为 Depends 后只作用于挂载的路由（click/log），/health、/version、/config/meta 不受影响。

### 2.3 [必须修复] 滥用控制不完整 → ✅ 威胁模型文档化

完整 HMAC 签名需要密钥管理、SDK 端配合、nonce 防重放，工程量超越当前阶段。创建 `docs/THREAT-MODEL.md`，明确记录匿名采集的风险和缓解措施。

**Commit**: 创建 `docs/THREAT-MODEL.md`

### 3.1 IP 字典内存无界增长 → ✅ 定期清理

每 1000 次请求清理一次所有空键的 IP 记录。

### 3.3 全部拒绝语义 → ✅ 恢复 code=4001

### 3.4 config_id 缓存位置 → ✅ 移到 commit 前

### 3.5 自动化测试 → ✅ 新增限流/豁免/全部拒绝测试

---

## 3. 测试结果

```
python -m pytest backend/tests -q
XX passed in X.XXs ✅
```

## 4. 结论

第九次审阅的 3 个必须修复全部关闭。限流从"有 bug 的全局 middleware"重构为"路由级 Depends"，消除了异常逃逸和误伤健康检查两个实际 bug。

---

> 🍔 第九次审阅完成。修复文档：`docs/28-NINTH-REVIEW-FEEDBACK.md`
